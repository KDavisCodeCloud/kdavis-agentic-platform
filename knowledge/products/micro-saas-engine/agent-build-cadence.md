# Micro SaaS Engine — Agent Build Cadence

**Schedule:** Thursday nights, one agent per week.

---

## Rule

No agent gets built until the aggregator produces a `READY_TO_BUILD` stamp.
The aggregator runs 7 hard gates. All 7 must pass.

**7 gates:**
1. Conservative MRR potential >= $4,000
2. Niche viability score passes threshold
3. ICP clearly identified
4. Competitor gap confirmed
5. Pain language extracted (exact quotes)
6. Build time estimate < 60 days
7. No existing solution already solving this exactly

Until the stamp is issued, nothing builds. This is DB-enforced via the `opportunity_pipeline` table CHECK constraint.

---

## Build Order

### Week 1 — 2026-07-10 (Thursday)
**Build:** `agents/orchestrator/agent.py` + `agents/aggregator/agent.py`

The orchestrator coordinates the swarm. The aggregator runs the 7 gates and issues `READY_TO_BUILD` stamps.

These are the foundation. Every subsequent agent depends on these two being wired.

Also wire: `POST /research/run` → calls orchestrator → dispatches to active intel agents.

---

### Weeks 2–7 — Vertical Intel Agents

One agent per Thursday. Each agent:
- Scrapes its vertical (Reddit, G2, LinkedIn, Quora)
- Extracts: pain language, ICP, tools, competitor gaps, MRR estimates
- Returns structured JSON to the aggregator
- Has its own `agents/{vertical}-intel/prompt.md` in version control

| Week | Date | Vertical | Files |
|---|---|---|---|
| 2 | 2026-07-17 | Healthcare | `agents/healthcare-intel/agent.py`, `prompt.md` |
| 3 | 2026-07-24 | Legal | `agents/legal-intel/agent.py`, `prompt.md` |
| 4 | 2026-07-31 | E-commerce | `agents/ecommerce-intel/agent.py`, `prompt.md` |
| 5 | 2026-08-07 | Real Estate | `agents/realestate-intel/agent.py`, `prompt.md` |
| 6 | 2026-08-14 | HR/Ops | `agents/hr-ops-intel/agent.py`, `prompt.md` |
| 7 | 2026-08-21 | Finance | `agents/finance-intel/agent.py`, `prompt.md` |

---

### Week 8 — 2026-08-28 (Thursday)
**Build:** Full swarm end-to-end test

Run all 6 intel agents in parallel. Feed output into aggregator. Confirm:
- All agents return valid JSON matching schema
- Aggregator gates evaluate correctly
- `READY_TO_BUILD` stamps issue only when all 7 gates pass
- `opportunity_pipeline` rows insert correctly
- MRR floor CHECK constraint blocks any row below $4,000 that isn't `status = 'rejected'`

---

## LLM Routing for Agents

- **Intel agents (scraping/high volume):** Haiku — cheap, fast
- **Aggregator/orchestrator (analysis):** Sonnet — quality matters here
- **DataSanitizationShield runs before every LLM call** — no exceptions

---

## Prompt Files

Every agent prompt lives in version control at `agents/{name}/prompt.md`.
No prompt exists only in code. No inline system prompts without a file.

When a prompt changes:
1. Update the file
2. Commit with: `feat(agents/{name}): update prompt — [reason]`
3. The commit IS the version history

---

## Post-Build Checklist (every Thursday session)

- [ ] Agent extends `base_agent.py` lifecycle
- [ ] `DataSanitizationShield` called before every LLM call
- [ ] Prompt in `agents/{name}/prompt.md`
- [ ] Router uses Haiku for scraping, Sonnet for analysis
- [ ] Output JSON matches schema in `docs/data-dictionary.md`
- [ ] Agent registered in `api/main.py` or called by orchestrator
- [ ] Commit pushed to `main`
