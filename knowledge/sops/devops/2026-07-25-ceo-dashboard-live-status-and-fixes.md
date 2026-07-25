# SOP: CEO Decoded Dashboard — Live Status Pass + Role/Backend Fixes
Date: 2026-07-25
Product: CEO Decoded (internal)
URL: ceo.thdecodedempire.com
Repo: kdavis-agentic-platform/ceo-dashboard
Status: Live — supersedes the per-page status table in [[sops/devops/2026-07-06-ceo-dashboard]], which is now stale

---

## Why this exists

The 2026-07-06 SOP's department status table said Marketing, Technology, and Operations were pure stubs with no live data. That stopped being true somewhere along the way and nobody updated the doc — this SOP corrects the record and documents three real bugs found while doing it.

---

## Bug 1: Marketing wouldn't open — role-resolution drift

**Symptom:** sidebar showed "Marketing & Sales" as a normal, clickable nav item. Clicking it did nothing — page silently bounced back to Overview.

**Root cause:** `middleware.ts` and `app/dashboard/layout.tsx` each independently reimplemented "resolve this user's role." `layout.tsx` special-cased the owner email (`kdav2k5@gmail.com`) to `admin`. `middleware.ts` did not — it only read `user_metadata.role`, defaulting to `rnd` for anyone (including the owner) who never had that field explicitly set in Supabase.

Sidebar renders off `layout.tsx`'s (correct) role, so Marketing showed as clickable. Middleware then evaluated every request to `/dashboard/marketing` against its own (wrong) `rnd` role, and `rnd` isn't in that route's allowed roles (`["admin", "marketing"]`) — so it silently redirected back to `/dashboard/overview`.

**Fix:** extracted one shared `lib/role.ts` (`resolveRole(email, metadataRole)`) that both `middleware.ts` and `app/dashboard/layout.tsx` now call. They can't drift apart again because there's only one implementation.

**Lesson:** any time two files each reimplement the same "who is this user" logic, assume they'll eventually disagree. One shared function, always.

---

## Bug 2: LinkedIn batch panel — "Failed to fetch"

**Symptom:** the LinkedIn Monthly Batch panel (see [[sops/content/2026-07-25-linkedin-monthly-batch-pipeline]]) showed "Failed to fetch" and "0 posts" in production, despite 10 real posts sitting in the database.

**Root cause:** `NEXT_PUBLIC_API_URL` was never set in Vercel's production environment. `lib/api.ts` fell back to `http://localhost:8000` — which, from a real browser on a real machine, means "my own laptop," not the backend. Deeper root cause: the FastAPI backend (`api/main.py`) has **never been deployed anywhere publicly reachable** — it only ever ran in a local dev sandbox.

**Considered and rejected:** deploying a separate backend (tried Railway, hit a free-plan resource-provisioning limit; reconsidered afterward and concluded it isn't actually necessary right now — the publish cron (`scripts/dispatch_scheduled_posts.py`) already talks to Postgres directly via GitHub Actions, and generating a new monthly batch is a manual, occasional action that can run from any machine with the backend spun up temporarily).

**Fix:** moved the 3 endpoints the dashboard actually needs into Next.js route handlers living directly in `ceo-dashboard`:
- `app/api/linkedin-queue/route.ts` (GET, list + filter)
- `app/api/linkedin-queue/[id]/route.ts` (PATCH, approve/reject/reschedule/note)
- `app/api/linkedin-queue/batch-approve/route.ts` (POST)

Each uses a service-role Supabase client (`lib/supabase/admin.ts` — `linkedin_content_queue`'s RLS is service-role-only) and gates itself on admin/marketing role (`lib/api-auth.ts`), since route handlers sit outside `middleware.ts`'s `DEPT_ROUTES` check and would otherwise be reachable by any authenticated user regardless of role.

Image thumbnails hit the identical bug (same undeployed-backend cause) — fixed the same way: `app/api/asset/[...path]/route.ts` serves `assets_library/my_originals/` (only 5.8MB) directly, bundled into the deployment via `next.config.ts`'s `outputFileTracingIncludes`.

**Real gotcha inside that fix:** the tracing config's key has to be a glob like `/api/asset/**`, not the literal route path `/api/asset/[...path]` — Next.js matches these keys with `picomatch`, which parses `[...path]` as a glob character class (bracket syntax), not literal text. The exact-path version built clean and deployed clean but silently bundled zero files. Found by reading `node_modules/next/dist/build/collect-build-traces.js` directly rather than guessing a second time.

**Also fixed along the way:** CORS (`api/main.py`) was hardcoded to a single `FRONTEND_URL` origin (`theclouddecoded.com`, Cloud Decoded's customer site) — would have blocked ceo-dashboard and team-dashboard entirely the moment either needed it. Now reads a comma-separated `ALLOWED_ORIGINS` list.

**Lesson:** "it built successfully" and "the deployed function actually has the files it needs" are two different claims — verify the second one directly (checked the `.nft.json` trace file) rather than trusting a clean build.

---

## Current per-page status (replaces the 2026-07-06 table)

Every section on every page now shows an explicit LIVE / PARTIALLY LIVE / NOT YET BUILT badge (`components/ui/DataStatus.tsx`, wired through `SectionCard`'s `status`/`statusNote` props). Verified against the actual code and live database, not assumed:

| Page | Live sections | Partial | Not built |
|---|---|---|---|
| Overview | Agent Activity, HITL Approval Queue | All Products (real fire buttons, fake MRR numbers) | Team Ops |
| Finance | Operating Stack Cost | — | MRR Breakdown, Exit Gate Tracker, Finance Agents (code exists, zero real runs ever) |
| Marketing & Sales | LinkedIn Monthly Batch | Marketing Agents (LinkedIn real, roster static) | Sales Pipeline, Cold Outreach Tracker |
| R&D | Opportunity Pipeline | MSE Agent Swarm (Dispatch/Verdict real, roster static) | Build Pipeline |
| HR | Team Roster | — | Onboarding Flow, HITL Routing Rules (table exists, empty, unused), Approval Chain |
| Technology | System Health, Build Queue | Agent Health (data real, Re-run button can't fire — see below) | Infrastructure Health (always shows healthy, no real check), Cost Optimizer |
| Legal | Document Vault | — | Legal Agents (none exist), Legal Q&A |
| Operations | GAP Tracker, Session Log | Agent Triggers (fixed wrong IDs, still can't fire — see below) | Build Order, Weekly Rhythm |
| Advisory | — | All 3 advisor cards (thread history real, memory summary static, Brief button not wired) | — |
| Video / Creative | — | — | Everything — zero live wiring |

### A second, deeper button bug found doing this pass

Ops page's 4 "Agent Triggers" buttons used the wrong agent ID format (`cicd_triage` instead of the real `agent_01_cicd_triage`) — fixed. But even with correct IDs, **they still can't fire**: `/agents/{id}/run` requires `Depends(get_workspace)` (an `X-Workspace-Token`, the customer-facing Cloud Decoded auth model), and this dashboard's `FireButton`/`triggerAgent` only ever sends a Supabase session Bearer token. These are Cloud Decoded's *customer-facing* product agents, wired to the wrong auth path entirely for an owner-dashboard "just run this on my own infra" button. Tech page's "Re-run" buttons have the identical problem. This is a real architecture question (does the owner need a synthetic internal workspace, or does `/agents/{id}/run` need an admin bypass path?) — not fixed, labeled honestly instead.

---

## If this breaks again

- **A dashboard page won't open despite being visible in the sidebar:** check `lib/role.ts` is actually what both `middleware.ts` and `layout.tsx` call — if either one has grown its own inline role logic again, that's the bug.
- **A panel shows "Failed to fetch":** check whether it's calling `${API_BASE}/api/v1/...` (the FastAPI backend — not deployed anywhere, will always fail in production) vs. a local `/api/...` route handler (this app's own, should work). If a new feature needs the former, either build it as a local route handler like `linkedin-queue`/`asset` did, or resolve the Railway backend-hosting question first.
- **A new `outputFileTracingIncludes` entry silently includes nothing:** the key almost certainly has brackets in it. Use a `**` glob instead of the literal dynamic-route path.
