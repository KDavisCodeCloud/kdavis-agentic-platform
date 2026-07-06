# SOP: MSE Dashboard (Micro SaaS Engine)
Date: 2026-07-06
Product: Micro SaaS Engine (internal operator UI)
URL: mse.thdecodedempire.com
Repo: kdavis-microsaas-engine (parent git at /projects/)
Frontend path: kdavis-microsaas-engine/frontend/
Status: Live — UI complete, research swarm backend live

---

## Purpose

The MSE dashboard is the operator interface for the Micro SaaS Engine — the research and product factory that validates and builds micro-SaaS products. It is used by Kelvin only. It shows the research pipeline, agent roster, pipeline results, and retention loop status.

This is distinct from the CEO dashboard: MSE is focused entirely on the product factory workflow, not on business-wide operations.

---

## Git repo note

The MSE frontend lives inside `kdavis-microsaas-engine/` which is a subdirectory of the parent git repo at `/mnt/c/Users/Kelvin/projects/`. The parent repo's remote is `github.com/KDavisCodeCloud/kdavis-microsaas-engine.git`.

All git commands for MSE must be run from `/mnt/c/Users/Kelvin/projects/`, not from inside the `kdavis-microsaas-engine/` subdirectory. Running git from inside the subdirectory will fail or operate on the wrong repo.

```bash
# Correct
git -C /mnt/c/Users/Kelvin/projects/ add kdavis-microsaas-engine/frontend/...
git -C /mnt/c/Users/Kelvin/projects/ commit -m "..."
git -C /mnt/c/Users/Kelvin/projects/ push origin main

# Wrong — will fail
cd /mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine
git add .
```

---

## Auth

Same Supabase instance (microsaas-prod). Magic link login. Callback at `/auth/callback`.

---

## Layout

Same CEO Decoded design system — green accent (#6fce8f) instead of mint (#5eead4) to distinguish MSE from the CEO dashboard at a glance.

```
[60px icon rail — M brand mark] [196px sidebar] [flex main content]
```

Brand mark: "M" in a 32×32 rounded square with green background.

Sidebar nav items: Overview, Research, Pipeline, Agents, Retention.

---

## Five pages

### Overview (`/dashboard`)

High-level pipeline metrics:
- Total niches researched
- Niches in pipeline (passed validation)
- Products approved to build
- Current MRR

Cadence tracker: shows the weekly research schedule and when the next swarm run is due.

Agent event feed: live stream of recent agent activity from `agent_events` table. Shows which agent ran, what it found, verdict.

### Research Swarm (`/research`)

The fire button. This is where new product validation starts.

**How to use:**
1. Select a vertical (niche category) from the dropdown
2. Click "Fire Research Swarm"
3. Progress bar appears with elapsed timer
4. Dashboard polls `/research/session/{session_id}` every 3 seconds for status
5. When complete: results card renders with niche viability data

**What the swarm does (backend):**
- Fires 8 agents in parallel: Reddit scraper, G2 scraper, LinkedIn scraper, Quora scraper, ICP extractor, pain language extractor, competitor gap analyzer, viability scorer
- Each agent returns structured JSON
- Orchestrator aggregates results into a single research output
- Output saved to `pipeline` table in Supabase with confidence score and verdict

**Results card shows:**
- Niche name and one-sentence summary
- ICP profile (job title, company size, tools used)
- Top pain quotes (exact language from forums/reviews)
- Viability score (0-100)
- Estimated MRR range
- Verdict: PASS / FAIL / HOLD

If verdict is PASS or HOLD, a card appears in the CEO dashboard HITL queue for approval to proceed to build.

### Pipeline (`/pipeline`)

List view of all researched niches. Filter tabs:
- All
- Passed (approved to build)
- In Review (awaiting HITL decision)
- Failed (not viable)

Each row is expandable and shows:
- Niche name
- ICP summary
- MRR estimate range
- Top pain point (truncated with expand)
- Source list (Reddit subs, G2 categories, etc.)
- Confidence bar colored by competition density (green = low competition, amber = medium, red = high)
- Verdict badge

### Agents (`/agents`)

Roster of all 8 MSE research agents:

| Agent | Status | Role |
|---|---|---|
| Dispatch | ACTIVE | Orchestrates the swarm, assigns tasks to agents |
| Verdict | ACTIVE | Aggregates results, assigns viability score and verdict |
| Reddit Scraper | STUB | Scrapes relevant subreddits for pain posts |
| G2 Scraper | STUB | Pulls competitor reviews for gap analysis |
| LinkedIn Scraper | STUB | Finds ICP job titles and company pain signals |
| Quora Scraper | STUB | Extracts question patterns and pain language |
| ICP Extractor | STUB | Structures raw data into ICP profile format |
| Pain Language Extractor | STUB | Pulls exact quotes for landing page copy |

Thursday cadence schedule: shows which agents run on the weekly research cadence vs on-demand.

Architecture reference table: maps each agent to its data source, output format, and downstream consumer.

### Retention (`/retention`)

Six retention loops that run post-launch for each product:

1. Day-3 check-in — automated engagement nudge
2. Day-7 progress review — usage milestone check
3. Day-14 conversion push — trial end approaching
4. Day-30 power user identification — flag for case study
5. Day-60 expansion signal — identify upsell candidates
6. Day-90 churn prevention — re-engagement for inactive users

Each loop shows:
- Loop name and trigger
- n8n workflow status (active/inactive)
- Current count of users in this loop stage
- Last execution timestamp

n8n workflow status table: shows the live status of each automation in n8n.

Agent roster for retention: shows which agents handle the retention sequences.

---

## Backend API

The MSE dashboard talks to a FastAPI backend at `NEXT_PUBLIC_API_URL`.

Key endpoints:
- `POST /research/start` — fires the research swarm for a given vertical
- `GET /research/session/{id}` — polls for swarm progress
- `GET /pipeline` — returns all pipeline records
- `GET /agents` — returns agent roster and status

When `NEXT_PUBLIC_API_URL` is not set or the backend is down, the frontend renders empty states rather than crashing.

---

## If the dashboard breaks

- **Fire button does nothing**: check `NEXT_PUBLIC_API_URL` env var in Vercel — must point to the live FastAPI backend
- **Pipeline shows empty**: either no research sessions have been run yet, or the Supabase `pipeline` table is empty
- **Agent roster not loading**: `GET /agents` endpoint must be running — check FastAPI backend health
- **n8n workflow status all inactive**: n8n instance may be down or the webhook URLs need updating
- **Login loop**: verify `mse.thdecodedempire.com/auth/callback` is in Supabase redirect URLs
