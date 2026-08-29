"""
PulseFit storefront backend + (later) RecoverFlow agent API.
Run: python main.py   →  http://localhost:8000
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

# ---------- tiny local DB (moves to Postgres in Phase 3) ----------
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
init_db()

PLANS = {
    "shaker":     {"amount": 79900,   "description": "Protein Shaker Pro (one-time)"},
    "membership": {"amount": 149900,  "description": "PulseFit Pro Membership (monthly)"},
    "elite":      {"amount": 1499900, "description": "PulseFit Elite Annual"},
}

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
