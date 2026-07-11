# Compass Decoded — Vision & ICP Research Brief
**Product:** Compass Decoded (name TBD — also considering Blueprint Decoded, Horizon Decoded)
**Company:** THD Agentic Systems LLC
**Last updated:** 2026-07-04
**Status:** Internal only — ICP undefined. Research agent must run before any product decisions are locked.

---

## What This Is (Current Working Definition)

A personal life OS. You plug in your data across life dimensions — income, expenses, family, goals, health, personal values — and map short, mid, and long-term goals. A team of agents does live market research (cost of living, investment benchmarks, career comp data, education costs, housing markets) and surfaces feedback and path suggestions calibrated to your actual situation. The conversational layer (Claude/Anthropic API) lets you talk into it, reason through decisions, and have the dashboard adjust your life plan accordingly.

Faith-based content (devotionals, prayer journaling, reflection prompts aligned to stated values) is a configurable module — not the lead, not the default. A user opts into it if it's relevant to their life.

**This is not a budgeting app. Not a goal tracker. Not a devotional app. It's the combination of all three with an active agent layer keeping the plan current as life changes.**

---

## What Is NOT Locked Yet

- ICP — who exactly pays for this is a research question, not an assumption
- Product name — Compass Decoded is working title
- Pricing — $29–$79/mo range is a hypothesis, not a decision
- Data ingestion model — manual entry vs Plaid integration vs CSV import (this changes the entire data model)
- Feature priority — nothing gets built until ICP is defined

---

## ICP Research Brief — For Research Agent

### The Research Question
Who is already paying for multiple tools to manage their personal goals, finances, and life direction — and what do they hate about the current experience?

### Signals to Look For
- People paying simultaneously for: a financial planning app (YNAB, Mint, Monarch Money), a life coaching subscription or app, and a goal-tracking tool (Notion, Todoist, custom)
- People who have searched for: "personal life OS," "goal tracking with AI," "financial freedom planning tool," "legacy planning," "how to plan generational wealth"
- Communities where this person lives: r/financialindependence, r/FIRE, r/personalfinance, LinkedIn creator/solopreneur communities, faith-and-finance communities, Black wealth-building communities, first-gen wealth communities
- Price tolerance signals: what do they currently pay for coaching, planning tools, and apps combined

### Dimensions to Research
1. **Demographics** — age range, income range, family status, geographic concentration
2. **Psychographics** — what motivates them (freedom, legacy, family, faith, achievement)
3. **Current tool stack** — what they use now and what they hate about it
4. **Jobs to be done** — what outcome are they actually trying to reach
5. **Willingness to pay** — what price point do comparable tools charge, what do they consider fair
6. **Faith dimension** — what % of the potential ICP has faith as a meaningful life dimension, and would they pay more for a product that integrates it vs a secular alternative

### Hypothesis to Test
The ICP is not defined by faith. The ICP is defined by: having multiple life goals across multiple dimensions simultaneously (financial, family, career, health, legacy) and currently managing them in disconnected tools with no unified view or agent layer keeping the plan current.

Faith, fitness, family, finance — these are modules. The ICP is the person who needs the OS, regardless of which modules they activate.

### Deliverable
- Defined ICP: demographics, psychographics, jobs to be done, price tolerance
- Top 3 ICP segments ranked by market size and willingness to pay
- Competitive landscape: what exists, what it costs, where the gap is
- Recommended product name (Compass Decoded vs alternatives) based on ICP resonance
- Recommended lead positioning (what problem does the hero section solve in one sentence)

---

## v1 Feature Set (Kelvin's internal version — built before ICP research returns)

This is what gets built for internal use at THD. ICP research may add, remove, or reframe before any external marketing.

### Goal mapping
- Short-term (0–12 months), mid-term (1–3 years), long-term/legacy (3–10+ years)
- Per-dimension: financial, career, family, health, personal growth, faith (optional module)
- Progress tracking against each goal with agent-sourced context

### Financial layer
- Income tracking (manual entry + future: Plaid integration)
- Expense categories
- Operating stack cost tracking (shared with CEO dashboard)
- Self-funding milestone projections
- Exit model ($15M target, $2.5M ARR × 6× multiple)

### Agent market research layer
- Cost of living benchmarks (Phoenix, AZ as default — user-configurable)
- Career compensation ranges for target roles ($170K+ AI Platform/Infra)
- Investment benchmark data
- Housing/real estate signals if relevant to goals
- Updates on a cadence (weekly digest) — not real-time

### Conversational layer
- Claude/Anthropic API chat interface
- Context: user's current goal state, financial snapshot, recent agent research
- Use cases: "Should I take this job offer?", "How does this expense affect my timeline?", "What should I prioritize this month?"

### Faith module (opt-in)
- Daily devotional (user selects source or tradition)
- Weekly reflection prompt tied to stated values and current goals
- Decision alignment check: does this week's activity match the long-view mission

### Family layer
- Wife co-operator view (scoped to family financials, shared goals, son's milestones)
- Son build session log (generational record)
- Family financial milestones

---

## Data Model Design Constraint

**Plaid vs manual entry decision must be made before schema is built.** This is the most important architectural decision for Compass Decoded. Plaid connects to bank/investment accounts and pulls live data — high value, higher complexity, requires Plaid API credentials and compliance review. Manual entry is low friction to build, high friction to maintain for users. CSV import is the middle path. Recommendation: manual entry for internal v1, design schema to accept Plaid data in future without migration.

---

## Build Order

### Not started until:
1. ICP research agent returns findings
2. Product name confirmed
3. Data ingestion model decided (manual vs Plaid vs CSV)

### Internal v1 sequence (after above gates):
1. Schema design (goals table, dimensions table, milestones table, reflections table, son_sessions table)
2. Goal input UI — short/mid/long-term per dimension
3. Financial snapshot (manual entry)
4. Agent market research — weekly digest workflow via n8n
5. Conversational layer — Claude API chat wired to user context
6. Faith module (opt-in config)
7. Wife co-operator scoped view
8. Son build session log

### Not built for internal v1:
- Plaid integration
- Multi-user (only Kelvin + wife as co-operator)
- Subscription billing (internal use only)
