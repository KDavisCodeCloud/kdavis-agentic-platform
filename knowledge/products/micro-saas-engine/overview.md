# Micro SaaS Engine — Overview

**Status:** Building — factory pipeline live, first real READY_TO_BUILD opportunity in hand (Trades vertical, 2026-08-22), not yet taken through human build approval
**Progress:** ~75% (unchanged estimate — this update corrects what "75%" actually covers, see below, more than it adds new ground)
**Last updated:** 2026-08-22 — see [[sprint-log]] Sprint 5. This file was stale between 2026-07-17 and 2026-08-22; Verdict v5.0 and a substantial marketing engine (MKT-R1/ORCH/O1-O5/S1/V1, Brevo) shipped in that gap undocumented here — Sprint 5 only captures what that session directly touched/verified, not a full backfill of everything built since 2026-07-17.
**Repo:** `github.com/KDavisCodeCloud/kdavis-microsaas-engine`
**Local path:** `/mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine` (git root is the parent `/mnt/c/Users/Kelvin/projects/`, no separate `.git` in this folder)
**Supabase project:** `microsaas-prod`
**Stripe account:** dedicated MSE account — deferred until first opportunity clears Verdict (per Kelvin: "Stripe account can't happen until the first product is discovered")
**Domain:** `thdstack.com` — wildcard, one product-slug subdomain per launched product

---

## What It Is

A research-validated, retention-first software factory. Originally scoped to six problem-category research verticals (Healthcare/Medical Front Desk, Legal/Professional Services, E-commerce/Retail Ops, Real Estate/Property Management, HR/Ops/People Management, Finance/Accounting/Bookkeeping) — **none of these six ever got a real agent built** (confirmed 2026-08-22; all six `agents/*-intel/` directories are still empty `__init__.py` stubs, silently falling through to Dispatch's generic research prompt this whole time). As of 2026-08-22, four **industry** vertical agents are real and working — Residential Trades, Care Services, Personal Services, Field/Repair Services (`agents/{trades,care,service,field}_intel/`) — the first actual implementations of the per-vertical-agent pattern this repo has had.

**$4,000 MRR floor** enforced at DB level and by the aggregator/Verdict gate. No product enters development without hitting this bar.

---

## What's Built (as of 2026-07-17)

**Research → Verdict → Build pipeline (Phases 1-6, complete):**
- FastAPI backend, Next.js 15 dashboard, Supabase (RLS on every table), n8n self-hosted
- Research swarm across all 6 verticals — real live run confirmed producing real opportunities
- `opportunity_pipeline` table — Verdict scoring, status flow (`watch` → `validated` → `READY_TO_BUILD`)
- Full build/deploy pipeline (`agents/factory/`): `scaffold_generator.py` → `provision_supabase.py` → `provision_stripe.py` → `deploy.py` → `build_pipeline.py`, HITL-gated via admin-only `POST /factory/build/{id}`
- Outreach engine: Apollo.io lead sourcing + LinkedIn manual-outreach-only architecture (no auto-DM — HITL queue routes to a human for every cold DM)
- Real Systeme.io + Apollo.io API keys live in `.env`
- Test harness (`tests/conftest.py` fake Supabase fixtures) — 94 tests passing
- Dashboard: "Pipeline" tab renamed to **"Opportunities"** (2026-07-17 — clearer to a human than internal jargon)

**Factory Expansion (built 2026-07-17, this session):**
- Migrations `20260717000011`/`000012`: `industry_color_map` (seeded with the 6 real verticals + generic fallback), `mse_build_briefs`, `mse_monitoring_events`, `check_monitoring_activation()`/`activate_monitoring()` functions, Realtime enabled on both new tables
- `agents/factory/brief_generator.py` — generates `BUILD_BRIEF_CLAUDE_CODE.md` + `BUILD_BRIEF_CLAUDE_DESIGN.md` on Verdict PASS, pushes to a `brief/{product-slug}` git branch, inserts into `mse_build_briefs`. Triggered via admin-gated `POST /factory/generate-brief/{opportunity_id}`, mirroring the existing build-trigger pattern. Fully tested.
- MSE dashboard Opportunities page: new "Build Briefs" section — brief cards (product name, vertical, Verdict score, status pill), click to expand and read both generated briefs inline
- `docs/monitoring-agent-suite.md` / `docs/customer-docs-sop-template.md` — reference templates for the post-$4K Monitor/Incident/Support agent trio and customer docs site. **Not built yet, intentionally** — these only get created per-product once a product actually crosses the $4K/30-day maturity gate (nothing to monitor before then)
- CLAUDE.md updated with the SEO/AEO/GEO/SXO search-visibility rules, the brief-generation rule, and the monitoring-activation rule. Honest gap noted inline: `search_signals`/`objection_signals`/`geo_signals` are specified but not yet wired into the research swarm's actual output schema — follow-on work, not done yet.

---

**Industry Vertical Agents + Real Pipeline Wiring (built 2026-08-22, this session — full detail in [[sprint-log]] Sprint 5):**
- First 4 real vertical intel agents ever built in this repo: `agents/{trades,care,service,field}_intel/agent.py`
- `opportunity_pipeline.vertical_agent_extras` (JSONB) — carries each agent's extra fields (named Facebook groups, license DB sources, `parts_integration_verdict`, `free_tier_differentiation`) forward to brief generation
- `generate_research_report_from_verdict()` — every BUILD verdict now seeds the real `mse_research_reports`/`mse_icp_configs` and fires the already-built `run_campaign_orchestrator()` (MKT-O1/O2/O3/S1/V1), instead of a new disconnected marketing pipeline
- Real, live, non-mocked verification: a complete Dispatch→Verdict run for the new Trades vertical produced a genuine `READY_TO_BUILD` opportunity (**$23,840 MRR, confidence 94**) — this is the first real opportunity this factory has ever produced with a working vertical agent behind it, not the generic fallback
- Deployed: Railway `mse-api` + Vercel frontend, both auto-deploying from GitHub pushes as of 2026-08-22 (Railway's connection had gone stale — `connect_service_source` re-run to fix it, verified live with a real test push)

---

## Non-Negotiable Rules (CLAUDE.md)

1. Retention scaffold ships before any feature work
2. Infrastructure isolation — dedicated Supabase + Stripe per product
3. RLS on every table
4. Research agent gates every build (READY_TO_BUILD required)
5. $4K MRR floor is hard — enforced in DB and agent logic
6. Every agent action emits `POST /events` + audit_log entry (win/lose)
7. MCP endpoint ships with every product from day one
8. Stripe is per product — never shared
9. No autonomous outbound — every build/brief action requires a named human (`triggered_by`) and admin role
10. SEO/AEO/GEO/SXO search-visibility layer ships at launch, no exceptions (added 2026-07-17)

---

## What's Left to Go Live (see also `MSE-Build-Order.md` in the repo itself)

1. Take the real Trades opportunity produced 2026-08-22 ($23,840 MRR, confidence 94, `READY_TO_BUILD`) through brief generation → human build approval → build → deploy — the first candidate that's actually made it this far with a real vertical agent behind it, not the generic fallback
2. Stripe account creation — blocked on step 1 (first product discovered)
3. Dashboard "agent last-ran" correlation across MSE/CEO/DecodedSix dashboards (DecodedSix "never run" bug flagged, not yet fixed)
4. CEO dashboard cross-repo wiring: brief cards + monitoring health cards in the R&D department view (separate repo, not started)
5. Monitoring/Incident/Support agent trio — deferred by design until a product hits the $4K/30-day gate
6. Harden `node_write_pipeline`'s finding-to-result matching (currently exact `solution_concept` string equality — silently drops `icp`/`vertical_agent_extras`/etc. on a mismatch; see [[sprint-log]] Sprint 5)

LinkedIn HITL queue disclaimer for manual cold-DM outreach — **done**, deployed 2026-07-17 (amber banner + "MANUAL SEND" badge on `/outreach`).

See [[sprint-log]] for the detailed task board.
