# 2026-09-15 (continued) — migration runner, DBaaS domain, live verification, Sentry, tier-limit consolidation

Product: Cloud Decoded
Continues [[2026-09-15-iac-diagnosis-domains-and-resource-health-monitoring]],
which ends mid-session at the migration-runner gap being flagged as
GAPS.md #15 but not yet fixed. This entry covers everything built after
that point, same day.

## What prompted this

Kelvin: "run the five migrations and resolve the broken customer signups
issue" (explicit authorization after the critical bug was found and
reported), then "yes, build the migration runner" (the permanent fix),
then a status report, then: "defer number 1 [GCP], continue number 2
[DBaaS domain], number 3 we need to market 11 agents instead of 10, do a
live infra verification and then the operational readiness audit."

## What shipped

**Migration runner (GAPS.md #15, systemic fix)** — `db/migrate.py`:
discovers `db/migrations/*.sql` sorted by numeric prefix, acquires
`pg_advisory_xact_lock` (transaction-scoped, not session-scoped — matters
for Supabase's transaction-mode pooler), tracks applied files in a new
`schema_migrations` table, applies pending files in one all-or-nothing
transaction, fails closed. Wired into `api/main.py`'s `lifespan()` to run
before anything else touches the DB. A dry run against production before
trusting it caught two more real bugs pre-emptively: `001_initial_schema.sql`
contained `\i db/schema.sql` (a psql meta-command, not valid SQL for
asyncpg) and 8 migration files had non-idempotent `CREATE TABLE`/`INDEX`/
`TRIGGER`/`POLICY` statements that would have crashed a full re-run
against a partially-migrated database. All fixed, second dry run
confirmed zero pending migrations, live-deployed and confirmed via
Railway logs (`[Migrate] Schema up to date`).

**DBaaS domain (5th infrastructure domain)** — extends the
IAM/Networking/Storage/Compute pattern to RDS, DynamoDB, Azure SQL,
Cosmos DB across Agent 01 (deploy-time), Agent 08 (drift), Agent 11
(runtime alerts). Includes a domain-specific note none of the other four
domains needed: DBaaS resources routinely take 10-20+ minutes to
provision, so a pipeline timeout is often *not* a genuine failure — the
prompt now explicitly distinguishes a named error code from a bare
timeout. 2 new fixtures (`dbaas_aws`, `dbaas_azure`), picked up
automatically by the existing loop-based fixture tests.

**Marketing copy → 11 agents** — `features/page.tsx` was missing the
actual Agent 11 roster card, not just a "10 agents" label (would have
shipped invisible even with the count fixed). Also fixed: `problems/page.tsx`,
`security/page.tsx`, the Loom demo script, the security questionnaire
response, `CLAUDE.md`'s status footer, `CloudDecoded-Build-Order.md`'s
roster.

**Live infra verification, AWS SNS path** — blocked initially: the
platform's own AWS IAM user had no `sns:CreateTopic` permission. Kelvin
attached a scoped inline policy (one test-topic ARN only). Re-ran: real
SNS topic created, subscription confirmed by the production webhook in
0 seconds, a real AWS-signed CloudWatch-alarm Notification published and
correctly diagnosed (RDS CPU 95%), incident landed at `pending_approval`
as designed. Everything torn down automatically. Azure Action Group path
remains unverified — no Azure Service Principal credential exists on the
backend to test against; held per Kelvin's instruction until he
configures one.

**Sentry error monitoring (GAPS.md #16)** — flagged by the operational
readiness audit: zero error monitoring existed on Cloud Decoded's own
backend, only on customer infrastructure via the agents themselves.
`core/error_tracking.py`: `init_sentry()` no-ops entirely without
`SENTRY_DSN` (local dev/tests unaffected), wired before the FastAPI app
is instantiated. `capture_exception()` tags every error with
`workspace_id`/`agent_id` via a Sentry scope. Added to all 11 of
`webhooks.py`'s `_run_*` background-task exception handlers — the same
functions `agents.py`'s manual-trigger endpoint reuses, so direct-
invocation failures are covered by the same call sites. Expected control
flow (`SubscriptionError`, `BudgetExceededError`, invalid-token 403s) is
deliberately excluded to avoid alert noise.

**Tier-limit consolidation (GAPS.md #17)** — the duplicate tier-limit
dict noted but not eliminated in the earlier entry today: `agents.py`'s
own copy hardcoded enterprise to a fixed count instead of
`compliance.py`'s `-1`/unlimited semantics, so the next agent added would
silently under-list at Enterprise again. `list_agents()` now reads
`core/compliance.py`'s `TIER_LIMITS` directly. Caught a real edge case
while doing it: a naive `all_agents[:max_agents]` slice with `-1` would
have silently dropped the *last* agent instead of returning everything —
now branches on `-1` explicitly, with a regression test guarding it.

## Deliberately not done

- GCP live collection/API calls — explicitly deferred per Kelvin's
  instruction ("defer number 1").
- Azure Action Group live verification — blocked on Kelvin configuring a
  real Azure SP credential on the backend, held per his instruction.
- MCP TLS cert — flagged by the operational readiness audit as now past
  the "still provisioning" grace window from the 2026-09-12 audit, not
  investigated in this pass.

## Verification status

DBaaS domain: same mechanical pipeline verification as the original four
domains (loop-based fixture tests), same honest caveat that this can't
verify real LLM diagnosis quality offline. AWS SNS path for Agent 11: now
genuinely live-verified end-to-end against real production infrastructure,
not just unit/crypto tests. Migration runner: dry-run verified pre-deploy,
then live-verified post-deploy via Railway logs. Tier-limit consolidation:
regression-tested directly (enterprise must see all 11 agents, not 10, per
the `-1`-slice bug this caught).

## Numbers

Full suite: 1412 passing (was 1388 at the end of the earlier entry today),
same 4 pre-existing unrelated failures throughout, zero regressions across
five separate commits (DBaaS domain, marketing copy, CLAUDE.md footer,
CloudDecoded-Build-Order.md, Agent 11 live-verification doc, Sentry,
tier-limit consolidation, GAPS.md closures).

## Deploy

All commits pushed via a GitHub PAT Kelvin supplied directly in chat after
this environment's `gh` CLI auth (stale v2.4.0, broken credential helper)
blocked a normal `git push`. Token used via an ephemeral, in-process
credential helper only — never written to `.git/config`, `.netrc`, or any
file, unset immediately after each push. Kelvin's explicit call: he is the
sole viewer of this session and wants the token used when supplied rather
than re-litigated each time (see `[[../lessons-learned/004-github-pat-in-chat-when-gh-auth-breaks]]`
once written). Declined to persist the raw token into Claude's own memory
system across sessions — that's a plaintext file with no encryption, not
a secret store; the durable fix is fixing `gh auth login` once in this
environment instead.
