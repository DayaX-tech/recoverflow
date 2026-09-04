"""
RecoverFlow core — shared utilities for all agents.

Reuses the existing hash-chained audit ledger + pulsefit.db.

The virtual clock is owned here so every agent sees the
same demo time.
"""

import sqlite3
import urllib.parse
from datetime import datetime, time as dtime, timezone, timedelta

import audit
import policy


# ============================================================
# CONFIGURATION
# ============================================================

DB = "pulsefit.db"

IST = timezone(timedelta(hours=5, minutes=30))


# ============================================================
# DATABASE
# ============================================================

def db():
    """Return a SQLite connection using the shared database."""
    conn = sqlite3.connect(DB, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# AUDIT
# ============================================================

def audit_log(actor, event_type, subject, payload):
    """All agents log here — hash-chained, tamper-evident."""
    audit.audit(
        actor,
        event_type,
        subject,
        payload,
    )


# ============================================================
# PHONE / WHATSAPP
# ============================================================

def normalize_phone(phone: str) -> str:
    """
    Convert a phone number into wa.me format.

    Example:
        7989342710
        -> 917989342710
    """

    digits = "".join(
        c for c in str(phone)
        if c.isdigit()
    )

    if len(digits) == 10:
        digits = "91" + digits

    return digits


def build_wa_link(phone: str, message: str) -> str:
    """
    Build a WhatsApp deep link with a normalized number
    and URL-encoded message.
    """

    number = normalize_phone(phone) or "919999999999"

    return (
        f"https://wa.me/{number}"
        f"?text={urllib.parse.quote(message or '')}"
    )


# ============================================================
# VIRTUAL CLOCK
# ============================================================

_clock_offset_hours = 0.0


def set_clock_offset(hours: float):
    """
    Set the demo virtual-clock offset.

    Example:

        set_clock_offset(2)

    means:

        virtual time = real IST time + 2 hours

    The value is stored centrally so every agent uses the
    same virtual clock.
    """

    global _clock_offset_hours

    _clock_offset_hours = float(hours)


def get_now() -> datetime:
    """
    Return the current RecoverFlow virtual time.

    IMPORTANT:
    This is the ONLY clock agents should read when making
    scheduling or policy decisions.
    """

    return (
        datetime.now(IST)
        + timedelta(hours=_clock_offset_hours)
    )


# ============================================================
# TRAI MESSAGING WINDOW
# ============================================================

def messaging_allowed_now(now=None):
    """
    Check whether customer messaging is currently allowed.

    If `now` is not supplied, use the shared RecoverFlow
    virtual clock.

    Passing `now` explicitly is supported so diagnosis can
    make its decision using exactly the same timestamp it
    already obtained from get_now().
    """

    if now is None:
        now = get_now()

    g = policy.GUARDRAILS

    start = dtime(
        *map(
            int,
            g["window_start"].split(":"),
        )
    )

    end = dtime(
        *map(
            int,
            g["window_end"].split(":"),
        )
    )

    current_time = now.timetz().replace(
        tzinfo=None
    )

    if start <= current_time <= end:
        return (
            True,
            (
                f"within TRAI window "
                f"({g['window_start']}–"
                f"{g['window_end']} IST)"
            ),
        )

    return (
        False,
        (
            f"outside window "
            f"({current_time.strftime('%H:%M')} IST) "
            f"— QUEUED, not sent"
        ),
    )

