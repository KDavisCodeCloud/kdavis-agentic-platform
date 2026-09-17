# Cloud Decoded — Build Order
**Project:** `theclouddecoded.com`
**Company:** THD Agentic Systems LLC
**Last updated:** 2026-09-14 (corrected again — see `GAPS.md` entries #6-11
for the full record of what changed and why; this file was stale since
2026-09-12, predating the entire connectivity build sequence below, item
5's Azure DevOps support, and six numbered "Phase" sessions that closed
real credential/security gaps agents 02/04/08/10 had carried since they
were first built)
**Status:** Priority 1 (auth + Stripe) is done and live. The connectivity
build sequence (GitHub App, Azure DevOps, real per-workspace K8s creds,
BYOK routing, MCP OAuth provisioning) is done except one externally-blocked
item (MCP TLS). Priority 2/3 items below are the real remaining backlog.

---

## What This Is

A HITL agentic DevOps automation platform targeting mid-market platform engineering teams (50–500 engineers, multi-cloud, dedicated platform team of 3+) as an alternative to Microsoft Copilot and AWS AgentCore. Positioning: no runtime lock-in, no cloud-first bias, human gate before anything executes. B2B sales cycle — expect 30–90 days per client. MRR comes slower than MSE. That's accounted for.

**ICP:** VP Engineering / VP Platform (economic buyers), Head of Platform Engineering / Director of DevOps (champions), Platform Leads / DevOps Managers (users)

**Pricing:** Starter $299/mo · Growth $699/mo · Enterprise $2,499/mo

**Exit gate:** $15K MRR × 3 consecutive months → Kelvin exits CorVel

---

## Completed — Do Not Redo

- Landing page complete (9 sections, SEO/AEO, FAQPage JSON-LD schema) ✅
- Design system locked: bg `#070910`, blue `#5a96ff`/`#2f6fe6`, amber `#f5a623`, green `#3fd17a` ✅
- Fonts locked: Space Grotesk, IBM Plex Sans, JetBrains Mono ✅
- All 11 agents built ✅ — real roster is `agent_01_cicd_triage` through
  `agent_11_resource_health` (see `CLAUDE.md`'s CURRENT STATUS footer for
  the corrected list with real names — the "Agent Roster" section below
  in this file is the old placeholder list, kept below only as a
  changelog of what this doc used to claim, not current fact)
- SOC 2 readiness architecture in place (per-tenant pgvector + RLS, DataSanitizationShield, HITL audit log, access controls, incident response, data retention policy) ✅
- **Auth pages (`/login`, `/signup`) — done and live**, real pages built
  as part of the 2026-09-12 paywall closure (see
  `CLOUD_DECODED_AUDIT_2026-09-12.md`), not just Supabase-wired stubs.
- **Stripe billing — done and live.** Real paywall: every new workspace
  locks (`pending_payment`) until checkout completes; suspend/reactivate/
  rotate-token/set-tier/mcp-invite are real, tested backend admin levers
  in `api/routes/internal_workspaces.py`. **Correction (2026-09-14): there
  is no actual `/dashboard/customers` frontend page** — this file and the
  2026-09-12 audit both claimed one existed; a repo-wide search found zero
  frontend code calling any `/internal/workspaces/*` route. The backend is
  real and tested; reaching it today means calling the API directly
  (curl/Postman) until a dashboard page is built. Verified with real
  end-to-end test-mode checkouts, not just webhook code review.
- **MCP server — deployed**, new Railway service `cloud-decoded-mcp`, DNS
  on `mcp.theclouddecoded.com`, 24+ tests. **TLS certificate still not
  issued as of 2026-09-14** — `CERTIFICATE_STATUS_TYPE_VALIDATING_OWNERSHIP`,
  DNS `PROPAGATED` the entire time since 2026-09-12. This is now past
  Railway's own stated "up to 72 hours" window; needs a Railway support
  ticket from Kelvin's account, not fixable from a coding session. Blocks
  the final live SSE tool-call verification.
- **Enterprise-tier OAuth 2.1 — provisioning route built 2026-09-14**,
  `POST /internal/workspaces/{id}/mcp-invite` (admin-gated, two-step
  Supabase Admin API call setting `app_metadata.workspace_id`/
  `workspace_tier`/`mcp_scopes`, the fields `mcp/auth/oauth.py`'s JWT
  validation already trusted but nothing could ever populate). Real,
  unit-tested, not live-verified end-to-end yet — blocked on the same MCP
  TLS gap above. Starter/Growth via API key works today, unaffected.
- **Azure onboarding + CIS compliance scanning — done and live** across
  `kdavis-cloud-audit`, `kdavis-finops-agent`, `kdavis-compliance-agent`,
  and this repo's `AgentConnectFlow.tsx`, alongside the existing AWS path.
  Not mentioned anywhere in this file's original scope — see
  `CLOUD_DECODED_AUDIT_2026-09-12.md` section 6 for full detail.
- **Connectivity build sequence — done except the MCP TLS item above.**
  GitHub App (item 4), Azure DevOps support incl. `AzureDevOpsRepoTools`
  (item 5), per-workspace webhook secrets, and a six-session "Phase"
  cleanup (2026-09-14) that found and fixed real gaps along the way:
  agents 02/04/10 were silently running on a shared platform GitHub/K8s
  token instead of each customer's own (GAPS.md #7, #9 — a correctness
  and cross-tenant-leak risk, not just a missing feature); three duplicate
  hand-rolled GitHub PR implementations collapsed onto `core/repo_tools.py`
  (GAPS.md #8); the K8s global-`KUBECONFIG_YAML` stopgap replaced with
  real per-workspace cluster credentials for Agents 02/08 (GAPS.md #9);
  `workspaces.llm_provider`/BYOK were stored at onboarding but never once
  read by any of the 10 agents until now (GAPS.md #10). Full detail,
  including a self-caught scripting bug during the BYOK wiring pass, lives
  in `GAPS.md` entries #6 through #11 — read those before assuming any of
  this is still broken or still needs building.

---

## Org Layer — LOCKED DECISION, not yet built (2026-09-17)

Surfaced during the 24-gap-closure build's Phase 8 scoping (design-only,
explicitly not built that session — see that run's final report).
Kelvin made the following call explicitly; a future session should
inherit it, not re-litigate it:

**Organizations are identity/grouping only. Billing stays strictly
per-workspace, permanently — not just for a first version.**

Concretely, when this gets built:
- Relax `workspace_members.supabase_user_id`'s `UNIQUE` constraint
  (migration 033) so one Supabase user can belong to multiple
  workspaces — today it's a hard 1:1, and every member-session auth
  path (`api/middleware/auth.py`'s `get_workspace_member`) assumes
  exactly one row per user.
- New `organizations` table above `workspaces`.
- A workspace switcher in the dashboard nav.
- An org-level member list (an aggregate view across a member's
  workspaces, not a new source of truth for role/permissions).

**Explicitly NOT in scope, ever, per this decision**: no billing, tier,
or seat-cap logic moves to the org level. Every workspace keeps its own
Stripe subscription, its own tier, its own seat cap — exactly as built
through Phase 7 of the 24-gap-closure run (downgrade enforcement,
credential-expiry, MFA-required, rate limits — all workspace-scoped, all
staying that way). An org is a grouping/identity layer sitting above
workspaces that otherwise remain fully independent billing units.

This resolves what the Phase 8 scoping flagged as the single biggest
open question (whether an org becomes the billing unit) — it does not.
Don't build shared-billing org logic later without a new, explicit
decision to reverse this one.

---

## Build Order — Remaining

### Priority 2 — done 2026-09-14 (Phases 8-9, same connectivity session)

All five items below shipped in the same session as the connectivity
build sequence, per Kelvin's "draft it all now" decision when asked how
to handle GTM content:

- ✅ **Admin workspace UI** — still open, genuinely not built (see
  `GAPS.md` #11 and the correction above). Kept here as the one real
  Priority 2 gap: `api/routes/internal_workspaces.py`'s levers
  (list/suspend/reactivate/rotate-token/set-tier/mcp-invite) are real
  and tested but curl-only. Matters more once MCP TLS clears.
- ✅ **og:image** — `frontend/src/app/opengraph-image.tsx`, Next.js's
  dynamic `ImageResponse` file convention (1200×630, generated from JSX
  using the real design tokens) rather than a static PNG. Found and
  fixed a real pre-existing bug while building it: `page.tsx`'s metadata
  referenced `/og-image.png`, a file that never existed anywhere in this
  repo (no `public/` directory at all) — the homepage's social share
  image has been silently broken since it shipped.
- ✅ **Features page** — `frontend/src/app/features/page.tsx`, all 10
  real agents (not the homepage's narrower "5 shipping" framing — see
  note below), tier-badged, matches the locked design system exactly
  (same inline-style approach as the homepage, shared nav/footer
  extracted to `components/marketing/SiteChrome.tsx`).
- ✅ **10-problems AEO page** — `frontend/src/app/problems/page.tsx`,
  one direct question+answer per problem, FAQPage JSON-LD schema.
- ✅ **Comparison page** — `frontend/src/app/comparison/page.tsx`,
  Cloud Decoded vs Microsoft Copilot vs AWS AgentCore. Deliberately
  scoped to architecture/positioning claims (cloud dependency, approval
  gate, buying motion) rather than specific unverifiable technical
  claims about either named competitor.
- ✅ **Security page** — `frontend/src/app/security/page.tsx`, SOC 2
  readiness (explicitly *not* an attestation claim), tenant isolation,
  HITL audit trail, data retention, "request the questionnaire" CTA.

**Note on the Features page vs. the homepage:** `page.tsx`'s own
"Workflows" section says "five production workflows... more in private
beta." The Features page shows all 10, because all 10 are real, built,
and tested (confirmed directly this session, including live EKS/AKS
verification for two of them last session) — the homepage's "5 shipping"
framing reads as stale marketing conservatism from before all 10 were
finished, not a technical reality. Not reconciled here (out of scope for
what was asked — the homepage itself wasn't touched); worth a real
decision on whether to update the homepage copy to match.

---

### Priority 3 — drafted 2026-09-14, same session

- ✅ **Docs** — `docs/customer/setup-guide.md`, `agent-reference.md`,
  `workflow-howtos.md`. Grounded directly in the real connect routes
  built this same session (GitHub App, AWS role, Azure SP, Azure DevOps
  PAT, Kubernetes cluster creds) — not generic filler.
- ✅ **Loom demo script** — `docs/customer/loom-demo-script.md`, the
  exact Hook/Solution/Outcome template from this file, CI/CD triage
  scenario, shot-by-shot with production notes. The recording itself
  still needs a human with a camera — this is the script only.
- ✅ **Security questionnaire response doc (draft)** —
  `docs/customer/security-questionnaire-response.md`. Marked explicitly
  as draft-not-yet-sent, with placeholder markers for the items that
  need a real confirmed answer (data residency, current sub-processor
  list, real incident-response SLA) rather than fabricated specifics.
- ✅ **DPA — outline only, not a real DPA** —
  `docs/customer/dpa-outline.md`. Deliberately NOT drafted as usable
  contract language — a real DPA needs an actual attorney (GDPR/CCPA
  clauses, jurisdiction-specific terms) who knows the current data flows.
  This file is what to bring to that conversation with MSE legal, not a
  substitute for it. Do not send this file to a customer.

---

## Dashboard Architecture

Two views, one shell at `theclouddecoded.com/dashboard`:

**Tenant view (client):** Approval queue (HITL), agent activity feed (Realtime, scoped to `tenant_id`), metrics (hours saved, incidents triaged), audit trail, workspace settings, autonomy threshold sliders

**Operator view (Kelvin):** All tenants table, cross-tenant HITL monitor, revenue feed (Stripe webhooks), agent health across all tenants, SOC 2 readiness checklist, exit tracker

Real-time update flow: Agent runs → `POST /events` (with `tenant_id`) → inserts to `agent_events` → Supabase CDC fires → Realtime pushes to per-tenant WebSocket channel → widget re-renders. Zero manual SQL.

Batch review: Similar pending actions grouped by `pattern_hash` (same agent + action type + environment). Approve once, apply to all matching. Required before 27 clients to prevent HITL bottleneck.

---

## Agent Roster — CORRECTED 2026-09-12, UPDATED 2026-09-15

The 10 names originally below (from this file's 2026-07-04 draft) did not
match what was actually built as of the 2026-09-12 correction. A new
Agent 11 (Cloud Resource Health Monitoring) shipped 2026-09-15, along
with a fifth diagnosis domain (Database-as-a-Service) across Agents 01,
08, and 11. The real roster, confirmed directly against
`agents/agent_01_*` … `agents/agent_11_*` in this repo:

1. CI/CD Triage (`agent_01_cicd_triage`)
2. Kubernetes Alert Fatigue & Remediation (`agent_02_k8s_alert`)
3. PR Review — Architecture & Security (`agent_03_pr_review`)
4. Legacy Code & Infrastructure Migration (`agent_04_migration`, Growth+)
5. IAM Policy Minimization (`agent_05_iam_minimizer`, Growth+)
6. FinOps Cost Optimization (`agent_06_finops`, Growth+)
7. Interactive Runbook Automation (`agent_07_runbook`, Growth+)
8. Drift Detection & Auto-Correction (`agent_08_drift_detection`, Growth+)
9. Context-Aware Onboarding & On-Call Buddy (`agent_09_onboarding_buddy`, Growth+)
10. Dependency & Vulnerability Patching (`agent_10_dependency_patch`, Growth+)
11. Cloud Resource Health Monitoring (`agent_11_resource_health`, Growth+)

DataSanitizationShield is not a numbered agent — it's shared platform
infrastructure (`security/sanitizer.py`) every agent runs through, per
this file's own "Key Constraints" section below.

<details>
<summary>Original (wrong) 2026-07-04 list — kept for changelog only</summary>

1. CI/CD Triage Agent — detects failures, proposes remediation
2. PR Review Agent — posts review comments, flags security/quality issues
3. Cost Optimization Agent — identifies waste, proposes scale-down actions
4. Infra Monitor Agent — anomaly detection, health checks
5. Runbook Agent — executes approved runbooks (Growth+)
6. Security Agent — CVE scanning, config drift detection (Growth+)
7. Incident Response Agent — coordinates response, assembles timeline
8. Deployment Agent — manages rollouts, rollbacks
9. Capacity Planning Agent — forecasts, recommends scaling
10. DataSanitizationShield — scrubs client data before any agent embedding

</details>

---

## Key Constraints (Do Not Violate)

- Funnel is no-sales-call: sole primary CTA is "Start free trial" — "Book a demo" is removed
- HITL gate is non-negotiable: high blast-radius actions always require human approval regardless of tenant autonomy settings
- Per-tenant Supabase pgvector with RLS keyed to `tenant_id` — no cross-tenant data leakage
- DataSanitizationShield runs before any client data is embedded
- Tiered autonomy: low-risk previously-approved actions can auto-execute within guardrails; novel/high-blast-radius always HITL
- X/Twitter account suspended — DM channel dormant until compliance ticket resolves
- SOC 2 readiness baked in from the start — not retrofitted later
