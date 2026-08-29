"""
RecoverFlow Policy-as-Code
==========================
Every recovery rule the agent enforces, with its regulatory source.
This file is the single source of truth. Auditors review this file.

Sources:
- RBI Master Direction on Digital Lending, 2025 (MD-DL-01/2025-26):
    * to stop auto-recovery after 3 unsuccessful attempts... display upfront
    * grievance escalation
- TRAI TCCCPR 2024 (Commercial Communications):
    * promotional/transactional messaging window, DND compliance
- RBI e-Mandate framework (auto-debit circulars, Aug 2019 / Jun 2022):
    * fresh customer consent required before any recurring charge;
      pre-debit notification mandatory
- DPDP Act 2023:
    * purpose limitation + data minimization
"""

# ---------------------------------------------------------------- taxonomy
# Machine-readable failure taxonomy. Codes are OUR canonical codes;
# gateway-specific codes are mapped in classification.py / main.py.

FAILURE_TAXONOMY = {
    "abandoned": {
        "code": "UI-ABANDON",
        "source_regulation": None,  # behavioral, not regulatory
        "strategy": "nudge_now",
        "max_touches": 2,           # abandoned carts: gentler cap
        "cooldown_hours": 6,        # intent is fresh — shorter cycle
    },
    "insufficient_funds": {
        "code": "NPCI-IF-001",
        "source_regulation": "RBI MD-DL: recovery must not harass",
        "strategy": "retry_later",
        "retry_delay_hours": 48,    # salary-cycle aware
        "max_touches": 3,
        "cooldown_hours": 72,
    },
    "declined_card": {
        "code": "HSM-4002",
        "source_regulation": "RBI MD-DL: failed-charge disclosure",
        "strategy": "alt_method",
        "max_touches": 3,
        "cooldown_hours": 24,
    },
    "expired_card": {
        "code": "HSM-4006",
        "source_regulation": "RBI card-on-file norms",
        "strategy": "update_instrument",
        "max_touches": 3,
        "cooldown_hours": 72,
    },
    "stale_mandate": {
        "code": "NPCI-MANDATE-REVOKED",
        "source_regulation": "RBI e-mandate: fresh consent required",
        "strategy": "reauth",
        "max_touches": 1,           # ONE consent request, then human handoff
        "cooldown_hours": 168,
    },
    "gateway_issue": {
        "code": "GW-TRANSIENT",
        "source_regulation": None,  # technical transient, not regulatory
        "strategy": "retry_later",
        "retry_delay_hours": 4,     # transient issues clear quickly
        "max_touches": 3,
        "cooldown_hours": 8,
    },
    "unknown_failure": {
        "code": "UNCLASSIFIED",
        "source_regulation": None,
        "strategy": "escalate",     # -> Claude (Phase 5)
        "max_touches": 0,
        "cooldown_hours": 0,
    },
}

# ---------------------------------------------------------------- guardrails
GUARDRAILS = {
    # TRAI TCCCPR: permitted messaging hours
    "window_start": "10:00",
    "window_end":   "21:00",
    "timezone":     "Asia/Kolkata",

    # RBI MD-DL 2025: stop automated recovery after 3 failed attempts,
    # escalate to human grievance channel
    "global_max_touches": 3,
    "human_escalation_after": 3,

    # Amount ceiling: recovery attempts above this need human approval
    "auto_recovery_amount_ceiling_paise": 500000,   # ₹5,000

    # DPDP Act: data minimization — fields we're allowed to store/use
    "allowed_pii_fields": ["phone", "amount", "plan", "failure_reason"],

    # RBI MD-DL: grievance escalation contact required in recovery comms
    "grievance_contact": "grievance@pulsefit.example",
}

# ---------------------------------------------------------------- messages
# One template per failure type. Every message is:
#   - honest about WHY the payment failed (RBI fair-practice disclosure)
#   - actionable (clear next step matched to the failure cause)
#   - compliant (MESSAGE_SUFFIX appended: opt-out + grievance contact)

MESSAGES = {
    "abandoned":
        "Hi! Your PulseFit {plan} order (₹{amount}) is still waiting 🛒 "
        "Your checkout didn't complete — want to finish it now? {link}",

    "insufficient_funds":
        "Hi! Your PulseFit {plan} payment (₹{amount}) didn't go through — "
        "looks like insufficient balance in your account. No worries! "
        "We'll retry automatically in 48 hours, or pay now: {link}",

    "declined_card":
        "Hi! Your PulseFit {plan} payment (₹{amount}) was declined by your "
        "bank. Your card may still work via UPI — try paying with UPI here: {link}",

    "expired_card":
        "Hi! The card saved for your PulseFit {plan} payment (₹{amount}) "
        "has expired. Update your card and complete payment: {link}",

    "stale_mandate":
        "Hi! Your PulseFit {plan} membership (₹{amount}) auto-pay needs a "
        "one-time re-approval as per RBI rules. Re-approve here: {link}",

    "gateway_issue":
        "Hi! Your PulseFit {plan} payment (₹{amount}) hit a temporary "
        "technical hiccup — no money is lost. We'll retry shortly, "
        "or pay now: {link}",

    "unknown_failure":
        None,   # never messaged — escalated to human/LLM triage
}

# Every recovery message MUST carry an opt-out and grievance contact
# (RBI fair-practice + TRAI TCCCPR compliance).
MESSAGE_SUFFIX = "\n\nReply STOP to opt out. Grievances: {grievance}"

# ---------------------------------------------------------------- helpers
def get_policy(failure_type: str) -> dict:
    """Return the policy block for a failure type (unknown types are
    handled by the caller before this — escalate, never guess)."""
    return FAILURE_TAXONOMY.get(failure_type, FAILURE_TAXONOMY["unknown_failure"])

def build_message(failure_type: str, amount_rupees: int, plan: str,
                  link: str) -> str | None:
    """Build a compliant recovery message, or None if this failure type
    must never be messaged (e.g. unknown_failure)."""
    template = MESSAGES.get(failure_type)
    if template is None:
        return None
    body = template.format(amount=amount_rupees, plan=plan, link=link)
    suffix = MESSAGE_SUFFIX.format(grievance=GUARDRAILS["grievance_contact"])
    return body + suffix
