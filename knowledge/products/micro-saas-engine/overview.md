# Micro SaaS Engine — Overview

**Status:** Building  
**Progress:** 45%  
**Last updated:** 2026-07-03  
**Repo:** `github.com/KDavisCodeCloud/kdavis-microsaas-engine`  
**Local path:** `/mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine`  
**Supabase project:** `microsaas-prod` (ref: `gjezchcoyytxcpsbvkrg`)  
**Stripe account:** Micro Saas Decoded (`acct_1TpLcKLIpoJRr7Tc`) — live mode

---

## What It Is

A research-validated, retention-first software factory. Not a single product — a repeatable system for validating, building, launching, and scaling micro SaaS tools.

**$4,000 MRR floor** enforced at DB level (CHECK constraint) and by the aggregator agent's 7 gates. No product enters development without hitting this bar.

---

## Non-Negotiable Rules (CLAUDE.md)

1. Retention scaffold ships before any feature work
2. Infrastructure isolation — dedicated Supabase + Stripe per product
3. RLS on every table
4. Research agent gates every build (READY_TO_BUILD required)
5. $4K MRR floor is hard — enforced in DB and agent logic
6. Agent prompts live in version control (`/agents/{name}/prompt.md`)
7. MCP endpoint ships with every product from day one
8. Stripe is per product — never shared
9. Weekly digest is behavioral, never marketing
10. Exit readiness is always on — data dictionary + ADRs updated every commit

---

## Infrastructure — All Live

| Service | Detail |
|---|---|
| Supabase | `microsaas-prod` — 6 tables + RLS — CLI linked |
| FastAPI | 12 routes — port 8000 — JWT auth via Supabase |
| Next.js 15 | 4 routes — UsageTracker in root layout |
| n8n 2.28.6 | Port 5678 — 2 workflows imported — needs credential setup |
| Stripe | Micro Saas Decoded — live mode — webhook handler not yet built |
| GitHub | `KDavisCodeCloud/kdavis-microsaas-engine` — main branch |

---

## Database Tables (microsaas-prod)

| Table | Purpose |
|---|---|
| `tenants` | Subscribers — tier, Stripe IDs, status |
| `usage_events` | Every product interaction — retention heartbeat |
| `milestones` | Threshold achievements per tenant |
| `retention_sequences` | Active re-engagement sequences |
| `weekly_digest_log` | Digest send history + skip log |
| `opportunity_pipeline` | Research agent output — $4K MRR floor enforced |

---

## .env Status

| Variable | Status |
|---|---|
| `SUPABASE_URL` | Filled |
| `SUPABASE_SERVICE_KEY` | Filled |
| `SUPABASE_JWT_SECRET` | Filled |
| `STRIPE_SECRET_KEY` | Filled (sk_live_...) |
| `ANTHROPIC_API_KEY` | **MISSING** — console.anthropic.com |
| `RESEND_API_KEY` | **MISSING** — resend.com |
| `STRIPE_WEBHOOK_SECRET` | Pending — fill after webhook endpoint built |

---

## Open Gaps

| Gap | Owner | Priority |
|---|---|---|
| Fill `ANTHROPIC_API_KEY` in `.env` | Kelvin | High |
| Fill `RESEND_API_KEY` in `.env` | Kelvin | High |
| n8n first-run setup + credential + activate workflows | Kelvin | High |
| `api/routers/stripe.py` — webhook handler | Claude | High |
| `core/supabase_client.py` — RLS per-request fix | Claude | High |
| `legal/` — EULA, privacy policy, DPA | Claude | Mid |
| All `agent.py` files | Claude (Thursday cadence) | High |

See [[sprint-log]] for full task board.
