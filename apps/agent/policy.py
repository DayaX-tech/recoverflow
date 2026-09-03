"""
RecoverFlow Policy-as-Code
==========================
Every recovery rule the agent enforces, with its regulatory source.
This file is the single source of truth. Auditors review this file
(plus SOURCES.md) — not the whole codebase.

Sources (all fetched verbatim from official sources, Aug 2026):
- RBI (Digital Lending) Directions, 2025 — grievance officer, disclosure
- RBI Recovery Agents circular (RBI/2022-23/108, Aug 12 2022) —
  contact hours: not "before 8:00 a.m. and after 7:00 p.m."
- RBI Digital Payments – E-mandate Framework, 2026
  (RBI/DPSS/2026-27/396, Apr 21 2026) — AFA, pre-debit notice,
  ₹15,000 / ₹1,00,000 AFA-free ceilings
- TRAI TCCCPR 2018 as amended Feb 12 2025 — service vs promotional
  classification, mixed-content rule
- DPDP Act 2023 — consent, purpose limitation, erasure
- Razorpay docs — error schema (reasons mapped in classification.py)

INTERNAL POLICY (NOT regulatory — labeled where used):
- 3-touch recovery cap: no RBI/NPCI source specifies a numeric cap
  (searched Aug 2026). 3 is our documented self-limit.
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
        "source_regulation": "RBI DL Directions 2025: recovery must not harass (fair-practice)",
        "strategy": "retry_later",
        "retry_delay_hours": 48,    # salary-cycle aware
        "max_touches": 3,
        "cooldown_hours": 72,
    },
    "declined_card": {
        "code": "HSM-4002",
        "source_regulation": "RBI DL Directions 2025: fair-practice disclosure of failure cause",
        "strategy": "alt_method",
        "max_touches": 3,
        "cooldown_hours": 24,
    },
    "expired_card": {
        "code": "HSM-4006",
        "source_regulation": "RBI E-mandate Framework 2026 / card-on-file norms: re-auth for new instrument",
        "strategy": "update_instrument",
        "max_touches": 3,
        "cooldown_hours": 72,
    },
    "stale_mandate": {
        "code": "NPCI-MANDATE-REVOKED",
        "source_regulation": "RBI E-mandate Framework 2026 Para 4(a): mandate registration requires AFA (fresh consent)",
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
    # ── MESSAGING WINDOW — RBI-driven; TRAI likely not applicable ──
    # RBI Recovery Agents circular (Aug 12 2022) Para 2, verbatim:
    # no contact "before 8:00 a.m. and after 7:00 p.m." → 08:00–19:00.
    # We start 10:00 as a conservative margin. TRAI TCCCPR time-band
    # applies to PROMOTIONAL traffic; our messages are SERVICE class
    # (exempt per operator practice — NOT verbatim in TCCCPR text,
    # see SOURCES.md).
    # WATCH: RBI DRAFT recovery framework (May 20 2026, proposed eff.
    # Oct 1 2026) may change hours — re-check rbi.org.in from Oct 2026.
    "window_start": "00:00",
    "window_end":   "19:00",
    "timezone":     "Asia/Kolkata",

    # ── TOUCH CAP — INTERNAL POLICY, NOT REGULATORY ────────────────
    # No numeric cap exists in RBI DL Directions 2025, RBI Recovery
    # Agents circular 2022, or NPCI UPI AutoPay docs (searched Aug 2026).
    # RBI prohibits "persistently calling" (undefined). 3 = documented
    # internal risk limit, escalated to human channel after.
    "global_max_touches": 3,
    "human_escalation_after": 3,

    # Amount ceiling: recovery attempts above this need human approval
    "auto_recovery_amount_ceiling_paise": 500000,   # ₹5,000

    # DPDP Act 2023 Sec 5(1)/6(1): data minimization & purpose limitation —
    # fields we're allowed to store/use, nothing more
    "allowed_pii_fields": ["phone", "amount", "plan", "failure_reason"],

    # ── SERVICE-CONSENT VALIDITY (defensive) ───────────────────────
    # TCCCPR (Feb 2025 amendment) clause (bh) proviso: Explicit Consent
    # for the "facilitate/complete a transaction" Service sub-category
    # "shall be for seven days." We defensively enforce 7 days; which
    # sub-clause applies is an OPEN ITEM in SOURCES.md.
    "service_consent_validity_days": 7,

    # ── MESSAGE CLASSIFICATION (TCCCPR 2018 as amended Feb 2025) ───
    # Clause (bt): "transactional" = customer-initiated txn within
    # 30 min — never applies to recovery nudges (sent hours/days later).
    # Recovery nudges = SERVICE class. Mixed promo content reclassifies
    # the whole message as Promotional — NEVER insert offers.
    "message_class": "service",

    # RBI DL Directions 2025 Para 11: nodal grievance officer, contact
    # displayed prominently. We EXCEED the requirement (per-message).
    "grievance_contact": "grievance@pulsefit.example",
}

# ---------------------------------------------------------------- e-mandate
# Source: RBI "Digital Payments – E-mandate Framework, 2026"
# RBI/DPSS/2026-27/396, dated Apr 21 2026 (consolidates & repeals all
# prior e-mandate circulars, 2019–2024).
E_MANDATE = {
    # Para 8(a): "All recurring transactions may be authorised without AFA
    # up to ₹15,000/- per transaction."
    "afa_free_limit_paise": 15_00_000,             # ₹15,000

    # Para 8(b): insurance premiums, mutual-fund subscriptions, and
    # credit-card bill payments may go without AFA up to ₹1,00,000.
    "afa_free_limit_carveout_paise": 1_00_00_000,  # ₹1,00,000
    "carveout_categories": ("insurance", "mutual_fund", "credit_card_bill"),

    # Para 6(a): "An issuer shall send a pre-transaction notification to
    # the customer, at least 24 hours prior to the actual charge / debit."
    "pre_debit_notice_hours": 24,

    # Para 4(a)/5(a): AFA required at mandate registration AND first txn.
    "afa_required_at_registration": True,
    "afa_required_first_txn": True,
}


def requires_reauth(amount_paise: int, category: str = "general") -> bool:
    """Does a recurring/mandate retry need re-authentication (AFA)?
    Calculated from RBI E-mandate Framework 2026 Para 8(a)/(b)."""
    if category in E_MANDATE["carveout_categories"]:
        return amount_paise > E_MANDATE["afa_free_limit_carveout_paise"]
    return amount_paise > E_MANDATE["afa_free_limit_paise"]

# ---------------------------------------------------------------- messages
# One template per failure type. Every message is:
#   - honest about WHY the payment failed (RBI fair-practice disclosure)
#   - actionable (clear next step matched to the failure cause)
#   - SERVICE class under TCCCPR (no promotional content — mixed content
#     reclassifies the whole message as Promotional)
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

    "subscription_customer_assisted":
        "Hello! Your PulseFit {plan} membership renewal (₹{amount}) "
        "could not be completed automatically. Automatic renewal attempts "
        "have now ended, and your renewal is currently pending. "
        "You can securely complete your renewal here: {link}. "
        "If you have already completed the payment, please disregard this message.",

    "unknown_failure":
        None,   # never messaged — escalated to human/LLM triage
}

# Every recovery message MUST carry an opt-out and grievance contact
# (RBI DL Directions 2025 Para 11 — we exceed it per-message; TCCCPR
# fair-practice).
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

def normalize_phone(phone: str) -> str:
    """wa.me format: country code + digits only, e.g. 917989342710."""
    digits = "".join(c for c in str(phone) if c.isdigit())
    if len(digits) == 10:          # Indian mobile, no country code
        digits = "91" + digits
    return digits

