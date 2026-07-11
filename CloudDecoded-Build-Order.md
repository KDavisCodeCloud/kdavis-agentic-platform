# Cloud Decoded — Build Order
**Project:** `theclouddecoded.com`
**Company:** THD Agentic Systems LLC
**Last updated:** 2026-07-04
**Status:** Landing page complete — auth + Stripe next

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
- MCP server live at `mcp.theclouddecoded.com` (OAuth 2.1/PKCE primary, workspace API keys fallback, 7 tools) ✅
- All 10 agents built ✅
- SOC 2 readiness architecture in place (per-tenant pgvector + RLS, DataSanitizationShield, HITL audit log, access controls, incident response, data retention policy) ✅

---

## Build Order — Remaining

### Priority 1 — Unblocks everything else

**Auth pages: `/signup` + `/login`**
- Wire to Supabase Auth
- On signup: create tenant row, provision per-tenant pgvector schema, set RLS policies keyed to `tenant_id`
- On login: issue JWT with `tenant_id` claim
- Redirect to `/dashboard` after auth
- This unblocks: Features page, Comparison page, Security page, Docs, all CTAs

**Stripe billing**
- Webhook handler: `subscription.created` → activate tenant, `subscription.updated` → update plan tier, `subscription.deleted` → mark churned, `invoice.payment_failed` → log + trigger re-engagement
- Tie plan tier to agent access (Starter: 5 agents, Growth: all 10, Enterprise: custom)
- 14-day trial: provision full access, set trial expiry, send conversion email at day 11

---

### Priority 2 — After auth is live

**og:image**
- 1200×630 PNG
- Wordmark + tagline: "Your 2am incident, already triaged."
- Eyebrow label on design system background
- Export and add to landing page meta

**Features page**
- All 10 agent workflows with console UI previews
- CTAs point to `/signup`
- Matches locked design system

**10-problems AEO page**
- One H2 per problem
- One citable, specific claim per section
- Structured for LLM answer extraction (answers questions like "what does Cloud Decoded do")

**Comparison page**
- Cloud Decoded vs Microsoft Copilot vs AWS AgentCore
- No lock-in angle is the lead
- Factual, specific, no puffery

**Security page**
- SOC 2 readiness posture (not attestation — readiness)
- Per-tenant RLS architecture
- HITL audit trail
- Data retention and deletion policy summary
- "Security questionnaire available on request" CTA

---

### Priority 3 — After first client is close

**Docs**
- Setup guide (written — no video)
- How-to per agent workflow (written — no video)
- Agent reference (what each agent does, what it touches, what it requires approval for)
- Video reserved for sales demo page only

**Loom demo**
- 2-minute template: Hook (0:00–0:15, "2am production incident" narrative) → Solution in action (0:15–1:30) → Outcome + CTA (1:30–2:00)
- Record after infrastructure is stood up
- CI/CD failure triage is the first proof-of-concept scenario

**Security questionnaire response doc**
- Required to unblock mid-market deals before formal SOC 2 attestation
- DPA template (shared with MSE legal)

---

## Dashboard Architecture

Two views, one shell at `theclouddecoded.com/dashboard`:

**Tenant view (client):** Approval queue (HITL), agent activity feed (Realtime, scoped to `tenant_id`), metrics (hours saved, incidents triaged), audit trail, workspace settings, autonomy threshold sliders

**Operator view (Kelvin):** All tenants table, cross-tenant HITL monitor, revenue feed (Stripe webhooks), agent health across all tenants, SOC 2 readiness checklist, exit tracker

Real-time update flow: Agent runs → `POST /events` (with `tenant_id`) → inserts to `agent_events` → Supabase CDC fires → Realtime pushes to per-tenant WebSocket channel → widget re-renders. Zero manual SQL.

Batch review: Similar pending actions grouped by `pattern_hash` (same agent + action type + environment). Approve once, apply to all matching. Required before 27 clients to prevent HITL bottleneck.

---

## Agent Roster (All 10 Built)

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

---

## Key Constraints (Do Not Violate)

- Funnel is no-sales-call: sole primary CTA is "Start free trial" — "Book a demo" is removed
- HITL gate is non-negotiable: high blast-radius actions always require human approval regardless of tenant autonomy settings
- Per-tenant Supabase pgvector with RLS keyed to `tenant_id` — no cross-tenant data leakage
- DataSanitizationShield runs before any client data is embedded
- Tiered autonomy: low-risk previously-approved actions can auto-execute within guardrails; novel/high-blast-radius always HITL
- X/Twitter account suspended — DM channel dormant until compliance ticket resolves
- SOC 2 readiness baked in from the start — not retrofitted later
