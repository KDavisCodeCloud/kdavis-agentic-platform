# 2026-09-15 (continued) — 12-phase scale-readiness build

Product: Cloud Decoded
Continues [[2026-09-15-migration-runner-dbaas-domain-and-observability]].

## What prompted this

A pre-build scale/reliability readiness assessment (this session) found
a real set of gaps that would bite at real customer volume: no dedup on
repeated alerts, no rate limiting on webhook ingestion, an unsafe shared
checkpointer connection, no durable queue for dropped alerts under
backpressure, unbounded concurrent agent execution, a DB pool sized for
one worker process while the app claimed four, no LLM retry/backoff, no
structured logging, zero RLS on the core tables despite the security
questionnaire claiming otherwise, and no retention policy. Kelvin
approved the merged 12-phase sequence to close all of it in one
continuous build, phase-gated (full suite green, commit, push, verify
live deploy, before the next phase starts) the same way this session's
other multi-phase work has run.

## What shipped (Phases 1-9, brief — full detail in earlier commits this session)

Incidents schema (resource/metric columns) → ingest fixes → dedup
(`find_open_incident`/`bump_occurrence`, collapses repeat alerts into one
incident with an occurrence count instead of spawning a new row per
alert) → webhook rate limiting (`slowapi`, per-workspace key) →
checkpointer connection safety (`core/checkpointer_lock.py`'s
`LockedAsyncPostgresSaver` — serializes access to LangGraph's single
shared psycopg connection) → durable queue (`alert_ingestion_log` table +
`core/ingestion_log.py`, so a dropped alert under backpressure is
recoverable, not silently gone) → execution semaphore + pool
acquire-timeout (`core/execution_semaphore.py`, `core/pool_timeout.py` —
bounds concurrent agent runs and DB connection waits instead of an
unbounded pile-up) → DB pool `max_size=20` + real `--workers 4` (Procfile
and `railway.json` both claimed 4 workers; production had been running
one the whole time) → LLM retry/backoff (`.llm/router.py`'s `complete()`
retries a transient error up to 3x with exponential backoff + jitter on
the same provider before falling through the existing cross-provider
failover chain).

Phase 8's `--workers 4` had a real, explicit tradeoff Kelvin chose to
accept rather than block on: `slowapi`'s in-memory rate limiter has no
shared state across the 4 worker processes, so effective rate limits
became ~4x more permissive than configured until a Redis-backed limiter
is provisioned (GAPS.md #18) — checked for a Postgres-backed option
first (matching Phase 6's durable-queue pattern of avoiding new infra)
and none exists in the `limits` package.

## What shipped (Phases 10-12, this session's visible work)

**Phase 10 — structured logging + failed-run visibility.** `core/hitl.py`
gains `create_failed_incident()` — a direct, one-shot INSERT with
`execution_status='failed'`, no `interrupt()`/operator approval needed,
since there's nothing to approve when diagnosis itself never completed.
All 11 agents' `_hitl_gate_node` now call it from the upstream-error
branch instead of silently `return {}`-ing and dropping the run with no
queryable trace beyond a log line + Sentry capture. `core/json_logging.py`
replaces `api/main.py`'s plain `logging.basicConfig()` with a
`JSONFormatter` — one JSON object per log line, `extra={}` fields
(`workspace_id`, `agent_id`, `incident_id`, LLM provider/retry fields,
webhook block reasons) promoted to top-level keys instead of buried in a
message string. Railway's log viewer confirmed live post-deploy that it
parses these correctly — `logger`/`timestamp`/`level` show as structured
attributes, not raw text.

**Phase 11 — row-level security on core tables.** `workspaces`,
`incidents`, `audit_events`, `token_usage` had zero RLS despite
`docs/customer/security-questionnaire-response.md` telling customers
"row-level security enforced at the database layer, not just application
logic" — that claim was false until migration 031. `ENABLE ROW LEVEL
SECURITY` + a `service_role` bypass + a `workspace_isolation` policy
keyed on `current_setting('app.current_workspace_id')`, set by
`core/workspace_scope.py`'s `workspace_scoped_connection()` — wired into
`get_incident`/`list_incidents` as the proof-of-mechanism, not a
platform-wide rollout.

Deliberately did NOT set `FORCE ROW LEVEL SECURITY` — forcing it blind
against an unknown-posture connecting role risked a full outage (every
unwrapped query path would suddenly see zero rows). `db/migrate.py`'s new
`log_security_posture()` checks `pg_roles` at every startup instead of
assuming, and the real finding, confirmed live: Supabase's `postgres`
role is **not** a superuser but **does** carry `BYPASSRLS=true` — a
specific, checked fact worth remembering for any future RLS work on this
platform, not a generic assumption about what "the postgres role" does.
Not-FORCE was the right call: this app's own connection is unaffected
either way, while the policies still close the real gap for every other
access path (Supabase Studio, anon/authenticated keys, future tools).

**Phase 12 — retention + composite indexes.** `core/compliance.py`'s
`TIER_LIMITS` (already the single source of truth for tier caps, GAPS.md
#16) gains `retention_days`: starter=90, growth=365, enterprise=-1
(unlimited, "configurable" only as a future per-customer override, not
built). `core/retention.py`'s `run_retention_cleanup()` deletes
`incidents`/`audit_events` past that window per-workspace-tier, running
as an in-process periodic task (`api/main.py`'s lifespan: once at
startup, then every 24h) — no separate cron/worker service exists in
this deployment. Guarded by `pg_try_advisory_xact_lock` (transaction-
scoped, matching `db/migrate.py`'s established Supabase-pooler-safe
pattern) so Phase 8's 4 worker processes don't double-delete — confirmed
live post-deploy: exactly the expected mix of "another worker holds the
lock, skipping" and "cleanup pass — nothing past retention" across the 4
workers on the same boot. `db/migrations/032_retention_and_indexes.sql`
adds the composite indexes matching real query/cleanup filter shapes.

## Deliberately not done

- Platform-wide `workspace_scoped_connection()` rollout — only the two
  incidents read routes use it; every other route still relies solely on
  application-layer `WHERE workspace_id = $N` scoping (correct today, no
  DB-level backstop yet).
- A real-Postgres integration test harness — this codebase has none at
  all (asyncpg is stubbed in `tests/conftest.py`), so RLS enforcement and
  the retention DELETE's actual behavior were verified live against
  production post-deploy, not captured as a repeatable regression test.
- Retention DELETE batching — a single unbounded `DELETE ... WHERE
  created_at < cutoff` per tier/table, fine at current table sizes,
  flagged (GAPS.md #21) for when it isn't.
- A real per-customer "configurable Enterprise retention" override —
  still just the `-1` sentinel; no Enterprise customer has asked for a
  specific number yet.

## Verification status

Every phase live-deployed and verified via Railway logs before the next
phase started — migration applied, all 4 workers reaching "Application
startup complete," and for Phases 10-12 specifically, live `curl` checks
against `/health`/`/health/db` plus reading the actual structured log
output (Phase 10), the `log_security_posture()` finding (Phase 11), and
the advisory-lock behavior across all 4 workers on one boot (Phase 12).

## Numbers

Full suite: 1511 passing at the close of Phase 12 (was ~1463 at the start
of Phase 8), same 4 pre-existing unrelated failures throughout, zero
regressions across the full 12-phase sequence.

## Deploy

Every phase: commit → push (GitHub PAT supplied in chat, ephemeral
in-process credential helper, never persisted, `gh` CLI auth still
broken in this environment) → Railway auto-deploy on both services →
verified via `list-deployments`/`get-logs` before moving on. See
[[../lessons-learned/004-github-pat-in-chat-when-gh-auth-breaks]].
