# SOP: 24-Gap-Closure Build, Phase 3 — Notification Layer
Date: 2026-09-16
Status: Live — deployed, verified, committed, pushed

---

## Scope

Phase 3 of Kelvin's 24-gap-closure build. Ran as part of the "autonomous
continuation" directive covering Phases 3-7 with no external checkpoint
between phases, but the same internal safety discipline as Phases 1-2
(read first, build, full suite zero-regression, commit, push, confirm
deploy, verify live, write SOP) still applies to each phase before moving
on.

- Email as a third `workspace_notification_channels` channel type
  (reuses `core/email.py`)
- Per-channel `min_severity` floor
- Timezone-aware quiet hours with a suppressed-incident digest fired at
  window end
- Outbound retry queue for failed Slack/PagerDuty/ticketing/email sends
  (5 attempts, exponential backoff), exhausted retries flagged in the
  dashboard

## What was read before building

- `api/routes/workspace_notifications.py` (existing Slack/PagerDuty
  self-serve config pattern) and `core/notifications.py`'s
  `notify_incident_channels` dispatch loop, before adding a third
  channel type or touching the per-channel loop.
- `core/ticketing.py`'s two failure points (`_dispatch_pagerduty_resolve`,
  the main ticketing dispatch in `notify_resolution`) before wiring
  retry-queue enqueueing into them.
- The detached-background-task DB-connection pattern already established
  in `core/notifications.py`/`core/ticketing.py`/`core/onboarding_sequence.py`
  (own short-lived `asyncpg.connect`, not a reused request-scoped
  connection) — followed exactly in the new `core/notification_retry.py`
  rather than inventing a new pattern.
- Existing advisory-lock constants (`db/migrate.py`=847_291_055,
  `core/retention.py`=592_014_773, `core/onboarding_sequence.py`=401_887_226)
  before picking new, distinct constants for the two new periodic jobs.

## What was built

**Migration 043** (`db/migrations/043_notification_layer_phase3.sql`):
adds `min_severity`, `quiet_hours_start`, `quiet_hours_end`,
`quiet_hours_timezone` to `workspace_notification_channels`; creates
`notification_retry_queue` and `notification_suppressed`, both with RLS
matching the migration 031/033/037 convention (service_role_all +
workspace_isolation policies). Applied directly to production (confirmed
idempotent, so `db/migrate.py`'s boot-time runner safely no-ops on it).

**`core/notification_retry.py`** (new): `enqueue_retry`,
`run_pending_retries` (advisory-lock-gated, exponential backoff
`[1, 5, 15, 60, 240]` minutes, 5 max attempts, exhausts to a
`status='exhausted'` row rather than retrying forever),
`is_channel_in_quiet_hours` (midnight-wrap-aware, fails OPEN — never
suppresses — on an invalid IANA timezone), `suppress_for_quiet_hours`,
`run_quiet_hours_digests` (one digest per channel per window-close;
PagerDuty digest is a documented no-op — marks suppressed rows digested
without attempting a send, since PagerDuty has no digest event shape).

**`core/notifications.py`**: added `send_email_notification`; the
per-channel loop in `notify_incident_channels` now applies the severity
floor (via `core/severity.py`'s `SEVERITY_SORT_RANK`, never filtering an
incident with no severity set), checks quiet hours before sending, and
enqueues a retry on any send exception instead of only logging it.

**`core/ticketing.py`**: both existing failure points now also call
`enqueue_retry` (with `send_kind="resolve"`) after their existing
log/audit-event code — unchanged otherwise.

**`api/main.py`**: two new lifespan background loops
(`_notification_retry_loop` every 60s, `_notification_digest_loop` every
600s), same try/except/sleep/cancel-on-shutdown pattern as the existing
retention/onboarding loops.

**`api/routes/workspace_notifications.py`**: new `QuietHoursFields` base
model (validated: severity must be a real `VALID_SEVERITIES` value,
timezone must construct a real `ZoneInfo`) shared by
`ConnectSlackRequest`/`ConnectPagerDutyRequest`/new `ConnectEmailRequest`;
new `PATCH /email`; `GET /workspace/notifications` extended with the 4
new fields; new `GET /workspace/notifications/retry-queue/exhausted` —
the one explicit "flagged in dashboard" surface named in Kelvin's spec.

**Frontend** (`ConnectionsPanel.tsx`, `lib/types.ts`, `lib/api.ts`): new
`ExhaustedRetry`/`ExhaustedRetriesResponse` types, `listExhaustedRetries`
API function, and a red banner (existing amber-warning visual pattern,
red variant) shown when any retries have exhausted, naming the affected
channel type(s) and prompting a credential check.

## Two bugs caught and fixed before any test run (self-caught, not
user- or test-reported)

- `_attempt_send` originally referenced `_channel_config.conn` — the
  class itself, not the context-manager instance — while wiring
  `create_github_issue_ticket`'s live-connection need through the retry
  path. Fixed to capture the instance (`cm = _channel_config(...)`) and
  reference `cm.conn`.
- `_in_quiet_hours`'s `except (ZoneInfoNotFoundError, Exception):` was
  redundant (`Exception` already covers it) — simplified to
  `except Exception:`, removed the now-unused import.

## Two test regressions caught and fixed (same class Phase 1/2 already
document: expanding a SELECT breaks existing mocked-row fixtures)

- `tests/test_notifications.py::TestNotifyIncidentChannels` (2 tests):
  the SELECT gained `min_severity`/`quiet_hours_*`, breaking two mocked
  rows shaped with only `channel_type`/`config_encrypted`. Fixed with a
  `_channel_row()` test helper, not by weakening the new code to `.get()`.
- `tests/test_workspace_notifications_routes.py::TestListNotificationChannels::test_never_returns_config_encrypted_column`:
  same class of break in `list_notification_channels`'s SELECT. Same fix.

## Verification

- Full backend suite: 1976 passed, same 4 pre-existing unrelated
  failures (`test_diagnose_node_returns_three_options` +
  `test_security.py`'s AWS/Azure secret-redaction tests) — zero
  regressions.
- `npx tsc --noEmit`: clean.
- `next build`: clean, 31 routes, no new warnings.
- Deployed: Railway (`kdavis-agentic-platform` service,
  commit `07a4302`) — `list-deployments` showed `SUCCESS`; live-verified
  via `curl` against `/api/v1/workspace/notifications` returning `401`
  (auth-gated real route, not a 404) rather than trusting the status
  field alone.
- Vercel frontend: confirmed serving (200 on root) — no separate
  Vercel-console check performed this pass since the frontend change was
  additive-only (new banner, hidden unless retries have exhausted) and
  `next build` was already clean; flagged here rather than silently
  assumed.

## If this fails next time

- If `notification_retry_queue` grows unbounded: check whether
  `run_pending_retries`'s advisory lock (`_RETRY_LOCK_ID = 738_204_915`)
  is being acquired every pass across all 4 workers — a stuck lock holder
  (crashed mid-transaction) would silently stop all retry processing.
- If quiet-hours digests never fire: check `_DIGEST_LOCK_ID = 219_663_408`
  the same way, and confirm the channel's `quiet_hours_timezone` is a
  real IANA name — an invalid one fails OPEN (no suppression, no digest
  needed) rather than raising, so a typo'd timezone silently disables
  the whole quiet-hours feature for that channel with no error surfaced
  anywhere yet.
