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
from core import db, audit_log, messaging_allowed_now, get_now, build_wa_link
from agents import monitoring, diagnosis, action, scheduler

from fastapi.responses import FileResponse
import os


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
                purchase_type TEXT DEFAULT 'one_time',
                created_at TEXT
            )
         """)
      
         
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id TEXT UNIQUE,
                phone TEXT,
                plan TEXT,
                amount INTEGER,
                status TEXT DEFAULT 'active',
                started_at TEXT,
                next_billing_at TEXT,
                autopay_enabled INTEGER DEFAULT 1,
                payment_method TEXT DEFAULT 'razorpay',
                created_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscription_renewals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id TEXT,
                attempt_number INTEGER DEFAULT 1,
                billing_at TEXT,
                order_id TEXT,
                status TEXT DEFAULT 'pending',
                failure_type TEXT,
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
               "" 
                "ALTER TABLE orders "
                "ADD COLUMN payment_method TEXT DEFAULT 'razorpay'"""
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
        "amount": 79900,
        "purchase_type": "one_time",
    },
    "membership": {
        "amount": 149900,
        "purchase_type": "subscription",
    },
    "elite": {
        "amount": 1499900,
        "purchase_type": "one_time",
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
    purchase_type: str = "one_time"


@app.post("/create-order")
def create_order(req: OrderRequest):

    if req.plan not in PLANS:
        raise HTTPException(400, "unknown plan")

    p = PLANS[req.plan]
    purchase_type = p.get("purchase_type", req.purchase_type)

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
                (order_id, plan, phone, amount, purchase_type, created_at)
            VALUES
                (?,?,?,?,?,?)
            """,
            (
                order["id"],
                req.plan,
                req.phone,
                p["amount"],
                purchase_type,
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

        activated_sub = None
        with db() as conn:
            rzp_order_id = payload["razorpay_order_id"]

            # 1. Resolve original order: could be direct order_id or via executions
            order = conn.execute(
                """
                SELECT *
                FROM orders
                WHERE order_id=?
                """,
                (rzp_order_id,),
            ).fetchone()

            case_id = rzp_order_id
            if not order:
                execution = conn.execute(
                    """
                    SELECT case_id
                    FROM executions
                    WHERE order_id=?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (rzp_order_id,),
                ).fetchone()

                if execution:
                    case_id = execution["case_id"]
                    order = conn.execute(
                        """
                        SELECT *
                        FROM orders
                        WHERE order_id=?
                        """,
                        (case_id,),
                    ).fetchone()

            if order:
                order = dict(order)
                orig_order_id = order["order_id"]

                conn.execute(
                    "UPDATE orders SET status='paid' WHERE order_id=?",
                    (orig_order_id,),
                )
                conn.execute(
                    "UPDATE executions SET status='paid' WHERE order_id=?",
                    (rzp_order_id,),
                )
                conn.execute(
                    "UPDATE failed_payments SET status='recovered' WHERE order_id=?",
                    (case_id,),
                )

                if order.get("purchase_type") == "subscription":
                    started_at = get_now()
                    next_billing_at = started_at + timedelta(days=30)
                    subscription_id = f"sub_{orig_order_id}"

                    existing_sub = conn.execute(
                        "SELECT * FROM subscriptions WHERE subscription_id=?",
                        (subscription_id,),
                    ).fetchone()

                    if not existing_sub:
                        conn.execute(
                            """
                            INSERT INTO subscriptions (
                                subscription_id,
                                phone,
                                plan,
                                amount,
                                status,
                                started_at,
                                next_billing_at,
                                autopay_enabled,
                                payment_method,
                                created_at
                            )
                            VALUES (?, ?, ?, ?, 'active', ?, ?, 1, 'razorpay', ?)
                            """,
                            (
                                subscription_id,
                                order["phone"],
                                order["plan"],
                                order["amount"],
                                started_at.isoformat(),
                                next_billing_at.isoformat(),
                                started_at.isoformat(),
                            ),
                        )
                        activated_sub = {
                            "id": subscription_id,
                            "order_id": orig_order_id,
                            "next_billing_at": next_billing_at.isoformat(),
                        }
                    else:
                        conn.execute(
                            """
                            UPDATE subscriptions
                            SET status='active',
                                autopay_enabled=1,
                                payment_method='razorpay'
                            WHERE subscription_id=?
                            """,
                            (subscription_id,),
                        )

        if activated_sub:
            audit_log(
                "subscription",
                "subscription.activated",
                activated_sub["id"],
                {
                    "source": "verify_payment",
                    "order_id": activated_sub["order_id"],
                    "next_billing_at": activated_sub["next_billing_at"],
                },
            )

        audit_log(
            "storefront",
            "payment.verified",
            payload["razorpay_order_id"],
            {},
        )

        return {"verified": True}

    except Exception as e:
        print("VERIFY PAYMENT ERROR:", repr(e))
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

    # AGENT 2 wakes up -> AGENT 3 handoff
    orch_result = orchestrate_diagnosis(case_id)

    return {
        "case_id": case_id,
        "failure_type": req.failure_type,
        "status": "diagnosed" if orch_result.get("diagnosed") else "open — awaiting agent",
        "orchestration": orch_result,
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

    # AGENT 2 also handles abandonment cases -> AGENT 3 handoff
    orchestrate_diagnosis(req.order_id)

    return {
        "logged": True
    }


@app.get("/failures")
def list_failures():

    with db() as conn:
        rows = conn.execute(
            """
            SELECT f.*, o.purchase_type
            FROM failed_payments f
            LEFT JOIN orders o ON f.order_id = o.order_id
            ORDER BY f.id DESC
            LIMIT 100
            """
        ).fetchall()

    failures = []
    for r in rows:
        d = dict(r)
        if not d.get("purchase_type"):
            if d.get("failure_source") == "subscription_renewal":
                d["purchase_type"] = "subscription"
            elif d.get("plan") in PLANS:
                d["purchase_type"] = PLANS[d["plan"]].get("purchase_type", "one_time")
            else:
                d["purchase_type"] = "one_time"
        failures.append(d)

    return failures


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

        # AGENT 2 -> AGENT 3 ORCHESTRATION
        if result.get("should_diagnose"):
            orchestrate_diagnosis(
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
# AGENT 2 -> AGENT 3 ORCHESTRATION & HANDOFF
# ============================================================

IMMEDIATE_EXECUTION_STRATEGIES = {
    "alt_method",
    "nudge_now",
    "reauth",
    "customer_assisted",
}


def orchestrate_handoff_for_decision(case_id: str, decision: dict) -> dict:
    """
    Inspects an Agent 2 decision and, if immediately executable,
    invokes Agent 3 with mandatory idempotency and audit trail.
    """
    status = decision.get("status")
    strategy = decision.get("strategy")

    # Immediate execution decisions
    if status == "decided" and strategy in IMMEDIATE_EXECUTION_STRATEGIES:
        # Idempotency check: verify whether an execution already exists for this case_id
        with db() as conn:
            existing_exec = conn.execute(
                """
                SELECT *
                FROM executions
                WHERE case_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (case_id,),
            ).fetchone()

        if existing_exec:
            ex = dict(existing_exec)
            with db() as conn:
                f_row = conn.execute(
                    "SELECT phone, amount FROM failed_payments WHERE order_id=?",
                    (case_id,),
                ).fetchone()
            phone = f_row["phone"] if f_row else ""
            amt = f_row["amount"] if f_row else 0
            wa_link = build_wa_link(phone, ex.get("message") or "")

            return {
                "executed": True,
                "idempotent_reused": True,
                "case_id": case_id,
                "status": status,
                "strategy": strategy,
                "retry_order_id": ex.get("order_id"),
                "amount": amt,
                "payment_link": ex.get("link"),
                "whatsapp_link": wa_link,
                "note": "idempotent: reused existing execution",
            }

        # Invoke Agent 3
        exec_res = action.execute_latest_decision(
            case_id,
            STORE_BASE,
            client,
        )

        # Audit the automatic handoff
        audit_log(
            "orchestrator",
            "agent2.agent3_handoff",
            case_id,
            {
                "strategy": strategy,
                "decision_status": status,
                "retry_order_id": exec_res.get("retry_order_id"),
                "executed": exec_res.get("executed", False),
            },
        )

        return {
            "case_id": case_id,
            "status": status,
            "strategy": strategy,
            "executed": exec_res.get("executed", False),
            "execution": exec_res,
        }

    # Queued / deferred / non-immediate decisions
    return {
        "case_id": case_id,
        "status": status,
        "strategy": strategy,
        "executed": False,
        "note": f"decision status '{status}' / strategy '{strategy}' deferred to scheduler/manual path",
    }


def orchestrate_diagnosis(case_id: str) -> dict:
    """
    Runs Agent 2 diagnosis for a case, then orchestrates handoff to Agent 3 if executable.
    """
    diag_res = diagnosis.diagnose(case_id)

    with db() as conn:
        decision_row = conn.execute(
            """
            SELECT *
            FROM agent_decisions
            WHERE case_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()

    if not decision_row:
        return diag_res or {"case_id": case_id, "processed": 0}

    decision = dict(decision_row)
    handoff_res = orchestrate_handoff_for_decision(case_id, decision)
    return {
        **(diag_res if isinstance(diag_res, dict) else {}),
        **handoff_res,
    }


def orchestrate_all_open_diagnoses() -> dict:
    diag_res = diagnosis.diagnose(None)
    results = []
    for dec in (diag_res.get("decisions", []) if isinstance(diag_res, dict) else []):
        cid = dec.get("case_id")
        if cid:
            res = orchestrate_handoff_for_decision(cid, dec)
            results.append(res)
    return {
        "processed": diag_res.get("processed", 0) if isinstance(diag_res, dict) else 0,
        "results": results,
    }


@app.post("/agent/diagnose")
def agent_diagnose_route(
    case_id: str = None,
):
    if case_id:
        return orchestrate_diagnosis(case_id)
    return orchestrate_all_open_diagnoses()


# ============================================================
# AGENT 3 — ACTION / EXECUTION
# ============================================================

@app.post("/agent/execute/{case_id}")
def execute_decision(
    case_id: str,
):
    # Enforce idempotency on direct invocation as well
    with db() as conn:
        existing_exec = conn.execute(
            """
            SELECT *
            FROM executions
            WHERE case_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()

    if existing_exec:
        ex = dict(existing_exec)
        with db() as conn:
            f_row = conn.execute(
                "SELECT phone, amount FROM failed_payments WHERE order_id=?",
                (case_id,),
            ).fetchone()
        phone = f_row["phone"] if f_row else ""
        amt = f_row["amount"] if f_row else 0
        wa_link = build_wa_link(phone, ex.get("message") or "")
        return {
            "executed": True,
            "idempotent_reused": True,
            "case_id": case_id,
            "strategy": ex.get("strategy"),
            "retry_order_id": ex.get("order_id"),
            "amount": amt,
            "payment_link": ex.get("link"),
            "whatsapp_link": wa_link,
            "note": "idempotent: reused existing execution",
        }

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
            SELECT e.*, f.phone
            FROM executions e
            LEFT JOIN failed_payments f ON f.order_id = e.case_id
            ORDER BY e.id DESC
            LIMIT 50
            """
        ).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        if d.get("phone") and d.get("message"):
            d["whatsapp_link"] = build_wa_link(d["phone"], d["message"])
        else:
            d["whatsapp_link"] = None
        results.append(d)

    return results


# ============================================================
# AGENT 4 — SCHEDULER + VIRTUAL CLOCK
# ============================================================

@app.get("/agent/clock")
def get_clock():
    now = get_now()
    return {
        "virtual_time": now.isoformat(),
        "formatted": now.strftime("%d %b %Y, %I:%M %p IST").upper()
    }


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
        orchestrate_diagnosis
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

    # Automatically invoke the existing scheduler to evaluate due work at the new virtual time
    scheduler_result = scheduler.run_due(
        orchestrate_diagnosis
    )

    return {
        "virtual_time": new_time,
        "scheduler": scheduler_result,
    }


@app.post("/agent/clock/reset")
def clock_reset():

    new_time = scheduler.reset_clock()

    # Automatically evaluate scheduler on clock reset
    scheduler_result = scheduler.run_due(
        orchestrate_diagnosis
    )

    return {
        "reset": True,
        "virtual_time": new_time,
        "scheduler": scheduler_result,
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


@app.get("/pay.html")
def recovery_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "pay.html"))

@app.get("/order_meta")
def order_meta(oid: str):
    with db() as conn:
        row = conn.execute("SELECT plan, amount FROM orders WHERE order_id=?", (oid,)).fetchone()
        if row:
            audit_log("customer", "checkout.viewed", oid, {"plan": row["plan"], "amount": row["amount"]})
            return {"item_name": row["plan"], "amount": row["amount"]}
        return {"item_name": None, "amount": None}


@app.get("/subscriptions")
def list_subscriptions():
    with db() as conn:
        subs = conn.execute("SELECT * FROM subscriptions ORDER BY id DESC").fetchall()
        renewals = conn.execute("SELECT * FROM subscription_renewals ORDER BY id DESC").fetchall()
    return {
        "subscriptions": [dict(s) for s in subs],
        "renewals": [dict(r) for r in renewals],
    }



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

