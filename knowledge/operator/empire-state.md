# Empire State — Current Status

**Last updated:** 2026-07-25
**Entity:** THD Agentic Systems LLC
**Brand:** The Hustle: Decoded / Decoded Empire
**Owner:** Kelvin Davis — USAF veteran, Fortune 500 cloud DevOps

---

## Products

### Micro SaaS Engine
| Field | Value |
|---|---|
| Status | Building — factory pipeline live, no product has gone through it end-to-end yet |
| Progress | ~75% |
| MRR | $0 |
| Supabase | `microsaas-prod` — full schema live, RLS confirmed on every table |
| Stripe | Dedicated account — **not yet created**, deferred until first opportunity clears Verdict |
| GitHub | `KDavisCodeCloud/kdavis-microsaas-engine` (git root is the parent `projects/` folder) |
| Domain | `thdstack.com` — wildcard, per-product subdomains |
| Full notes | [[micro-saas-engine/overview]] |
| Sprint log | [[micro-saas-engine/sprint-log]] |

**What's built:** Full research → Verdict → build/deploy pipeline (Phases 1-6), outreach engine (Apollo.io + LinkedIn manual-outreach-only, HITL-gated), 94 passing tests, real Systeme.io/Apollo.io keys live. "Pipeline" dashboard tab renamed to "Opportunities" (2026-07-17). Factory Expansion shipped this session: `industry_color_map`/`mse_build_briefs`/`mse_monitoring_events` tables, `brief_generator` agent (auto-generates build briefs on Verdict PASS, HITL-gated), Build Briefs section added to the Opportunities dashboard page, monitoring/incident/support agent + customer-docs templates saved as reference docs (intentionally not built — no live product to monitor yet).

**Blockers (Kelvin — manual):**
- Pick and greenlight the first opportunity to run through the full pipeline
- Create the dedicated MSE Stripe account once that opportunity clears Verdict

**Blockers (Claude — code):**
- CEO dashboard cross-repo wiring for brief cards / monitoring health cards (separate repo, not started)
- "Agent last-ran" correlation fix across MSE/CEO/DecodedSix dashboards

**Done since last update:** LinkedIn HITL queue disclaimer for manual cold-DM outreach — amber banner + "MANUAL SEND" badge live on `/outreach` (2026-07-17).

---

### Cloud Decoded / CEO Command Center
| Field | Value |
|---|---|
| Status | Building — 14/16 CEO dashboard agents live |
| Progress | ~85% |
| MRR | $0 |
| GitHub | `KDavisCodeCloud/kdavis-agentic-platform` |

**What's built:** Full FastAPI backend, specialized agents (14/16 live on the CEO dashboard), MCP server, Next.js frontend, Stripe billing routes. HITL `interrupt()` bug fixed 2026-07-14 (was silently broken under Python 3.10, confirmed working on 3.11).

**Note:** this repo's own `CLAUDE.md` describes a much larger from-scratch build plan (LangGraph engine, DeepSeek-primary LLM routing, full team-management/onboarding system, revenue intelligence, finance/tax/wealth agents) that is largely aspirational relative to what's actually running today — treat that file as a long-range spec, not a status report. Actual current state is captured here and in [[micro-saas-engine/overview]] instead.

**Dashboard honesty pass (2026-07-25):** every section across all 10 department pages now carries a visible LIVE / PARTIALLY LIVE / NOT YET BUILT badge instead of silently showing hardcoded placeholder data indistinguishable from something real. Full breakdown in [[sops/devops/2026-07-25-ceo-dashboard-live-status-and-fixes]] — supersedes the per-page status table in the 2026-07-06 CEO dashboard SOP, which is now stale (it still calls Marketing/Tech/Ops pure stubs; they're not anymore).

**Role-resolution bug found and fixed (2026-07-25):** `middleware.ts` and `app/dashboard/layout.tsx` each independently resolved the logged-in user's role and had silently drifted apart — layout.tsx special-cased the owner email to `admin`, middleware.ts didn't. Sidebar showed Marketing as clickable (driven by the correct layout logic); clicking it hit the middleware's stale check and silently redirected back to Overview. Extracted into one shared `lib/role.ts` so the two can't diverge again. Full account: [[sops/devops/2026-07-25-ceo-dashboard-live-status-and-fixes]].

**Backend deployment gap found (2026-07-25):** the FastAPI backend (`api/main.py`, everything under `/api/v1/...`) has never been deployed anywhere publicly reachable — it only ever ran in a local dev sandbox. This is why the dashboard's LinkedIn batch panel 404'd/failed to fetch in production. Rather than deploying a separate backend (Railway hit a free-plan resource limit; decided it's not necessary right now anyway — the publish cron already talks to Postgres directly, and generating a new batch is a manual monthly action), the 3 endpoints the dashboard actually needs moved into Next.js route handlers living directly in `ceo-dashboard` itself, using a service-role Supabase client. Full account: [[sops/content/2026-07-25-linkedin-monthly-batch-pipeline]].

**Blocking full launch:**
- CEO dashboard R&D panel: brief cards + monitoring health cards from MSE (not wired)
- Remaining 2/16 agents
- DNS + hosting finalization
- FastAPI backend still not deployed anywhere — fine for now (nothing currently depends on it being always-on), but the "Publish now" button and any future feature needing live backend logic (not just Supabase reads) will need Railway resolved first

---

### DecodedSix (decodedsix.com)
| Field | Value |
|---|---|
| Status | **LIVE** — since 2026-07-08 |
| MRR | $0 (pre-monetization / fan utility phase) |
| Supabase | `decodedsix-prod` — live, 10 tables + 4 seed articles |
| Vercel | `decoded-six-sand.vercel.app` → `thedecodedsix.com` |

GTA 6 fan utility / gaming content site. Vice City stats aesthetic design system (dark bg + stripe pattern, cyan/pink accents, WASTED/MISSION PASSED overlays). Content agent (DSX-CA1) scheduled to start 2026-07-15. Dashboard "Agents" tab previously showed "never run" incorrectly for agents that had in fact run — flagged, not yet fixed; part of the broader cross-dashboard agent-correlation gap.

---

### LinkedIn Monthly Batch Pipeline (was "LinkedIn + Canva Pipeline")
| Field | Value |
|---|---|
| Status | **LIVE** — first real end-to-end monthly batch ran successfully 2026-07-23/24 |
| MRR | N/A — personal brand / authority content, not a monetized product |

No longer paused, no longer blocked on the OAuth issue from 07-14 (that was three real `await` bugs in `core/publishers/linkedin.py` — fixed, validated with a real post). Canva is intentionally parked (Kelvin's call: only for original-idea generation, not in use) — replaced entirely by Gemini image generation instead.

**What's built and confirmed working end to end:**
- MKT-LI1 moved from a pooled weekly (4/week) model to a fixed monthly batch (~12 posts), each with a real `scheduled_for` date (Tue/Wed/Thu, 9am ET)
- `assets_library/gemini_image_gen.py` — one Gemini API call per post (`gemini-2.5-flash-image`), re-attaches the generated image to its own queue row by id, never fuzzy topic-matched
- `scripts/monthly_batch.sh` — the once-a-month manual trigger (drafts the batch, generates images)
- `scripts/dispatch_scheduled_posts.py` — GitHub Actions cron (every 15 min), publishes each approved post on its own scheduled date. Runs directly against Postgres, never needed the FastAPI backend at all
- ceo-dashboard's Marketing page has a full review UI: approve/reject/reschedule/append-a-note per post, "Approve all pending" for the whole batch at once (never all-or-nothing), a "Review" button per post showing the full untruncated text + full-size image, and real image thumbnails

**Real bugs found and fixed getting this to actually run once, end to end** (none of this had ever been exercised against live data before 2026-07-23 — see [[lessons-learned/002-verify-against-live-data-not-mocks]]):
- Migration 007 (`linkedin_content_queue`) had never been applied to the live database at all
- Once applied, the insert still failed — `pillar`/`topic`/`hitl_tier`/`estimated_length`/`notes`/`pillar_name` were never defined as columns despite the code always writing them
- `security/audit_log.py` wrote a column (`actor`) that doesn't exist (real column is `agent_id`) and inserted plain strings into `uuid`-typed columns — had never once succeeded for any of the 5 marketing agents that use it
- `audit_log_outcome_check` only allowed `'win'`/`'lose'` (one caller's vocabulary) — blocked every other agent's own outcome vocabulary
- `_draft_post` never stripped Claude's ` ```json ` markdown fence — every real call had silently fallen back to raw-text mode
- `post_formatter.py`'s sentence-splitter treated a numbered list's "1." as a sentence-ending period, splitting the number from its own statement

Full account of the whole build: [[sops/content/2026-07-25-linkedin-monthly-batch-pipeline]].

---

### The Hustle: Decoded (Brand/Content)
| Field | Value |
|---|---|
| Status | Active lead magnet in progress |
| MRR | $0 |
| Platform | Systeme.io |

Lead magnet + landing page project. See memory: [[project_hustle_decoded]].

---

## Empire Dashboard

**Separate tracking app** for all products + session logs + tasks.

- **Repo:** `kdavis-agentic-platform/empire-dashboard/`
- **Supabase:** Dedicated project (not microsaas-prod)
- **To update:** Write migration SQL → paste into empire-dashboard Supabase SQL Editor → run
- **Latest applied migration:** `003_update_2026_07_03_session3.sql`

---

## Tech Stack (Engine Standard)

All micro SaaS products built from this stack:

| Layer | Tech |
|---|---|
| Backend | FastAPI (Python) |
| Database | Supabase (Postgres 15) |
| Auth | Supabase JWT |
| Frontend | Next.js 15 + Tailwind |
| Automation | n8n 2.28.6 |
| LLM | Anthropic Haiku + Sonnet |
| Agents | LangGraph |
| Email | Resend |
| Payments | Stripe (dedicated per product — NEVER shared) |
| Integration lock | MCP endpoint (ships day one) |

---

## Environment

- OS: Windows 11 + WSL2 Ubuntu 22.04
- Working path: `/mnt/c/Users/Kelvin/projects/`
- GitHub org: `KDavisCodeCloud`
- Node version in use: v22.23.1 (via nvm — v24 is incompatible with n8n)

---

## Session Cadence

- Claude sessions: weekly, start by reading `EXECUTION_ORDER.md` in the active repo
- Agent builds: Thursday nights — one agent per week
- Empire dashboard: updated at end of every Claude session via SQL migration
