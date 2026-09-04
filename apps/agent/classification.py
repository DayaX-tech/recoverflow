"""
RecoverFlow — Vendor Mapping Layer
==================================
The ONLY file that knows Razorpay's error schema. If you swap
Razorpay for Stripe/PayU later, you edit THIS file only.

Sources: razorpay.com/docs/errors (verified Aug 2026) + live
webhook evidence (error_reason can be empty — description fallback
added after real webhook order_TWBdza5b1YXJpT misclassified).

Razorpay payment entity fields used:
  error_source  → customer | gateway | bank | internal
  error_reason  → machine reason (e.g. insufficient_funds)
  error_code    → e.g. BAD_REQUEST_ERROR, GATEWAY_ERROR
  error_description → human text (sometimes the ONLY clue)

Rule: never silently retry customer-caused declines.
"""

# Razorpay error_reason → (canonical_type, recommended_action)
REASON_MAP = {
    # ── customer-caused — never auto-retry the same instrument ──
    "insufficient_funds":         ("insufficient_funds", "retry_later"),
    "card_expired":               ("expired_card",       "new_instrument"),
    "card_declined":              ("declined_card",      "contact_bank_or_alt"),
    "authentication_failed":      ("declined_card",      "retry_now"),
    "incorrect_otp":              ("declined_card",      "retry_now"),
    "incorrect_cvv":              ("declined_card",      "retry_now"),
    "payment_timed_out":          ("abandoned",          "retry_now"),
    "payment_cancelled":          ("abandoned",          "retry_now"),
    "transaction_limit_exceeded": ("limit_hit",          "alt_instrument"),
    "payment_risk_check_failed":  ("declined_card",      "contact_bank"),
    "debit_instrument_blocked":   ("declined_card",      "contact_bank"),
    "invalid_vpa":                ("bad_vpa",            "fix_vpa"),
    # card-type / issuer-eligibility (customer-caused)
    "card_type_not_supported":    ("declined_card",      "alt_instrument"),
    "issuer_not_available":       ("declined_card",      "contact_bank_or_alt"),
    "international_not_allowed":  ("declined_card",      "alt_instrument"),
    "international_transaction_not_allowed": ("declined_card", "alt_instrument"),
    "payment_failed":             ("declined_card",      "contact_bank_or_alt"),

    # ── gateway/bank-caused — transient, auto-retry eligible ────
    "gateway_technical_error":    ("gateway_issue",      "auto_retry_later"),
    "bank_technical_error":       ("gateway_issue",      "auto_retry_later"),
    "issuer_technical_error":     ("gateway_issue",      "auto_retry_later"),
    "bank_not_available":         ("gateway_issue",      "auto_retry_later"),
    "vpa_resolution_failed":      ("gateway_issue",      "support_ticket"),

    # ── mandate / autopay ──────────────────────────────────────
    "mandate_creation_declined":  ("stale_mandate",      "reauth_mandate"),
    "mandate_creation_failed":    ("stale_mandate",      "reauth_mandate"),
    "funds_blocked_by_mandate":   ("stale_mandate",      "reauth_mandate"),
}

# error_code fallback when reason is empty
CODE_MAP = {
    "BAD_REQUEST_ERROR": "unknown_failure",
    "GATEWAY_ERROR":     "gateway_issue",
    "SERVER_ERROR":      "gateway_issue",
}


def classify(ent: dict) -> tuple[str, str, str]:
    """Returns (canonical_type, recommended_action, detail_string).
    `ent` = payment entity from the payment.failed webhook payload."""
    reason = (ent.get("error_reason") or "").strip()
    source = (ent.get("error_source") or "?").strip()
    code   = (ent.get("error_code") or "?").strip()
    desc   = (ent.get("error_description") or "").strip()
    method = (ent.get("method") or "").strip().lower()

    detail = f"{desc} [{source}/{reason or code}]"

    # 1) exact machine-reason match (best case)
    if reason in REASON_MAP:
        ftype, action = REASON_MAP[reason]
        return ftype, action, detail

    # 2) fallback: reason empty/unmapped — scan description text & method
    d = desc.lower()
    if method == "card" or source in ("issuer", "customer") or "card" in d:
        if any(k in d for k in ("declined", "refunded", "temporary", "not through", "failed", "reject")):
            return "declined_card", "contact_bank_or_alt", detail

    if any(k in d for k in ("domestic", "international",
                            "another payment method",
                            "not supported", "not enabled",
                            "declined")):
        return "declined_card", "alt_instrument", detail
    if any(k in d for k in ("insufficient", "balance")):
        return "insufficient_funds", "retry_later", detail
    if any(k in d for k in ("authentication", "otp", "cvv")):
        return "declined_card", "retry_now", detail
    if any(k in d for k in ("technical", "temporarily", "try again",
                            "bank", "issuer")):
        return "gateway_issue", "auto_retry_later", detail

    # 3) last resort — escalate, never guess
    return CODE_MAP.get(code, "unknown_failure"), "escalate", detail
