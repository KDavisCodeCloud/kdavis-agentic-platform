# 2026-09-14 — Connectivity roadmap completion + operational readiness assessment

Product: Cloud Decoded
Commits: `66ff0ba`..`0bda522` (master)

## What shipped this session

1. **`fix(agents)` `66ff0ba`** — Agents 04 (Migration) and 10 (Dependency
   Patch) never received a workspace's own GitHub credential; they fell
   back to a shared `GITHUB_TOKEN` env var, which was either broken or a
   real cross-tenant credential leak risk for every Growth+ customer.
   Wired `build_agent_credentials()` into both the same way agents
   01/05/06/08 already worked. While in there: routed agents 04/08/10's
   PR creation through `core/repo_tools.py`'s `GitHubRepoTools` /
   `AzureDevOpsRepoTools` instead of three duplicate hand-rolled GitHub
   API implementations — this is also what makes Azure DevOps support
   real end-to-end. Added real per-workspace Kubernetes credentials
   (migration 025, replacing the global `KUBECONFIG_YAML` stopgap) and
   Azure DevOps per-workspace PAT + webhook secret (migration 024).

2. **`feat(connections)` `81a921d`** — `ConnectionsPanel`'s GitHub card
   was still posting a PAT to a route that now unconditionally 410s.
   Replaced with a real "Install the Cloud Decoded GitHub App" button.

3. **`feat(workspaces)` `a1805c0`** — Enterprise MCP invite provisioning
   (`POST /internal/workspaces/{id}/mcp-invite`, admin-gated Supabase
   Auth account creation) + **contact email capture** at signup
   (migration 026: `workspaces.contact_email`). The email gap was found
   during the operational-readiness assessment below — the workspaces
   table had no email column at all, so nothing in Cloud Decoded's own
   code could ever send a welcome email or an Enterprise-tier alert, and
   there was no way to identify a customer without going to Stripe
   directly.

4. **`feat(marketing)` `e6ed6b6`** — Features, Comparison, Problems,
   Security pages + dynamic og:image (GTM Priority 2 backlog).

5. **`docs(customer)` `ffe8083`** — DPA outline, security questionnaire
   response draft, Loom demo script, setup guide, workflow how-tos,
   agent reference (GTM Priority 3 backlog — explicitly source material
   for a real attorney/prospect conversation, not send-ready).

6. **`docs` `0bda522`** — reconciled `GAPS.md` and
   `CloudDecoded-Build-Order.md` with what's actually built.

## Operational readiness assessment (full findings, not yet all fixed)

Asked and answered with direct code reads, not assumptions — the
question was "can this onboard/manage/offboard a paying customer without
manual intervention." Findings:

- **Stripe → onboarding**: checkout success redirects to a plain
  `/dashboard`, not into any guided setup. No email sent at all — zero
  email infrastructure exists anywhere in the codebase (confirmed via
  full grep of both frontend and backend).
- **Onboarding UI**: `OnboardingWizard` (3 steps: workspace/LLM
  key/webhooks) is stale and disconnected from the real Stripe-gated
  signup — it independently creates a second, unpaid workspace if
  reached from a logged-in dashboard. The real connector UI (GitHub
  App/AWS/Azure/Azure DevOps/K8s) exists and works, but lives in an
  undiscoverable separate "Connections" tab with no onboarding linkage.
- **Offboarding**: Stripe's hosted Customer Portal is a real self-serve
  cancel path. Cancellation preserves all data (intentional, per
  `stripe_billing.py`'s own comment) — but there is **no data-deletion
  mechanism at all**, self-serve or admin-triggered. Real GDPR/CCPA gap.
- **SOPs**: zero exist for Cloud Decoded customer lifecycle (onboarding,
  offboarding, credential rotation, MCP invite trigger) — only internal
  dashboard SOPs exist in `knowledge/sops/`.
- **Contracts**: no ToS/Privacy Policy pages exist at all (the signup
  checkbox links to nothing), no acceptance is recorded in the DB, no
  DPA acceptance mechanism exists.
- **Enterprise MCP alert**: no notification path exists, and couldn't
  until contact_email existed — root cause fixed this session, but no
  actual alert (email/Slack) fires yet on tier change.
- **GitHub App ("the-cloud-decoded")**: registration machinery is fully
  built and automatic. The one real blocker: the manifest hardcodes
  `"public": false` — a private GitHub App can only be installed by its
  own owning account, so **no real customer can install it until it's
  flipped to public** in GitHub's own App settings (one click, no
  re-registration).

## Still open (not built this session, in priority order)

1. Make the GitHub App public (GitHub-side setting, 2 minutes).
2. Post-checkout redirect into an actual guided setup flow (currently
   lands on a bare dashboard).
3. Welcome/confirmation email sending (contact_email now exists to send
   to — no send mechanism built yet).
4. Real data-deletion path for cancelled/offboarded workspaces.
5. ToS/Privacy Policy pages + DB-recorded acceptance; DPA acceptance for
   Enterprise.
6. Customer-lifecycle SOPs (onboarding, offboarding, credential
   rotation, MCP-invite trigger).
7. Legacy PAT-based GitHub workspaces have no prompted migration nudge
   to the App.

## Deploy (round 1 — connectivity roadmap + contact email)

Pushed to `origin/master`. Railway's GitHub webhook auto-deploy did not
pick up the push within the wait window, so triggered manually via
`railway up --service kdavis-agentic-platform --environment production`
from local source at these same commits. Frontend (Vercel) deploys via
its own GitHub integration on push, unaffected by the Railway path.

## Round 2 — operational-readiness build-out (same session, continued)

Built and shipped the highest-priority items from the still-open list
above: guided post-checkout flow (`?tab=connections&welcome=1` +
dismissible banner), Settings icon repointed off the broken
OnboardingWizard onto Connections, a real "LLM Key" card in
ConnectionsPanel (previously only settable via the broken wizard),
legacy-PAT-to-App migration nudge (`github_via_legacy_pat` on
`GET /workspace/credentials/status`), a real data-deletion path
(`POST /internal/workspaces/{id}/purge-data`, migration 027 — refuses to
run against a live subscription, requires typing the exact company_name
to confirm), and click-through ToS acceptance (`tos_accepted_at`,
migration 028, plus real `/terms` and `/privacy` pages — previously
neither page existed and the signup checkbox's state was silently
discarded). Wrote the four customer-lifecycle SOPs that didn't exist
(`knowledge/sops/customer-ops/`).

24 new/updated tests, full suite 1305 passing (up from 1293), same
pre-existing unrelated failures. Frontend `next build` clean, 18 routes.

**Deploy (round 2):** Same pattern as round 1 — Railway's GitHub webhook
still isn't auto-deploying on push (confirmed twice now; worth a real
look at whether the webhook itself is still correctly configured on
GitHub's side, not just re-triggering around it every time). Used
`railway service source connect --repo ... --branch master` to force a
fresh GitHub-source build rather than `railway up` (which failed once
this session with a `mise`/Procfile parsing error caused by something in
`railway up`'s own local-directory tar/upload path, not the source
itself — the same commit deployed clean via the GitHub-source path
immediately after). Vercel: `vercel --prod --yes`, succeeded, aliased to
theclouddecoded.com. Live-verified post-deploy: `/terms` and `/privacy`
return 200, and `POST /workspaces` with an incomplete body now correctly
returns 422 (confirms the new contact_email/tos_accepted validation is
live in production, not just committed).

**Follow-up worth doing:** figure out why neither Railway's nor Vercel's
GitHub auto-deploy fired on push this session, twice. Manual triggers
worked both times, but that shouldn't be the normal path.

## Round 3 — email sending + GitHub App made public (same session)

Kelvin provided a Resend API key directly in chat and confirmed the
GitHub App is now public.

- Set `RESEND_API_KEY` on the Railway service via the Railway MCP tool
  (`set-variables`) — never written to any file or committed to git,
  matching CLAUDE.md's "no hardcoded secrets, env vars only" rule.
- Added `core/email.py`: `send_email()` (Resend REST API via httpx, no
  new dependency), `EmailError`, and two HTML builders. Skips the send
  (logs a warning) if `RESEND_API_KEY` is unset rather than raising —
  every call site treats a send failure as non-fatal.
- Wired into two call sites: `_handle_checkout_completed`
  (stripe_billing.py) sends a welcome email; `set_workspace_tier`
  (internal_workspaces.py) alerts `OWNER_ALERT_EMAIL` only on a real
  transition *into* enterprise (not every PATCH, not if already
  enterprise). Both closed real gaps flagged in this same file's Round 1
  section.
- Verified GitHub App is publicly reachable:
  `https://github.com/apps/the-cloud-decoded` → 200.
- 21 new tests (`tests/test_email.py`, plus additions to
  `test_internal_workspaces.py`/`test_stripe_billing.py` covering the
  alert-only-fires-on-real-transition and non-fatal-on-failure behavior).
  Full suite: 1320 passing, same pre-existing unrelated failures.
- Updated the two SOPs this closed
  (`knowledge/sops/customer-ops/customer-onboarding.md`,
  `enterprise-mcp-invite.md`) and GAPS.md to move these from "still open"
  to "closed."
