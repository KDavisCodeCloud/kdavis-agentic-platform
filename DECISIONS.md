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

## 2026-11-18 — Agent 07 runbook execution removed; webhook tokens redacted from access logs (G26)

Kelvin's decision after the 2026-11-18 claims audit ("NOW: disable Agent 07
execution in production … own PR, merged with G26").

- **Agent 07.** Runbook steps (shell via `create_subprocess_exec`, HTTP,
  kubectl, notifications) ran from Cloud Decoded's shared, multi-tenant API
  host once an operator approved `opt_1`. That is our server and network
  position, not the customer's environment. The step executors are
  **deleted**, not flagged off. `execute_runbook_plan()` and
  `execute_option(opt_1)` return `refused`, and the module no longer imports
  anything that can spawn a process. The diagnose node ignores the LLM's
  option list and offers a fixed pair: `opt_2` (file the plan as a GitHub
  issue, whose body is now the real plan instead of the old empty string)
  and `hold`. An approval of a stale `opt_1` card (for incidents created
  before this deploy) is refused and the incident is marked **failed**, not
  executed. Re-enabling needs a design that runs steps inside the
  customer's environment; the prompt file is unchanged (its `opt_1` is
  discarded in code), so no prompt version bump.
- **G26.** Alert sources that can't send headers (Azure Monitor, SNS,
  AlertManager, Grafana) authenticate with `?token=` in the webhook URL,
  and uvicorn's access log wrote the full URL to Railway's logs. Railway's
  own HTTP log strips query strings; only uvicorn leaked. `configure_logging`
  now installs `AccessLogRedactionFilter` on `uvicorn.access`, replacing the
  value of any credential-like query parameter (`token`, `key`, `secret`,
  `password`, `sig`/`signature`, `code`) with `[REDACTED]`. Verified under a
  real `--workers 2` uvicorn. **Log lines already written still contain
  tokens**, so every workspace whose webhooks used `?token=` must rotate its
  workspace token.

## 2026-11-17 — Fix session item 1: option labels bound to executed code (G12 + G5)

Evidence: Break-It Lab (`KDavisCodeCloud/cloud-decoded-lab`, results.md @ 365ea2b).

- **One definition per option.** Each agent's `tools.py` exports
  `option_catalog(context)`: title, description, impact and `calls` (the tool
  methods that id runs). The diagnose node sends the catalog to the LLM and
  passes its options through `core/option_catalog.bind_options`: catalog text
  replaces the LLM's, the LLM's wording is kept as `rationale` ("Why the agent
  suggests this" on the card), and ids with no code are dropped.
  `execute_option` refuses ids outside the catalog (`not_available`).
- **The catalog varies with context because the code does**: cloud (05, 06),
  CI provider and whether a PR exists (01), drift source (08). Same keys at
  diagnose and execute time.
- **Test, not convention.** `tests/test_option_catalog.py` runs every option of
  every agent with all tool methods mocked and asserts the methods called are
  exactly `calls`. Changing behavior without changing the label fails CI.
- **Behavior changes where the code itself contradicted any honest label:**
  Agent 01 opt_2 now re-runs the whole workflow (it duplicated opt_1), opt_3
  is offered only when the run has a PR (it silently fell back to a full
  re-run); Agent 08 opt_2 exists only for Kubernetes (on Terraform it was
  "Apply correction directly" but opened a second PR); Agent 07 opt_2's issue
  now contains the plan (its body was empty); Agent 05 opt_1 refuses clouds it
  has no code for (it fell back to the AWS call).
- **G5 (narrowed per Kelvin's review, 2026-11-17):** Agent 05 Azure opt_1 is
  "Remove the over-privileged role assignment(s)". At diagnose time the agent
  lists the identity's live assignments and flags only privileged built-in
  roles (Owner, Contributor, User Access Administrator, RBAC Administrator,
  matched by their fixed role-definition GUIDs) at the subscription scope
  itself. The card lists each flagged assignment's id, role and scope. On
  approval it creates or keeps the minimized assignment(s), then deletes only
  those listed ids, and only if each is still privileged at subscription scope
  (an id that is gone or changed is reported, not deleted). Every other
  assignment is left untouched. Nothing is deleted if creation fails, and a
  minimized set that still contains a flagged role is refused. opt_1 isn't
  offered when nothing is flagged or the assignments can't be listed (the
  reason goes on the incident).
  - **Why not "replace everything":** analysis can miss legitimate access, and
    a broad delete could cause an outage on a customer's first approval. The
    first version (delete every other assignment in the subscription) is
    dropped. No "replace all" option was added: no lab case needs it, and an
    operator who wants it can do it via "I'll handle this myself".
  - The old create-only `apply_azure_role_assignment` is removed.
- **"Custom solution" is gone.** The card promised "a custom fix for the
  platform to execute"; no agent could. The API now refuses `custom` with a
  pointer to "I'll handle this myself" (`/resolve-manually`). Approved on the
  condition that a human path stays on every card. It does:
  `RemediationCard.tsx` adds "I'll handle this myself" to every incident
  regardless of agent, and `bind_options` always keeps Hold.
- Option `impact` is now the catalog's low/medium/high, not LLM free text.

## 2026-11-17 — Fix session item 2: honest execution status (G1) + no-drift creates no incident (G15)

Baseline: Break-It Lab results.md @ 365ea2b. A1/Z1 returned `skipped` and the
incident said **executed** with no failure_reason; A2/Z2 opened a PR, nothing
changed live, and the incident said **executed**; A2's bad-IaC check said "No
drift detected" and still created a `pending_approval` incident with PR and
apply options.

- **One rule for all 11 agents** (`core/execution_outcome.py`,
  `HITLGate.record_execution`). Every `_complete_node` calls it; none decides
  'executed' itself.
  - held → `held`
  - skipped / not_implemented / not_available / failed / error / no_change /
    no status → `failed`, `failure_kind = not_executed`, with the tool's
    reason in `failure_reason`
  - a runbook `partial`, or a multi-call option where some part did nothing →
    `failed`, `failure_kind = partial_execution`, naming the parts
  - success of an option that only proposes a fix → **`proposed`** (new
    status): nothing changed live; not counted as resolved, no `resolved_at`,
    no ticketing "resolved" notification
  - success of an option that is the change itself → `executed`
- **`OptionSpec.proposal`** marks the proposal options (13: every PR/issue
  option in Agents 04/05/07/08/10/11, Agent 06's report issue and Slack
  alert). Agent 09's issue/Slack post is the deliverable, so it stays
  `executed`. A test fails if a PR/issue-only option isn't flagged.
- **'executed' now means "the approved action ran"**, not "resolved and
  verified". The card said "The incident has been resolved and verified"; it
  now says the live resource hasn't been re-checked. Verification is item 4
  (G4). The status label "Resolved" is now "Executed".
- **A `proposed` incident can be marked resolved** (`/resolve-manually` accepts
  `pending_approval` or `proposed`). The card shows "Fix proposed — nothing
  changed live yet" with a "Mark resolved" box for after the merge.
- **G15:** Agent 08 routes diagnose → `no_drift_complete` when `drift_items` is
  empty: no incident, an audit entry `complete:no_drift`. Same pattern as the
  existing exempted-resource path. An empty result with severity `UNKNOWN`
  (the prompt's answer when desired or actual state is missing) is "couldn't
  check", not "no drift": it becomes a failed incident with the reason.
- **G15 generalized (Kelvin's review, 2026-11-17): any agent that finds
  nothing creates no incident, only an audit entry.** A shared base-agent path
  is used: diagnose returns `nothing_found: "<why>"` and the graph routes to
  `nothing_found_complete`, which writes action `complete`, status
  `nothing_found`, with the reason in metadata.
  - **Agents that can find nothing:**
    - **05 IAM:** nothing to remove, judged against a real access log. An empty
      access log still becomes an incident, because usage can't be judged.
    - **06 FinOps:** no savings, recommendations or idle resources.
    - **08 Drift:** no drift items.
    - **10 Dependencies:** OSV.dev checked every pinned dependency and none is
      vulnerable. This is decided before the LLM call, so a clean scan costs
      no tokens.
  - **"Couldn't check" is a failed incident with the reason, never "nothing
    found":**
    - 06: no cost data.
    - 08: severity UNKNOWN.
    - 10: zero dependencies parsed, or any OSV query failed. The scan now
      records checked, failed and unversioned counts; it used to skip
      failures silently.
  - **Agents left out on purpose:** 01, 02, 07, 09 and 11 are triggered by an
    event that is itself the finding. 03 always has a verdict to post. 04 runs
    on an operator's request. `tests/test_nothing_found.py` pins this list.
- **"Fix Proposed" is not a resolution downstream.**
  - `schedule_resolution_notification` (Jira, Linear, GitHub Issues,
    ServiceNow, PagerDuty resolve) now refuses any status other than
    `executed` or `resolved_manually`. Both callers pass the status
    explicitly.
  - No channel notification fires on the transition; those fire only when an
    incident is created.
  - MTTR: the product has no MTTR computation. The resolution end time is
    `resolved_at` (migration 038), and a proposed incident never gets one.
    When it is later resolved, that resolution goes downstream normally.
- **Bulk and single actions share one status rule** (Kelvin, 2026-11-17).
  - `core/hitl.py` holds `REJECTABLE_STATUSES` (`pending_approval`) and
    `MANUALLY_RESOLVABLE_STATUSES` (`pending_approval`, `proposed`), behind
    `rejection_allowed()` / `manual_resolution_allowed()`. The single reject,
    single resolve-manually and bulk endpoints all call them.
  - Bulk dismiss keeps reject's rule: a Fix Proposed incident already opened a
    PR or issue, so there is nothing to reject. The UI disables Dismiss while
    one is selected.
  - The frontend mirrors both lists in `types.ts`; a test pins them equal to
    the backend's, and another drives every status through the single and bulk
    endpoints and asserts they accept the same set.
  - Known gap, unchanged: bulk resolve doesn't fire resolution ticketing or
    PagerDuty resolve; single resolve does.
- **One `_complete_node` for all eleven agents**, in `BaseAgent`. Item 2 had
  made ten copies identical, and the code-quality gate (fixed in
  `fix/ci-code-quality-gate`) flagged the new duplication. Agent 02 overrides
  `_before_state()` to keep its rollback snapshot.
- **Added to item 3:** a GitHub App `pull_request` webhook. When the fix PR
  merges, the incident moves to "Fix merged — awaiting verification". Item 4's
  verification then closes it as `verified` or `verification_failed`.

## 2026-11-17 — Fix session item 3: PR fixes work (G13, G16, G17, GitHub App)

- **G17, branch names:** every fix PR uses `core/pr_branch.py`'s
  `cloud-decoded/<kind>/<incident-uuid>`. No incident ID raises instead of
  inventing a suffix. Fixes the Z2/Z4 409 collision, and lets the merge
  webhook find the incident from the head branch.
- **GitHub App linking** (Kelvin: never auto-link):
  - The manifest now sets `setup_url` (the existing signed-state callback)
    and `setup_on_update`. The registered App must be updated by hand in
    GitHub.
  - An `installation` webhook for an unclaimed installation is recorded in
    `github_app_unclaimed_installations` (migration 062), never linked: the
    payload can't prove which workspace started the install.
  - An uninstall unlinks the workspace.
  - The callback refuses an installation already held by another workspace;
    the signed state proves the claimant's workspace, not ownership of
    `installation_id`.
  - **Ownership proof (Kelvin: build it now).** The manifest sets
    `request_oauth_on_install` and `callback_urls`. The callback exchanges
    GitHub's `code` for the installing user's token, used once and never
    stored, and links only if `installation_id` is in that user's
    `GET /user/installations`.
    - No code, a refused code, or an installation not listed: recorded as
      unclaimed, never linked. This includes a hand-completed callback like
      the lab run-2 workaround.
    - The workspace is proven by the signed state. GitHub's docs don't
      promise that state survives the OAuth-on-install redirect, so if it's
      missing the browser gets a 15-minute signed claim for the verified
      installation. The logged-in dashboard redeems it via
      `POST /github-app/claim`, and the session proves the workspace.
    - The registered App needs "Request user authorization (OAuth) during
      installation" turned on and the callback URL set by hand. Until then,
      new installs stay unclaimed.
- **Merged fix PR → `fix_merged`** ("Fix merged — awaiting verification"):
  - Set by the `pull_request` closed event on both the App and the
    per-workspace webhooks.
  - Only for a fix branch naming an incident in the installation's own
    workspace, and only from `proposed`. Sets no `resolved_at`, is not a
    downstream resolution, and can be resolved manually.
  - Closed unmerged is audited only.
  - Item 4's verification closes it as verified or verification_failed.
- **G13, repo mapping** (migration 063, `core/repo_mapping.py`,
  Settings → Repositories). The repo comes from the alert payload, else the
  longest matching resource-ID prefix rule (case-insensitive), else the
  workspace default.
  - No tag rules: alert payloads carry no tags.
  - Admin-only `PUT /workspace/repo-mappings`, audited.
- **G16, one-block IaC PRs:** `core/hcl_edit.py` (a deterministic splice
  that understands strings, comments and heredocs) plus `core/iac_fix.py`,
  shared by agents 08 and 11.
  - **Diagnose:** reads the real `.tf` file and shows it sanitized to the
    LLM, which returns one address and block. The exact diff goes on opt_1.
    JSON, multiple blocks, a rename, or a redaction placeholder means no PR
    option, and the card says why.
  - **Execute:** the block is re-checked against the current file (refused
    if it changed since review), then terraform fmt + validate run, then the
    PR is opened. Any failure → incident `failed` with the reason, no PR.
  - **Agent 08:** PRs only for Terraform; CloudFormation, ARM and generic
    sources get the issue only.
  - **Agent 11:** used to commit `payload["corrected_content"]` (never sent)
    over the whole file.
- **Terraform gate runs in an isolated service** (Kelvin's choice):
  `services/terraform_runner`.
  - Why: `terraform init` executes the provider binaries the customer's code
    declares, and the API process holds every tenant's decrypted
    credentials.
  - The runner has no database and no customer credentials; providers are
    restricted to `registry.terraform.io/hashicorp/*`; it uses
    `-backend=false`, a fresh temp dir and hard timeouts.
  - The client (`core/terraform_gate.py`) fails closed when
    `TERRAFORM_RUNNER_URL`/`TOKEN` are unset.
  - Verified against real terraform 1.14.8 locally: a valid edit passes;
    the lab's JSON fails with "Argument or block definition required"; an
    unknown argument fails validate; a third-party provider fails init.
  - **Not deployed.** It needs its own Railway service, staging first.
- **Found, not fixed (outside scope):** `api/routes/policies.py` is imported
  in `api/main.py` but never mounted, so Settings → Policies (execution
  policy, exemptions, "Exempt this resource") 404s.

## 2026-11-17 — Fix session item 4: post-fix verification (G4) + Agent 06 live state (G14)

- **G14:** Agent 06 reads each idle candidate's live power state
  (`core/live_state.py`: EC2 DescribeInstances, Azure VM instanceView) and
  drops the ones already stopped, deallocated or gone, saying so on the card.
  - If the state can't be read, the candidates stay (stopping a stopped
    instance is a no-op) and the card says they weren't checked.
  - opt_2 disappears when nothing idle is left.
- **G4, statuses:** after an action, the live resource is re-read
  (`core/verification.py`, migration 064). The incident closes as
  `verified` ("Verified fixed") or `verification_failed` ("Fix didn't
  work").
  - **Deterministic, no LLM.** At execute/complete time each agent records a
    spec of what to re-read and what "fixed" means:

    | Agent | Verified when |
    |---|---|
    | 05 AWS | the policy's live default version equals the minimized policy |
    | 05 Azure | the removed assignments are gone |
    | 06 | the stopped instances / deallocated VMs read that way |
    | 08 | the live reader's security findings at diagnosis are gone (SG, NSG, S3, Azure blob, via the shared `DriftTools.fetch_live`) |
    | 11 | the CloudWatch alarm is OK / the Azure Monitor alert is Resolved |

  - **When:** a live action (`executed`) is checked from 2 minutes, every
    5, with a 30-minute deadline. A proposal waits for its PR to merge
    (`fix_merged`), then from 10 minutes, every 15, with a 24-hour
    deadline, so the pipeline has time to apply it.
  - **Can't check** (no credentials, an API error, alarm INSUFFICIENT_DATA)
    is never reported as fixed or as failed. It retries until the deadline,
    then stops with outcome `unverifiable` and leaves the status alone.
  - **Agents with no deterministic check** (01, 02, 03, 04, 07, 09, 10; 05
    on GCP; 08 without a live reader) record no spec, so their incidents
    stay `executed` / `fix_merged` rather than claiming `verified`.
  - **Downstream:** `verified` counts as a resolution for ticketing and
    PagerDuty, but only notifies when it comes from `fix_merged` (an
    executed action already notified when it ran). `verification_failed` is
    not a resolution and can be resolved manually.
  - **Runs** as an in-process loop every 60 seconds. Every uvicorn worker
    runs it, so due rows are claimed with `FOR UPDATE SKIP LOCKED` plus a
    10-minute lease.

## 2026-11-17 — Break-It Lab item 5: regression linking (G2), source-resolved ingest (G3), "your fix didn't work" alerts, bulk-resolve ticketing

- **G2: a fixed problem that comes back says so.** Lab step 6 re-injected
  every fixed problem. Each came back as a fresh incident with no link, and
  agents 05, 06 and 08 stored no resource identity to link on.
  - Each agent now passes a deterministic `regression_key` (never LLM text),
    built in `core/regression.py`:

    | Agent | Key |
    |---|---|
    | 05 AWS | the policy ARN |
    | 05 Azure | the scope plus the principal |
    | 06 | the sorted set of instances / VMs recommended for stopping |
    | 08 | the drifted resource (08 also stores `resource_id` now; its exemptions already keyed on it) |
    | 11 | the resource plus the alert rule |

  - `create_incident` links the new incident to the most recent earlier one
    with the same workspace, agent and key (`previous_incident_id`). It sets
    `is_regression` only when that earlier incident was fixed or claimed to
    be (`executed`, `fix_merged`, `verified`, `resolved_manually`). A
    recurrence of something never fixed is linked, but it isn't a regression.
  - When a regression arrives, the notification leads with "REGRESSION". If
    the earlier incident is still awaiting verification, its check is pulled
    forward to now.
  - **Not changed:** 05 and 06 still store no `resource_id`. Exemptions key
    on it and those agents don't honour exemptions, so setting it would
    offer an "Exempt" button that does nothing. 05, 06 and 08 still have no
    open-incident dedup: a second manual trigger while the first incident is
    pending creates a second, linked incident.
- **G3: the alert source's "resolved" is no longer dropped.** CloudWatch `OK`
  and Azure Monitor `Resolved` now take Agent 11's existing source-resolution
  path (Alertmanager/Grafana already did). It never diagnoses and never
  creates an incident.
  - It matches open incidents and also ones awaiting verification
    (`executed`, `proposed`, `fix_merged`). Lab Z1's alert auto-resolved
    after its incident said "executed".
  - It records `source_resolved_at` and pulls that incident's verification
    forward. The source's word alone never closes anything; verification
    re-reads live state.
  - `source_resolved_at` and the regression fields are now returned by the
    API and shown on the dashboard.
  - **Known limit:** Agent 11's verification check *is* the alarm state. A
    lab-Z1-style auto-resolve (CPU credits exhausted, the stress loop still
    running) would verify as fixed. Alarm state is the only deterministic
    signal Agent 11 has.
  - The AKS route (Agent 02) still drops resolved alerts. It's out of the
    lab's scope.
- **verification_failed is "your fix didn't work", the most important alert
  this product sends.** It goes to every notification channel (Slack,
  PagerDuty, email) with that headline.
  - It's sent at severity `critical` so no channel's severity floor filters
    it out. The incident's own severity is unchanged and travels along as
    `incident_severity`. Quiet hours still apply because they're the
    customer's explicit choice.
  - PagerDuty pages critical on its own dedup key (`<incident>:fix-failed`).
    The incident's original alert may still be open (a merged PR was never a
    resolution), and PagerDuty folds a repeat trigger on an open key into
    that alert without paging. A later resolve clears both keys.
  - The resolution ticket, if one was filed (the incident's successful
    `ticket_created` audit event), is reopened with a comment:

    | Provider | Reopen |
    |---|---|
    | GitHub | reopen |
    | Jira | transition out of a Done-category status |
    | Linear | move to the team's unstarted (else started) state |
    | ServiceNow | work note plus the same literal-state caveat as creation |

  - A failed reopen is audited and retried through the notification retry
    queue (`send_kind = 'reopen'`, migration 065).
- **Bulk resolve fires ticketing through the single endpoint's path.**
  `_record_manual_resolution` is the one path for both: it writes the status,
  the per-incident audit row and the resolution ticketing / PagerDuty
  resolve. A test asserts that single and bulk send identical ticketing
  payloads.
- **Still open:** manually resolving a `verification_failed` incident files a
  new resolution ticket rather than re-closing the reopened one.

## 2026-11-18 — Claims-audit builds: Read-Only by default, no execution-policy toggle, alert payload retention + RLS

Kelvin's step-3 decisions after the claims audit ("Build: read-only default,
delete auto_execution_enabled, alert_ingestion_log retention + RLS. Everything
else: reword.").

- **Read-Only by default (migration 067).** New AWS/Azure connections start in
  Read-Only. The column default changes, and workspaces that haven't connected
  that provider yet are flipped. **Workspaces already connected keep their
  current mode**, because flipping them would silently revoke write access a
  customer granted (the same reasoning as migration 050). The UI and the status
  API now fall back to `read_only`, never `execute`.
- **`auto_execution_enabled` removed.** The toggle was read by nothing, and its
  existence contradicted "approval can't be turned off". The following are
  deleted:
  - `GET /workspace/policies`
  - `PATCH /workspace/policies/execution`
  - `core/execution_policy.py`
  - the Policies-page toggle, and the column from the auth SELECT

  Settings → Policies now states plainly that every fix needs an approval. **The
  column itself is dropped in a follow-up migration**, after this deploy is
  live. Dropping it in the same deploy would break the old workers' auth SELECT
  during the rolling switchover.
- **`alert_ingestion_log` (migration 068 + `core/retention.py`).**
  - RLS: the same service-role + `workspace_isolation` pair as migration 031.
  - Retention: raw webhook payloads are deleted after **30 days** on every
    tier. They're only needed while an alert is processed.
  - Each workspace's first row is kept with its payload replaced, because the
    setup checklist reads `MIN(received_at)` to show the alert source as
    verified.
  - Proved on a real Postgres:
    - migrations through `db/migrate.py`
    - an unscoped non-bypass role sees 0 rows
    - the purge keeps exactly the first row, scrubbed
    - a second pass is a no-op

  As before, the app's own DB role has `bypassrls`, so RLS here is defence in
  depth; the application's workspace filters remain the boundary.
