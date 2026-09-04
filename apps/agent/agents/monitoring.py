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
from datetime import datetime, timedelta

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

    from classification import classify

    order_id = ent.get("order_id") or "unknown"

    # ========================================================
    # DEDUPE
    # ========================================================

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

    try:
        ftype, recommended_action, detail = classify(ent)

    except Exception as exc:

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

    IMPORTANT:
    Razorpay's captured payment contains the RETRY order ID.

    Example:

        Original failed order:
            order_ABC

        Retry order:
            order_XYZ

    failed_payments stores:
        order_ABC

    executions stores:
        case_id = order_ABC
        order_id = order_XYZ

    Therefore we use executions to connect the successful
    retry payment back to the original failed case.
    """

    # This is the order ID from Razorpay payment.captured.
    payment_order_id = ent.get("order_id") or "unknown"
    activated_sub = None

    # ========================================================
    # FIND THE ORIGINAL RECOVERY CASE
    # ========================================================

    with db() as conn:

        # ----------------------------------------------------
        # FIRST:
        # Check whether the captured order itself is an
        # original failed order.
        # ----------------------------------------------------

        row = conn.execute(
            """
            SELECT id, order_id
            FROM failed_payments
            WHERE order_id=?
              AND status NOT IN ('recovered')
            ORDER BY id DESC
            LIMIT 1
            """,
            (payment_order_id,)
        ).fetchone()

        case_id = payment_order_id

        # ----------------------------------------------------
        # SECOND:
        # If it is not the original order, it is probably
        # a retry order created by Agent 3.
        #
        # executions.order_id = retry Razorpay order
        # executions.case_id  = original failed order
        # ----------------------------------------------------

        if not row:

            execution = conn.execute(
                """
                SELECT case_id
                FROM executions
                WHERE order_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (payment_order_id,)
            ).fetchone()

            if execution:

                case_id = execution["case_id"]

                # Find the original failed case.
                row = conn.execute(
                    """
                    SELECT id, order_id
                    FROM failed_payments
                    WHERE order_id=?
                      AND status NOT IN ('recovered')
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (case_id,)
                ).fetchone()

        # ====================================================
        # MARK CASE AS RECOVERED
        # ====================================================

        if row:

            conn.execute(
                """
                UPDATE failed_payments
                SET status='recovered'
                WHERE order_id=?
                  AND status NOT IN ('recovered')
                """,
                (case_id,)
            )

            # ------------------------------------------------
            # Mark the retry execution as paid.
            # ------------------------------------------------

            conn.execute(
                """
                UPDATE executions
                SET status='paid'
                WHERE order_id=?
                """,
                (payment_order_id,)
            )

            # ------------------------------------------------
            # INITIAL PURCHASE ORDER RECONCILIATION
            # ------------------------------------------------
            orig_order = conn.execute(
                """
                SELECT *
                FROM orders
                WHERE order_id=?
                """,
                (case_id,),
            ).fetchone()

            if orig_order:
                orig_order = dict(orig_order)
                conn.execute(
                    "UPDATE orders SET status='paid' WHERE order_id=?",
                    (case_id,),
                )

                if orig_order.get("purchase_type") == "subscription":
                    from core import get_now
                    started_at = get_now()
                    next_billing_at = started_at + timedelta(days=30)
                    subscription_id = f"sub_{case_id}"

                    existing_sub = conn.execute(
                        "SELECT * FROM subscriptions WHERE subscription_id=?",
                        (subscription_id,),
                    ).fetchone()

                    if not existing_sub:
                        conn.execute(
                            """
                            INSERT INTO subscriptions (
                                subscription_id,
                                phone,
                                plan,
                                amount,
                                status,
                                started_at,
                                next_billing_at,
                                autopay_enabled,
                                payment_method,
                                created_at
                            )
                            VALUES (?, ?, ?, ?, 'active', ?, ?, 1, 'razorpay', ?)
                            """,
                            (
                                subscription_id,
                                orig_order["phone"],
                                orig_order["plan"],
                                orig_order["amount"],
                                started_at.isoformat(),
                                next_billing_at.isoformat(),
                                started_at.isoformat(),
                            ),
                        )
                        activated_sub = {
                            "id": subscription_id,
                            "order_id": case_id,
                            "next_billing_at": next_billing_at.isoformat(),
                        }
                    else:
                        conn.execute(
                            """
                            UPDATE subscriptions
                            SET status='active',
                                autopay_enabled=1,
                                payment_method='razorpay'
                            WHERE subscription_id=?
                            """,
                            (subscription_id,),
                        )

            # ------------------------------------------------
            # SUBSCRIPTION RENEWAL RECONCILIATION
            # ------------------------------------------------
            renewal = conn.execute(
                """
                SELECT subscription_id
                FROM subscription_renewals
                WHERE order_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (case_id,),
            ).fetchone()

            if renewal:
                subscription_id = renewal["subscription_id"]

                conn.execute(
                    """
                    UPDATE subscription_renewals
                    SET status='paid',
                        retry_due_at=NULL
                    WHERE order_id=?
                    """,
                    (case_id,),
                )

                sub_row = conn.execute(
                    "SELECT next_billing_at FROM subscriptions WHERE subscription_id=?",
                    (subscription_id,),
                ).fetchone()

                new_next_billing = None
                if sub_row and sub_row["next_billing_at"]:
                    try:
                        from core import IST
                        cur_billing = datetime.fromisoformat(sub_row["next_billing_at"])
                        if cur_billing.tzinfo is None:
                            cur_billing = cur_billing.replace(tzinfo=IST)
                        new_next_billing = (cur_billing + timedelta(days=30)).isoformat()
                    except Exception:
                        pass

                if not new_next_billing:
                    from core import get_now
                    new_next_billing = (get_now() + timedelta(days=30)).isoformat()

                conn.execute(
                    """
                    UPDATE subscriptions
                    SET next_billing_at=?
                    WHERE subscription_id=?
                    """,
                    (new_next_billing, subscription_id),
                )

    if activated_sub:
        audit_log(
            "subscription",
            "subscription.activated",
            activated_sub["id"],
            {
                "source": "monitoring_webhook",
                "order_id": activated_sub["order_id"],
                "next_billing_at": activated_sub["next_billing_at"],
            },
        )

    # ========================================================
    # CASE RECOVERED
    # ========================================================

    if row:

        audit_log(
            "monitoring",
            "case.recovered",
            case_id,
            {
                "payment_order_id": payment_order_id,
                "note": (
                    "customer paid after recovery touch — "
                    "case closed"
                )
            }
        )

        return {
            "handled": True,
            "recovered": True,
            "case_id": case_id,
            "payment_order_id": payment_order_id
        }

    # ========================================================
    # NO MATCHING CASE
    # ========================================================

    audit_log(
        "monitoring",
        "payment.captured",
        payment_order_id,
        {
            "source": "webhook",
            "note": "no matching recovery case found"
        }
    )

    return {
        "handled": True,
        "recovered": False,
        "case_id": payment_order_id,
        "payment_order_id": payment_order_id
    }