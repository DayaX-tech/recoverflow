"""
SUBSCRIPTION RENEWAL ENGINE

Responsible for:
- Finding subscriptions whose billing time is due
- Creating a renewal attempt
- Simulating the autopay result for the demo
- Filing a normal failed_payments case on failure

It does NOT:
- Diagnose failures
- Choose recovery strategies
- Send customer messages

Agent 2 remains responsible for diagnosis and policy.
"""

from datetime import timedelta,  datetime

from core import db, audit_log, get_now


def run_due_renewals(
    failure_type: str = "insufficient_funds",
) -> dict:
    """
    Process subscriptions whose next billing time has arrived.

    Demo behavior:
        The renewal attempt intentionally fails with the
        supplied failure_type so the existing recovery
        pipeline can be demonstrated.

    Returns a summary of processed renewals.
    """

    now = get_now()

    with db() as conn:

        subscriptions = conn.execute(
        """
        SELECT *
        FROM subscriptions
        WHERE status='active'
          AND autopay_enabled=1
          AND (
                next_billing_at<=?
                OR subscription_id IN (
                    SELECT subscription_id
                    FROM subscription_renewals
                    WHERE status='failed'
                      AND retry_due_at IS NOT NULL
                      AND retry_due_at<=?
                )
          )
        ORDER BY id ASC
        """,
        (
            now.isoformat(),
            now.isoformat(),
        ),
        ).fetchall()

    results = []

    for subscription in subscriptions:

        subscription = dict(subscription)

        subscription_id = subscription["subscription_id"]

        # =====================================================
        # PREVENT DUPLICATE RENEWAL FOR THE SAME BILLING DATE
        # =====================================================

        billing_at = subscription["next_billing_at"]

        with db() as conn:
            latest = conn.execute(
        """
        SELECT *
        FROM subscription_renewals
        WHERE subscription_id=?
        ORDER BY attempt_number DESC
        LIMIT 1
        """,
        (subscription_id,),
    ).fetchone()

        if latest:
            latest = dict(latest)

    # A failed attempt can only be retried
    # once its scheduled retry time arrives.
            if latest["status"] == "failed":
                retry_due_at_value = latest.get("retry_due_at")

                if not retry_due_at_value:
                    continue

                try:
                    retry_due_at_check = datetime.fromisoformat(
                    retry_due_at_value
                )
                except (TypeError, ValueError):
                    continue

                if now < retry_due_at_check:
                    continue

    # Prevent another renewal if the latest attempt
    # has not failed.
        else:
            continue

        # =====================================================
        # DETERMINE ATTEMPT NUMBER
        # =====================================================

        with db() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(attempt_number), 0) AS last_attempt
                FROM subscription_renewals
                WHERE subscription_id=?
                """,
                (subscription_id,),
            ).fetchone()

        attempt_number = int(row["last_attempt"] or 0) + 1
                # =====================================================
        # AUTOMATIC RETRY LIMIT
        # =====================================================

        if attempt_number > 3:
            audit_log(
                "subscriptions",
                "renewal.retry_limit_reached",
                subscription_id,
                {
                    "attempt_number": attempt_number,
                    "reason": "automatic_retry_limit_reached",
                },
            )

            continue

                # =====================================================
        # RETRY SCHEDULE
        # =====================================================

        retry_due_at = now + timedelta(hours=48)

        # =====================================================
        # DEMO RENEWAL ORDER ID
        # =====================================================

        renewal_order_id = (
            f"renewal_{subscription_id}_{attempt_number}"
        )

        # =====================================================
        # FILE RENEWAL ATTEMPT
        # =====================================================

        with db() as conn:

            conn.execute(
                """
                INSERT INTO subscription_renewals (
                    subscription_id,
                    attempt_number,
                    billing_at,
                    order_id,
                    status,
                    failure_type,
                    created_at,
                    retry_due_at

                )
                VALUES (?, ?, ?, ?, 'failed', ?, ?, ?)
                """,
                (
                    subscription_id,
                    attempt_number,
                    billing_at,
                    renewal_order_id,
                    failure_type,
                    now.isoformat(),
                    retry_due_at.isoformat(),
                ),
            )

            # =================================================
            # CREATE NORMAL RECOVERY CASE
            # =================================================

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
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (
                    renewal_order_id,
                    subscription["phone"],
                    subscription["plan"],
                    subscription["amount"],
                    failure_type,
                    "subscription_renewal",
                    (
                        f"Subscription renewal attempt "
                        f"{attempt_number} failed "
                        f"at {billing_at}"
                    ),
                    now.isoformat(),
                ),
            )

        audit_log(
            "subscriptions",
            "renewal.failed",
            subscription_id,
            {
                "attempt_number": attempt_number,
                "order_id": renewal_order_id,
                "failure_type": failure_type,
                "billing_at": billing_at,
            },
        )

        results.append(
            {
                "subscription_id": subscription_id,
                "attempt_number": attempt_number,
                "order_id": renewal_order_id,
                "failure_type": failure_type,
                "status": "failed",
            }
        )

    return {
        "checked": len(subscriptions),
        "renewed": 0,
        "failed": len(results),
        "results": results,
        "virtual_time": now.isoformat(),
    }