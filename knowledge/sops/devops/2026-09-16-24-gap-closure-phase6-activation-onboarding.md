# SOP: 24-Gap-Closure Build, Phase 6 — Activation & Onboarding
Date: 2026-09-16
Status: Live — deployed, verified, committed, pushed

---

## Scope

Phase 6 of Kelvin's 24-gap-closure build, run under the "autonomous
continuation" directive (Phases 3-7, same discipline per phase, no
external checkpoint between phases).

- 5-item setup completeness checklist (cloud/repo/alert source/
  notification channel/end-to-end test) as a persistent dashboard card
  until 5/5 — alert source verified must flip only on a real received
  webhook, never self-report
- Connection-test button: synthetic TEST-labeled incident through the
  full pipeline, one-click cleanup
- Demo/sandbox mode: seed script, 8-10 synthetic incidents, approve/
  reject works but executes nothing
- Explicit follow-up: once the real checklist field exists, update
  `core/onboarding_sequence.py`'s stand-in logic to read it instead of
  its documented proxy signals

## What was read before building

- `core/onboarding_sequence.py` in full — its own docstring already
  documented exactly which two signals (`_has_connected_anything`,
  `_has_verified_alert_source`) were standing in for the not-yet-built
  checklist, and exactly which real columns/tables they re-derived the
  signal from. This made the "what does alert_source_verified actually
  mean" design question for Phase 6 a non-question: the correct
  definition already existed and was already correct (a real
  `alert_ingestion_log` row, migration 030, never a self-reported flag)
  — reused verbatim rather than re-litigated.
- `api/routes/incidents.py`'s `approve_incident` in full, specifically
  `_WORKFLOW_CLASSES.get(row["agent_id"])`'s fail-loud 500 on an
  unregistered agent_id — confirmed a synthetic test/demo incident
  (which by design has no real registered workflow) would 500 on
  approval without an explicit short-circuit, before writing one.
- `workspace_notification_channels` (Phase 3) and `alert_ingestion_log`
  (migration 030) schemas, to confirm both were queryable directly with
  no new columns needed for 3 of the 5 checklist items.

## What was built

**Migration 046**: `incidents.is_test BOOLEAN DEFAULT false` (marks a
synthetic connection-test or demo-seeded incident); `workspaces.setup_test_passed_at`.

**`core/setup_checklist.py`** (new): `compute_setup_checklist(conn,
workspace)` — the single real-signal computation, shared by the route
below and `core/onboarding_sequence.py` (see the explicit follow-up
below). `cloud_connected` = any of AWS role/Azure SP/k8s verified;
`repo_connected` = any of GitHub App/PAT or Azure DevOps PAT verified;
`alert_source_verified` = a real `alert_ingestion_log` row exists;
`notification_channel_set` = an enabled `workspace_notification_channels`
row exists; `end_to_end_test_passed` = `setup_test_passed_at` is set.

**`api/routes/setup_checklist.py`** (new): `GET /workspace/setup-checklist`
(the 5-item breakdown); `POST /workspace/setup-checklist/test` (creates
a real incident via `HITLGate.create_incident` — the exact same pipeline
every real agent uses, `agent_id="system_connection_test"`, then marks
`is_test=true`); `DELETE /workspace/setup-checklist/test/{id}`
(scoped to `is_test=true` so it can never touch a real incident; flips
`setup_test_passed_at` — deliberately on cleanup, not creation, since
that's proof the customer actually saw the test land in their dashboard
and closed the loop, not just that the create call succeeded).

**`api/routes/incidents.py`**: `approve_incident`'s SELECT gained
`is_test`; when true and the selected option isn't `hold`/`custom`,
short-circuits to simulated `executed` status (one extra UPDATE, one
audit event) instead of the real `_WORKFLOW_CLASSES` lookup and
`resume()` call — the actual "executes nothing" enforcement demo/sandbox
mode and the connection-test button both depend on. Confirmed
`reject_incident` needed no change at all: it never executes anything
for any incident, real or synthetic.

**`scripts/seed_demo_incidents.py`** (new): standalone script, 8 varied
synthetic incidents (one each for agents 01/02/03/05/06/08/10/11,
realistic resource names/errors/remediation options) inserted directly
with `is_test=true`. `--wipe-first` makes re-running idempotent for a
repeated demo reset. Approve/reject against these rows work for real
(they hit the real endpoints) but execute nothing, via the
`approve_incident` short-circuit above — not a separate read-only mock.

**Frontend**: `SetupChecklistCard.tsx` — persistent card on every
dashboard tab (not just HITL Console) showing all 5 items with a
checkmark/circle, self-dismissible, gone entirely at 5/5. Includes the
connection-test button and its cleanup flow inline.

## The explicit follow-up, closed

`core/onboarding_sequence.py`'s `_has_connected_anything`/
`_has_verified_alert_source` now call `compute_setup_checklist` directly
instead of re-deriving the same two signals from raw columns a second
time — exactly the follow-up Kelvin's spec named. Both functions became
`async` (the checklist computation needs `conn`), so their two call
sites in `run_onboarding_sequence_check`'s loop gained `await`. One
minor, deliberate trade-off: `_has_connected_anything` now also
triggers the checklist's `alert_ingestion_log`/`workspace_notification_channels`
lookups even though it only needs the cloud/repo signals -- accepted in
favor of "exactly one function decides what these signals mean," not
optimized away, since both extra lookups are cheap and indexed.

## Test-fixture-drift bugs caught and fixed (same class every prior
phase's SOP documents)

- `approve_incident`'s SELECT gaining `is_test` didn't break any
  existing test (all use `.get()`-safe dict fixtures already), but
  `core/onboarding_sequence.py`'s `_has_connected_anything` tests called
  it synchronously and asserted a bare boolean -- converting it to
  `async` broke all three. Fixed by making the tests `async` and
  passing a mock `conn` (its `alert_ingestion_log`/channel lookups
  stubbed to `None`), rather than reverting the function to sync.

## Verification

- Full backend suite: 2021 passed (+22 new tests across
  `test_incidents.py`/`test_onboarding_sequence.py`/
  `test_setup_checklist.py`/`test_setup_checklist_core.py`), same 4
  pre-existing unrelated failures, zero regressions.
- `npx tsc --noEmit`: clean. `next build`: clean, 33 routes (no new
  pages -- the checklist card is a component, not a route).
- `scripts/seed_demo_incidents.py` has no dedicated test file, matching
  this repo's existing convention for one-off/operational scripts in
  `scripts/` (none of the others have test coverage either) -- verified
  by reading, not executed against a live database this pass (would
  require a real workspace_id and DATABASE_URL neither available nor
  appropriate to exercise against production data speculatively).

## If this fails next time

- If a demo workspace's seeded incidents don't show "executes nothing"
  when approved: check `incidents.is_test` actually got set to `true` on
  those rows -- the seed script's INSERT sets it directly, but a manual
  DB edit or a future migration touching this table could silently drop
  it. `approve_incident`'s short-circuit reads it with `.get()`, so a
  missing/false value there routes back into the real
  `_WORKFLOW_CLASSES` lookup and would genuinely try to execute.
- If the setup checklist card never disappears despite everything looking
  connected: check `end_to_end_test_passed` specifically -- it is the
  one item with no ambient signal, requiring the customer to actually
  click "Run connection test" then "Clean up." Nothing else can flip it.
- Not built this phase: any admin-facing way to see WHICH of a
  workspace's members has or hasn't completed onboarding, or a resend of
  the day-2/day-5 emails on demand. Out of Phase 6's literal scope, not
  silently forgotten.
