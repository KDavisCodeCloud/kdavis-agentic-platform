# Release: Cloud Decoded Email Lifecycle System
Date: 2026-09-21
Product: Cloud Decoded
Migration: 051

## What was built
Full lifecycle email engine: onboarding (6 steps, folded in from the
retired day2/day5 cron), stall nudges, abandoned checkout, dunning,
winback, expansion (3 independent templates), trust drip, and the
Decoded Ops newsletter (16 issues + 4 overflow drafts). Compliance layer
(suppression, daily cap, RFC 8058 headers, compliance footer), a 15-min
scheduler mirroring the existing notification-retry claim-loop pattern,
click tracking with UTM attribution, and an admin approval API for the
future CEO Decoded dashboard queue.

## Why it was done
Kelvin's build spec, run as part of a three-workstream session (Cloud
Decoded here; a CEO Decoded dashboard queue and an MSE campaign engine in
separate repos/workstreams). Recon before building found the spec's
assumed topology was wrong in two places (see DECISIONS.md 2026-09-21
entry) and that two existing systems overlapped with this build's scope —
both retired with Kelvin's explicit sign-off rather than left running
alongside the new engine.

## Decisions made (Kelvin's sign-off, pre-build)
1. Retire the Brevo lead-nurture stack (confirmed zero real callers) —
   rewire capture to the new Resend-based engine.
2. Fold the existing onboarding cron's content into the new 7→6-step
   onboarding sequence, retire the old cron.
3. Build all three workstreams (Cloud Decoded, MSE, CEO Decoded) in one
   session, including operating directly in the separate
   `kdavis-microsaas-engine` repo for the MSE workstream.
4. No Kelvin-authored campaign scripts exist — all copy is generated,
   `origin='generated'` on every template.

## Outcome
2134 tests passing (was 2051 before this build's own new tests; +83 net
new, zero regressions against the 4 pre-existing unrelated failures in
`test_agent01_local.py`/`test_security.py`). Deployed to Railway,
`/health` verified live. Full honest gap list in GAPS.md #31 — most
notably: Resend webhook signature verification is implemented but not
yet exercised against a real delivery, and the `hitl` role Kelvin wants
for his wife's template-approval access doesn't exist in this backend's
auth model yet.

## If this fails next time
- Migration 051 is idempotent (`IF NOT EXISTS` throughout) — safe to
  re-run `db/migrate.py` if a prior deploy partially applied it.
- `core/email_seed.py`'s seeding is `ON CONFLICT DO NOTHING` per row —
  re-running never clobbers an approved/edited template.
- If marketing sends stop going out entirely, check for
  `CD_UNSUBSCRIBE_SECRET` unset first — the scheduler fails the whole
  pass closed (not per-row) on that specific condition, by design.
- See the two new SOPs in `knowledge/sops/customer-ops/` for template
  approval and suppression/deliverability incident response.
