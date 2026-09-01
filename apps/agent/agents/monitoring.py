"""
RecoverFlow — AGENT 1: MONITORING
=================================

The watcher & file-keeper.

Owns the webhook front door:
  1. Verify Razorpay webhook signatures (HMAC)
  2. Ingest payment.failed / payment.captured events
  3. Dedupe Razorpay webhook retries
  4. Classify the failure via classification.py
  5. File a case in failed_payments + audit ledger
  6. Hand off to AGENT 2 (diagnosis) via should_diagnose flag

Design rule:
This agent has NO opinions.
It observes, files, and wakes the brain.
All strategy lives in AGENT 2 + policy.py.
"""

import hmac
import hashlib
import os
from datetime import datetime

from core import db, audit_log


# ============================================================
# CONFIGURATION
# ============================================================

WEBHOOK_SECRET = os.getenv(
    "RAZORPAY_WEBHOOK_SECRET",
    "rf_webhook_secret_2025"
)


# ============================================================
# 1. SIGNATURE VERIFICATION
# ============================================================

def verify_signature(body: bytes, signature: str) -> bool:
    """
    Verify Razorpay webhook HMAC-SHA256 signature.

    Never trust an unverified webhook event.
    """

    if not signature:
        return False

    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ============================================================
# 2. FAILURE INGESTION
# ============================================================

def handle_failed_payment(ent: dict, orders_lookup) -> dict:
    """
    Handle a Razorpay payment.failed event.

    Parameters
    ----------
    ent:
        Razorpay payment entity.

    orders_lookup:
        Callable:
            order_id -> order row
        Returns None when the order is not found.

    Returns
    -------
    dict:
        Result consumed by main.py.

    If should_diagnose=True, main.py should wake Agent 2.
    """

    # IMPORTANT:
    # The previous version attempted:
    #
    #     from classification import classify_gateway_error
    #
    # But classification.py does not expose that function.
    #
    # The RecoverFlow design uses `classify(ent)` instead.
    from classification import classify

    order_id = ent.get("order_id") or "unknown"

    # ========================================================
    # DEDUPE
    # ========================================================
    #
    # Razorpay can retry webhooks.
    # One failed payment should create one recovery case.
    #

    with db() as conn:
        existing = conn.execute(
            """
            SELECT id, failure_type
            FROM failed_payments
            WHERE order_id=?
            """,
            (order_id,)
        ).fetchone()

    if existing:
        audit_log(
            "monitoring",
            "case.duplicate_ignored",
            order_id,
            {
                "existing_failure_type": existing["failure_type"]
            }
        )

        return {
            "handled": True,
            "duplicate": True,
            "case_id": order_id,
            "should_diagnose": False
        }

    # ========================================================
    # CLASSIFICATION
    # ========================================================
    #
    # classification.py is the vendor mapping layer.
    #
    # Expected return:
    #
    #     failure_type,
    #     recommended_action,
    #     detail
    #

    try:
        ftype, recommended_action, detail = classify(ent)

    except Exception as exc:
        # Monitoring should not silently crash the webhook
        # because a classification rule failed.
        #
        # Record the problem and use a safe generic classification.
        audit_log(
            "monitoring",
            "classification.failed",
            order_id,
            {
                "error": str(exc),
                "source": "webhook"
            }
        )

        ftype = "unknown"
        recommended_action = "diagnose"
        detail = f"classification_error: {str(exc)}"

    # ========================================================
    # ENRICH ORDER INFORMATION
    # ========================================================

    order = (
        orders_lookup(order_id)
        if order_id != "unknown"
        else None
    )

    if order:
        phone = order["phone"]
        plan = order["plan"]
        amount = order["amount"]

    else:
        # Webhook belongs to an order that does not exist
        # in our local orders table.
        #
        # Still file the case using Razorpay entity data.

        phone = ent.get("contact") or "unknown"
        plan = "unknown"
        amount = ent.get("amount") or 0

        audit_log(
            "monitoring",
            "case.order_not_found",
            order_id,
            {
                "fallback": "filed_from_webhook_entity_only"
            }
        )

    # ========================================================
    # FILE CASE
    # ========================================================

    with db() as conn:
        conn.execute(
            """
            INSERT INTO failed_payments
            (
                order_id,
                phone,
                plan,
                amount,
                failure_type,
                failure_source,
                raw_detail,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                phone,
                plan,
                amount,
                ftype,
                "webhook",
                detail,
                datetime.now().isoformat()
            )
        )

    # ========================================================
    # AUDIT LEDGER
    # ========================================================

    audit_log(
        "monitoring",
        "case.filed",
        order_id,
        {
            "failure_type": ftype,
            "recommended_action": recommended_action,
            "source": "webhook",
            "detail": detail
        }
    )

    # ========================================================
    # WAKE AGENT 2
    # ========================================================

    return {
        "handled": True,
        "duplicate": False,
        "case_id": order_id,
        "failure_type": ftype,
        "recommended_action": recommended_action,
        "should_diagnose": True
    }


# ============================================================
# 3. SUCCESS INGESTION
# ============================================================

def handle_captured_payment(ent: dict) -> dict:
    """
    Handle Razorpay payment.captured.

    If a customer previously had an open recovery case and
    subsequently paid, mark the case as recovered.

    This prevents additional recovery actions after payment.
    """

    order_id = ent.get("order_id") or "unknown"

    # ========================================================
    # FIND OPEN CASE
    # ========================================================

    with db() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM failed_payments
            WHERE order_id=?
              AND status='open'
            """,
            (order_id,)
        ).fetchone()

        # ====================================================
        # CLOSE RECOVERY CASE
        # ====================================================

        if row:
            conn.execute(
                """
                UPDATE failed_payments
                SET status='recovered'
                WHERE order_id=?
                  AND status='open'
                """,
                (order_id,)
            )

    # ========================================================
    # CASE RECOVERED
    # ========================================================

    if row:
        audit_log(
            "monitoring",
            "case.recovered",
            order_id,
            {
                "note": (
                    "customer paid after recovery touch — "
                    "case closed"
                )
            }
        )

        return {
            "handled": True,
            "recovered": True,
            "case_id": order_id
        }

    # ========================================================
    # NO OPEN CASE
    # ========================================================

    audit_log(
        "monitoring",
        "payment.captured",
        order_id,
        {
            "source": "webhook"
        }
    )

    return {
        "handled": True,
        "recovered": False,
        "case_id": order_id
    }

