"""
RecoverFlow Audit Ledger
========================

Append-only, hash-chained event log.

Every meaningful event — ingestion, decision, refusal, execution —
lands here.

Tamper-evident: each record chains the previous record's hash.
Auditors can verify the chain.
"""

import hashlib
import json
import sqlite3
from datetime import datetime


DB = "pulsefit.db"


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_audit():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                actor TEXT NOT NULL,
                event_type TEXT NOT NULL,
                subject TEXT,
                payload TEXT,
                prev_hash TEXT,
                entry_hash TEXT NOT NULL
            )
            """
        )


def audit(
    actor: str,
    event_type: str,
    subject: str,
    payload: dict,
):
    """
    Append one hash-chained entry.
    Never update, never delete.
    """

    # Get the previous entry's hash
    with db() as conn:
        prev = conn.execute(
            """
            SELECT entry_hash
            FROM audit_ledger
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    prev_hash = prev["entry_hash"] if prev else None

    # Create timestamp
    ts = datetime.now().isoformat()

    # Create the record body
    body = json.dumps(
        {
            "ts": ts,
            "actor": actor,
            "event_type": event_type,
            "subject": subject,
            "payload": payload,
        },
        sort_keys=True,
    )

    # Create SHA-256 hash using the previous hash + current record
    entry_hash = hashlib.sha256(
        (str(prev_hash) + body).encode("utf-8")
    ).hexdigest()

    # Insert the new audit record
    with db() as conn:
        conn.execute(
            """
            INSERT INTO audit_ledger (
                ts,
                actor,
                event_type,
                subject,
                payload,
                prev_hash,
                entry_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                actor,
                event_type,
                subject,
                json.dumps(payload),
                prev_hash,
                entry_hash,
            ),
        )


def verify_chain() -> dict:
    """
    Recompute the entire hash chain.

    If any record was modified, deleted, or inserted incorrectly,
    the chain verification will detect a broken link.
    """

    # Read all audit records in chronological order
    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM audit_ledger
            ORDER BY id
            """
        ).fetchall()

    prev_hash = None
    broken = 0

    # Verify every record
    for row in rows:

        # Reconstruct the original record body
        body = json.dumps(
            {
                "ts": row["ts"],
                "actor": row["actor"],
                "event_type": row["event_type"],
                "subject": row["subject"],
                "payload": json.loads(row["payload"] or "{}"),
            },
            sort_keys=True,
        )

        # Calculate what the hash should be
        expected = hashlib.sha256(
            (str(prev_hash) + body).encode("utf-8")
        ).hexdigest()

        # Compare calculated hash with stored hash
        if expected != row["entry_hash"]:
            broken += 1

        # The current hash becomes the previous hash
        # for the next record in the chain.
        prev_hash = row["entry_hash"]

    # Return verification result
    return {
        "entries": len(rows),
        "broken_links": broken,
        "verdict": (
            "TAMPER-EVIDENT ✅ chain intact"
            if broken == 0
            else f"⚠️ {broken} broken links — records were altered"
        ),
    }


if __name__ == "__main__":
    # Create the audit table if it doesn't exist
    init_audit()

    # Add a test audit event
    audit(
        actor="agent",
        event_type="test.event",
        subject="recoverflow-test",
        payload={
            "message": "RecoverFlow audit ledger is working"
        },
    )

    # Verify the hash chain
    result = verify_chain()

    print("Audit verification:")
    print(json.dumps(result, indent=2))