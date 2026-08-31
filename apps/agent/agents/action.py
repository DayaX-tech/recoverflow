"""
AGENT 3 — ACTION

The only agent allowed to reach external payment infrastructure.

Responsibilities:
- Execute an approved decision
- Create retry Razorpay order
- Build compliant customer message
- Prepare WhatsApp deep link
- Record execution

Never:
- Diagnose
- Change strategy
- Execute queued/refused/escalated decisions
"""

from datetime import datetime

import policy
from core import (
    db,
    audit_log,
    normalize_phone,
    build_wa_link,
)


def execute_latest_decision(
    case_id: str,
    store_base: str,
    rzp_client,
) -> dict:
    """
    Execute the latest decision for a case.

    Only decisions with status='decided' may execute.
    """

    with db() as conn:
        case = conn.execute(
            """
            SELECT *
            FROM failed_payments
            WHERE order_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()

        decision = conn.execute(
            """
            SELECT *
            FROM agent_decisions
            WHERE case_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()

    if not case or not decision:
        return {
            "executed": False,
            "reason": "case or decision not found",
        }

    case = dict(case)
    decision = dict(decision)

    # =========================================================
    # EXECUTION GUARD
    # =========================================================
    if decision["status"] != "decided":
        return {
            "executed": False,
            "reason": (
                f"decision status is '{decision['status']}' "
                "— not executable"
            ),
        }

    # =========================================================
    # CASE SAFETY
    # =========================================================
    if case["status"] not in ("open", "diagnosed"):
        return {
            "executed": False,
            "reason": (
                f"case status is '{case['status']}' "
                "— case is not executable"
            ),
        }

    amount = case["amount"]

    # =========================================================
    # CREATE RETRY RAZORPAY ORDER
    # =========================================================
    try:
        retry_order = rzp_client.order.create(
            {
                "amount": amount,
                "currency": "INR",
                "receipt": f"rf_{case_id}",
                "notes": {
                    "case_id": case_id,
                    "original_failure": case["failure_type"],
                },
            }
        )

    except Exception as exc:
        audit_log(
            "action",
            "execution.failed",
            case_id,
            {"error": str(exc)},
        )

        return {
            "executed": False,
            "reason": f"razorpay error: {exc}",
        }

    # =========================================================
    # BUILD PAYMENT LINK
    # =========================================================
    link = (
        f"{store_base}/pay.html"
        f"?oid={retry_order['id']}"
        f"&case={case_id}"
    )

    # =========================================================
    # BUILD CUSTOMER MESSAGE
    # =========================================================
    message = policy.build_message(
        case["failure_type"],
        amount // 100,
        case["plan"] or "order",
        link,
    )

    # =========================================================
    # BUILD WHATSAPP DEEP LINK
    # =========================================================
    whatsapp_link = build_wa_link(
        case["phone"],
        message,
    )

    normalized_phone = normalize_phone(
        case["phone"] or ""
    )

    # =========================================================
    # RECORD EXECUTION
    # =========================================================
    with db() as conn:
        conn.execute(
            """
            INSERT INTO executions (
                case_id,
                order_id,
                strategy,
                channel,
                message,
                link,
                status,
                executed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'sent', ?)
            """,
            (
                case_id,
                retry_order["id"],
                decision["strategy"],
                decision["channel"],
                message,
                link,
                datetime.now().isoformat(),
            ),
        )

        conn.commit()

    audit_log(
        "action",
        "execution.sent",
        case_id,
        {
            "strategy": decision["strategy"],
            "retry_order": retry_order["id"],
            "wa_to": normalized_phone,
        },
    )

    return {
        "executed": True,
        "case_id": case_id,
        "strategy": decision["strategy"],
        "retry_order_id": retry_order["id"],
        "amount": amount,
        "payment_link": link,
        "whatsapp_link": whatsapp_link,
        "note": (
            "wa.me deep-link now; "
            "WhatsApp Business API in production"
        ),
    }