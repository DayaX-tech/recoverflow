"""
RecoverFlow Agent Service — production build
============================================
Ingestion -> Diagnosis -> Policy Guardrails -> (Execution Phase 5)
Every step audited to a hash-chained ledger. Vendor-agnostic design.

Run:  python main.py   ->   http://localhost:8000
"""
import os
import hmac
import hashlib
import json
import sqlite3
from datetime import datetime, time as dtime, timezone, timedelta

import razorpay
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import policy
import audit

load_dotenv()

RAZORPAY_KEY_ID = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "rf_webhook_secret_2025")

# Public base for payment links (set in .env as STORE_BASE_URL when possible)
STORE_BASE = os.getenv("STORE_BASE_URL", "https://overdraft-gag-unsmooth.ngrok-free.dev")

client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
app = FastAPI(title="RecoverFlow Agent Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

DB = "pulsefit.db"
IST = timezone(timedelta(hours=5, minutes=30))


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


# ================= SCHEMA =================
def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT, plan TEXT, phone TEXT,
                amount INTEGER, status TEXT DEFAULT 'created',
                payment_method TEXT DEFAULT 'razorpay', created_at TEXT)""")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(orders)").fetchall()]
        if "payment_method" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'razorpay'")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS failed_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT, phone TEXT, plan TEXT, amount INTEGER,
                failure_type TEXT, failure_source TEXT, raw_detail TEXT,
                status TEXT DEFAULT 'open', created_at TEXT)""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT, failure_type TEXT, diagnosis_code TEXT,
                in_scope INTEGER, strategy TEXT, channel TEXT, message TEXT,
                reasoning TEXT, status TEXT DEFAULT 'decided', created_at TEXT)""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT, order_id TEXT,
                strategy TEXT, channel TEXT,
                message TEXT, link TEXT,
                status TEXT DEFAULT 'sent',
                scheduled_for TEXT,
                executed_at TEXT)""")


init_db()
audit.init_audit()

PLANS = {
    "shaker":     {"amount": 79900},
    "membership": {"amount": 149900},
    "elite":      {"amount": 1499900},
}

RECOVERY_SCOPE = {"razorpay"}   # COD is structurally out of scope


# ================= HELPERS =================
def audit_log(actor, event_type, subject, payload):
    audit.audit(actor, event_type, subject, payload)


def messaging_allowed_now():
    g = policy.GUARDRAILS
    start = dtime(*map(int, g["window_start"].split(":")))
    end = dtime(*map(int, g["window_end"].split(":")))
    now = datetime.now(IST).time()
    if start <= now <= end:
        return True, f"within TRAI window ({g['window_start']}–{g['window_end']} IST)"
    return False, f"outside window ({now.strftime('%H:%M')} IST) — QUEUED, not sent"


def classify_gateway_error(err: str, code: str) -> str:
    """Vendor mapping layer — ONLY this function knows Razorpay's error strings.
    All gateway-specific wording lives here; one line per new pattern."""
    e = f"{err} {code}".lower()

    # order of checks matters — most specific first
    if "insufficient" in e:
        return "insufficient_funds"
    if "mandate" in e or "autopay" in e or "auto-debit" in e:
        return "stale_mandate"
    if "expired" in e:
        return "expired_card"
    if "authentication" in e or "declined" in e or "denied" in e or "declined by issuer" in e:
        return "declined_card"
    # Razorpay transient / BAD_REQUEST_ERROR wording (seen live in webhooks)
    if "temporary issue" in e or "bad_request_error" in e or "didn't go through" in e:
        return "gateway_issue"
    return "unknown_failure"


# ================= STOREFRONT PAYMENTS =================
class OrderRequest(BaseModel):
    plan: str
    phone: str


@app.post("/create-order")
def create_order(req: OrderRequest):
    if req.plan not in PLANS:
        raise HTTPException(400, "unknown plan")
    p = PLANS[req.plan]
    order = client.order.create({"amount": p["amount"], "currency": "INR",
                                 "receipt": f"pf_{req.plan}_{int(datetime.now().timestamp())}"})
    with db() as conn:
        conn.execute("INSERT INTO orders (order_id, plan, phone, amount, created_at) VALUES (?,?,?,?,?)",
                     (order["id"], req.plan, req.phone, p["amount"], datetime.now().isoformat()))
    audit_log("storefront", "order.created", order["id"], {"plan": req.plan, "amount": p["amount"]})
    return {"order_id": order["id"], "amount": p["amount"], "key_id": RAZORPAY_KEY_ID,
            "description": req.plan}


@app.post("/verify-payment")
def verify_payment(payload: dict):
    try:
        expected = hmac.new(RAZORPAY_KEY_SECRET.encode(),
                            f"{payload['razorpay_order_id']}|{payload['razorpay_payment_id']}".encode(),
                            hashlib.sha256).hexdigest()
        assert hmac.compare_digest(expected, payload["razorpay_signature"])
        with db() as conn:
            conn.execute("UPDATE orders SET status='paid' WHERE order_id=?",
                         (payload["razorpay_order_id"],))
        audit_log("storefront", "payment.verified", payload["razorpay_order_id"], {})
        return {"verified": True}
    except Exception:
        return {"verified": False}


# ================= COD =================
COD_FEE = 4900
COD_ALLOWED = {"shaker"}


@app.post("/create-cod-order")
def create_cod_order(req: OrderRequest):
    if req.plan not in PLANS:
        raise HTTPException(400, "unknown plan")
    if req.plan not in COD_ALLOWED:
        raise HTTPException(400, "COD available for physical products only")
    total = PLANS[req.plan]["amount"] + COD_FEE
    cod_id = f"cod_{int(datetime.now().timestamp())}"
    with db() as conn:
        conn.execute("""INSERT INTO orders (order_id, plan, phone, amount, status,
                        payment_method, created_at) VALUES (?,?,?,?,?,?,?)""",
                     (cod_id, req.plan, req.phone, total, "cod_confirmed", "cod",
                      datetime.now().isoformat()))
    audit_log("storefront", "order.cod_created", cod_id, {"plan": req.plan, "amount": total})
    return {"order_id": cod_id, "amount": total / 100, "payment_method": "cod",
            "message": f"COD confirmed — pay ₹{total/100:.0f} at your doorstep"}


@app.get("/recovery-scope/{order_id}")
def recovery_scope(order_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(404, "order not found")
    o = dict(row)
    in_scope = o.get("payment_method") in RECOVERY_SCOPE
    audit_log("agent", "scope.checked", order_id, {"in_scope": in_scope})
    return {"order_id": order_id, "in_scope": in_scope,
            "agent_action": "PROCEED — eligible for recovery" if in_scope
            else "REFUSE — out of recovery scope (COD collects at delivery)"}


@app.get("/orders")
def list_orders():
    with db() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


# ================= FAILURE INGESTION =================
class SimulateFailureRequest(BaseModel):
    plan: str
    phone: str
    failure_type: str


FAILURE_MAP = {
    "declined_card": ("card declined by issuing bank", "HSM-4002"),
    "insufficient_funds": ("customer has insufficient balance", "NPCI-IF-001"),
    "expired_card": ("card expired", "HSM-4006"),
    "abandoned": ("customer closed checkout without paying", "UI-ABANDON"),
    "stale_mandate": ("auto-debit mandate revoked or stale", "NPCI-MANDATE-REVOKED"),
    "gateway_issue": ("temporary gateway processing issue", "GW-TRANSIENT"),
}


def file_case(order_id, phone, plan, amount, ftype, source, detail):
    with db() as conn:
        conn.execute("""INSERT INTO failed_payments (order_id, phone, plan, amount,
                        failure_type, failure_source, raw_detail, created_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                     (order_id, phone, plan, amount, ftype, source, detail,
                      datetime.now().isoformat()))
    audit_log(source, "case.filed", order_id, {"failure_type": ftype, "source": source})


@app.post("/simulate-failure")
def simulate_failure(req: SimulateFailureRequest):
    if req.failure_type not in FAILURE_MAP:
        raise HTTPException(400, "unknown failure_type")
    if req.plan not in PLANS:
        raise HTTPException(400, "unknown plan")
    detail, code = FAILURE_MAP[req.failure_type]
    case_id = f"case_{int(datetime.now().timestamp())}"
    file_case(case_id, req.phone, req.plan, PLANS[req.plan]["amount"],
              req.failure_type, "simulator", f"{detail} [{code}]")
    return {"case_id": case_id, "failure_type": req.failure_type,
            "status": "open — awaiting agent"}


class DismissReport(BaseModel):
    order_id: str
    phone: str
    plan: str
    amount: int


@app.post("/report-abandonment")
def report_abandonment(req: DismissReport):
    file_case(req.order_id, req.phone, req.plan, req.amount,
              "abandoned", "checkout_dismiss", "customer closed checkout [UI-ABANDON]")
    return {"logged": True}


@app.get("/failures")
def list_failures():
    with db() as conn:
        rows = conn.execute("SELECT * FROM failed_payments ORDER BY id DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]


# ================= WEBHOOK (auto agent trigger) =================
@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        audit_log("webhook", "webhook.rejected", "signature_invalid", {})
        raise HTTPException(400, "invalid webhook signature — rejected")
    event = json.loads(body)
    etype = event.get("event", "")
    audit_log("webhook", f"webhook.{etype}",
              event.get("payload", {}).get("payment", {}).get("entity", {}).get("order_id", "?"), {})

    if etype == "payment.captured":
        ent = event["payload"]["payment"]["entity"]
        order_id = ent.get("order_id", "?")
        with db() as conn:
            # normal success path
            conn.execute("UPDATE orders SET status='paid' WHERE order_id=?", (order_id,))
            # RECOVERY path: was this a retry payment for a filed case?
            ex = conn.execute("SELECT * FROM executions WHERE order_id=? LIMIT 1",
                              (ent.get("id", ""),)).fetchone()
            if ex:
                case_id = ex["case_id"]
                conn.execute("UPDATE executions SET status='paid' WHERE order_id=?",
                             (ent.get("id", ""),))
                conn.execute("UPDATE failed_payments SET status='recovered' WHERE order_id=?",
                             (case_id,))
                audit_log("agent", "recovery.success", case_id,
                          {"via": "retry_link", "amount": ent.get("amount")})
        return {"handled": "captured"}

    if etype == "payment.failed":
        ent = event["payload"]["payment"]["entity"]
        err = ent.get("error_description", "unknown error")
        code = ent.get("error_code", "?")
        ftype = classify_gateway_error(err, code)
        case_id = ent.get("order_id", f"case_{int(datetime.now().timestamp())}")
        # Razorpay sends contact only if collected; fallback to order record phone
        phone = ent.get("contact") or ""
        plan = "membership"
        amount = ent.get("amount", 0)
        if not phone or amount == 0:
            with db() as conn:
                o = conn.execute("SELECT * FROM orders WHERE order_id=?", (case_id,)).fetchone()
                if o:
                    phone = phone or o["phone"]
                    plan = plan if amount else o["plan"]
                    amount = amount or o["amount"]
        file_case(case_id, phone, plan, amount, ftype, "webhook", f"{err} [{code}]")
        await agent_diagnose(case_id)   # 🔥 agent wakes itself up
        return {"handled": "failed", "case_id": case_id, "classified_as": ftype}

    return {"handled": etype or "ignored"}


# ================= DIAGNOSIS ENGINE + POLICY GUARDRAILS =================
async def agent_diagnose(case_id: str = None):
    with db() as conn:
        if case_id:
            rows = conn.execute("SELECT * FROM failed_payments WHERE order_id=? AND status='open'",
                                (case_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM failed_payments WHERE status='open'").fetchall()

    decisions = []
    for row in rows:
        case = dict(row)
        t = policy.FAILURE_TAXONOMY.get(case["failure_type"],
                                        policy.FAILURE_TAXONOMY["unknown_failure"])

        # GATE 1 — jurisdiction
        if case["failure_source"] == "cod":
            d = {"case_id": case["order_id"], "failure_type": case["failure_type"],
                 "diagnosis_code": "OUT-OF-SCOPE", "in_scope": False,
                 "strategy": "none", "channel": "none", "message": None,
                 "reasoning": "REFUSED: outside recovery jurisdiction (COD).",
                 "status": "refused"}
        # GATE 2 — unknown type → Claude escalation (Phase 5)
        elif case["failure_type"] == "unknown_failure" or "strategy" not in t:
            d = {"case_id": case["order_id"], "failure_type": case["failure_type"],
                 "diagnosis_code": "UNCLASSIFIED", "in_scope": True,
                 "strategy": "escalate", "channel": "none", "message": None,
                 "reasoning": "No deterministic rule matched — flagged for LLM triage (Phase 5).",
                 "status": "escalated"}
        else:
            with db() as conn:
                nudges = conn.execute(
                    "SELECT COUNT(*) FROM agent_decisions WHERE case_id=? AND in_scope=1",
                    (case["order_id"],)).fetchone()[0]
            max_touches = min(t.get("max_touches", 3), policy.GUARDRAILS["global_max_touches"])

            # GATE 3 — nudge cap (RBI: stop after max attempts)
            if nudges >= max_touches:
                d = {"case_id": case["order_id"], "failure_type": case["failure_type"],
                     "diagnosis_code": t["code"], "in_scope": True,
                     "strategy": "stop", "channel": "none", "message": None,
                     "reasoning": f"REFUSED: {nudges} touches >= cap {max_touches} "
                                  f"(RBI MD-DL: stop automated recovery, escalate to human "
                                  f"{policy.GUARDRAILS['grievance_contact']}).",
                     "status": "human_handoff"}
            else:
                ok, why = messaging_allowed_now()
                # GATE 4 — TRAI messaging window
                if not ok:
                    d = {"case_id": case["order_id"], "failure_type": case["failure_type"],
                         "diagnosis_code": t["code"], "in_scope": True,
                         "strategy": "queued", "channel": "none", "message": None,
                         "reasoning": f"DEFERRED: {why}",
                         "status": "queued"}
                else:
                    # message composed by policy.build_message — single source of truth
                    link = f"{STORE_BASE}/pay.html?case={case['order_id']}"
                    msg = policy.build_message(
                        case["failure_type"],
                        case["amount"] // 100,
                        case["plan"] or "order",
                        link)
                    d = {"case_id": case["order_id"], "failure_type": case["failure_type"],
                         "diagnosis_code": t["code"], "in_scope": True,
                         "strategy": t["strategy"], "channel": "whatsapp",
                         "message": msg,
                         "reasoning": f"Policy for {case['failure_type']} "
                                      f"(source: {t.get('source_regulation') or 'behavioral'}); "
                                      f"touch {nudges+1}/{max_touches}.",
                         "status": "decided"}

        with db() as conn:
            conn.execute("""INSERT INTO agent_decisions (case_id, failure_type,
                            diagnosis_code, in_scope, strategy, channel, message,
                            reasoning, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (d["case_id"], d["failure_type"], d["diagnosis_code"],
                          int(d["in_scope"]), d["strategy"], d["channel"],
                          d["message"], d["reasoning"], d["status"],
                          datetime.now().isoformat()))
            if d["status"] not in ("queued",):
                conn.execute("UPDATE failed_payments SET status='diagnosed' WHERE id=?",
                             (case["id"],))
        audit_log("agent" if d["status"] == "decided" else "guardrail",
                  f"decision.{d['status']}", d["case_id"],
                  {"strategy": d["strategy"], "reasoning": d["reasoning"]})
        decisions.append(d)

    return {"processed": len(decisions), "decisions": decisions}


# keep the old POST route working too
@app.post("/agent/diagnose")
async def agent_diagnose_route(case_id: str = None):
    return await agent_diagnose(case_id)


# ================= EXECUTION (Phase 5) =================
@app.post("/agent/execute/{case_id}")
def execute_decision(case_id: str):
    """Execute the latest decided decision: create a retry Razorpay order
    (linked to the case), build payment link, prepare WhatsApp send."""
    with db() as conn:
        case = conn.execute("SELECT * FROM failed_payments WHERE order_id=? "
                            "ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
        dec = conn.execute("SELECT * FROM agent_decisions WHERE case_id=? "
                           "ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
    if not case or not dec:
        raise HTTPException(404, "case or decision not found")
    case, dec = dict(case), dict(dec)

    if dec["status"] != "decided":
        return {"executed": False,
                "reason": f"decision status is '{dec['status']}' — not executable "
                          f"(refused/queued/handoff cases are never executed)"}

    amount = case["amount"]
    try:
        retry_order = client.order.create({
            "amount": amount, "currency": "INR",
            "receipt": f"rf_{case_id}",   # 🔗 matching key: order ↔ case
            "notes": {"case_id": case_id, "original_failure": case["failure_type"]},
        })
    except Exception as e:
        audit_log("executor", "execution.failed", case_id, {"error": str(e)})
        raise HTTPException(502, f"razorpay order creation failed: {e}")

    link = f"{STORE_BASE}/pay.html?oid={retry_order['id']}&case={case_id}"
    import urllib.parse
    wa_number = (case["phone"] or "").replace("+", "") or "919999999999"
    wa_msg = urllib.parse.quote(dec["message"] or "Complete your PulseFit payment")
    wa_link = f"https://wa.me/{wa_number}?text={wa_msg}"


    with db() as conn:
        conn.execute("""INSERT INTO executions (case_id, order_id, strategy, channel,
                        message, link, status, executed_at)
                        VALUES (?,?,?,?,?,?, 'sent', ?)""",
                     (case_id, retry_order["id"], dec["strategy"], dec["channel"],
                      dec["message"], link, datetime.now().isoformat()))
    audit_log("executor", "execution.sent", case_id,
              {"strategy": dec["strategy"], "retry_order": retry_order["id"]})

    return {"executed": True, "case_id": case_id, "strategy": dec["strategy"],
            "retry_order_id": retry_order["id"], "amount": amount,
            "payment_link": link,
            "whatsapp_link": wa_link,
            "note": "wa.me deep-link now; WhatsApp Business API in production"}


@app.get("/retry-checkout/{order_id}")
def retry_checkout(order_id: str):
    with db() as conn:
        row = conn.execute("""SELECT f.amount FROM executions e
                              JOIN failed_payments f ON f.order_id=e.case_id
                              WHERE e.order_id=? LIMIT 1""", (order_id,)).fetchone()
    if not row:
        raise HTTPException(404, "retry order not found")
    return {"key_id": RAZORPAY_KEY_ID, "amount": row["amount"]}


@app.get("/executions")
def list_executions():
    with db() as conn:
        rows = conn.execute("SELECT * FROM executions ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


# ================= INTROSPECTION ENDPOINTS =================
@app.get("/agent/decisions")
def list_decisions():
    with db() as conn:
        rows = conn.execute("SELECT * FROM agent_decisions ORDER BY id DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]


@app.get("/agent/guardrails")
def guardrails_status():
    ok, why = messaging_allowed_now()
    return {"messaging_window_ok": ok, "reason": why,
            "policy_source": "policy.py (RBI MD-DL 2025, TRAI TCCCPR 2024, DPDP 2023)",
            "global_max_touches": policy.GUARDRAILS["global_max_touches"],
            "grievance_contact": policy.GUARDRAILS["grievance_contact"]}


@app.get("/audit")
def audit_trail(limit: int = 100):
    with db() as conn:
        rows = conn.execute("SELECT * FROM audit_ledger ORDER BY id DESC LIMIT ?",
                            (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/audit/verify")
def audit_verify():
    result = audit.verify_chain()
    audit_log("auditor", "audit.verified", "chain", result)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
