# 2026-11-15 — Cloud Decoded: demo rebuild, funnel tracking, outreach refs, sanitizer hardening

**Platform (kdavis-agentic-platform, master):** c90a1f1, 102cf40, fb32b5b, fa500f4, 7e08667, dfa2705, 2a50ac1, b3d5ab9, ca41246, 9edd76a.
**Engine (kdavis-microsaas-engine, main):** abadac1 (mse-api staging first, then prod; both deployed by SHA).
**Migrations:** 059 (per-visitor demo), 060 (funnel events + ref attribution), 061 (incident evidence). All applied cleanly in prod.
**Source:** live demo audit 2026-11-14 (gap table #1-#16).

## What shipped
- **Copy (#1):** every "free trial", "no card required" and "money-back guarantee" claim removed. There is no trial; checkout charges the first month. Checkout button reads "Subscribe — $X/mo →".
- **Demo isolation (#3/#4):** each visitor gets their own 8 incidents; one visitor can no longer empty the demo for others. Controls a demo token can't use (bulk, assign, exempt) are hidden; IAM/FinOps show as Read-Only.
- **Demo content (#5-#10):** four target scenarios (k8s CrashLoopBackOff/OOMKilled, Terraform SG drift on 5432, CI deploy failing on an IAM mismatch, S3 bucket made public) plus four supporting. Each has evidence (kubectl/logs/metrics/terraform/CLI), a diff per option, a blast-radius badge, its own execution log, an explicit Reject with reason, and an audit trail. An option whose log fails ends `failed`, never "resolved".
- **CTA (#11):** after a first approval, "Get started" plus "Book a 15-min walkthrough" — the booking button appears only when `CAL_BOOKING_URL` is set on the Railway API (read per request; no build needed).
- **Funnel (#12/#13):** first-party `cd_funnel_events`, no cookies. Browser events: demo_opened, incident_viewed, signup_clicked, booking_clicked. Server-only: fix_approved, fix_resolved_manually, fix_rejected, signup_completed, checkout_started, subscribed. `?ref=` links attribute everything to a lead. Privacy page discloses it; 13-month retention.
- **Outreach refs (#34):** every Cloud Decoded demo link in outreach copy carries `?ref=r<10 hex of lead id>`, attached at generation and at approval (never trimming approved copy). Outreach cards show each contact's demo activity.
- **Sanitizer (#35):** 13 of 18 real secret formats were leaking (JSON keys, aws sts / az ad sp output, k8s Secret data, GitHub/Slack/Stripe tokens, password= in logs). Now 0/18; diagnostic text preserved. Full suite green for the first time (2430 passed).

## Verified live
- Two browsers (Chromium + Firefox): approving all 8 in one leaves 8 pending in the other.
- `?ref=` journey: session minted with ref, events 204, signup_clicked received during navigation (Railway HTTP log).
- #5-#11 browser run: evidence, diff, blast radius, Reject, stream-to-completion, failure honesty, audit trail, CTA, no API errors, no overflow at 390px.

## Still open
- **Set `CAL_BOOKING_URL=https://cal.com/kelvin-davis-6uitwu/15min`** on the Railway API to show the booking button.
- **Lead-sources expansion:** `lead-sources-expansion-prompt.md` was not found on this machine.
- **Pending outreach draft 0b55f969 (consulting, email)** says "you can find time here: https://thdagentic.com" — edit before approving.
- Test rows from the post-deploy checks: ref `rqa0000test`, campaign `post-deploy-check`.
- Walkthrough video (#16) and /security policy JSON + k8s RBAC manifest (#14/#15) not started.

## If this fails next time
- Demo empty or 403: `demo_sessions` / `incidents.demo_session_id`; the page re-mints on 401/403 once per load.
- Funnel: `select event_name, count(*) from cd_funnel_events group by 1`; per lead: `GET /api/v1/internal/funnel/refs/{ref}` (admin).
- Refs missing on a sent draft: approval response `demo_ref_skipped_over_limit` (touch over its channel cap keeps the plain link).
- Rollback IDs (pre-#5-#11): API d3926d8f-cf30-40ed-afb8-6ca14801b259, frontend dpl_A1kXpFwB9eNGA7NcidWrTHaHRTUt, dashboard dpl_5Bh2Ek8wxEVcQz9HQV5Zm5m9QKTN, mse-api prod 757d2ef3-41f0-4810-bfc0-0b441966c281.
