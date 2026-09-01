"""
AGENT 2 — DIAGNOSIS

Responsibilities:
- Read open cases
- Apply policy taxonomy
- Apply recovery guardrails
- Produce a decision
- Record the decision

Never:
- Send messages
- Create Razorpay orders
- Execute recovery
"""

from core import (
    db,
    audit_log,
    messaging_allowed_now,
    get_now,
)

import policy


def diagnose(case_id: str = None) -> dict:
    """
    Diagnose one case or all open cases.

    Decision statuses:
        decided
        queued
        refused
        escalated
        human_handoff
    """

    # =========================================================
    # LOAD OPEN CASES
    # =========================================================

    with db() as conn:
        if case_id:
            rows = conn.execute(
                """
                SELECT *
                FROM failed_payments
                WHERE order_id=?
                  AND status='open'
                """,
                (case_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM failed_payments
                WHERE status='open'
                ORDER BY id ASC
                """
            ).fetchall()

    decisions = []

    # =========================================================
    # DIAGNOSE EACH CASE
    # =========================================================

    for row in rows:
        case = dict(row)

        taxonomy = policy.FAILURE_TAXONOMY.get(
            case["failure_type"],
            policy.FAILURE_TAXONOMY["unknown_failure"],
        )

        # =====================================================
        # GATE 1 — JURISDICTION
        # =====================================================

        if case["failure_source"] == "cod":
            decision = {
                "case_id": case["order_id"],
                "failure_type": case["failure_type"],
                "diagnosis_code": "OUT-OF-SCOPE",
                "in_scope": False,
                "strategy": "none",
                "channel": "none",
                "message": None,
                "reasoning": (
                    "REFUSED: outside recovery jurisdiction (COD)."
                ),
                "status": "refused",
            }

        # =====================================================
        # GATE 2 — UNKNOWN / UNCLASSIFIED FAILURE
        # =====================================================

        elif (
            case["failure_type"] == "unknown_failure"
            or "strategy" not in taxonomy
        ):
            decision = {
                "case_id": case["order_id"],
                "failure_type": case["failure_type"],
                "diagnosis_code": "UNCLASSIFIED",
                "in_scope": True,
                "strategy": "escalate",
                "channel": "none",
                "message": None,
                "reasoning": (
                    "No deterministic rule matched — "
                    "flagged for LLM triage (Phase 5)."
                ),
                "status": "escalated",
            }

        else:
            # =================================================
            # GATE 3 — TOUCH CAP
            # =================================================

            with db() as conn:
                nudges = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM agent_decisions
                    WHERE case_id=?
                      AND in_scope=1
                    """,
                    (case["order_id"],),
                ).fetchone()[0]

            max_touches = min(
                taxonomy.get("max_touches", 3),
                policy.GUARDRAILS["global_max_touches"],
            )

            if nudges >= max_touches:
                decision = {
                    "case_id": case["order_id"],
                    "failure_type": case["failure_type"],
                    "diagnosis_code": taxonomy["code"],
                    "in_scope": True,
                    "strategy": "stop",
                    "channel": "none",
                    "message": None,
                    "reasoning": (
                        f"REFUSED: {nudges} touches >= cap "
                        f"{max_touches} "
                        f"(RBI MD-DL: stop automated recovery, "
                        f"escalate to human "
                        f"{policy.GUARDRAILS['grievance_contact']})."
                    ),
                    "status": "human_handoff",
                }

            else:
                # =============================================
                # GATE 4 — TRAI MESSAGING WINDOW
                # =============================================

                # IMPORTANT:
                # The virtual clock is owned by core.py.
                # Never use datetime.now() here.
                now = get_now()

                allowed, reason = messaging_allowed_now(now)

                if not allowed:
                    decision = {
                        "case_id": case["order_id"],
                        "failure_type": case["failure_type"],
                        "diagnosis_code": taxonomy["code"],
                        "in_scope": True,
                        "strategy": "queued",
                        "channel": "none",
                        "message": None,
                        "reasoning": f"DEFERRED: {reason}",
                        "status": "queued",
                    }

                else:
                    # Message creation belongs to Agent 3 / ACTION.
                    # Agent 2 only decides the strategy.

                    decision = {
                        "case_id": case["order_id"],
                        "failure_type": case["failure_type"],
                        "diagnosis_code": taxonomy["code"],
                        "in_scope": True,
                        "strategy": taxonomy["strategy"],
                        "channel": "whatsapp",
                        "message": None,
                        "reasoning": (
                            f"Policy for {case['failure_type']} "
                            f"(source: "
                            f"{taxonomy.get('source_regulation') or 'behavioral'}"
                            f"); touch "
                            f"{nudges + 1}/{max_touches}."
                        ),
                        "status": "decided",
                    }

        # =====================================================
        # RECORD DECISION
        # =====================================================

        _record_decision(case, decision)
        decisions.append(decision)

    return {
        "processed": len(decisions),
        "decisions": decisions,
    }


# =============================================================
# RECORD DECISION
# =============================================================

def _record_decision(case: dict, decision: dict) -> None:
    """
    Persist the diagnosis decision and audit it.

    `created_at` uses the shared virtual clock so the demo
    database remains consistent with the simulated time.

    Queued cases remain open so Agent 4 can find them later.
    """

    with db() as conn:
        conn.execute(
            """
            INSERT INTO agent_decisions (
                case_id,
                failure_type,
                diagnosis_code,
                in_scope,
                strategy,
                channel,
                message,
                reasoning,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision["case_id"],
                decision["failure_type"],
                decision["diagnosis_code"],
                int(decision["in_scope"]),
                decision["strategy"],
                decision["channel"],
                decision["message"],
                decision["reasoning"],
                decision["status"],
                get_now().isoformat(),
            ),
        )

        # Queued cases remain OPEN.
        #
        # Any other terminal/intermediate decision moves the
        # failed payment out of the scheduler's open queue.

        if decision["status"] != "queued":
            conn.execute(
                """
                UPDATE failed_payments
                SET status='diagnosed'
                WHERE id=?
                """,
                (case["id"],),
            )

        conn.commit()

    audit_log(
        "agent" if decision["status"] == "decided" else "guardrail",
        f"decision.{decision['status']}",
        decision["case_id"],
        {
            "strategy": decision["strategy"],
            "reasoning": decision["reasoning"],
        },
    )

