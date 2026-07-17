# MSE Factory Expansion — Build Brief

**Date:** 2026-07-17
**Status:** Migrations + CLAUDE.md rules + brief_generator agent all shipped and tested this session. Monitoring/incident/support agents intentionally deferred.
**Related:** [[overview]]

---

## What Was Requested

Four things, in this order (per Kelvin's explicit sequencing: "the migrations run first, then the CLAUDE.md append, then brief_generator gets wired. The monitoring agents don't get created until a product actually hits the maturity gate"):

1. Rename the MSE dashboard's "Pipeline" tab to "Opportunities" — the internal term "pipeline" wasn't legible to a human glancing at the dashboard
2. Ship a new rule set into `kdavis-microsaas-engine/CLAUDE.md`: a mandatory SEO/AEO/GEO/SXO search-visibility layer at launch, a search-signal requirement gating Verdict passes, automatic build-brief generation on every Verdict PASS, a post-$4K monitoring/incident/support agent trio that activates per-product at the maturity gate, and a customer-facing docs requirement
3. Build the `brief_generator` agent itself
4. Update the whole Decoded Empire's current status plus this build brief in the Obsidian vault, and refresh the MSE go-live punch list

---

## What Shipped

### 1. Dashboard rename
`frontend/lib/types.ts` NAV_ITEMS + `frontend/app/pipeline/page.tsx` — "Pipeline" → "Opportunities" everywhere a human sees it (nav label, page title, loading/empty states). Frontend rebuilt clean.

### 2. Migrations (`supabase/migrations/`)
- `20260717000011_factory_expansion.sql` — `industry_color_map`, `mse_build_briefs`, `mse_monitoring_events`, `check_monitoring_activation()`/`activate_monitoring()` functions, Realtime enabled on both new tables. **Corrected from the original spec**: the FK on `mse_build_briefs.opportunity_id` referenced a table (`mse_opportunities`) that doesn't exist in this project — the real table is `opportunity_pipeline`. Verified against the live schema before running, not assumed.
- `20260717000012_industry_color_map_real_verticals.sql` — the original spec's seed data used placeholder vertical names (finops, govtech, creator, cloudops, retention, open) that don't match any vertical this system's research swarm actually produces. Added a second migration seeding the real 6 verticals (Healthcare/Medical Front Desk, Legal/Professional Services, E-commerce/Retail Ops, Real Estate/Property Management, HR/Ops/People Management, Finance/Accounting/Bookkeeping), confirmed against `research.py`'s `VALID_VERTICALS` and a real live swarm run. Without this fix, every real brief-generation FK insert would have failed.

Both applied live against `microsaas-prod` and verified with direct SQL queries.

### 3. CLAUDE.md rule additions
Appended after the existing Session Start Checklist. Honest gaps flagged inline rather than implied as done:
- SEARCH VISIBILITY LAYER rule — full SEO/AEO/GEO/SXO checklist, mandatory at launch
- SEARCH SIGNAL REQUIREMENT FOR VERDICT PASS — **noted as not yet wired**: the live research swarm's output schema doesn't include `search_signals`/`objection_signals`/`geo_signals` yet. Follow-on work.
- POST-VERDICT BUILD BRIEF GENERATION rule
- POST-$4K MONITORING AND INCIDENT RESPONSE ACTIVATION rule — points to `docs/monitoring-agent-suite.md` for the full agent prompts and Supabase table templates, explicitly deferred until a product hits the $4K/30-day gate
- CUSTOMER-FACING DOCS rule — points to `docs/customer-docs-sop-template.md`
- BRIEF_GENERATOR AGENT rule — adapted to match this repo's real trigger convention (`POST /factory/generate-brief/{opportunity_id}`, mirroring the existing `/factory/build/{id}` pattern) rather than inventing a new one

### 4. `agents/factory/brief_generator.py` — built and tested
Mirrors every convention already established in `agents/factory/build_pipeline.py`: `AGENT_ID` constant, `_emit_event`/`_write_audit` helpers, required non-optional `triggered_by`, wrapped `RuntimeError` on failure (never fails silently).

Flow: reads the opportunity from `opportunity_pipeline` → looks up the vertical's color palette from `industry_color_map` (falls back to the `open` palette if a vertical somehow isn't seeded, since the FK would otherwise reject the insert) → generates `BUILD_BRIEF_CLAUDE_CODE.md` and `BUILD_BRIEF_CLAUDE_DESIGN.md` via `core.llm_router.analyze` (Sonnet, per the model-routing rule) → pushes both to a new `brief/{product-slug}` git branch → inserts the row into `mse_build_briefs` (Realtime already enabled, so the insert itself is what notifies the dashboard — no separate broadcast step).

Wired to a new admin-gated route, `POST /factory/generate-brief/{opportunity_id}` in `api/routers/factory.py`, structured identically to the existing `trigger_build` endpoint (403 without admin role, 401 without an authenticated `triggered_by`, runs in a background task).

Test coverage (`tests/test_brief_generator.py`, `tests/test_factory_routes.py` additions): 13 new tests — happy path (branch created, both files written, correct DB insert), missing-opportunity failure, git-failure wrapping and audit logging, vertical-fallback logic, and the route's auth/HITL gating. Full suite: 94 passing.

### Dashboard: Build Briefs section
Added to the Opportunities page (`frontend/app/pipeline/page.tsx`) below the existing opportunity list — brief cards showing product name, vertical, Verdict score, and a status pill (`pending_review` → `approved` → `in_build` → `launched` → `monitoring_pending` → `monitoring_active` → `archived`), click to expand and read the Claude Code and Claude Design briefs inline (tab toggle between the two documents). `StatusBadge` component extended with the new status variants.

---

## What Was Intentionally NOT Built (by design, not oversight)

- The three per-product monitoring agents (`[slug]_monitor.py`, `[slug]_incident.py`, `[slug]_support.py`) and their Supabase tables — these only get created per-product at the $4K/30-day maturity gate. Full system prompts and table templates are saved as reference docs (`docs/monitoring-agent-suite.md`) for when that day comes.
- The customer-facing docs site itself — template saved (`docs/customer-docs-sop-template.md`), generated per-product at build time, not now.
- CEO dashboard cross-repo wiring (brief cards / monitoring cards in the R&D panel) — flagged as remaining work, not started this session; lives in the separate `kdavis-agentic-platform` repo.
- Wiring `search_signals`/`objection_signals`/`geo_signals` into the actual research swarm output — the CLAUDE.md rule exists, the schema doesn't yet.

---

## Immediate Next Step

Pick the first real opportunity out of the Opportunities tab and run it through the entire pipeline by hand — research (done) → Verdict → brief_generator → human review of the brief → `run_build_pipeline` → deploy. Nothing has gone through the full flow end-to-end yet; doing so once is the fastest way to surface any remaining gap before repeating it monthly.
