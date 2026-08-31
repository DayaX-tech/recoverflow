"""
RecoverFlow core — shared utilities for all agents.
Reuses the existing hash-chained audit ledger + pulsefit.db.
"""
import sqlite3
import urllib.parse
from datetime import datetime, time as dtime, timezone, timedelta

import audit
import policy

DB = "pulsefit.db"
IST = timezone(timedelta(hours=5, minutes=30))


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def audit_log(actor, event_type, subject, payload):
    """All agents log here — hash-chained, tamper-evident."""
    audit.audit(actor, event_type, subject, payload)


def normalize_phone(phone: str) -> str:
    """wa.me format: country code + digits only, e.g. 917989342710."""
    digits = "".join(c for c in str(phone) if c.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def messaging_allowed_now():
    """TRAI window check — shared by diagnosis + action agents."""
    g = policy.GUARDRAILS
    start = dtime(*map(int, g["window_start"].split(":")))
    end = dtime(*map(int, g["window_end"].split(":")))
    now = datetime.now(IST).time()
    if start <= now <= end:
        return True, f"within TRAI window ({g['window_start']}–{g['window_end']} IST)"
    return False, f"outside window ({now.strftime('%H:%M')} IST) — QUEUED, not sent"


def build_wa_link(phone: str, message: str) -> str:
    """wa.me deep link with normalized number + url-encoded message."""
    number = normalize_phone(phone) or "919999999999"
    return f"https://wa.me/{number}?text={urllib.parse.quote(message or '')}"
