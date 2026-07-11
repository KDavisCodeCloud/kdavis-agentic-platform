# CEO Decoded — Vision & Internal Build Plan
**Product:** CEO Decoded
**Company:** THD Agentic Systems LLC
**Last updated:** 2026-07-04
**Status:** Internal only — not marketed. Built for THD first. Sellable eventually.

---

## What This Is

A full agentic executive suite for solopreneurs and small business owners. Not a generic dashboard — an opinionated system with fixed department structure and configurable agents within those departments. Built internally for THD Agentic Systems first. Every iteration running on a real business is proof that makes it sellable later.

**Market position (future):** Replaces fractional CFO ($1–3K/mo), fractional CMO ($2–5K/mo), and legal retainer ($500–2K/mo) for solopreneurs at $99–$499/mo. At $499 it's 90% cheaper than the human equivalent.

**Customization philosophy:** Opinionated defaults, not a blank canvas. Department names are fixed. Agent archetypes are fixed. What's configurable: which departments are active, which agents are enabled within a department, what the agent's focus areas are, what human team members own. No infinite customization — too much engineering, no ROI.

---

## Department Roster

Every department has an agent roster displayed as a team org chart. Active agents, queued agents, and gap indicators (agent that should exist but doesn't yet → adds to build queue).

| Department | Primary Function | Key Agents |
|------------|-----------------|------------|
| Finance | Revenue, burn, runway, MRR across all products, scenario modeling | Revenue tracker, cash flow monitor, expense categorizer |
| Marketing & Sales | Outreach pipelines, content strategy, lead gen, conversion tracking | LinkedIn content agent, cold email agent, conversion tracker |
| R&D | Market intelligence, competitor monitoring, product gap analysis | MSE research swarm lives here |
| HR | Human team roster, permission scoping, role management, HITL routing | Onboarding agent, permission manager |
| Technology | Infrastructure health, uptime, costs, agent health, build queue | Infra monitor, cost optimizer, agent health checker |
| Legal | Business legal Q&A (with attorney caveat on every response) | Contract review agent, entity advisor, IP flagging agent |
| Operations | Cross-product ops, build queue, weekly rhythm, GAP tracker | Build order agent, sprint tracker |
| Advisory | Strategic counsel from configured archetypes (CFO, CMO, CTO) | Advisor agents with persistent memory layer |
| Video/Creative | AI avatar marketing pipeline, script → render → distribute | Script agent, HeyGen render agent, distribution agent |

---

## Advisor Agents — Architecture Notes

Advisors are different from department agents. A department agent executes tasks. An advisor agent thinks alongside you over time.

Requirements:
- Persistent memory layer — remembers decisions, context, and reasoning across sessions
- Structured context window strategy — long-term memory + recent session summary + current query
- Configurable archetype at setup (CFO-style, CMO-style, CTO-style, legal-style)
- Knowledge base configuration — what documents, financials, and product context does this advisor have access to
- Separate from HITL queue — advisor output is counsel, not an action requiring approval

**This is a dedicated architecture session before build.** Do not build advisor agents using the same pattern as department agents.

---

## Human Team Layer

### Current Team
| Name | Role | Department | HITL Touchpoints |
|------|------|------------|-----------------|
| Kelvin Davis | CEO / Architect | All | Final approval on all proposals from any team member |
| Wife | Co-Operator | Marketing & Sales, HR, Operations | Outreach approval, content approval, spend awareness |
| Son | Apprentice Builder | Technology | Tuesday build sessions logged; no approval authority yet |

### Onboarding Flow (Interactive)
When a human is added:
1. Name + contact
2. Department assignment
3. Role definition (what they own, what they can propose, what they can approve)
4. Permission scope selection (department-only view, read-only on other departments, no CEO-level data)
5. HITL touchpoints defined (what agent actions route to them for approval)
6. Proposal routing: any change they propose (new agent, new rule, new task) routes up the chain for approval before entering master system

### Permission Levels
- **CEO** — full access, all departments, all products, all data
- **Department Head** — full access to their department, read-only snapshot of others, can approve team member proposals
- **Department Member** — their department view only, can propose changes, cannot approve own proposals
- **Contractor** — scoped to specific project or task, time-limited access

### Approval Chain
Department member proposes → Department head reviews → CEO approves → enters master system. No proposal from below bypasses the chain. This is the internal HITL governance model applied to humans, not just agents.

---

## All-Product Live Snapshot

CEO Decoded shows a live snapshot of every product under THD Agentic Systems. Each card shows:
- Product name + status
- Current MRR
- Active agents (count + health)
- Open items / build queue
- Last agent activity timestamp
- Drill-down link → that product's dedicated dashboard

Real-time feed pulls from `agent_events` table across all product Supabase projects. Supabase Realtime CDC → CEO dashboard WebSocket → widget updates. No manual refresh.

---

## Build Order (Internal)

### Phase 1 — After Cloud Decoded auth is live (Q3 2026)
- Core department shell (Finance, Marketing, Operations, Technology)
- Human team roster table (`team_members`, `roles`, `permissions`)
- Interactive onboarding flow for new team members
- Permission scoping — department-only views enforced by RLS
- All-product snapshot widget pulling from `agent_events` across all projects
- Operating stack cost widget (feeds from `Empire-Operating-Stack.md` data)

### Phase 2 — After Phase 1 is stable (Q4 2026)
- Remaining departments (R&D, HR, Legal, Advisory, Video/Creative)
- Advisor agent architecture — persistent memory layer design session first
- Proposal → approval routing for human team members
- Cross-product HITL monitor (all pending agent actions across all products)

### Phase 3 — After 6+ months internal use (2027)
- Iterations from real usage incorporated
- Multi-tenancy confirmed (tenant_id on everything from day one, so this is architecture not rebuild)
- Packaging assessment — Docker for resale? MCP server for CEO dept agents?
- Subscription model design if selling

---

## Architecture Rules

- Same shared stack as all THD products: Supabase, FastAPI, LangGraph, Next.js, Vercel, n8n
- CEO Decoded likely needs its own MCP server — different tool set from Cloud Decoded's DevOps agents
- `tenant_id` on every table from day one — even though only THD uses it internally now
- Dockerization trigger: multi-service orchestration complexity, cloud deployment target, or packaging for resale — not before a concrete reason
- No cross-product data leakage — each product's Supabase project is isolated; CEO dashboard reads via API, not direct DB connection

---

## What This Is Not

- Not a replacement for Cloud Decoded (that's a DevOps automation product for platform engineering teams)
- Not a personal life OS (that's Compass Decoded)
- Not marketed yet — internal iterations need to prove it works before it's sold
- Not infinitely customizable — fixed department structure, configurable within departments only
