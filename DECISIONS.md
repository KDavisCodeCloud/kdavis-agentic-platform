# DECISIONS

Architectural decisions log.

## 2026-09-15 — 12-phase scale-readiness build (merged sequence, complete)

Full detail: `knowledge/operator/architecture-decisions/2026-09-15-scale-readiness-build.md`

Sequential 12-phase build addressing real scale/reliability gaps found in
a pre-build readiness assessment. Phases 1-9 (incidents schema, ingest
fixes, dedup, webhook rate limiting, checkpointer connection safety,
durable queue + `alert_ingestion_log`, execution semaphore + pool
acquire-timeout, DB pool `max_size=20` + real `--workers 4`, LLM
retry/backoff) landed earlier in this session. This entry closes out the
remaining three:

- **Phase 10** — `core/hitl.py`'s new `create_failed_incident()` gives
  all 11 agents a real `execution_status='failed'` incident instead of a
  silently dropped run when a diagnose-node error occurs upstream of
  HITL. `core/json_logging.py` replaces plain-text logging with one JSON
  object per line (Railway-queryable by field) across the highest-value
  call sites (HITL, LLM router, webhook ingestion).
- **Phase 11** — Real Postgres RLS policies on `workspaces`/`incidents`/
  `audit_events`/`token_usage` (migration 031), closing a real gap
  between what the customer security questionnaire claimed and what
  existed. Deliberately did **not** set `FORCE ROW LEVEL SECURITY`
  blind — `db/migrate.py`'s new `log_security_posture()` confirmed live
  in production that `DATABASE_URL`'s role (`postgres`) carries
  `rolbypassrls=true`, meaning the app's own connection bypasses these
  policies regardless of FORCE; the policies still close the gap for
  every *other* access path (Supabase Studio, anon/authenticated keys).
  `core/workspace_scope.py` wires real DB-level scoping into the two
  customer-facing incident read routes as a proof of the mechanism, not
  a platform-wide rollout (see GAPS.md #20).
- **Phase 12** — Tier-based retention (`core/compliance.py`'s
  `TIER_LIMITS` gains `retention_days`: 90/365/unlimited) enforced by an
  in-process periodic cleanup task (`core/retention.py`,
  `pg_try_advisory_xact_lock`-guarded across Phase 8's 4 worker
  processes), plus composite/GIN indexes matching the actual query and
  cleanup filter shapes (migration 032).

Real, checked-not-assumed finding worth calling out on its own: Supabase's
`postgres` role is **not** a Postgres superuser but **does** carry
`BYPASSRLS`. Any future RLS work on this platform must account for that
specific fact, not a generic assumption about what "the postgres role"
does.

Full test suite: 1511 passing (was ~1463 before Phase 9), same 4
pre-existing unrelated failures throughout. See GAPS.md #18-#21 for
every deliberate scope-narrowing decision made along the way.

## 2026-09-14 — Connectivity roadmap completion + operational readiness fixes

Full detail: `knowledge/operator/architecture-decisions/2026-09-14-connectivity-roadmap-and-operational-readiness.md`

- Agents 04/10 now receive per-workspace GitHub credentials via
  `build_agent_credentials()` (were silently falling back to a shared
  `GITHUB_TOKEN` env var — a cross-tenant leak risk for every Growth+
  customer). Agents 04/08/10 route PR creation through
  `core/repo_tools.py` instead of three duplicate GitHub API
  implementations.
- Real per-workspace Kubernetes credentials (migration 025) and Azure
  DevOps PAT + webhook secret (migration 024) replace prior global
  stopgaps.
- `workspaces.contact_email` added (migration 026) — the table had no
  email column at all, so nothing in Cloud Decoded's own code could ever
  send a welcome email or an Enterprise MCP-invite alert. Now required
  and validated at signup.
- GitHub App "the-cloud-decoded" is registered but still marked private
  in GitHub's own settings — a private App can only be installed by its
  owning account, so no real customer can install it until it's flipped
  to public (GitHub-side setting, not a code change).
- Deploy note: Railway's and Vercel's GitHub auto-deploy webhooks did
  not pick up this session's push within a reasonable wait; both were
  triggered manually (`railway service source connect` re-trigger,
  `vercel --prod`) from the same pushed commits. Worth checking whether
  the GitHub webhook itself is still correctly configured on both sides.
  **Confirmed again on a second push later the same session** — not a
  one-off; genuinely worth Kelvin checking the GitHub webhook config on
  both Railway's and Vercel's project settings.
- Follow-on pass same session: guided post-checkout flow, real LLM key
  management (ConnectionsPanel), legacy-PAT migration nudge, real data
  deletion (`purge-data`, migration 027), click-through ToS acceptance +
  real `/terms`/`/privacy` pages (migration 028), and the four
  customer-lifecycle SOPs. Full detail in the same architecture-decisions
  file linked above (now has a "Round 2" section). Live-verified after
  deploy: `/terms`/`/privacy` return 200, `POST /workspaces` 422s on an
  incomplete body in production.
- Round 3, same session: Kelvin provided a Resend API key (set on Railway
  via the MCP tool, never in code) and confirmed the GitHub App is now
  public. `core/email.py` added — welcome email on checkout, owner alert
  on a real transition to Enterprise tier. Both were "still open" items
  from Round 1/2, now closed. See the architecture-decisions file's
  "Round 3" section.

## 2026-09-15 — IaC deploy-failure diagnosis + live resource monitoring, domain-complete

Full detail: `knowledge/operator/architecture-decisions/2026-09-15-iac-diagnosis-domains-and-resource-health-monitoring.md`

- Three-phase build (Agent 01 IaC deploy diagnosis, Agent 08 drift
  coverage + Azure App Service live fetch, new Agent 11 resource-health
  monitoring), organized around four domains (IAM/RBAC/Policy,
  Networking, Storage, Compute) at Kelvin's explicit request mid-build.
- Real bug caught and fixed: `core/compliance.py`'s `TIER_LIMITS` and a
  second, independent duplicate copy in `api/routes/agents.py` both
  gated purely on numeric agent-id position — Agent 11 would have
  silently become Enterprise-only by numbering accident without the fix.
- Also fixed autodeploy for Railway `cloud-decoded-mcp` service (was
  still on its 2026-09-12 build) and confirmed the platform-wide
  autodeploy fix from the previous session holds across this entire
  multi-commit build with zero manual intervention.
- 1388 passing (was 1320), same pre-existing unrelated failures.
- **Post-deploy, same session: found and fixed a critical production
  bug.** Migrations 024–028 had never been applied to production —
  confirmed via direct read-only query — meaning real customer signups
  had been failing with a 500 since earlier this session's
  contact-email-capture commit deployed. No migration runner exists
  anywhere in the deploy pipeline (root cause, still open — see GAPS.md
  #15). Kelvin approved after being shown all five migrations are pure
  additive `ADD COLUMN IF NOT EXISTS`; applied directly to production via
  `DATABASE_URL`, verified, live-tested the previously-broken signup flow
  end-to-end (now `201`s correctly).

## 2026-09-17 — Retired the private Gitea mirror (`gitea-mirror.yml`)

Kelvin noticed `gitea-mirror.yml` hadn't run since 2026-08-13 and asked
to fix it. Investigation: no real Gitea server was ever provisioned for
this project — `GITEA_SSH_PRIVATE_KEY`/`GITEA_HOST`/`GITEA_REMOTE_URL`
never existed as repo secrets (`gh secret list` confirmed), which is why
the workflow was switched to `workflow_dispatch`-only on 2026-08-13 in
the first place (same root cause `deploy.yml`'s AWS/Fargate path has,
per the 24-gap-closure Phase 7 SOP). `GAPS.md`/`DECISIONS.md` had no
prior entry tracking a real Gitea server as planned work — the entire
"GitHub public + Gitea private" dual-repo architecture was carried over
verbatim from the generic project-scaffold template (`CLAUDE.md`'s Core
Principles #7 and Phase 1 step 14/16), never a decision made for this
project specifically.

Given a choice between (a) providing real Gitea infrastructure, (b)
retiring it, or (c) leaving it dormant, Kelvin chose to retire it.
Removed `.github/workflows/gitea-mirror.yml` entirely, its section in
`.github/workflows/WORKFLOWS.md`, and corrected `CLAUDE.md`'s Core
Principle #7 (struck through, dated, reasoned — not silently deleted,
matching this file's own established correction convention) plus its
two other now-dead references in the "GitHub Actions — daily visibility"
guide section. GitHub is the sole repo for this project going forward.

## 2026-09-21 — Cloud Decoded email lifecycle system (migration 051), and retiring the systems it supersedes

Built the full onboarding/nurture/dunning/winback/newsletter email engine
(`core/email_scheduler.py`, `core/marketing_email.py`,
`core/email_content/*.py`, `api/routes/email_public.py`,
`api/routes/internal_email_campaigns.py`) per Kelvin's build spec. Two
existing systems directly overlapped with its scope; both were surfaced
to Kelvin before building, and he chose to retire both rather than run
two competing systems:

**Retired: the Brevo lead-nurture stack** —
`agents/internal/email_sequence_agent.py`, `leads/integrations/brevo_client.py`,
`leads/capture/signup_handler.py`/`trial_handler.py`'s Brevo sync calls,
and migration 039's `email_sequences`/`email_sequence_steps` tables.
Investigation found these had **zero real callers anywhere outside their
own tests** — never wired to an HTTP route, so no live traffic or
customer-facing behavior actually changes by retiring them. Flagged
DEPRECATED in code comments, not deleted (tables, historical test
coverage, and the files themselves stay intact). New capture
(`POST /email/subscribe`) uses the new `cd_email_subscribers` table
directly, on the Resend-based engine, per the new build's own locked
decision ("no new email provider, no Brevo").

**Retired: `core/onboarding_sequence.py`'s day-2/day-5 cron** — this
module's 6-hourly loop was real, live, and sending (day0 remains a
separate, unchanged, synchronous transactional welcome email in
`core/email.py`). Its content and skip_if logic (real setup-checklist
signals) were folded into the new engine's `onboarding` sequence as
steps 1-2 (`core/email_content/onboarding.py` calls the same HTML-builder
functions directly rather than rewriting the copy). `run_onboarding_sequence_check`
is now a documented no-op — kept, not deleted, so `api/main.py`'s
existing task registration and the `workspace_onboarding_emails` table
don't need touching, and a rollback is reverting one file.

**Architecture correction vs. the original build spec:** the spec
assumed three separate repos/codebases (Cloud Decoded, an "MSE repo",
and a "CEO Decoded repo"). Recon found `ceo-dashboard/` is a
subdirectory of *this* repo, not a separate one, and the real MSE
campaign-factory code lives in a genuinely separate repo
(`kdavis-microsaas-engine`) unrelated to `agents/mse/` in this repo
(which is a different, pre-existing agent set — opportunity finder,
demand validator, product-spec writer). See
`docs/internal/email-approval-api.md` for the corrected cross-repo
contract this build publishes for the CEO Decoded dashboard to consume.

Full honest gap list: GAPS.md #31.
