# SOP: 24-Gap-Closure Build, Phase 7 — Platform Hardening
Date: 2026-09-16
Status: Live — deployed, verified, committed, pushed

---

## Scope

Phase 7 of Kelvin's 24-gap-closure build, run under the "autonomous
continuation" directive (Phases 3-7, same discipline per phase). This is
the final build phase before Phase 8 (org layer, design-scoping only,
explicitly not built) and the run's consolidated final report.

- Billing transition tests: card-expired dunning, payment failure →
  past_due → suspended, mid-cycle upgrade proration, downgrade below
  current seat count (decide and implement BLOCK with clear error)
- LLM usage visibility: per-workspace token_usage in dashboard, this
  month + by agent
- Verify whether a GitHub Actions CI pipeline genuinely exists (CLAUDE.md
  describes one) and build if absent

## Finding #1: the documented CI pipeline does not genuinely function

Checked via `gh workflow list`, `gh run list --limit 15`, and `gh pr list
--state all` against the live repo — not guessed from the YAML alone.

- **`deploy.yml`** (CLAUDE.md Phase 1 step 15's "test → build → Fargate
  → notify" pipeline): a real file, but its own header comment says it
  has been `workflow_dispatch`-only (never auto-triggers) since
  2026-08-13 — it targets AWS Fargate/ECR/ECS and `DASHBOARD_WEBHOOK_*`
  secrets that were never provisioned. The real deploy path is Railway
  (backend) + Vercel (frontend) auto-deploy on push, entirely outside
  GitHub Actions. `gh run list` across dozens of pushes this session
  alone shows zero Deploy-workflow runs.
- **`code-quality-gate.yml`** and **`prompt-version-check.yml`**: both
  trigger on `pull_request: branches: [main]` — but this repo's default
  (and only-ever-used) branch is `master`, and `gh pr list --state all`
  returns zero PRs, ever. Neither has fired even once, for the same
  reason: their trigger doesn't match how this repo is actually used.

Net result: no workflow in this repo runs tests on every push, which is
what "a CI pipeline" means in practice — genuinely absent in function,
even though genuinely present as files.

**Built**: `.github/workflows/ci.yml` — triggers on `push`/`pull_request`
to `master` (matching how this repo is actually used, not a PR flow it's
never had), runs backend `pytest tests/ -q` and frontend `tsc --noEmit`
+ `next build`. Deliberately excludes ruff/mypy: `deploy.yml`'s own
header notes every push-triggered run there failed at the ruff lint step
first, meaning ruff fails against this codebase as it stands today —
adding a lint gate that starts red teaches everyone to ignore CI
failures, and cleaning up every existing lint violation is well outside
this phase's scope.

**Deliberately not done**: fixing `code-quality-gate.yml`/
`prompt-version-check.yml`'s `branches: [main]` mismatch. That's a
smaller, separate, lower-risk follow-up (rename one YAML value) — but it
also reflects a real product decision (does this project want a PR-based
review gate at all, given it has never used PRs) that isn't this
session's call to make unilaterally. Flagged for Kelvin in the final
report.

## Finding #2: `past_due` was tracked but never blocked, `suspended` was
blocked but nothing ever set it, and `invoice.payment_failed` was
entirely unhandled

Read `api/middleware/auth.py`'s `_BLOCKED_SUBSCRIPTION_STATUSES =
("canceled", "suspended", "pending_payment")` and
`api/routes/stripe_billing.py`'s webhook dispatch in full before
assuming the chain worked. Confirmed: `invoice.payment_failed` fell
through to the "unhandled event type" no-op branch (grep of the whole
dispatch block); `past_due` was never in the blocked list (a workspace
with a declined card kept full access indefinitely); Stripe's own
`unpaid` subscription status (its own retry schedule exhausted, not
canceled) was never translated to this platform's `suspended` value —
nothing, ever, set a workspace to `suspended`, despite the frontend's
`/billing` page already having full `past_due`/`suspended` UI copy
waiting for a backend that would actually send them.

**Built** (migration 047, `api/routes/stripe_billing.py`):
- `invoice.payment_failed` handler: marks `past_due` immediately (does
  not wait for a later `customer.subscription.updated`, since Stripe's
  Smart Retries can hold a subscription `active` through several failed
  attempts before it ever flips status) and sends one dunning email
  (`core/email.py`'s new `payment_failed_dunning_html`) per failed
  invoice — reflects Stripe's own retry cadence rather than running a
  parallel one.
- `customer.subscription.updated`: Stripe's `unpaid` status now maps to
  this platform's own `suspended` — the actual cutoff at the end of
  "payment failure → past_due → suspended." **Design call**: `past_due`
  itself stays unblocked (a grace period while Stripe's own retries run,
  matching Stripe's recommended dunning UX) — only `suspended` (already
  in the blocked list) actually cuts access. Flagged as a decision, not
  assumed: if Kelvin wants `past_due` to block immediately instead, that
  is a one-line change to `_BLOCKED_SUBSCRIPTION_STATUSES`.
- Downgrade below current seat count: **decided and implemented as a
  BLOCK**. When `customer.subscription.updated` reports a lower-ranked
  tier (`_TIER_RANK`) than the workspace's current one, and the current
  active+invited member count exceeds the new tier's `max_seats`
  (`core/compliance.py`'s existing `TIER_LIMITS`), the tier change is
  **not applied** in this system (stays at the current, higher tier) and
  `workspaces.downgrade_blocked_reason` is set with a specific,
  human-readable reason — surfaced via `GET /billing/status` and now
  rendered as a banner on `/billing`. An audit event
  (`downgrade_blocked`) is written. **Real limitation flagged, not
  silently assumed safe**: this only blocks what OUR system serves —
  Stripe's own subscription record still reflects the lower price paid.
  Programmatically reverting the Stripe subscription itself back to the
  old price is a genuine financial action (see AGENTS/system guidance on
  risky, hard-to-reverse actions) not taken unilaterally here; it's a
  real follow-up for Kelvin to decide on, not a gap silently left open
  without mention.
- Mid-cycle upgrade proration: **verified already correctly handled,
  nothing to build**. This platform delegates every plan change to
  Stripe's own hosted Customer Portal (`create_customer_portal`), which
  prorates automatically by Stripe's own default behavior — there is no
  custom upgrade endpoint in this codebase that could get proration
  wrong.
- Card-expired dunning: the same `invoice.payment_failed` handler above
  covers this — Stripe fires the identical event for an expired card as
  for any other decline; there is no separate "card expired" event type
  to special-case.

## LLM usage visibility

`token_usage` (db/schema.sql) already existed and was already written to
on every real agent LLM call, via every one of the 11 agent workflows +
`core/token_budget.py`'s `record_usage` — confirmed by grep before
assuming a write path needed building. There was simply no dashboard
read of it anywhere in the frontend. Built `GET /workspace/llm-usage`
(`api/routes/llm_usage.py`) — this month's total tokens/cost plus a
per-agent breakdown, alongside the existing budget/utilization figures
`core/token_budget.py`'s `get_spend_summary` already tracks on
`workspaces` itself (reused, not duplicated). New `LlmUsagePanel.tsx`
dashboard tab: totals, a utilization badge color-coded by threshold, and
a per-agent bar breakdown.

## Verification

- Full backend suite: 2035 passed (+14 new tests across
  `test_stripe_billing.py`/`test_llm_usage.py`), same 4 pre-existing
  unrelated failures, zero regressions.
- `npx tsc --noEmit`: clean. `next build`: clean, 33 routes (no new
  pages — LLM usage is a dashboard tab, not a route).
- `.github/workflows/ci.yml` itself could not be exercised by a live
  push+observe cycle within this same session (GitHub Actions runs
  asynchronously on the push this commit makes) — its correctness was
  verified by running the exact same commands (`pytest tests/ -q`,
  `npx tsc --noEmit`, `npm run build`) locally, which is what the
  workflow itself invokes verbatim.

## Test-fixture-drift bugs caught and fixed (same class every prior
phase documents)

- `_handle_subscription_updated`'s new seat-check logic calls
  `db_pool.acquire()` whenever a recognized tier is present in the
  event — three existing tests passed a bare `MagicMock()` as `db_pool`
  (fine when `tier` stayed `None` and the new code path never ran) but
  `test_subscription_updated_recognized_price_maps_to_tier` sets
  `tier="enterprise"`, which now does reach `db_pool.acquire()`. Fixed
  by giving it a real `_pool_with_conn` mock (this file's own existing
  helper) instead of loosening the new logic to tolerate a fake pool.

## If this fails next time

- If a customer disputes their downgrade "not working": check
  `workspaces.downgrade_blocked_reason` first — Stripe's dashboard will
  show the lower price already applied (that side is genuinely not
  blocked), while this app continues serving the old tier's limits until
  the reason clears. This mismatch is the accepted, documented trade-off
  above, not a bug.
- If a workspace never receives a dunning email: check `contact_email`
  is set (optional at signup, migration 026) — logged as a warning, not
  surfaced anywhere in the dashboard yet, same known gap
  `2026-09-16-24-gap-closure-phase5-credential-lifecycle.md`'s own "if
  this fails next time" section already flagged for expiry-warning
  emails. One dashboard nudge ("add a contact email") would close both.
- `.github/workflows/ci.yml` will only start actually gating anything
  once this commit is pushed and GitHub Actions picks it up — confirm
  its first real run in the Actions tab after this phase's push, the
  same "verify live, don't just assume" discipline every other phase in
  this build used for Railway/Vercel.
