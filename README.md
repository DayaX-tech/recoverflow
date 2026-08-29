# RecoverFlow — Governed Payment Recovery Agent

Not another retry system. RecoverFlow is the authorization, refusal,
and audit layer that a payment-recovery agent needs before it's
allowed to move money.

**Track 3 positioning:** Razorpay shipped Subscription Recovery Agents
in Agent Studio. We build the layer beside them — deterministic
RBI/NPCI authorization, check-then-act safety, and rupee-denominated
proof that governed recovery beats naive retry.

## Status
- [x] Phase 1: DB + repo + customer messaging channel verified
- [ ] Phase 2: Storefront (PulseFit gym — products + subscriptions)
- [ ] Phase 3: Failure zoo (6 forced failure types)
- [ ] Phase 4: Sense + Diagnose
- [ ] Phase 5: Authorize (RBI/NPCI gate + check-then-act)
- [ ] Phase 6: Plan + Act (retry / WhatsApp link / reschedule)
- [ ] Phase 7: Audit + benchmark vs naive retry
- [ ] Phase 8: Dashboard
- [ ] Phase 9: Docs + pitch video

## Stack
FastAPI · Postgres (Docker) · Razorpay (test mode) · wa.me deep-link
notification (pluggable transport — WhatsApp Business Cloud API in production)
