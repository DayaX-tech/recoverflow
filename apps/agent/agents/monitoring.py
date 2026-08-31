"""
AGENT 1 — MONITORING

Responsibilities:
- Verify Razorpay webhook signatures
- Ingest payment events
- Classify gateway failures
- Prevent duplicate webhook cases
- Ignore already-resolved orders
- Record payment recovery

Never:
- Make recovery decisions
- Compose customer messages
- Execute recovery actions
"""

import hashlib
import hmac
import os
from datetime import datetime

from core import db, audit_log


def verify_signature(raw_body: bytes, signature: str) -> bool:
    """Verify Razorpay webhook HMAC-SHA256 signature."""
    secret = os.getenv(
        "RAZORPAY_WEBHOOK_SECRET",
        "rf_webhook_secret_2025",
    )

    expected = hmac.new(
        secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature or "")


def handle_failed_payment(ent: dict, orders_lookup) -> dict:
    """
    Process a Razorpay payment.failed event.

    One Razorpay order = one webhook-sourced failure case.
    Repeated webhook deliveries update the existing case.
    """

    from classification import classify_gateway_error

    err = ent.get("error_description", "unknown error")
    code = ent.get("error_code", "?")

    failure_type = classify_gateway_error(err, code)

    order_id = ent.get(
        "order_id",
        f"case_{int(datetime.now().timestamp())}",
    )

    # ---------------------------------------------------------
    # BUSINESS IDEMPOTENCY
    # Never create recovery cases for already-resolved orders.
    # ---------------------------------------------------------
    with db() as conn:
        order = conn.execute(
            "SELECT status FROM orders WHERE order_id=?",
            (order_id,),
        ).fetchone()

    if order and order["status"] in ("paid", "cod_confirmed"):
        audit_log(
            "monitoring",
            "case.skipped_already_resolved",
            order_id,
            {"order_status": order["status"]},
        )

        return {
            "handled": "failed_ignored",
            "reason": f"order_{order['status']}",
        }

    # Razorpay may provide contact/amount directly.
    # Fall back to our orders table when necessary.
    phone = ent.get("contact") or ""
    plan = "membership"
    amount = ent.get("amount", 0)

    if not phone or amount == 0:
        order_row = orders_lookup(order_id)

        if order_row:
            phone = phone or order_row["phone"]
            plan = plan if amount else order_row["plan"]
            amount = amount or order_row["amount"]

    detail = f"{err} [{code}]"

    outcome = _file_or_update_webhook_case(
        order_id=order_id,
        phone=phone,
        plan=plan,
        amount=amount,
        failure_type=failure_type,
        detail=detail,
    )

    return {
        "handled": "failed",
        "case_id": order_id,
        "classified_as": failure_type,
        "case": outcome,
        "should_diagnose": outcome == "filed",
    }


def _file_or_update_webhook_case(
    order_id,
    phone,
    plan,
    amount,
    failure_type,
    detail,
):
    """
    Webhook idempotency.

    A webhook retry updates the existing webhook case instead
    of inserting another failure record.
    """

    with db() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM failed_payments
            WHERE order_id=?
              AND failure_source='webhook'
            """,
            (order_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE failed_payments
                SET failure_type=?,
                    raw_detail=?,
                    status='open'
                WHERE order_id=?
                  AND failure_source='webhook'
                """,
                (
                    failure_type,
                    detail,
                    order_id,
                ),
            )
            conn.commit()

            audit_log(
                "monitoring",
                "case.updated",
                order_id,
                {"failure_type": failure_type},
            )

            return "updated"

    _file_case(
        order_id,
        phone,
        plan,
        amount,
        failure_type,
        "webhook",
        detail,
    )

    return "filed"


def _file_case(
    order_id,
    phone,
    plan,
    amount,
    failure_type,
    source,
    detail,
):
    """Create a new failure case."""
    with db() as conn:
        conn.execute(
            """
            INSERT INTO failed_payments (
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
                failure_type,
                source,
                detail,
                datetime.now().isoformat(),
            ),
        )

    audit_log(
        source,
        "case.filed",
        order_id,
        {
            "failure_type": failure_type,
            "source": source,
        },
    )


def handle_captured_payment(ent: dict) -> dict:
    """
    Handle payment.captured.

    Marks the original order as paid and closes a recovery
    case when the payment came through a retry execution.
    """

    order_id = ent.get("order_id", "?")
    payment_id = ent.get("id", "")

    with db() as conn:
        conn.execute(
            "UPDATE orders SET status='paid' WHERE order_id=?",
            (order_id,),
        )

        execution = conn.execute(
            """
            SELECT *
            FROM executions
            WHERE order_id=?
            LIMIT 1
            """,
            (payment_id,),
        ).fetchone()

        if execution:
            case_id = execution["case_id"]

            conn.execute(
                """
                UPDATE executions
                SET status='paid'
                WHERE order_id=?
                """,
                (payment_id,),
            )

            conn.execute(
                """
                UPDATE failed_payments
                SET status='recovered'
                WHERE order_id=?
                """,
                (case_id,),
            )

            audit_log(
                "monitoring",
                "recovery.success",
                case_id,
                {
                    "via": "retry_link",
                    "amount": ent.get("amount"),
                },
            )

        conn.commit()

    return {
        "handled": "captured",
        "order_id": order_id,
    }