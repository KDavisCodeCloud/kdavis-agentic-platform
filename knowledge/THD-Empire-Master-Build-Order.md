# THD Agentic Systems — Master Build Order
**Company:** THD Agentic Systems LLC
**Last updated:** 2026-07-04
**Owner:** Kelvin Davis (King Kelz)
**Purpose:** Single source of truth for what gets built next across all products. No phases, no timelines — just ordered execution. Do the next thing on the list.

---

## The Rule

Work the list top to bottom. Don't jump ahead. Don't work two items from different products simultaneously unless they're explicitly marked as parallel. When an item is done, mark it ✅ and move to the next one.

---

## Right Now — This Session (Saturday 2026-07-04)

These three run in the same Claude Code session. All are MSE. All are Claude Code tasks.

- [ ] GAP 4 — `api/routers/stripe.py` — webhook handler for MSE (subscription.created/updated/deleted, invoice.payment_failed, signature verify, writes to tenants table)
- [ ] GAP 11 — `core/supabase_client.py` — refactor to `get_supabase_admin()` + `get_supabase_for_request(jwt)`, RLS enforced per user
- [ ] GAP 12 — `legal/EULA.md` + `legal/privacy-policy.md` + `legal/dpa-template.md`

**Before Claude Code session — Kelvin manual (must be done first):**
- [ ] Fill `ANTHROPIC_API_KEY` in MSE `.env`
- [ ] Fill `RESEND_API_KEY` in MSE `.env`
- [ ] n8n first-run setup at http://localhost:5678
- [ ] n8n: add Supabase credential (`microsaas-supabase`)
- [ ] n8n: update RESEND_API_KEY in `n8n/start-n8n.sh`, activate both workflows

---

## Next — After Today's Session

### Cloud Decoded auth (Saturday sprint or next available session)
- [ ] `/signup` page — wired to Supabase Auth, creates tenant row, provisions RLS, issues JWT with `tenant_id`
- [ ] `/login` page — wired to Supabase Auth, redirects to `/dashboard`
- [ ] Tenant dashboard shell — real-time Supabase Realtime subscription on `agent_events` channel

### Cloud Decoded og:image
- [ ] 1200×630 PNG export — wordmark + "Your 2am incident, already triaged." + design system bg

---

## Thursday 2026-07-10 — Agent Build Night

- [ ] GAP 13 Week 1: `agents/orchestrator/agent.py` — LangGraph orchestrator, emits POST /events on every state change
- [ ] GAP 13 Week 1: `agents/aggregator/agent.py` — quality gate, validates research output before acceptance
- [ ] Wire `/research/run` endpoint

---

## After GAP 13 Week 1 Is Stable

### Cloud Decoded pages (all depend on /signup + /login being live)
- [ ] Features page — all 10 agent workflows, console UI previews, CTAs → /signup
- [ ] 10-problems AEO page — one H2 per problem, one citable claim per section
- [ ] Comparison page — Cloud Decoded vs Copilot vs AgentCore, no lock-in lead
- [ ] Security page — SOC 2 readiness, per-tenant RLS, HITL audit trail

### MSE agent cadence (one per Thursday)
- [ ] Week 2: Market sizing agent
- [ ] Week 3: Competitor signal agent
- [ ] Week 4: ICP research agent (also runs Compass Decoded ICP research in parallel)
- [ ] Week 5: Retention pattern agent
- [ ] Week 6: Pricing signal agent
- [ ] Week 7: Distribution channel agent
- [ ] Week 8: Full swarm test + end-to-end research run

---

## After MSE Full Swarm Is Live

### First MSE product ships
- [ ] Research swarm identifies first vertical
- [ ] Product built on MSE retention scaffold (6 retention loops before feature work)
- [ ] Stripe billing live on dedicated MSE account
- [ ] Hard $4K MRR floor enforced at DB constraint level
- [ ] Launch

### Video marketing department (after stack is self-funded ~6 MSE clients)
- [ ] HeyGen account setup — record base avatar video (2–5 min)
- [ ] ElevenLabs voice clone — record 1–2 min voice sample
- [ ] Script agent — generates video scripts from content calendar or LinkedIn posts
- [ ] Distribution agent — posts to IG Reels, YouTube Shorts, TikTok after approval
- [ ] Wife approval gate — script reviewed before render, render reviewed before publish
- [ ] First Cloud Decoded demo video using 2-minute template

### Cloud Decoded docs + demo
- [ ] Docs — setup guide, how-to per agent, agent reference (written only)
- [ ] Loom demo — CI/CD failure triage scenario, 2-minute template
- [ ] Security questionnaire response doc
- [ ] DPA template

---

## After Cloud Decoded Has First Trial Converting

### CEO Decoded internal v1
- [ ] Architecture session: permission model + approval chain design (on paper before code)
- [ ] Schema: `team_members`, `roles`, `permissions`, `proposals`, `approval_queue`
- [ ] Department shell: Finance, Marketing, Operations, Technology
- [ ] Human team onboarding flow (name, dept, role, permissions, HITL touchpoints)
- [ ] All-product snapshot widget (reads `agent_events` across all product Supabase projects)
- [ ] Operating stack cost widget (live cost vs MRR, self-funding gap, projection)
- [ ] Remaining departments: R&D, HR, Legal, Advisory, Video/Creative
- [ ] Advisor agent architecture session (persistent memory layer — separate design before build)

### Compass Decoded internal v1
- [ ] ICP research agent returns findings (Week 4 of MSE agent cadence)
- [ ] ICP and product name confirmed
- [ ] Data ingestion decision: manual entry v1, schema supports Plaid future
- [ ] Schema: `goals`, `dimensions`, `milestones`, `reflections`, `son_sessions`
- [ ] Goal input UI (short/mid/long-term per dimension)
- [ ] Financial snapshot (manual entry)
- [ ] Agent market research weekly digest
- [ ] Conversational layer (Claude API chat with user context)
- [ ] Faith module (opt-in)
- [ ] Wife co-operator scoped view

---

## Ongoing — Every Week

| Day | Focus | Products |
|-----|-------|---------|
| Monday | Cloud Decoded + career | Cloud Decoded, portfolio projects |
| Tuesday | GTA 6 Hub + son build session | GTA 6 Hub (DecodedSix), son apprenticeship |
| Wednesday | Planning + internal dashboard | Empire overview, build order updates |
| Thursday | Agent build night | MSE agent cadence (rotating one agent/week) |
| Saturday | Major sprint | Current priority item from this list |
| Sunday | Rest — protected | Nothing |

---

## Parking Lot — Real But Not Next

These are real items that will get done. They are not next. Do not start them until the items above are complete.

- GTA 6 Hub (DecodedSix) — targeting November 2026 GTA 6 launch window
- CEO Decoded subscription model + marketing (after 6+ months internal use and iteration)
- Compass Decoded subscription model + marketing (after ICP is confirmed + internal use)
- Plaid integration for Compass Decoded
- Docker packaging for CEO Decoded resale
- MCP server for CEO Decoded department agents
- Hustle Decoded — parallel brand, not primary focus until Cloud Decoded has revenue traction
- White-label option for CEO Decoded and Compass Decoded

---

## Files That Feed Into This

| File | What It Covers |
|------|---------------|
| `MSE-Build-Order.md` | Full MSE GAP list, agent cadence, architecture reference |
| `CloudDecoded-Build-Order.md` | Cloud Decoded remaining build items, dashboard architecture, agent roster |
| `CEODecoded-Vision-And-Build.md` | CEO Decoded department roster, human team layer, permission model, build sequence |
| `CompassDecoded-Vision-And-ICP-Research.md` | Compass Decoded vision, ICP research brief, v1 feature set |
| `Empire-Operating-Stack.md` | Monthly tool costs, funding milestones, CEO dashboard integration requirements |
| `THD-Empire-Master-Build-Order.md` | This file — master ordered list |
