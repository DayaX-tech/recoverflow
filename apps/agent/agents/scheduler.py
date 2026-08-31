"""
AGENT 4 — SCHEDULER

The heartbeat.

Responsibilities:
- Own the demo virtual clock
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

import threading
from datetime import datetime, timedelta, timezone

from core import db, audit_log


IST = timezone(timedelta(hours=5, minutes=30))

# Demo-only virtual clock offset.
_offset = timedelta(0)

# Prevent concurrent jump/reset operations.
_lock = threading.Lock()


def _now() -> datetime:
    """Return the current virtual IST time."""
    with _lock:
        current_offset = _offset

    return datetime.now(IST) + current_offset


def jump(hours: float) -> str:
    """
    Move the demo clock forward.

    Example:
        jump(2)
        -> virtual time moves forward by 2 hours.

    This affects scheduler timing only.
    It does not modify database timestamps.
    """

    if hours < 0:
        raise ValueError("hours must be >= 0")

    global _offset

    with _lock:
        _offset += timedelta(hours=hours)
        virtual_now = datetime.now(IST) + _offset

    audit_log(
        "scheduler",
        "clock.jumped",
        "demo_clock",
        {
            "hours": hours,
            "virtual_time": virtual_now.isoformat(),
        },
    )

    return virtual_now.isoformat()


def reset_clock() -> str:
    """Reset the demo virtual clock back to real IST time."""

    global _offset

    with _lock:
        _offset = timedelta(0)
        virtual_now = datetime.now(IST)

    audit_log(
        "scheduler",
        "clock.reset",
        "demo_clock",
        {
            "virtual_time": virtual_now.isoformat(),
        },
    )

    return virtual_now.isoformat()


def run_due(diagnose_fn) -> dict:
    """
    Wake eligible open cases and re-run diagnosis.

    The scheduler only decides WHEN a case should be reconsidered.
    The injected diagnose_fn decides WHAT should happen.

    A case becomes eligible after 15 minutes from creation.

    Cases remain 'open' while waiting for a future diagnosis.
    """

    results = []

    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, order_id, created_at
            FROM failed_payments
            WHERE status='open'
            ORDER BY id ASC
            """
        ).fetchall()

    now = _now()

    for row in rows:
        try:
            created_at = datetime.fromisoformat(row["created_at"])

            # Handle old records stored without timezone information.
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=IST)

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

        age = now - created_at

        # Not due yet.
        if age < timedelta(minutes=15):
            continue

        try:
            diagnosis_result = diagnose_fn(row["order_id"])

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

    return {
        "checked": len(rows),
        "rediagnosed": len(results),
        "results": results,
    }