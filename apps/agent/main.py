"""
RecoverFlow Agent Service — thin router
=======================================
The 4 agents live in agents/ — this file only wires HTTP to them:

    webhooks -> monitoring (AGENT 1) -> diagnosis (AGENT 2)
    execute  -> action (AGENT 3)
    cron/clock -> scheduler (AGENT 4)

Every step audited to the hash-chained ledger.

Run:
    python main.py

URL:
    http://localhost:8000
"""

import os
import hmac
import hashlib
import json
from datetime import datetime, timezone, timedelta

import razorpay
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import policy
import audit
from core import db, audit_log, messaging_allowed_now
from agents import monitoring, diagnosis, action, scheduler


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

RAZORPAY_KEY_ID = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]

STORE_BASE = os.getenv(
    "STORE_BASE_URL",
    "https://overdraft-gag-unsmooth.ngrok-free.dev"
)


# ============================================================
# APP
# ============================================================

client = razorpay.Client(
    auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
)

app = FastAPI(title="RecoverFlow Agent Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

IST = timezone(timedelta(hours=5, minutes=30))


# ============================================================
# DATABASE SCHEMA
# ============================================================

def init_db():
    with db() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                plan TEXT,
                phone TEXT,
                amount INTEGER,
                status TEXT DEFAULT 'created',
                payment_method TEXT DEFAULT 'razorpay',
                created_at TEXT
            )
        """)

        # Backward compatibility for existing DBs
        cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(orders)"
            ).fetchall()
        ]

        if "payment_method" not in cols:
            conn.execute(
                "ALTER TABLE orders "
                "ADD COLUMN payment_method TEXT DEFAULT 'razorpay'"
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS failed_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                phone TEXT,
                plan TEXT,
                amount INTEGER,
                failure_type TEXT,
                failure_source TEXT,
                raw_detail TEXT,
                status TEXT DEFAULT 'open',
                created_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT,
                failure_type TEXT,
                diagnosis_code TEXT,
                in_scope INTEGER,
                strategy TEXT,
                channel TEXT,
                message TEXT,
                reasoning TEXT,
                status TEXT DEFAULT 'decided',
                created_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT,
                order_id TEXT,
                strategy TEXT,
                channel TEXT,
                message TEXT,
                link TEXT,
                status TEXT DEFAULT 'sent',
                scheduled_for TEXT,
                executed_at TEXT
            )
        """)


init_db()
audit.init_audit()


# ============================================================
# BUSINESS CONFIG
# ============================================================

PLANS = {
    "shaker": {
        "amount": 79900
    },
    "membership": {
        "amount": 149900
    },
    "elite": {
        "amount": 1499900
    },
}

# COD is intentionally outside automated payment recovery.
RECOVERY_SCOPE = {"razorpay"}


# ============================================================
# STOREFRONT PAYMENTS
# ============================================================

class OrderRequest(BaseModel):
    plan: str
    phone: str


@app.post("/create-order")
def create_order(req: OrderRequest):

    if req.plan not in PLANS:
        raise HTTPException(400, "unknown plan")

    p = PLANS[req.plan]

    order = client.order.create({
        "amount": p["amount"],
        "currency": "INR",
        "receipt": (
            f"pf_{req.plan}_"
            f"{int(datetime.now().timestamp())}"
        ),
    })

    with db() as conn:
        conn.execute(
            """
            INSERT INTO orders
                (order_id, plan, phone, amount, created_at)
            VALUES
                (?,?,?,?,?)
            """,
            (
                order["id"],
                req.plan,
                req.phone,
                p["amount"],
                datetime.now().isoformat(),
            ),
        )

    audit_log(
        "storefront",
        "order.created",
        order["id"],
        {
            "plan": req.plan,
            "amount": p["amount"],
        },
    )

    return {
        "order_id": order["id"],
        "amount": p["amount"],
        "key_id": RAZORPAY_KEY_ID,
        "description": req.plan,
    }


@app.post("/verify-payment")
def verify_payment(payload: dict):

    try:

        expected = hmac.new(
            RAZORPAY_KEY_SECRET.encode(),
            (
                f"{payload['razorpay_order_id']}"
                f"|{payload['razorpay_payment_id']}"
            ).encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(
            expected,
            payload["razorpay_signature"],
        ):
            return {"verified": False}

        with db() as conn:
            conn.execute(
                """
                UPDATE orders
                SET status='paid'
                WHERE order_id=?
                """,
                (payload["razorpay_order_id"],),
            )

        audit_log(
            "storefront",
            "payment.verified",
            payload["razorpay_order_id"],
            {},
        )

        return {"verified": True}

    except Exception:
        return {"verified": False}


# ============================================================
# COD
# ============================================================

COD_FEE = 4900
COD_ALLOWED = {"shaker"}


@app.post("/create-cod-order")
def create_cod_order(req: OrderRequest):

    if req.plan not in PLANS:
        raise HTTPException(400, "unknown plan")

    if req.plan not in COD_ALLOWED:
        raise HTTPException(
            400,
            "COD available for physical products only",
        )

    total = PLANS[req.plan]["amount"] + COD_FEE

    cod_id = f"cod_{int(datetime.now().timestamp())}"

    with db() as conn:
        conn.execute(
            """
            INSERT INTO orders
                (
                    order_id,
                    plan,
                    phone,
                    amount,
                    status,
                    payment_method,
                    created_at
                )
            VALUES
                (?,?,?,?,?,?,?)
            """,
            (
                cod_id,
                req.plan,
                req.phone,
                total,
                "cod_confirmed",
                "cod",
                datetime.now().isoformat(),
            ),
        )

    audit_log(
        "storefront",
        "order.cod_created",
        cod_id,
        {
            "plan": req.plan,
            "amount": total,
        },
    )

    return {
        "order_id": cod_id,
        "amount": total / 100,
        "payment_method": "cod",
        "message": (
            f"COD confirmed — "
            f"pay ₹{total / 100:.0f} at your doorstep"
        ),
    }


@app.get("/recovery-scope/{order_id}")
def recovery_scope(order_id: str):

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE order_id=?",
            (order_id,),
        ).fetchone()

    if not row:
        raise HTTPException(404, "order not found")

    o = dict(row)

    in_scope = (
        o.get("payment_method") in RECOVERY_SCOPE
    )

    audit_log(
        "agent",
        "scope.checked",
        order_id,
        {
            "in_scope": in_scope
        },
    )

    return {
        "order_id": order_id,
        "in_scope": in_scope,
        "agent_action": (
            "PROCEED — eligible for recovery"
            if in_scope
            else
            "REFUSE — out of recovery scope "
            "(COD collects at delivery)"
        ),
    }


@app.get("/orders")
def list_orders():

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM orders
            ORDER BY id DESC
            LIMIT 50
            """
        ).fetchall()

    return [dict(r) for r in rows]


# ============================================================
# FAILURE INGESTION
# ============================================================

class SimulateFailureRequest(BaseModel):
    plan: str
    phone: str
    failure_type: str


FAILURE_MAP = {
    "declined_card": (
        "card declined by issuing bank",
        "HSM-4002",
    ),
    "insufficient_funds": (
        "customer has insufficient balance",
        "NPCI-IF-001",
    ),
    "expired_card": (
        "card expired",
        "HSM-4006",
    ),
    "abandoned": (
        "customer closed checkout without paying",
        "UI-ABANDON",
    ),
    "stale_mandate": (
        "auto-debit mandate revoked or stale",
        "NPCI-MANDATE-REVOKED",
    ),
    "gateway_issue": (
        "temporary gateway processing issue",
        "GW-TRANSIENT",
    ),
}


@app.post("/simulate-failure")
def simulate_failure(req: SimulateFailureRequest):

    if req.failure_type not in FAILURE_MAP:
        raise HTTPException(
            400,
            "unknown failure_type",
        )

    if req.plan not in PLANS:
        raise HTTPException(
            400,
            "unknown plan",
        )

    detail, code = FAILURE_MAP[
        req.failure_type
    ]

    case_id = (
        f"case_{int(datetime.now().timestamp())}"
    )

    with db() as conn:
        conn.execute(
            """
            INSERT INTO failed_payments
                (
                    order_id,
                    phone,
                    plan,
                    amount,
                    failure_type,
                    failure_source,
                    raw_detail,
                    created_at
                )
            VALUES
                (?,?,?,?,?,?,?,?)
            """,
            (
                case_id,
                req.phone,
                req.plan,
                PLANS[req.plan]["amount"],
                req.failure_type,
                "simulator",
                f"{detail} [{code}]",
                datetime.now().isoformat(),
            ),
        )

    audit_log(
        "simulator",
        "case.filed",
        case_id,
        {
            "failure_type": req.failure_type,
            "source": "simulator",
        },
    )

    # AGENT 2 wakes up
    diagnosis.diagnose(case_id)

    return {
        "case_id": case_id,
        "failure_type": req.failure_type,
        "status": "open — awaiting agent",
    }


# ============================================================
# CHECKOUT ABANDONMENT
# ============================================================

class DismissReport(BaseModel):
    order_id: str
    phone: str
    plan: str
    amount: int


@app.post("/report-abandonment")
def report_abandonment(req: DismissReport):

    # Do not create a duplicate if webhook already filed
    # a case for this order.
    with db() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM failed_payments
            WHERE order_id=?
            """,
            (req.order_id,),
        ).fetchone()

    if existing:

        audit_log(
            "checkout_dismiss",
            "case.note_abandonment",
            req.order_id,
            {
                "note": (
                    "webhook case already exists "
                    "— no duplicate filed"
                )
            },
        )

        return {
            "logged": True,
            "note": (
                "existing case kept, "
                "no duplicate"
            ),
        }

    with db() as conn:
        conn.execute(
            """
            INSERT INTO failed_payments
                (
                    order_id,
                    phone,
                    plan,
                    amount,
                    failure_type,
                    failure_source,
                    raw_detail,
                    created_at
                )
            VALUES
                (?,?,?,?,?,?,?,?)
            """,
            (
                req.order_id,
                req.phone,
                req.plan,
                req.amount,
                "abandoned",
                "checkout_dismiss",
                "customer closed checkout [UI-ABANDON]",
                datetime.now().isoformat(),
            ),
        )

    audit_log(
        "checkout_dismiss",
        "case.filed",
        req.order_id,
        {
            "failure_type": "abandoned"
        },
    )

    # AGENT 2 also handles abandonment cases
    diagnosis.diagnose(req.order_id)

    return {
        "logged": True
    }


@app.get("/failures")
def list_failures():

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM failed_payments
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()

    return [dict(r) for r in rows]


# ============================================================
# WEBHOOKS — AGENT 1
# ============================================================

@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):

    body = await request.body()

    signature = request.headers.get(
        "X-Razorpay-Signature",
        "",
    )

    # AGENT 1 verifies the webhook signature
    if not monitoring.verify_signature(
        body,
        signature,
    ):

        audit_log(
            "webhook",
            "webhook.rejected",
            "signature_invalid",
            {},
        )

        raise HTTPException(
            400,
            "invalid webhook signature — rejected",
        )

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        audit_log(
            "webhook",
            "webhook.rejected",
            "invalid_json",
            {},
        )
        raise HTTPException(
            400,
            "invalid webhook JSON",
        )

    event_type = event.get(
        "event",
        "",
    )

    entity = (
        event
        .get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )

    audit_log(
        "webhook",
        f"webhook.{event_type}",
        entity.get("order_id", "?"),
        {},
    )

    # --------------------------------------------------------
    # PAYMENT FAILED
    # --------------------------------------------------------

    if event_type == "payment.failed":

        def orders_lookup(order_id):
            with db() as conn:
                return conn.execute(
                    """
                    SELECT *
                    FROM orders
                    WHERE order_id=?
                    """,
                    (order_id,),
                ).fetchone()

        # AGENT 1
        result = monitoring.handle_failed_payment(
            entity,
            orders_lookup,
        )

        # AGENT 2
        if result.get("should_diagnose"):
            diagnosis.diagnose(
                result["case_id"]
            )

        return result

    # --------------------------------------------------------
    # PAYMENT CAPTURED
    # --------------------------------------------------------

    if event_type == "payment.captured":

        # AGENT 1
        return monitoring.handle_captured_payment(
            entity
        )

    return {
        "handled": event_type or "ignored"
    }


# ============================================================
# AGENT 2 — DIAGNOSIS
# ============================================================

@app.post("/agent/diagnose")
def agent_diagnose_route(
    case_id: str = None,
):

    return diagnosis.diagnose(
        case_id
    )


# ============================================================
# AGENT 3 — ACTION / EXECUTION
# ============================================================

@app.post("/agent/execute/{case_id}")
def execute_decision(
    case_id: str,
):

    return action.execute_latest_decision(
        case_id,
        STORE_BASE,
        client,
    )


@app.get("/retry-checkout/{order_id}")
def retry_checkout(order_id: str):

    with db() as conn:
        row = conn.execute(
            """
            SELECT f.amount
            FROM executions e
            JOIN failed_payments f
                ON f.order_id=e.case_id
            WHERE e.order_id=?
            LIMIT 1
            """,
            (order_id,),
        ).fetchone()

    if not row:
        raise HTTPException(
            404,
            "retry order not found",
        )

    return {
        "key_id": RAZORPAY_KEY_ID,
        "amount": row["amount"],
    }


@app.get("/executions")
def list_executions():

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM executions
            ORDER BY id DESC
            LIMIT 50
            """
        ).fetchall()

    return [dict(r) for r in rows]


# ============================================================
# AGENT 4 — SCHEDULER + VIRTUAL CLOCK
# ============================================================

@app.post("/agent/run-due")
def run_due():

    """
    Production:
        cron calls this periodically.

    Demo:
        time-travel button calls clock/jump,
        then this endpoint wakes due cases.
    """

    return scheduler.run_due(
        diagnosis.diagnose
    )


@app.post("/agent/clock/jump")
def clock_jump(hours: float = 1.0):

    new_time = scheduler.jump(
        hours
    )

    audit_log(
        "demo",
        "clock.jumped",
        "virtual_clock",
        {
            "hours": hours
        },
    )

    return {
        "virtual_time": new_time,
        "note": (
            "scheduler will now treat "
            "queued cases as due"
        ),
    }


@app.post("/agent/clock/reset")
def clock_reset():

    scheduler.reset_clock()

    return {
        "reset": True
    }


# ============================================================
# INTROSPECTION
# ============================================================

@app.get("/agent/decisions")
def list_decisions():

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM agent_decisions
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()

    return [dict(r) for r in rows]


@app.get("/agent/guardrails")
def guardrails_status():

    # Directly use the shared helper from core.py.
    ok, why = messaging_allowed_now()

    return {
        "messaging_window_ok": ok,
        "reason": why,
        "policy_source": (
            "policy.py "
            "(RBI MD-DL 2025, "
            "TRAI TCCCPR 2024, "
            "DPDP 2023)"
        ),
        "global_max_touches": (
            policy.GUARDRAILS[
                "global_max_touches"
            ]
        ),
        "grievance_contact": (
            policy.GUARDRAILS[
                "grievance_contact"
            ]
        ),
    }


@app.get("/audit")
def audit_trail(
    limit: int = 100,
):

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM audit_ledger
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(r) for r in rows]


@app.get("/audit/verify")
def audit_verify():

    result = audit.verify_chain()

    audit_log(
        "auditor",
        "audit.verified",
        "chain",
        result,
    )

    return result


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )