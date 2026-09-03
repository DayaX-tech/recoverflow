"""
AGENT 4 — SCHEDULER

The heartbeat.

Responsibilities:
- Use the virtual clock owned by core.py
- Wake open cases after their cooldown
- Re-run diagnosis when cases become eligible
- Keep scheduling separate from business decisions

The scheduler knows WHEN to wake a case.
It does NOT know WHAT decision should be made.

Production:
    cron / worker every 15 minutes

Demo:
    frontend ⏩ time-travel button
"""

from datetime import datetime, timedelta, timezone

from core import (
    db,
    audit_log,
    get_now,
    set_clock_offset,
)
from agents import subscriptions


IST = timezone(timedelta(hours=5, minutes=30))


# ============================================================
# DEMO CLOCK
# ============================================================

def jump(hours: float) -> str:
    """
    Move the demo virtual clock forward by `hours`.

    Example:
        jump(2)

    sets the virtual clock to:

        real IST + 2 hours

    The clock itself is owned by core.py.
    """

    if hours < 0:
        raise ValueError("hours must be >= 0")

    # IMPORTANT:
    # set_clock_offset() is a SETTER, not an incrementer.
    #
    # Therefore we read the current virtual time and calculate
    # the new offset relative to real IST.

    current_virtual = get_now()
    current_real = datetime.now(IST)

    current_offset = (
        current_virtual - current_real
    ).total_seconds() / 3600

    new_offset = current_offset + hours

    set_clock_offset(new_offset)

    virtual_now = get_now()

    audit_log(
        "scheduler",
        "clock.jumped",
        "demo_clock",
        {
            "hours": hours,
            "virtual_time": virtual_now.isoformat(),
            "offset_hours": new_offset,
        },
    )

    return virtual_now.isoformat()


def reset_clock() -> str:
    """
    Reset the demo virtual clock back to real IST time.
    """

    set_clock_offset(0)

    virtual_now = get_now()

    audit_log(
        "scheduler",
        "clock.reset",
        "demo_clock",
        {
            "virtual_time": virtual_now.isoformat(),
        },
    )

    return virtual_now.isoformat()


# ============================================================
# RUN DUE CASES
# ============================================================

def run_due(diagnose_fn) -> dict:
    """
    Wake eligible open cases and re-run diagnosis.

    The scheduler decides WHEN a case should be reconsidered.

    The injected diagnose_fn decides WHAT should happen.

    A case becomes eligible after 15 minutes from creation.

    Cases remain 'open' while waiting for a future diagnosis.
    """

    results = []

    # ========================================================
    # LOAD OPEN CASES
    # ========================================================

    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, order_id, created_at
            FROM failed_payments
            WHERE status='open'
            ORDER BY id ASC
            """
        ).fetchall()

    # ========================================================
    # SHARED VIRTUAL TIME
    # ========================================================

    now = get_now()

    # ========================================================
    # CHECK EACH CASE
    # ========================================================

    for row in rows:
        try:
            created_at = datetime.fromisoformat(
                row["created_at"]
            )

            # Existing database records may not have timezone
            # information. Treat them as IST.
            if created_at.tzinfo is None:
                created_at = created_at.replace(
                    tzinfo=IST
                )

        except (TypeError, ValueError):
            audit_log(
                "scheduler",
                "case.skipped_invalid_timestamp",
                row["order_id"],
                {
                    "created_at": row["created_at"],
                },
            )

            continue

        # ====================================================
        # CASE AGE
        # ====================================================

        age = now - created_at

        # Not due yet.
        if age < timedelta(minutes=15):
            continue

        # ====================================================
        # RE-RUN DIAGNOSIS
        # ====================================================

        try:
            diagnosis_result = diagnose_fn(
                row["order_id"]
            )

            results.append(
                {
                    "order_id": row["order_id"],
                    "age_minutes": round(
                        age.total_seconds() / 60,
                        1,
                    ),
                    **diagnosis_result,
                }
            )

        except Exception as exc:
            audit_log(
                "scheduler",
                "diagnosis.failed",
                row["order_id"],
                {
                    "error": str(exc),
                },
            )

            results.append(
                {
                    "order_id": row["order_id"],
                    "error": str(exc),
                }
            )

    # ========================================================
    # AUDIT
    # ========================================================

    audit_log(
        "scheduler",
        "run_due",
        "batch",
        {
            "cases_checked": len(rows),
            "rediagnosed": len(results),
            "virtual_time": now.isoformat(),
        },
    )
        # ============================================================
    # SUBSCRIPTION RENEWALS
    # ============================================================

    renewal_result = subscriptions.run_due_renewals()

    # Send newly created renewal failures into Agent 2.
    for renewal in renewal_result["results"]:
        try:
            diagnosis_result = diagnose_fn(
                renewal["order_id"]
            )

            renewal["diagnosis"] = diagnosis_result

        except Exception as exc:
            audit_log(
                "scheduler",
                "subscription.diagnosis.failed",
                renewal["order_id"],
                {"error": str(exc)},
            )

            renewal["diagnosis_error"] = str(exc)

    return {
        "checked": len(rows),
        "rediagnosed": len(results),
        "subscription_renewals": renewal_result,
        "results": results,
    }

