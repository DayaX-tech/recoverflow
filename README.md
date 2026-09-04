<div align="center">

# RecoverFlow

### Payment failures are inevitable. Blind retries don't have to be.

**Razorpay AI Buildathon 2026 · Track 03 — AI Revenue Recovery**

[![Razorpay](https://img.shields.io/badge/Razorpay-Test%20Mode-blue?logo=razorpay)](https://razorpay.com/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Database](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite)](https://sqlite.org/)
[![Track](https://img.shields.io/badge/Buildathon-AI%20Revenue%20Recovery-8A2BE2)](https://razorpay.com/)
[![Status](https://img.shields.io/badge/Status-Demo%20Ready-brightgreen)]()

**[▶ Live Demo](#-demo-flow)** · **[🏗 Architecture](#-system-architecture)** · **[🎥 5-Min Pitch](#-buildathon-pitch)**

</div>

---

> **Payment failure is not revenue loss.**
> **The real problem is deciding what should happen next.**

RecoverFlow is a payment-recovery control plane that turns failed Razorpay payments into bounded, explainable recovery actions — and *proves* whether the money actually came back.

<!-- 📸 HERO SCREENSHOT — place your main Mission Control dashboard image here.
     Save the file at: assets/screenshots/mission-control-hero.png
     Then uncomment the line below.
-->
<!-- ![RecoverFlow Mission Control](assets/screenshots/mission-control-hero.png) -->

---

## 📚 Table of Contents

- [The 30-Second Overview](#-the-30-second-overview)
- [Problem](#-problem)
- [Core Idea](#-core-idea)
- [System Architecture](#-system-architecture)
- [Agent Architecture](#-agent-architecture)
- [Workflows (1–4)](#-workflow-1--₹799-one-time-recovery)
- [Where AI / Intelligence Fits](#-where-ai--intelligence-fits)
- [Guardrails](#️-guardrails)
- [Audit Trail](#-audit-trail)
- [Mission Control Dashboard](#-mission-control-dashboard)
- [Virtual Clock](#️-virtual-clock)
- [Razorpay Integration](#-razorpay-integration)
- [Recovery State Machine](#-recovery-state-machine)
- [End-to-End Test Matrix](#-end-to-end-test-matrix)
- [What Broke During Development](#-what-broke-during-development)
- [What Counts as "Recovered"](#-what-counts-as-recovered)
- [Repository Structure](#-repository-structure)
- [Tech Stack](#️-tech-stack)
- [Local Setup](#-local-setup)
- [Environment Variables](#-environment-variables)
- [API Surface](#-important-api-surface)
- [Demo Flow](#-demo-flow)
- [Real vs Simulated](#️-real-vs-simulated)
- [Security & Safety Principles](#-security--safety-principles)
- [Engineering Principles](#-engineering-principles)
- [Buildathon Track](#-razorpay-ai-buildathon-2026)
- [Product Thesis](#-the-product-thesis)
- [Future Direction](#-future-direction)
- [Buildathon Pitch](#-buildathon-pitch)

---

## 🚀 The 30-Second Overview

A payment failure does **not** automatically mean lost revenue.

A card decline, a temporary payment failure, a subscription renewal failure, and an unknown gateway error should not all receive the same recovery action.

RecoverFlow answers the harder question:

> **What should happen next?**

It observes the Razorpay event, diagnoses the failure, selects a bounded recovery strategy, schedules or executes the action, waits for the actual Razorpay payment outcome, and reconciles the recovered payment back to the original failure.

```text
                    PAYMENT FAILURE
                           │
                           ▼
                    ┌─────────────┐
                    │   AGENT 1   │
                    │  MONITORING │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   AGENT 2   │
                    │  DIAGNOSIS  │
                    │  + POLICY   │
                    └──────┬──────┘
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
        RECOVER NOW    RETRY LATER   CUSTOMER ASSISTED
             │             │             │
             │             ▼             │
             │        ┌───────────┐      │
             │        │  AGENT 4  │      │
             │        │ SCHEDULER │      │
             │        └─────┬─────┘      │
             │              │            │
             └──────────────┼────────────┘
                            ▼
                     ┌─────────────┐
                     │   AGENT 3   │
                     │    ACTION   │
                     └──────┬──────┘
                            │
                            ▼
                       RAZORPAY API
                            │
                            ▼
                        CUSTOMER
                            │
                            ▼
                    RAZORPAY WEBHOOK
                            │
                            ▼
                     RECONCILIATION
                            │
                            ▼
                      💰 RECOVERED
```

---

## 🎯 Problem

Most payment recovery systems can answer:

> "Did the payment fail?"

RecoverFlow focuses on the more important questions:

- Why did it fail?
- Should we retry it?
- When should we retry it?
- Should we use an alternate recovery method?
- When should automatic retries stop?
- When should the customer take over?
- Did the recovery action actually recover the money?
- Can we explain how the decision was made?

The objective is not maximum automation. The objective is:

> **Maximum recoverability within explicit boundaries.**

---

## 💡 Core Idea

```text
SENSE → DIAGNOSE → DECIDE → SCHEDULE / ACT → CUSTOMER → RECONCILE → PROVE RECOVERY
```

RecoverFlow deliberately separates **decision intelligence** from **financial execution**.

> **Intelligence chooses the recovery path.**
> **Policy defines the boundary.**
> **Razorpay confirms the money.**

Financial actions should never depend on an unrestricted autonomous decision.

---

## 🏗️ System Architecture

<!-- 📸 ARCHITECTURE DIAGRAM (optional export) — assets/screenshots/architecture.png -->

```text
                         ┌────────────────────────┐
                         │    RAZORPAY TEST MODE  │
                         │  Payments + Webhooks   │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │        AGENT 1         │
                         │       MONITORING       │
                         │                        │
                         │ • Webhook verification │
                         │ • Deduplication        │
                         │ • Failure detection    │
                         │ • Classification       │
                         │ • Reconciliation       │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │        AGENT 2         │
                         │   DIAGNOSIS + POLICY   │
                         │                        │
                         │ • Failure diagnosis    │
                         │ • Recovery scope       │
                         │ • Retry eligibility    │
                         │ • Strategy selection   │
                         │ • Guardrails           │
                         └────────────┬───────────┘
                                      │
                         ┌────────────┴────────────┐
                         │                         │
                         ▼                         ▼
                ┌─────────────────┐       ┌─────────────────┐
                │     AGENT 4     │       │     AGENT 3     │
                │    SCHEDULER    │       │     ACTION      │
                │                 │       │                 │
                │ • Cooldowns     │       │ • Retry order  │
                │ • Virtual clock │       │ • Payment link │
                │ • Renewals      │       │ • WhatsApp URL │
                │ • Retry limits  │       │ • Execution log│
                └────────┬────────┘       └────────┬────────┘
                         │                         │
                         └───────────┬─────────────┘
                                     ▼
                            ┌──────────────────┐
                            │     CUSTOMER     │
                            │ Recovery Payment │
                            └────────┬─────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │ RAZORPAY WEBHOOK │
                            │ Payment Outcome  │
                            └────────┬─────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │  RECONCILIATION  │
                            │                  │
                            │ Retry → Case     │
                            │ Case → Payment   │
                            │ Payment → Result │
                            └────────┬─────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │   AUDIT LEDGER   │
                            │  Hash-chained    │
                            └────────┬─────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │ MISSION CONTROL  │
                            │   Live Dashboard │
                            └──────────────────┘
```

The dashboard is connected to the live FastAPI backend and SQLite database — real mappings for failed payments, decisions, executions, and audit records.

---

## 🤖 Agent Architecture

### Agent 1 — Monitoring
**Purpose:** Understand what happened.

- Razorpay webhook events
- Webhook verification
- Duplicate-event handling
- Payment failure classification
- Creation of failed-payment cases
- Successful-payment reconciliation

Agent 1 establishes the canonical recovery case and later maps successful retry payments back to the original failure.

### Agent 2 — Diagnosis & Policy
**Purpose:** Decide what should happen next.

Evaluates:
- Recovery jurisdiction / scope
- Failure taxonomy
- Retry / touch limits
- Communication / action constraints

Selectable strategies: `retry_later` · `alt_method` · `update_instrument` · `nudge_now` · `reauth` · `customer_assisted`

Unsupported or ambiguous cases are **escalated**, never forced into an unsafe action.

> **Design choice:** the financial policy layer is intentionally deterministic and auditable. No unrestricted model has authority over money movement.

### Agent 3 — Action
**Purpose:** Execute an approved strategy.

- Creates Razorpay retry orders
- Generates secure recovery payment links
- Prepares WhatsApp recovery deep links
- Records executions
- Associates recovery actions with the original failure case

Agent 3 executes an already-approved strategy — it does not invent one.

### Agent 4 — Scheduler
**Purpose:** Control *when* time-based recovery is allowed.

- Retry cooldowns
- Scheduled retries
- Subscription renewal timing
- Retry eligibility & limits
- Application-level virtual time

Prevents the system from repeatedly attempting a failing payment outside of policy.

---

## 🔄 Workflow 1 — ₹799 One-Time Recovery
*PulseFit Shaker Bottle*

```text
Customer → ₹799 Razorpay Checkout → Payment Failure
   → Agent 1 (Detect + Classify)
   → Agent 2 (Select alternate-method recovery)
   → Agent 3 (Create retry order + recovery link)
   → Customer completes payment
   → Razorpay Webhook
   → Agent 1 Reconciliation
   → Original Case = RECOVERED
```

**Business invariant:** the Shaker is a one-time purchase — recovery must not accidentally create a subscription.

`Purchase Type = ONE_TIME` · `Subscription Created = 0` · `Recovery = SUCCESSFUL`

---

## 🔄 Workflow 2 — ₹14,999 Annual One-Time Recovery
*PulseFit Elite Annual Pass*

```text
₹14,999 Checkout → Payment Failure → Diagnosis → Recovery Strategy
   → Retry Payment → Razorpay Capture → Webhook → Reconciliation
   → ₹14,999 RECOVERED
```

`Purchase Type = ONE_TIME` · `Subscription Created = 0`

This proves recovery preserves the semantics of the original purchase.

---

## 🔄 Workflow 3 — ₹1,499 Subscription Initial Checkout
*PulseFit Pro Membership*

```text
₹1,499 Initial Checkout → Payment Failure → Recovery Decision
   → Recovery Payment → Razorpay Webhook → Reconciled
   → Subscription ACTIVE → Next Billing Date = +30 days
```

`Purchase Type = SUBSCRIPTION` — successful recovery activates the subscription and establishes the next billing date.

---

## 🔁 Workflow 4 — Subscription Renewal Recovery
*The most important lifecycle in the demo*

```text
Renewal Attempt #1 → ❌ Failure → Agent 2: RETRY_LATER → Agent 4: 48H COOLDOWN
Renewal Attempt #2 → ❌ Failure → Agent 4: 48H COOLDOWN
Renewal Attempt #3 → ❌ Failure → AUTOMATIC RETRIES STOP
   → CUSTOMER_ASSISTED → Secure Recovery Link → Customer Pays
   → Razorpay Webhook → Reconciliation → Renewal = PAID
   → Subscription = ACTIVE → Next Billing Date +30 days
```

RecoverFlow does **not** interpret "recovery" as "retry forever":

> **Automatic recovery → bounded retries → customer-assisted recovery**

---

## 🧠 Where AI / Intelligence Fits

> **Use intelligence where reasoning adds value. Use deterministic controls where financial correctness matters.**

```text
Payment Context → Failure Understanding → Recovery Strategy → Policy Guardrails → Financial Execution
```

The current implementation keeps the core financial policy and execution path **deterministic and auditable**. This is deliberate — an unrestricted AI model should not directly decide:

- whether money is captured
- how many times a payment may be retried
- whether a retry limit can be exceeded
- whether a payment was actually successful
- whether a subscription should be marked paid

```text
Agentic / intelligent decision → Policy boundary → Deterministic execution → Razorpay result
```

> **Intelligence proposes the path. Policy controls the boundary. Razorpay confirms the outcome.**

---

## 🛡️ Guardrails

- Recovery scope
- Supported failure taxonomy
- Retry limits
- Cooldown periods
- Customer-assisted handoff
- Unknown-case escalation
- Action eligibility
- Auditability

```text
Unknown failure → Do NOT guess → Escalate
Retry limit reached → Do NOT retry forever → Customer-assisted recovery
```

---

## 🔐 Audit Trail

A financial recovery system must explain not only *what* happened, but *why*. RecoverFlow records meaningful state transitions through a **hash-chained audit ledger**.

```text
Razorpay Webhook → Failure Classified → Diagnosis Created → Strategy Selected
   → Scheduler Decision → Recovery Action → Retry Order Created → Payment Captured
   → Webhook Reconciled → Recovery Closed
```

Verification endpoint: `GET /audit/verify`

Secrets, payment signatures, and unnecessary sensitive information are never written to the audit trail.

---

## 💻 Mission Control Dashboard

<!-- 📸 DASHBOARD SCREENSHOTS — recommended location: assets/screenshots/
     Suggested filenames:
       - assets/screenshots/mission-control-overview.png
       - assets/screenshots/agent-pipeline.png
       - assets/screenshots/case-inspection.png
       - assets/screenshots/audit-verification.png
     Embed with:
       ![Mission Control Overview](assets/screenshots/mission-control-overview.png)
-->

```text
┌─────────────────────────────────────────────────────────────┐
│                 RECOVERFLOW MISSION CONTROL                 │
│  LIVE BACKEND     VIRTUAL CLOCK        RAZORPAY TEST MODE   │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ RECOVERED    │ RECOVERY     │ ACTIVE       │ ACTIVE         │
│ REVENUE      │ RATE         │ CASES        │ SUBSCRIPTIONS  │
├──────────────┴──────────────┴──────────────┴────────────────┤
│ Gateway → Agent 1 → Agent 2 → Agent 4 → Agent 3              │
│                              ↓              ↓                │
│                           Customer → Reconciliation          │
│                                         ↓                    │
│                                      RECOVERED                │
├─────────────────────────────────────────────────────────────┤
│ Agent Coordination │ Case Inspection │ Audit │ Guardrails    │
└─────────────────────────────────────────────────────────────┘
```

The dashboard reads **live backend state** — it does not maintain a second source of truth. It provides: recovery pipeline · agent coordination · case inspection · subscription renewal timeline · guardrail state · audit verification · virtual clock controls · payment/recovery links · live status updates.

---

## ⏱️ Virtual Clock

Subscription retry workflows normally take days to reproduce. RecoverFlow uses an application-level virtual clock for deterministic demos.

**Controls:** `+12 HOURS` · `+48 HOURS` · `+1 MONTH` · `RESET DEMO`

```text
Attempt #1 → +48h → Attempt #2 → +48h → Attempt #3 → Retry Cap → Customer Assisted → Recovery
```

The virtual clock changes application business time only — it never modifies the OS clock.

---

## 💳 Razorpay Integration

Used for: order creation · payment failure events · payment capture events · webhook processing · retry orders · recovery payment links · successful payment reconciliation.

```text
Action Created ≠ Payment Succeeded ≠ Recovery Reconciled
```

A case is considered recovered **only after** the successful payment event is received and reconciled to the original failure.

---

## 📊 Recovery State Machine

```text
FAILED → OBSERVED → DIAGNOSED → DECIDED
                                   │
                 ┌─────────────────┼──────────────┐
                 ▼                 ▼              ▼
             EXECUTE           SCHEDULE       ESCALATE
                 │                 │
                 │                 ▼
                 │             COOLDOWN → EXECUTE
                 │                 │
                 └────────┬────────┘
                          ▼
                 CUSTOMER PAYMENT
                          │
                          ▼
                  RAZORPAY WEBHOOK
                          │
                          ▼
                  RECONCILIATION
                          │
                          ▼
                     RECOVERED
```

---

## 🧪 End-to-End Test Matrix

| Scenario | Purchase Type | Expected Outcome |
|---|---|---|
| PulseFit Shaker — ₹799 | One-time | Recovered, zero subscription |
| PulseFit Elite — ₹14,999 | One-time | Recovered, zero subscription |
| PulseFit Membership — ₹1,499 initial | Subscription | Recovered, active subscription |
| Renewal Attempt #1 | Subscription renewal | Failure → retry later |
| Renewal Attempt #2 | Subscription renewal | Failure → retry later |
| Renewal Attempt #3 | Subscription renewal | Automatic retry cap |
| Customer-assisted recovery | Subscription renewal | Recovery link generated |
| Successful renewal | Subscription renewal | Reconciled + next billing advanced |

---

## 🐛 What Broke During Development

RecoverFlow was tested against **actual Razorpay Test Mode events**, not just mocked happy paths.

Razorpay returned an issuer failure containing `error_source = issuer`, `error_reason = payment_failed`. The first implementation incorrectly classified this as `unknown_failure`, causing the system to escalate a recoverable card failure instead of choosing an alternate recovery method.

The gateway error taxonomy and classifier mapping were corrected, and the flow was re-tested end-to-end:

```text
Razorpay Failure → Correct Classification → Diagnosis → Alternate Recovery
   → Retry Order → Customer Payment → Webhook → Reconciliation → RECOVERED
```

**Lesson:** real payment integrations expose failure semantics that idealized test cases often miss.

---

## 📈 What Counts as "Recovered"?

```text
ACTION CREATED ≠ PAYMENT SUCCEEDED ≠ PAYMENT RECONCILED
```

The final recovery state is based on the actual successful payment event and reconciliation against the original failure case — this prevents operational activity from being reported as recovered revenue.

---

## 📦 Repository Structure

```text
recoverflow/
│
├── README.md
├── assets/
│   └── screenshots/              ⭐ Put all dashboard/demo images here
│       ├── mission-control-overview.png
│       ├── agent-pipeline.png
│       ├── case-inspection.png
│       └── audit-verification.png
│
├── apps/
│   ├── agent/
│   │   ├── agents/
│   │   │   ├── monitoring.py
│   │   │   ├── diagnosis.py
│   │   │   ├── action.py
│   │   │   ├── scheduler.py
│   │   │   └── subscriptions.py
│   │   ├── audit.py
│   │   ├── classification.py
│   │   ├── core.py
│   │   ├── main.py
│   │   ├── policy.py
│   │   └── pulsefit.db
│   │
│   ├── dashboard/
│   │   ├── dashboard.html
│   │   ├── dashboard.css
│   │   └── dashboard.js
│   │
│   └── storefront/
│       ├── index.html
│       ├── lab.html
│       └── pay.html
│
├── docker-compose.yml
└── README.md
```

---

## 🛠️ Tech Stack

**Backend:** Python · FastAPI · REST APIs · Razorpay SDK · SQLite
**Recovery Engine:** Monitoring agent · Diagnosis/policy engine · Action agent · Scheduler · Subscription lifecycle engine · Hash-chained audit ledger
**Frontend:** HTML · CSS · JavaScript · Live polling
**Integration:** Razorpay Test Mode · Razorpay payment APIs · Razorpay webhooks · WhatsApp recovery deep links

---

## 🚀 Local Setup

**1. Start Backend**
```bash
cd apps/agent
python -m uvicorn main:app --port 8000
```
Backend → `http://localhost:8000`

**2. Start Storefront** *(new terminal)*
```bash
cd apps/storefront
python -m http.server 3000
```
Storefront → `http://localhost:3000`

**3. Start Mission Control** *(new terminal)*
```bash
cd apps/dashboard
python -m http.server 3001
```
Dashboard → `http://localhost:3001/dashboard.html`

---

## 🔑 Environment Variables

Create `apps/agent/.env`:

```env
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
STORE_BASE_URL=http://localhost:3000
```

**Never commit:** `.env` · API secrets · Razorpay private keys · webhook secrets · production credentials

---

## 🔌 Important API Surface

```text
/failures
/orders
/executions
/agent/decisions
/agent/guardrails
/audit
/audit/verify
/agent/clock/jump
/agent/clock/reset
/agent/run-due
/agent/diagnose
/agent/execute/{case_id}
/recovery-scope/{order_id}
```

These endpoints power the live recovery pipeline, agent decision feed, guardrail state, audit verification, and virtual-time controls.

---

## 🧭 Demo Flow

**Demo A — One-Time Recovery**
```text
₹799 Shaker → Fail Payment → Agent 1 → Agent 2 → Agent 3
   → Recovery Payment → Razorpay Webhook → RECOVERED
```

**Demo B — Subscription Lifecycle**
```text
₹1,499 Membership → Recover Initial Checkout → Subscription ACTIVE
   → +1 MONTH → Renewal Failure → +48H → Attempt #2 → +48H → Attempt #3
   → Retry Cap → Customer Assisted → Recovery Payment → Webhook
   → RECONCILIATION → Subscription ACTIVE
```

---

## ⚖️ Real vs Simulated

**Real in Razorpay Test Mode:** order creation · payment failures · payment capture · webhook events · retry orders · recovery payment flow · payment reconciliation

**Application-level simulation:** the subscription scheduler uses a virtual application clock to reproduce multi-day renewal timelines within minutes. The OS clock is never modified.

**WhatsApp:** RecoverFlow generates a WhatsApp deep link — it does not claim WhatsApp has automatically delivered a message. The customer opens the link and sends/approves it themselves.

---

## 🔒 Security & Safety Principles

1. **Test Mode** — all demonstrated payment operations use Razorpay Test Mode
2. **Bounded Automation** — recovery strategies are constrained by application policy
3. **Retry Limits** — subscription recovery stops automatic retries at a configured boundary
4. **Reconciliation** — a recovery action isn't "successful" until the payment result is received and reconciled
5. **Auditability** — meaningful state transitions are written to the audit ledger
6. **Secrets** — credentials come from environment variables, never committed source

---

## 🧠 Engineering Principles

1. **Don't blindly retry** — a failed payment requires diagnosis
2. **Separate decision from execution** — no single uncontrolled component decides *and* executes a financial action
3. **Bound automation** — retries need explicit limits and cooldowns
4. **Treat webhooks as financial evidence** — a generated recovery order is not proof of recovery
5. **Make every important decision reconstructable** — a financial workflow needs an audit trail

---

## 🏆 Razorpay AI Buildathon 2026
### Track 03 — AI Revenue Recovery

RecoverFlow is designed around the track's core objective:

> Find revenue that is slipping away and win it back through measured, compliant, and auditable recovery.

Focus areas: revenue recovery · agentic decisioning · bounded automation · Razorpay payment integration · subscription lifecycle recovery · measurable outcomes · auditability · failure-driven engineering

---

## 💰 The Product Thesis

A payment failure is not the end of the transaction — it's a **decision point**.

```text
FAILED PAYMENT → Why? → What is allowed? → What is the best recovery path?
   → When should it happen? → Did the customer pay? → Did we actually recover the revenue?
```

RecoverFlow turns that decision point into an auditable workflow.

---

## 🔮 Future Direction

- Merchant-specific recovery policies
- Confidence-aware recovery routing
- Learned recovery ranking
- Richer failure prediction
- Batch-level recovery benchmarking
- Human review queues
- Additional payment instruments
- Production-grade event infrastructure
- Merchant recovery analytics

> **Use intelligence to improve the decision. Use deterministic systems to protect the transaction.**

---

## 🎥 Buildathon Pitch
*The 5-minute story*

| Time | Beat |
|---|---|
| 0:00 | **Problem** — Payment failure doesn't mean revenue is lost; the problem is deciding what happens next |
| 0:30 | **Product** — Diagnose the failure, choose immediate recovery / scheduled retry / customer-assisted recovery |
| 1:00 | **Live Demo** — ₹799 one-time recovery |
| 1:45 | **Business Correctness** — ₹14,999 recovery with zero subscription created |
| 2:00 | **Recurring Recovery** — ₹1,499 subscription lifecycle |
| 2:30 | **Retry Policy** — Attempt 1 → +48h → Attempt 2 → +48h → Attempt 3 → automatic cap |
| 3:00 | **Customer-Assisted Recovery** — recovery link / WhatsApp deep link → successful payment |
| 3:30 | **Architecture** — Monitoring → Diagnosis → Scheduler/Action → Customer → Webhook → Reconciliation |
| 4:00 | **AI Judgment** — why intelligent decisioning is separated from deterministic execution |
| 4:20 | **What Broke** — the real `payment_failed` classification bug and the fix |
| 4:45 | **Results** — recovered payment outcomes, subscription correctness |
| 4:55 | **Closing** — *"Payment failures are inevitable. Blind retries don't have to be."* |

---

<div align="center">

## 🏁 Final Statement

**RecoverFlow is not a retry script. It is a revenue recovery control plane.**

It observes payment failures, understands the recovery context, chooses a bounded strategy, executes the approved action, respects retry boundaries, involves the customer when automation should stop, and uses Razorpay's actual payment outcome to prove recovery.

### Recover revenue deliberately — not blindly.

**Built for the Razorpay AI Buildathon 2026 · Track 03 — AI Revenue Recovery**

</div>