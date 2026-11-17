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

## 2026-10-17 — Loop Map tab in CEO Decoded

A top-level "Loop Map" tab (`/dashboard/loop-map`, admin only) ports
`docs/design/loop-map-reference.html` (the claude.ai "Decoded Empire Loop
Map" artifact) into React unchanged: same tokens, fonts, sprite, walk and
two-click confirms, every selector scoped under `.lm`.

- **Backend lives in kdavis-microsaas-engine** (`api/routers/loop_map.py`,
  migration `20261017000065_loop_map.sql`), next to the `/marketing/*`
  routes and the 8am digest counters it reuses
  (`core/outreach_counters.py` is now the single counter implementation
  for the digest summary and the map).
- **Desk color and check mark never share storage.** Status is computed
  per request from production rows (`core/loop_map_rules.py`); checks,
  laps and notes are `mse_loop_progress/laps/notes`. An unreadable source
  evaluates to `unknown`, never green.
- **Hourly history runs inside mse-api, not n8n.** mse-api has no
  `N8N_API_KEY`, so an n8n cron could neither be installed nor proven to
  run from here. A DB-side 50-minute gap check makes restarts and replicas
  safe; `LOOP_MAP_SNAPSHOT_DISABLED=1` turns it off (set on staging).
- **mse-api staging recreated 2026-10-17** as an empty environment with
  only mse-api (no n8n copy, which would have run the production crons
  twice). It still shares production's database.
- Notes are never deleted: no delete route, and admin RLS has no DELETE
  policy on `mse_loop_notes`.

## 2026-10-19 — Scheduled scouts, 8am watchdog, staging gets its own database

- **Schedules run inside mse-api, not n8n** (`agents/marketing/lead_schedule.py`):
  pain rescan after the Sunday scout, HN on the 3rd, partners (<=20 Brave,
  next result page each month) and VC on the 1st. The lock is a unique
  `(job_key, product_id, period_key)` row in `mse_scheduled_job_runs`.
  `LEAD_SCHEDULE_DISABLED=1` keeps an instance from running them.
- **8am enrollment is checked by a watchdog, not an exception hook.** Its
  endpoint returns "queued" before any work happens, and on Oct 19 the run
  stalled with no error. At 08:45 MST mse-api looks for today's
  `linkedin_dm_sequences_run` audit row and emails KELVIN_EMAIL from
  alerts@outreach.thdstack.com if it is missing or lost.
- **Long-running work uses `get_supabase_for_job()`**: the shared client's
  dropped connection lost the Oct 11 Cloud Decoded run, stalled the Oct 19
  8am run, and 500'd the Loop Map.
- **mse-api staging has its own Supabase project** (`microsaas-staging`,
  xmtgftwbyfqbaxffphwf, Pro org, Micro compute): schema cloned from
  production with pg_dump 17, plus migration-tracking and config rows. A
  staging boot no longer applies migrations to production.
- **DecodedSix discovery runs in-process every 4 hours**; every cycle writes
  audit_log `discovery_cycle`, which is the Loop Map heartbeat.

## 2026-10-18 — Lead targeting: pain phrases, partner lane, VC partners, HN

Engine `c2bdc07` (migration `20261018000066_lead_targeting_extensions.sql`).

- **Pain phrases are data.** `mse_icp_configs.pain_phrases` and
  `pain_phrase_boost` (+0.10 per match, capped at +0.20). Matching is
  literal (hyphen/space tolerant) because the matched sentence is quoted to
  the prospect in touch 1; "technical debt" does not match "tech debt"
  unless added to the list.
- **The partner lane is its own product** ("Referral Partners",
  `c0e8aaf3-…`), so it gets its own ICP, leads, Outreach lane
  (`?lane=partners`) and Loop Map desks without special-casing. Its
  `outbound_enabled` is false so the weekly ATS sweep never runs against it.
  Consultancies pass the exclusion only through `PARTNER_EXCLUSION_POLICY`;
  the prospect policies are unchanged. Digest counters exclude it.
- **VC funds are curated in `mse_vc_funds`** (25 rows). Contacts come only
  from team pages that render names in HTML; JS-rendered pages are recorded
  as `no_contacts_in_html`, never guessed. Portfolio companies are probed on
  the ATS JSON APIs (zero Brave) and found boards join the token cache.
- **HN uses the official Firebase API.** The freelancer thread moved from
  `whoishiring` to `jon_north` in Nov 2025; threads are found from both
  accounts' submissions. An infra term is required ("contract" alone was
  iOS/UX/sales roles); in the freelancer thread only SEEKING FREELANCER.
- **Found and fixed:** `/marketing/buyer-research` 401'd in production (no
  tenant-middleware exemption), so the Find-the-Buyer lane never loaded; and
  the board-token cache read an arbitrary 200 of 392 rows every run — it now
  reads least-recently-fetched first.

## 2026-11-14 — Public demo: per-visitor state (migration 059)

The `/demo` sandbox used one shared set of 8 incidents for every visitor, so
one visitor approving everything emptied the console for everyone for up to
30 minutes, and comments were visible to all concurrent visitors.

- **Each demo session owns its incidents.** `incidents.demo_session_id`
  (FK to `demo_sessions`, `ON DELETE CASCADE`). `create_demo_session` seeds
  the 8 baseline incidents for that session in the same transaction as the
  session row. The demo workspace itself stays a singleton.
- **One scoping helper, enforced by a test.** Every incidents route that
  accepts a demo token adds `core.demo_sandbox.demo_scope_clause` to its
  incident lookup. It returns an empty clause for real workspaces (so their
  queries are unchanged) and fails closed if a demo identity lacks a
  session id. `tests/test_demo_sandbox.py` fails if a demo-reachable route
  omits it.
- **Reset now prunes, never reseeds.** The 30-minute pass deletes expired
  sessions; their incidents and comments cascade away. `audit_events` and
  `token_usage` rows survive (their FKs are `SET NULL`).
- **Demo UI shows only what a demo token can do.** Bulk select, assignment,
  "Assigned to me", resource exemption and the connections lookup are not
  rendered for demo tokens (the API 401s them). IAM/FinOps cloud-write
  options show as Read-Only instead of an Approve that 403s. On a 401 the
  page mints a fresh session, at most once per load.
- **Comments are capped at 4,000 characters** for all callers.
- **Proved before deploy** against a throwaway Postgres 16 with the
  production migration chain: 059 applied through `db/migrate.py`, then an
  18-check end-to-end isolation run against the real route code.

## 2026-11-14 — First-party funnel events and outreach ref attribution (migration 060)

Gap-table #12/#13. Owner chose "disclose + attribute": outreach links may
carry a `?ref=` code, and activity from them is recorded against it.

- **No third-party analytics, no cookies.** One table, `cd_funnel_events`,
  written through `core/funnel_events.py`. The project's own spec already
  called for self-hosted tracking (`leads/capture/pixel.js`, never wired).
- **Client vs server events.** Browsers may only send `demo_opened`,
  `incident_viewed` and `signup_clicked` (`POST /api/v1/events`,
  rate-limited). Conversion steps (`fix_approved`, `fix_resolved_manually`,
  `signup_completed`, `checkout_started`, `subscribed`) are written by the
  API where they happen, so they cannot be forged. `subscribed` is recorded
  once per workspace because Stripe retries webhooks.
- **Identity.** Anonymous visitors get a random per-tab id (sessionStorage).
  The ref plus UTM tags persist in localStorage for 90 days and are stripped
  from the address bar after capture, so a shared URL doesn't credit
  someone else's visit to the lead. The ref rides on `demo_sessions` and
  `workspaces.signup_ref`, so server events inherit it.
- **Names.** The audit's `trial_clicked` is `signup_clicked` (there is no
  trial), and `diff_viewed` is `incident_viewed` until diffs exist (#7).
- **Privacy page updated** (effective 2026-11-14). It discloses visitor
  activity, the reference links and 13-month retention, and drops a
  country-level-location claim that was never true.
- **Retention.** `prune_funnel_events` deletes rows older than 395 days,
  from the daily retention loop. It is a separate function so
  `core/retention.py`'s per-tier contract is unchanged.
- **Read side.** `GET /internal/funnel/refs/{ref}` and
  `/internal/funnel/summary`, admin-only via `get_internal_user`. The
  mse-api half (generating ref links, the lead card) is GAPS.md #34.
- **Proved** on the throwaway Postgres 16: 060 applied through
  `db/migrate.py` with the production jsonb codec, then 20/20 end-to-end
  checks of a full ref journey against the real route code.

## 2026-11-15 — Sanitizer hardening, booking CTA at runtime, demo evidence (GAPS #35, gap-table #5-#11)

- **DataSanitizationShield (GAPS #35).** Key/value patterns now accept env,
  YAML, JSON and connection-string forms and replace only the value, keeping
  the key so an operator still sees which credential was involved. A
  catch-all redacts any key that *ends* in a secret word (ending, not
  containing, so `secretName`, `tokenUrl`, `passwordPolicy` stay readable for
  diagnosis). Generic patterns never re-label a value a specific one already
  redacted. `sanitize_dict` redacts by key. Over-redaction from the older
  `dotenv_assignment` rule (`max_tokens=…`, `keyvault_name=…`) was kept on
  purpose: narrowing it would let `GITHUB_TOKEN_PROD=…` through.
- **Fake secrets in tests are assembled at runtime.** GitHub push protection
  blocked a test file containing token-shaped literals; the fix was to build
  them from pieces, not to allow-list them.
- **Booking CTA (#11).** `CAL_BOOKING_URL` lives on the Railway API and is
  read per request by `GET /api/v1/demo/config`, because Vercel bakes env
  vars into each deployment (a `NEXT_PUBLIC_` var would need a rebuild). Only
  plain https URLs are ever returned; otherwise the button stays hidden.
- **Demo evidence (#5-#10).** Evidence is a nullable `incidents.evidence`
  JSONB column (migration 061); diff, blast radius and execution log are
  optional fields inside `remediation_options`, so real agents' incidents
  are unchanged until an agent starts producing them. A demo option whose
  log ends in a failure line is simulated as `failed`, never `executed`.
  Reject now writes `audit_events` (it never did, for anyone).
- **mse-api deploys are by SHA in both environments** (`serviceInstanceDeployV2`);
  a push to `main` deploys nothing. Staging first, then production.

## 2026-11-17 — Code-quality gate fixed: blocks only on issues a PR introduces

- **Why it was always red:** `code-quality-gate.yml` passed `--files-list`,
  `--pr-number` and `--product-id`. `code_quality_agent.py` accepted none of
  them, so argparse exited 2 on every PR. Kelvin: "A gate that's always red
  trains everyone to ignore CI."
- **Why fixing the args wasn't enough:** the analyzer reviews whole files, not
  changed lines. The 44 files the lab fix PRs touch carry 1,394 findings,
  almost all already on master, so the gate could still never pass.
- **Decision:** with `--baseline-ref`, the gate reviews the same files at the
  PR's base and blocks only on issues the PR introduces. Pre-existing ones are
  still reported, as non-blocking and marked "pre-existing".
  - Matching ignores line numbers.
  - A DRY finding is identified by its own function, not its list of other
    copies, which changes whenever any copy moves.
- **Analyzer change:** a function that only returns literals and constructor
  calls, never using its parameters (an option catalog), is not a DRY
  violation. Normalizing literals away made every same-sized table hash alike.
- **Weekly full sweep unchanged:** it still reports everything and never
  fails.
