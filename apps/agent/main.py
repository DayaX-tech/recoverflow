"""
RecoverFlow / PulseFit backend
==============================
Storefront payments (Razorpay test mode) + COD + Failure Zoo.

Run:  python main.py   ->   http://localhost:8000
"""
import os
import hmac
import hashlib
import sqlite3
from datetime import datetime

import razorpay
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

RAZORPAY_KEY_ID = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]

client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
app = FastAPI(title="PulseFit / RecoverFlow")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # demo only
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= DATABASE =================
DB = "pulsefit.db"

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT, plan TEXT, phone TEXT,
                amount INTEGER, status TEXT DEFAULT 'created',
                created_at TEXT
            )""")
        # migration: payment_method column (razorpay | cod)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(orders)").fetchall()]
        if "payment_method" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'razorpay'")

init_db()

PLANS = {
    "shaker":     {"amount": 79900,   "description": "Protein Shaker Pro (one-time)"},
    "membership": {"amount": 149900,  "description": "PulseFit Pro Membership (monthly)"},
    "elite":      {"amount": 1499900, "description": "PulseFit Elite Annual"},
}

# ================= RAZORPAY ONLINE PAYMENTS =================

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
        "receipt": f"pf_{req.plan}_{int(datetime.now().timestamp())}",
    })
    with db() as conn:
        conn.execute(
            "INSERT INTO orders (order_id, plan, phone, amount, created_at) VALUES (?,?,?,?,?)",
            (order["id"], req.plan, req.phone, p["amount"], datetime.now().isoformat()),
        )
    return {
        "order_id": order["id"],
        "amount": p["amount"],
        "key_id": RAZORPAY_KEY_ID,
        "description": p["description"],
    }

@app.post("/verify-payment")
def verify_payment(payload: dict):
    """HMAC verification — the same discipline the agent will apply to money actions."""
    try:
        expected = hmac.new(
            RAZORPAY_KEY_SECRET.encode(),
            f"{payload['razorpay_order_id']}|{payload['razorpay_payment_id']}".encode(),
            hashlib.sha256,
        ).hexdigest()
        assert hmac.compare_digest(expected, payload["razorpay_signature"])
        with db() as conn:
            conn.execute(
                "UPDATE orders SET status='paid' WHERE order_id=?",
                (payload["razorpay_order_id"],),
            )
        return {"verified": True}
    except Exception:
        with db() as conn:
            conn.execute(
                "UPDATE orders SET status='verification_failed' WHERE order_id=?",
                (payload.get("razorpay_order_id", "?"),),
            )
        return {"verified": False}

@app.get("/orders")
def list_orders():
    with db() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]

# ================= COD (CASH ON DELIVERY) =================

COD_FEE = 4900            # ₹49 COD handling fee (paise)
COD_ALLOWED = {"shaker"}  # business rule: physical products only, no memberships

class CODRequest(BaseModel):
    plan: str
    phone: str

@app.post("/create-cod-order")
def create_cod_order(req: CODRequest):
    """COD = no online charge. Money is collected at delivery."""
    if req.plan not in PLANS:
        raise HTTPException(400, "unknown plan")
    if req.plan not in COD_ALLOWED:
        raise HTTPException(400, "COD available for physical products only — memberships are online-payment")
    p = PLANS[req.plan]
    cod_id = f"cod_{int(datetime.now().timestamp())}"
    total = p["amount"] + COD_FEE
    with db() as conn:
        conn.execute(
            """INSERT INTO orders (order_id, plan, phone, amount, status, payment_method, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (cod_id, req.plan, req.phone, total, "cod_confirmed", "cod",
             datetime.now().isoformat()),
        )
    return {
        "order_id": cod_id,
        "amount": total / 100,
        "payment_method": "cod",
        "message": f"COD confirmed — pay ₹{total/100:.0f} at your doorstep",
    }

# ---- RECOVERY SCOPE: the agent's jurisdiction check ----
RECOVERY_SCOPE = {"razorpay"}   # only online payments are recoverable

@app.get("/recovery-scope/{order_id}")
def recovery_scope(order_id: str):
    """
    The agent's FIRST check before any recovery action:
    is this order even in scope? COD orders are refused with a reason,
    and the refusal gets logged. Governance starts with jurisdiction.
    """
    with db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(404, "order not found")
    order = dict(row)
    if order.get("payment_method") in RECOVERY_SCOPE:
        return {"order_id": order_id, "in_scope": True,
                "agent_action": "PROCEED — eligible for recovery"}
    return {
        "order_id": order_id,
        "in_scope": False,
        "reason": f"payment_method={order.get('payment_method')} — COD collects at delivery, no digital payment to recover",
        "agent_action": "REFUSE — out of recovery scope",
        "note": "refusal logged to audit trail",
    }

# ================= PHASE 3: FAILURE ZOO =================

def init_failure_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS failed_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT, phone TEXT, plan TEXT, amount INTEGER,
                failure_type TEXT,          -- machine code: declined_card, insufficient_funds...
                failure_source TEXT,        -- where detected: checkout_dismiss, webhook, simulator
                raw_detail TEXT,            -- whatever Razorpay told us
                status TEXT DEFAULT 'open', -- open -> agent picks it up in Phase 4
                created_at TEXT
            )""")

init_failure_db()


class SimulateFailureRequest(BaseModel):
    plan: str
    phone: str
    failure_type: str   # declined_card | insufficient_funds | expired_card | abandoned | stale_mandate


FAILURE_MAP = {
    "declined_card":       ("card declined by issuing bank", "HSM-4002"),
    "insufficient_funds":  ("customer has insufficient balance", "NPCI-IF-001"),
    "expired_card":        ("card expired", "HSM-4006"),
    "abandoned":           ("customer closed checkout without paying", "UI-ABANDON"),
    "stale_mandate":       ("auto-debit mandate revoked or stale", "NPCI-MANDATE-REVOKED"),
}

@app.post("/simulate-failure")
def simulate_failure(req: SimulateFailureRequest):
    """
    Failure Zoo: creates a failed-payment case file deterministically.
    In production these arrive via Razorpay webhooks; in the demo we
    generate them on demand so failures are repeatable and reviewable.
    """
    if req.failure_type not in FAILURE_MAP:
        raise HTTPException(400, f"unknown failure_type, use one of {list(FAILURE_MAP)}")
    if req.plan not in PLANS:
        raise HTTPException(400, "unknown plan")
    p = PLANS[req.plan]
    detail, code = FAILURE_MAP[req.failure_type]
    case_id = f"case_{int(datetime.now().timestamp())}"
    with db() as conn:
        conn.execute(
            """INSERT INTO failed_payments
               (order_id, phone, plan, amount, failure_type, failure_source, raw_detail, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (case_id, req.phone, req.plan, p["amount"],
             req.failure_type, "simulator", f"{detail} [{code}]",
             datetime.now().isoformat()),
        )
    return {
        "case_id": case_id,
        "failure_type": req.failure_type,
        "diagnosis_code": code,
        "detail": detail,
        "amount": p["amount"] / 100,
        "status": "open — awaiting agent",
    }

@app.get("/failures")
def list_failures():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM failed_payments ORDER BY id DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]


class DismissReport(BaseModel):
    order_id: str
    phone: str
    plan: str
    amount: int

@app.post("/report-abandonment")
def report_abandonment(req: DismissReport):
    """Frontend calls this when a customer closes the Razorpay popup."""
    with db() as conn:
        conn.execute(
            """INSERT INTO failed_payments
               (order_id, phone, plan, amount, failure_type, failure_source, raw_detail, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (req.order_id, req.phone, req.plan, req.amount,
             "abandoned", "checkout_dismiss", "customer closed checkout [UI-ABANDON]",
             datetime.now().isoformat()),
        )
    return {"logged": True, "failure_type": "abandoned"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
