# SOP: LinkedIn On-Demand Fire Button + First Cloud Decoded Backend Deploy
Date: 2026-08-17
Product: Kelvin's personal LinkedIn brand (MKT-LI1) + Cloud Decoded backend infra
Status: Live — ceo.thdecodedempire.com's Marketing page can fire posts on demand; kdavis-agentic-platform's FastAPI backend is deployed to Railway for the first time

---

## What this adds

The monthly batch (`scripts/monthly_batch.sh`, see [[2026-07-25-linkedin-monthly-batch-pipeline]]) needs Kelvin to hand-supply `research_report`/`idea_reservoir` content angles once a month. There was no way to draft a post or a handful of posts on demand between batches. Two things changed:

1. **`generate_on_demand_posts(count, pillar_focus)`** — new entry point in `agents/marketing/mkt_li1_linkedin_brand.py`. Reuses the evergreen pillar/Opinion Matrix/stance-rotation machinery (unlike `generate_builder_post`/`generate_product_launch_post`, which are deliberately separate from all of that), but since there's no curated research pool for an ad-hoc fire, each slot's source material comes from `PILLAR_TOPIC_SEEDS` — a fixed topical-grounding description per pillar — instead of a specific hand-picked angle. `pillar_focus=None`/`"balanced"` apportions `count` across the existing 40/30/20/10 `CONTENT_MIX_RATIO`; a specific `pillar_key` forces every post into that one pillar. Scheduling uses a new `_compute_ondemand_schedule` (starts from tomorrow's next Tue/Wed/Thu, not the batch_month's start) so an on-demand fire never collides with the monthly batch's own slots. Every row is tagged `source='on_demand'` (migration 017) so the queue can tell them apart from the monthly batch.
2. **CEO dashboard "🔥 Fire posts" control** — `ceo-dashboard/components/ui/FireLinkedInPosts.tsx`, on the Marketing page above the existing review queue (now `LinkedInBatchPanel.tsx`, which holds both). Count field (1-30) + pillar dropdown (Balanced mix or one of the four pillars). Posts land in the exact same HITL review queue as the monthly batch — nothing publishes without approval, same as always.

New route: `POST /api/v1/marketing/linkedin-on-demand` (`api/routes/marketing.py`), same `require_marketing_api_key` auth as `/linkedin-brand`. Dashboard side: `ceo-dashboard/app/api/linkedin-queue/generate/route.ts` — session-auth gated (`requireRole(["admin","marketing"])`), then calls the FastAPI backend server-side with the shared `MARKETING_API_KEY` secret (never exposed to the browser). This is the one LinkedIn-queue action that genuinely needs the FastAPI backend — everything else on that page (list/approve/reject/reschedule) reads/writes Supabase directly from Next.js route handlers, per the existing "backend never deployed" workaround.

## Real bug found and fixed along the way

`run_li1_brand_agent` (the monthly batch) and the new `generate_on_demand_posts` both had the same latent bug: when MKT-10 flags a post, the code escalated the *local* `hitl_tier` variable used for the actual `queue_for_review(tier=...)` call, but never updated the `post["hitl_tier"]` field that gets spread into `content_item` and written to the row. Net effect: a compliance-flagged post could be routed to Kelvin (tier 3) for review while its own stored `hitl_tier` column still said 2 — the dashboard would have shown the wrong tier on a row it was actually escalating. Caught by a test in `tests/test_mkt_li1_on_demand.py` (`test_mkt10_flag_escalates_to_tier_3`), fixed in both functions the same way: reassign `post["hitl_tier"]` before building `content_item`, not after.

---

## Cloud Decoded backend: first-ever deploy (Railway)

`api/main.py` had never been deployed anywhere reachable (see [[2026-07-25-linkedin-monthly-batch-pipeline]]'s "what this replaced" note, and the SOP-level gap it left: the dashboard's `NEXT_PUBLIC_API_URL` still pointed at `localhost:8000`). The on-demand fire button needed a real backend to call, so this session deployed the whole backend as-is (Kelvin's explicit call — full Stripe billing/workspace auth/rate-limiting/LangGraph-checkpointer surface, not a stripped-down marketing-only service) to a new Railway project, `kdavis-agentic-platform` (project id `cb8502a7-a9ea-4506-b7e0-cc3aa2c248ce`), service `kdavis-agentic-platform`, public URL `https://kdavis-agentic-platform-production.up.railway.app`.

### Real bug found getting the first build to succeed

Railway's default Railpack builder failed `railpack prepare` on this repo with `mise ERROR invalid tool version "\0\0\0\0\0": contains forbidden character '\0'` reading `.python-version`, and separately `Error reading Procfile as YAML: yaml: control characters are not allowed` — both files are genuinely clean 5-54 byte text files locally (verified with `xxd`/`cat -A`), so this is Railpack's Python-detection path corrupting them somewhere in its own snapshot/parse step, not a real file problem. Fix: added `railway.json` pinning `"build": {"builder": "NIXPACKS"}` plus an explicit `"deploy": {"startCommand": "..."}`, which routes around Railpack's buggy Python provider entirely and builds cleanly via classic Nixpacks. (A parallel attempt copying the repo off the WSL `/mnt/c/...` mount to a native Linux path before deploying did *not* by itself fix it on its own in isolation — the `railway.json` builder override is the fix that mattered; keep both for now since the WSL-mount copy also fixed `railway.json` not being picked up on the first two attempts, for reasons not fully root-caused.)

Also added `.railwayignore` — this is a monorepo (`ceo-dashboard/`, `empire-dashboard/`, `team-dashboard/`, `frontend/` all live at the same root as `api/`), and without it Railway would tar up 2GB+ of unrelated Next.js `node_modules`/`.next` output for a Python-only deploy. Excludes those four directories plus the usual `node_modules/`/`.venv/`/`.git/`/`__pycache__/`.

### Env vars set on the Railway service

Mirrored straight from the local `.env` (same values, nothing new invented) plus three new ones: `MARKETING_API_KEY` (freshly generated shared secret, also set on ceo-dashboard's Vercel project — did not exist before this session, `require_marketing_api_key` was running in dev-mode-no-auth), `ALLOWED_ORIGINS=https://ceo.thdecodedempire.com,http://localhost:3000` (CORS), `ENVIRONMENT=production`. `DATABASE_URL` points at the same shared `microsaas-prod` Supabase Postgres project (`gjezchcoyytxcpsbvkrg`) the Orchestrator and decoded-empire-os already use — Cloud Decoded's backend was never given its own isolated Supabase project despite CLAUDE.md's per-product-isolation intent; noted here, not fixed, since re-platforming the DB wasn't in scope for this session.

Verified end-to-end after deploy: `GET /health` and `/health/db` both return ok, and a real `POST /api/v1/marketing/linkedin-on-demand` call drafted a genuine post and landed it in `linkedin_content_queue` with `source='on_demand'`, `status='pending_review'` — confirmed by querying the row directly.

### Incident during this session — unrelated Vercel project redeployed by accident

While wiring `NEXT_PUBLIC_API_URL`/`MARKETING_API_KEY` into ceo-dashboard's Vercel env and redeploying, a `vercel --prod --yes` run from the wrong directory (`kdavis-agentic-platform` root, which has no local `.vercel` link) landed on and redeployed a completely unrelated project — `kdavis-microsaas-engine` (`mse.thdecodedempire.com`) — instead of ceo-dashboard. Root cause: the `ceo-decoded-dashboard` Vercel project has **Root Directory = `ceo-dashboard`** configured server-side, but `vercel link` had been run *from inside* `ceo-dashboard/`, so the link file lived at `ceo-dashboard/.vercel/project.json` — deploying from inside `ceo-dashboard/` double-appended the root directory (`ceo-dashboard/ceo-dashboard` — path error), and deploying from the parent found no link at all and fell through to some other project-resolution path that picked the wrong project. Fix: moved the link file to the monorepo root (`kdavis-agentic-platform/.vercel/project.json`) and deployed from there, which correctly resolved to `ceo-dashboard/` as the build root and aliased `ceo.thdecodedempire.com`. No source changes had been made to `kdavis-microsaas-engine` this session, and Kelvin confirmed `mse.thdecodedempire.com` looked fine afterward — but flagging clearly since it was a live, unintended production deploy of a project outside this session's scope.

---

## If this breaks again

- **Fire button gets "Failed to fetch" in production:** check `NEXT_PUBLIC_API_URL` and `MARKETING_API_KEY` are still set on ceo-dashboard's Vercel *production* env (`vercel env ls production`) — both were added fresh this session and nothing auto-syncs them.
- **Railway build fails on `.python-version`/Procfile parsing again:** confirm `railway.json`'s `"builder": "NIXPACKS"` is still present and actually being picked up (`railway deployment list --json` shows `meta.configFile` when it is).
- **A future deploy to `ceo.thdecodedempire.com` lands on the wrong Vercel project:** always run `vercel --prod` from `kdavis-agentic-platform/` (the repo root, one level *above* `ceo-dashboard/`), with `.vercel/project.json` present at that root, not inside `ceo-dashboard/` itself — Root Directory is configured server-side as `ceo-dashboard`.
