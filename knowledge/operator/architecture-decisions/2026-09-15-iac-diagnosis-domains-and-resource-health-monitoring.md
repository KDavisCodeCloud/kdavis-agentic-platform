# 2026-09-15 — IaC deploy-failure diagnosis + live resource monitoring (domain-complete)

Product: Cloud Decoded
Plan mode used twice (scope expanded mid-build at Kelvin's request, second
plan supersedes the first in the same plan file:
`~/.claude/plans/serialized-growing-tower.md`).

## What prompted this

Kelvin asked whether Cloud Decoded would detect ARM/Bicep/CloudFormation/
Terraform deploy failures, cross-resource auth failures, App Service
content/config problems, and live resource-health issues (SQL slowness, a
resource going down) — direct code investigation found: no ARM/Bicep
support anywhere, Terraform/CloudFormation only referenced for unrelated
purposes, and zero live-monitoring ingestion beyond AKS pod alerts. Kelvin
then asked for a full build sequence, then expanded scope mid-plan to
organize the whole thing around four cloud-infrastructure domains
(IAM/RBAC/Policy, Networking, Storage, Compute) across all three phases,
with Networking defined fresh in this pass (found to not exist anywhere
despite being referenced as "already scoped").

## What shipped (all three phases, `go ahead until completion` directive)

**Phase A** — `agents/agent_01_cicd_triage/prompts/diagnose.md` reorganized
into four domain sections, AWS+Azure deploy-failure categories each,
cross-cutting "domain-aware options, never generic retry" rule with an
explicit safety carve-out (credential exposure = investigation steps only,
never an auto-proposed fix). 8 new fixtures
(`tests/mocks/iac_fixtures.py`), mechanical sanitize→diagnose pass-through
tests only — explicitly does not and can't verify real LLM diagnosis
quality offline.

**Phase B** — Agent 08's already-generic drift-diff engine documented
across the same four domains (needed no code changes for most of it — the
desired-vs-actual diff works on any `resource_type`). One real new
capability: `DriftTools.fetch_app_service_state()` (Azure ARM + Kudu VFS
APIs, reusing the already-stored per-workspace Azure SP credential) plus
a `live_fetch` payload block in `_ingest_node` — this is what turns "App
Service missing a file" or "bad app settings JSON" into a normal drift
item instead of needing the caller to fetch live state themselves.

**Phase C** — new Agent 11 (Cloud Resource Health Monitoring): full agent
scaffold (`agents/agent_11_resource_health/`), new webhook
(`/resource-health-alert`) reusing `aks_alert_webhook`'s proven Azure
Common Alert Schema parsing, new `core/aws_sns.py` for the AWS
CloudWatch→SNS path (subscription-confirmation handshake + real RSA
signature verification — tested with a genuine self-signed cert generated
at test time, not just mocked calls). Deliberately no live cloud-mutation
API calls — every option is a PR proposal or an investigation issue,
same HITL gate as everything else.

## Real bug found and fixed mid-build

`core/compliance.py`'s `TIER_LIMITS` gates on the numeric position parsed
out of `agent_id` (`_extract_agent_number`). Adding Agent 11 without
bumping Growth's `max_agents` from 10→11 would have silently made it
Enterprise-only by numbering accident, not a real pricing decision —
caught before it shipped. Found the *same* bug a second time in
`api/routes/agents.py`'s own separate, duplicate tier-limit dict (which
additionally capped Enterprise at a hardcoded 10, unlike
`core/compliance.py`'s `-1`/unlimited — a second, independent
inconsistency). Both fixed. `agents.py`'s `valid_agents` prefix-check and
`GET /agents`'s listing were also missing Agent 11 entirely — fixed.
`core/compliance.py` had zero prior test coverage — added
`tests/test_compliance.py`.

## Deliberately not done

- Marketing copy (`features/page.tsx`, `problems/page.tsx`) still says
  "10 agents" — a GTM/announcement decision, not folded into this build.
- GCP: payload shape + category guidance documented in Agent 08's SOP and
  Agent 11's prompt, per Kelvin's explicit scope boundary — no GCP
  collection/API calls built.
- Database-as-a-service (RDS, Azure SQL, Cosmos DB, DynamoDB): explicitly
  out of scope per Kelvin's instruction, to be addressed separately.

## Verification status — what's real vs. what still needs a live round trip

Phase A/B: mechanically verified (pipeline handles all domain/cloud
combinations without breaking; App Service fetch logic unit-tested
against mocked Azure API responses). Phase C's SNS signature verification
is genuinely cryptographically proven (real RSA keypair, real sign/verify
round trip in the test itself) — but neither the SNS subscription-
confirmation handshake nor an Azure Action Group have been exercised
against real AWS/Azure infrastructure yet. Same caveat the plan itself
called out before any code was written: do the Azure path first if
piloting, it reuses a code path already proven live for AKS alerts.

## Numbers

100+ new tests (`tests/test_compliance.py`, `tests/test_aws_sns.py`,
`tests/test_agent11.py`, plus additions to three existing test files).
Full suite: 1388 passing (was 1320 before this build), same 4
pre-existing unrelated failures throughout, zero regressions introduced
across three separate commits (Phase A, Phase B, Phase C).

## Deploy

All three phases pushed and auto-deployed successfully via Railway's
GitHub integration — this is the first multi-commit build session where
autodeploy actually worked end-to-end without manual `railway service
source connect` intervention, confirming yesterday's webhook-access fix
holds.

## Post-deploy: critical production bug found and fixed same session

Live-testing Agent 11's new webhook after deploy surfaced a `500`
(expected `403` for an invalid token). Traced to
`asyncpg.exceptions.UndefinedColumnError` — a direct read-only query
against the live `workspaces` table confirmed migrations 024–028 had
**never been applied to production**, despite being committed and
deployed earlier this same session. Root cause: no migration runner
exists anywhere in the deploy pipeline — `db/migrations/*.sql` files are
committed but nothing ever actually executes them against
`DATABASE_URL`.

**Real, active impact:** `POST /workspaces`'s `INSERT` references
`contact_email`/`tos_accepted_at`, both missing — every real customer
signup had been failing with a `500` since the contact-email-capture
commit deployed earlier this session. Kelvin confirmed the fix (all five
migrations are pure `ADD COLUMN IF NOT EXISTS`, verified no drops/data
risk before asking) — connected to the production Supabase Postgres
directly via `DATABASE_URL` (already present on the Railway service),
applied all five in one transaction, verified via
`information_schema.columns`, then live-verified the actual previously-
broken flow end-to-end: `POST /workspaces` now `201`s with a real
workspace token, the resource-health-alert webhook now correctly `403`s.
Verification workspace created during the test was deleted immediately
after confirming success.

**Flagged as GAPS.md #15, not fixed in this pass:** nothing prevents this
exact failure mode from recurring on the next migration. Needs either an
automated migration-runner step in the deploy pipeline, or a hard
process rule that no `db/migrations/` PR merges without a human
confirming it was actually applied to production.
