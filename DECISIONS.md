# DECISIONS

Architectural decisions log.

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

