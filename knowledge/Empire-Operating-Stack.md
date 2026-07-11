# THD Agentic Systems — Operating Stack & Funding Tracker
**Company:** THD Agentic Systems LLC
**Last updated:** 2026-07-04
**Purpose:** Live cost tracking for CEO dashboard — every tool, every dollar, every funding milestone

---

## Monthly Operating Stack

| Tool | Category | Cost/mo | Purpose | Funded at |
|------|----------|---------|---------|-----------|
| Supabase | Infra | ~$25 | DB, auth, realtime, storage — all products | MSE client 1 |
| Vercel | Infra | ~$20 | Frontend hosting — all products | MSE client 1 |
| n8n (self-hosted VPS) | Infra | ~$10 | Workflow automation | MSE client 1 |
| Anthropic API | AI | ~$30–60 | Agent inference (Haiku + Sonnet routing) | MSE client 2 |
| Videomule | Media | $29 | Demo video production (~2/mo, 2min cap) | MSE client 2 |
| Resend | Infra | ~$0–20 | Transactional email | Free tier initially |
| ElevenLabs | Media | $22 | Voice clone for AI avatar videos | MSE client 3 |
| HeyGen | Media | $29–89 | AI avatar video production | MSE client 3–4 |
| **Total** | | **~$165–255/mo** | Full operating stack | **3–4 MSE clients** |

---

## Self-Funding Milestones

| MSE Clients | Est. MRR (blended $39 avg) | Stack Coverage | Status |
|-------------|---------------------------|----------------|--------|
| 0 | $0 | 0% | Now |
| 2 | ~$78 | Infra partially covered | Target |
| 4 | ~$156 | Infra + AI covered | Target |
| 6 | ~$234 | Full stack self-funded | Gate |
| 10 | ~$390 | $130+/mo surplus → reinvest in media | Growth |

**Gate: Full stack self-funded at ~6 MSE clients.** Every dollar after that is margin or reinvestment.

---

## Revenue Targets

| Milestone | What It Unlocks |
|-----------|-----------------|
| First MSE dollar | Proof of concept. Stack partially covered. |
| Stack self-funded (6 MSE clients) | HeyGen + ElevenLabs added. Avatar content starts. |
| Cloud Decoded first client ($299+) | B2B revenue layer begins. Faster MRR growth. |
| $15K MRR × 3 consecutive months | Kelvin exits CorVel. Full-time on empire. |
| $15M exit ($2.5M ARR × 6× multiple) | Generational wealth. PE/MSP acquirer target. |

---

## Products Under THD Agentic Systems

| Product | Status | MRR | Primary Agent |
|---------|--------|-----|---------------|
| Micro SaaS Engine | Building — active | $0 | Research swarm |
| Cloud Decoded | Building — active | $0 | 10 DevOps agents |
| GTA 6 Hub (DecodedSix) | Planned — Nov 2026 launch window | $0 | TBD |
| CEO Decoded | Internal only — not marketed | $0 | Dept agents |
| Compass Decoded | Internal only — ICP research pending | $0 | Life OS agents |
| Hustle Decoded | Parallel — not primary focus | $0 | Content agents |

---

## Shared Infrastructure (~80% complete from Cloud Decoded build)

- Supabase (multi-tenant, per-product projects)
- Next.js 14 (per-product frontends)
- Vercel (hosting)
- FastAPI (shared API layer)
- LangGraph (agent orchestration)
- n8n (self-hosted, workflow automation)
- Domain architecture: product subdomains off one umbrella, wildcard SSL

**Architecture rule:** Every new product gets its own Supabase project. `tenant_id` on every table from day one — even internal-only products. Multi-tenancy is not retrofitted.

---

## CEO Dashboard Integration Requirements

This file feeds the CEO Decoded dashboard operating cost widget. The widget must show:

1. **Live stack cost** — total monthly spend, updated when any tool is added/removed/changed
2. **Current MRR** — pulled from Stripe webhooks across all products
3. **Self-funding gap** — (stack cost) minus (current MRR) — the most important number until it hits zero
4. **Self-funding date projection** — based on MSE client growth rate, when does stack cost get covered
5. **Per-tool line items** — category, cost, purpose, which MSE milestone funds it

When a new subscription tool is added, it goes in this file immediately and reflects in the dashboard within one agent cycle.
