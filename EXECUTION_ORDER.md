# EXECUTION ORDER
# KDavis Agentic Platform — Claude Code vs Claude Design schedule
# Read this before starting any build session.

---

## THE RULE

Claude Code builds logic, data, and structure.
Claude Design builds visual systems, component appearance, and landing pages.
They are never blocked by each other if you sequence them correctly.
Run them in parallel where possible. Never wait on one to start the other.

---

## WEEK-BY-WEEK SCHEDULE

---

### WEEK 1 — Foundation only. Claude Code exclusively.

No design work this week. Zero.
The foundation must exist before any design system can reference real data.

Claude Code sessions:
- Session 1 (Day 1-2): Scaffold folder structure + providers layer
  Steps 1–4 from CLAUDE.md build sequence
  Goal: LLM router works, can call DeepSeek and Claude, returns completions

- Session 2 (Day 2-3): Core engine + HITL + assertion + token breaker
  Steps 5–8
  Goal: A state machine that can pause, serialize state, and resume from Supabase

- Session 3 (Day 3-4): Security layer
  Steps 9–11
  Goal: Sanitizer, tenant isolation, audit log all tested and green

- Session 4 (Day 4-5): Supabase schema + Stripe setup + Git dual remote
  Steps 12–14
  Goal: Database live, Stripe catalog created, both remotes configured

- Session 5 (Day 5): CI/CD pipeline
  Steps 15–17
  Goal: Push to main triggers test → build → deploy automatically

End of Week 1 checkpoint:
✓ LLM router calls work
✓ State machine serializes and resumes
✓ Security layer passes tests
✓ Supabase schema live with RLS
✓ GitHub push mirrors to Gitea
✓ deploy.yml runs green on a test push

---

### WEEK 2 — Internal agents. Claude Code + Claude Design start in parallel.

Claude Code: internal agents (sessions 6–9)
Claude Design: dashboard design system (runs simultaneously, different tool)

CLAUDE CODE (Week 2):
- Session 6 (Day 1-2): base_agent.py + research_agent.py
  Steps 18–19
  Goal: Research agent can scrape a niche and produce a structured JSON brief
  Test: run it against one real niche (your choice), review the output

- Session 7 (Day 2-3): content_agent.py + sop_agent.py
  Steps 20–21
  Goal: Content agent takes a research brief and produces a full content package
  SOP agent fires automatically on any agent completion

- Session 8 (Day 3-4): gap_detector_agent.py + portfolio_monitor.py
  Steps 22–23

- Session 9 (Day 4-5): chat_router_agent.py + release_notes_agent.py
  Steps 24–25

- Session 10 (Day 5 morning): code_quality_agent.py + code-quality-gate.yml
  Step 26 — build the agent, wire the CI gate, run first sweep

- Session 10 (Day 5 afternoon): Lead capture infrastructure
  Build in this order:
  1. leads/capture/pixel.js — visitor tracking, anonymous sessions only
  2. leads/capture/signup_handler.py — processes /signup/[product] forms
  3. leads/capture/trial_handler.py — processes trial starts
  4. leads/integrations/systeme_io.py — Systeme.io API wrapper
  5. leads/integrations/webhook_receiver.py — receives Systeme.io webhooks
  6. Supabase tables: leads, visitor_sessions, email_sequences,
     email_sequence_steps (add to schema, apply RLS)
  7. email_sequence_agent.py — drafts nurture sequences for HITL approval
  8. visitor_capture_agent.py — enriches leads, scores, routes high-intent

- Session 11 (start of Week 3, before dashboard work):
  GitHub Actions visibility setup:
  1. Write .github/workflows/WORKFLOWS.md — plain-English guide to all workflows
  2. Add weekly-sweep.yml — cron Monday 6am, runs quality + gap + portfolio agents
  3. Add email-sequence-deploy.yml — manual dispatch, deploys approved sequences
  4. Set up GitHub Actions notifications in repo Settings
  5. Verify all existing workflows are green with a test push
  Goal: you can open the Actions tab and understand everything you see

CLAUDE DESIGN (Week 2, starting Day 1 — does not need agents to be complete):

Brief 1: Dashboard design system
Paste this prompt into Claude Design:

---
You are a senior product designer at a world-class design studio in 2026.
Design a complete design system for an internal business command center
dashboard for a solo technical founder running a portfolio of AI agent products.

This is NOT a marketing product. It is a cockpit. Every design decision
must reduce decision time, not showcase visual creativity.

Design system to produce:
1. Color tokens (see spec below)
2. Typography scale with JetBrains Mono for data, Space Grotesk for UI
3. Component library:
   - Decision card (pending/held/approved/rejected states)
   - Status pill (active/inactive/recommended/held/expired)
   - Metric display (large number + label + sparkline)
   - Agent roster row
   - Command header bar
   - Chat message bubble (agent variant + Claude variant + user variant)
   - Portfolio health row with expandable detail
   - Analytics graph container with product switcher pills
   - Kanban card (research pipeline)
   - Alert badge

Color system:
  Background:      #0a0a0f
  Surface:         #12121a
  Surface raised:  #1a1a24
  Text primary:    #e8e6e0
  Text secondary:  #9997a0
  Text mono:       #c8c6be
  Active/healthy:  #00d4a8
  Needs attention: #f5a623
  Critical:        #ff4f4f
  Completed:       #3fd17a
  Archived/dead:   #555555
  Held:            #7a78ff

Motion spec:
  All transitions: under 200ms
  New card arrival: slide from right + 2s amber pulse border
  Approval: green flash (300ms) → collapse
  Rejection: red flash (300ms) → collapse with reason shown
  MRR update: count-up, never jumps
  Nothing decorative. Motion = information.

Output: complete Figma-ready component set OR fully styled React components
with CSS custom properties. Dark mode only.
---

Brief 2 (Day 3 of Week 2): Dashboard layout
Once Brief 1 is complete, paste into Claude Design:

---
Using the design system from Brief 1, design the full layout for the
internal command center dashboard. Single-page app, dark mode only.

Layout structure:
  Top bar (CommandHeader): MRR (large mono) | active products | signups today |
    agent runs today | alert badge | search/command palette (Cmd+K)

  Main grid (three columns):
    Left column (30%):
      - HITL approval queue (active decision cards)
      - On-hold cards section (collapsible, shows count when collapsed)

    Center column (40%):
      - Agent chat interface (persistent, collapsible to icon)
      - Research pipeline kanban below chat

    Right column (30%):
      - Portfolio health list (expandable rows)
      - Agent roster list below

  Bottom drawer (collapsed by default, click to expand):
    - Analytics panel: product switcher pills + graphs

Mobile layout (390px viewport):
  Bottom tab bar: Approvals | Portfolio | Research | Chat
  Each tab: full screen, single-context view
  Decision cards: full-screen swipe interface
    Swipe right = approve, swipe left = reject, swipe up = hold

Show all states: empty state, loading state, active with real-looking mock data.
Mock data should reflect a real portfolio: 4 products, $13K combined MRR,
3 pending approvals, 1 on hold, 2 recommended agents in gap detector.
---

End of Week 2 checkpoint:
✓ All internal agents built and tested with real inputs
✓ Dashboard design system complete from Claude Design
✓ Dashboard layout design complete from Claude Design

---

### WEEK 3 — Dashboard implementation + Finance agents. Claude Code uses Claude Design output.

This is where Code and Design output merge.
Import the design tokens and component specs from Claude Design into the codebase.
Finance agents also start Week 3 — they have no design dependency, run Day 1.

Claude Code sessions:
- Session 11 (Day 1 AM): GitHub Actions visibility + WORKFLOWS.md
  As noted above — all workflows documented, notifications configured

- Session 11 (Day 1 PM): Finance agent foundation
  Build in this order:
  1. finance/ folder structure and all sub-files
  2. New Supabase tables: expenses, revenue_events, invoices,
     tax_estimates, deductions, salary_records, investment_allocations
  3. document_store.py — Google Drive or S3 organized folder structure,
     create all year folders and category subfolders programmatically
  4. stripe_revenue.py — Stripe API polling, writes to revenue_events

- Session 12 (Day 2): Finance agents
  1. accounting_agent.py — receipt OCR, expense categorization,
     invoice tracking, monthly summary, Stripe sync
  2. receipt_processor.py + expense_categorizer.py + invoice_tracker.py
  3. Set up receipts@yourdomain.com email forwarding to processing endpoint
  4. finance_assistant_agent.py — read-only retrieval, chat-routable
  5. Wire finance_assistant to chat_router_agent for "where is X" queries

- Session 13 (Day 3 AM): Tax, wealth, and revenue intelligence agents
  1. tax_agent.py — deduction tracker, quarterly estimator, year-end packager
  2. wealth_agent.py — cash flow surplus, salary benchmark, investment tracking
  3. deduction_tracker.py, quarterly_estimator.py, year_end_packager.py
  4. cash_flow_monitor.py, salary_advisor.py, investment_tracker.py
  5. revenue_intelligence_agent.py — reads all existing tables, no new infra
     needed except revenue_opportunities table (add to Supabase now)
  Build revenue_intelligence last in this session — it depends on
  portfolio_monitor, visitor_capture, and lead data all being wired first.
  Run first scan manually after build: point at any test product data
  to confirm opportunity cards surface correctly in dashboard.
  Note: every output from tax and wealth agents carries the CPA/advisor
  disclaimer label — build this into base output, not per-agent

- Session 13 (Day 3 PM): Finance dashboard panel
  Finance Command Center panel in dashboard:
  - Always-visible header metrics (YTD revenue, expenses, net, reserve, surplus)
  - Recent transactions sub-panel
  - Pending items sub-panel (uncategorized receipts, overdue invoices)
  - Upcoming deadlines sub-panel (quarterly estimate due dates)
  - Deduction tracker sub-panel
  - Wealth targets sub-panel
  - CPA handoff button
  Wire to finance data hooks

- Session 14 (Day 4): Design system integration + DecisionCard + HITLQueue
  Step 29 + Step component from queue
  Copy Claude Design output into dashboard/internal/design/
  Build design-system.css from the token output
  Set up component file structure matching CLAUDE.md spec

- Session 11 (Day 2): Core hooks
  Steps 26–28: useAgentStream, useDecisionQueue, usePortfolioData
  These power all components — build them before any component

- Session 12 (Day 3): DecisionCard + HITLQueue
  Step 29 + Step component from queue
  This is your most important component. Test all card states.
  Test keyboard shortcuts A/M/H/R. Test hold with timer. Test expiry.

- Session 13 (Day 4): Analytics + PortfolioHealth
  Steps 30, 34
  Test product switcher — switching product updates all graphs in place
  Test kill switch toggle with confirmation modal

- Session 14 (Day 5): AgentRoster + AgentChat + CommandHeader + app.tsx
  Steps 31–33, 35
  Wire chat router to actual agents
  Test command palette Cmd+K
  Build PWA manifest for mobile access

End of Week 3 checkpoint:
✓ Dashboard running locally with mock data
✓ All decision card states working
✓ Analytics product switcher working
✓ Agent chat routing to correct handler
✓ HITL queue with hold, expiry, keyboard shortcuts working
✓ Mobile layout working on 390px viewport

---

### WEEK 4 — First product. Claude Code + Claude Design in parallel again.

At this point your foundation is live and your dashboard is running.
Now you build the first actual product on top of it.

BEFORE STARTING:
Run research_agent.py against your first chosen niche.
Review the structured JSON output.
Approve it via the dashboard HITL queue.
Content agent fires automatically, produces the full content package.
You approve the content package.
Now you have everything you need for both Code and Design to run simultaneously.

CLAUDE CODE (Week 4):
- Session 15: Clone agents/products/_template/ for Product 1
  Wire agent logic to shared infra
  Configure product in products.yaml and Stripe
  Set up Terraform vars for Product 1 Fargate deployment
  Step 36–38

- Session 15 continued: Wire lead capture to Product 1
  Create /signup/[product1] and /trial/[product1] routes
  Connect signup_handler and trial_handler to Product 1
  Create Product 1 tag set in Systeme.io
  Run email_sequence_agent for Product 1 — review drafts in dashboard
  Approve email sequence → triggers email-sequence-deploy.yml
  Verify sequence live in Systeme.io before launch

CLAUDE DESIGN (Week 4, same days — no dependency on Code):
Brief 3: Product 1 landing page
Paste LANDING_BRIEF_TEMPLATE.md from CLAUDE.md into Claude Design
with all [VARIABLE] slots filled from research_agent JSON output.

This is the only brief that changes per product.
Every other brief (design system, dashboard layout) is reused forever.

The content agent output feeds directly into this brief.
You are not writing copy. You are approving copy and pasting it into a template.

End of Week 4 checkpoint:
✓ Product 1 agent logic built on shared infra
✓ Product 1 Fargate module configured in Terraform
✓ Product 1 landing page designed by Claude Design
✓ Landing page implemented by Claude Code from Claude Design output

---

### WEEK 5 — Deploy Product 1 + versioning hardening

- Session 16: Prompt versioning system
  Step 39: prompts/VERSIONING.md, prompt-version-check.yml PR gate live

- Session 17: Release workflow documentation + Obsidian sync
  Steps 40–41
  Test full cycle: make change → PR → deploy → release notes → Obsidian

- Session 18: Product 1 end-to-end test
  Free trial signup flow works
  Stripe checkout works
  Agent runs against real trial data
  HITL queue receives alerts from Product 1
  Portfolio health panel shows Product 1 metrics

- Deploy Product 1 to production

End of Week 5 checkpoint:
✓ Product 1 live at product1.yourdomain.com
✓ Free trial signup working end to end
✓ Prompt versioning enforced by PR gate
✓ Obsidian vault syncing SOPs automatically
✓ Release notes agent documenting deploys

---

### WEEK 6 ONWARD — Portfolio expansion velocity

From Week 6, the pattern repeats for every new product:

Step 1 (Day 1): Run research_agent on new niche — 10 min to review and approve
Step 2 (Day 1): Content agent fires automatically — 10 min to review and approve
Step 3 (Day 2): Clone product template, configure — 2 hours
Step 4 (Day 2-3): Claude Design landing page brief (auto-populated) — runs async
Step 5 (Day 3): Implement landing page from Claude Design output — 2 hours
Step 6 (Day 3): Terraform new product vars + deploy — 30 min
Step 7 (Day 4): QA end-to-end trial flow — 1 hour
Step 8 (Day 4): Publish landing page, AEO page, LinkedIn post

Total elapsed time per new product: 3-4 working days.
Your bottleneck is approval decisions, not build time.

---

## SUMMARY: WHEN TO USE EACH TOOL

CLAUDE CODE — paste CLAUDE.md first, then session prompt:
  Week 1 Day 1-2:  Session 1 — Folder scaffold + providers
  Week 1 Day 2-3:  Session 2 — Core engine + HITL + assertion
  Week 1 Day 3-4:  Session 3 — Security layer
  Week 1 Day 4-5:  Session 4 — Supabase + Stripe + Git remotes
  Week 1 Day 5:    Session 5 — CI/CD all workflows
  Week 2 Day 1-2:  Session 6 — base_agent + research_agent
  Week 2 Day 2-3:  Session 7 — content_agent + sop_agent
  Week 2 Day 3-4:  Session 8 — gap_detector + portfolio_monitor
  Week 2 Day 4-5:  Session 9 — chat_router + release_notes
  Week 2 Day 5 AM: Session 10 AM — code_quality_agent + CI gate
  Week 2 Day 5 PM: Session 10 PM — lead capture + payments
  Week 3 Day 1-2:  Session 11 — finance agents + revenue intel
  Week 3 Day 3-4:  Session 12 — dashboard hooks + DecisionCard
  Week 3 Day 4-5:  Session 13 — remaining dashboard components
  Week 4 Day 1-2:  Session 14 — product factory template + Terraform
  Week 5 Day 1-2:  Session 15 — versioning + Obsidian + release docs
  Week 4+:         Per product — clone template, wire lead capture

CLAUDE DESIGN — paste brief directly, no CLAUDE.md needed:
  Week 2 Day 1:    Brief 1 — Dashboard design system
                   (start immediately, zero dependencies)
  Week 2 Day 3:    Brief 2 — Dashboard layout
                   (after Brief 1 complete)
  Week 4 Day 1:    Brief 3 — Product landing page
                   (after research_agent output approved)
  Week 4 Day 1:    Brief 4 — Product interactive demo
                   (parallel with Brief 3, same day)
  Week 6+:         Brief 3 + Brief 4 repeat per new product
                   Research agent auto-populates variables

NEVER WAIT ON ONE FOR THE OTHER:
  Design system can start Week 2 Day 1 with no agents built yet.
  Product landing page can design while Code builds the agent logic.
  The only true dependency: landing page brief needs research_agent JSON output.
  That takes 1 day. Run research_agent on Day 1, start Claude Design Day 2.

---

## QUICK REFERENCE — WHAT GOES WHERE

| Deliverable               | Tool          | When              |
|---------------------------|---------------|-------------------|
| Folder structure          | Claude Code   | Week 1            |
| LLM router                | Claude Code   | Week 1            |
| HITL state machine        | Claude Code   | Week 1            |
| Security layer            | Claude Code   | Week 1            |
| Supabase schema           | Claude Code   | Week 1            |
| CI/CD pipeline            | Claude Code   | Week 1            |
| Internal agents (all 6)   | Claude Code   | Week 2            |
| Code quality agent        | Claude Code   | Week 2 Day 5 AM   |
| Lead capture infra        | Claude Code   | Week 2 Day 5 PM   |
| Email sequence agent      | Claude Code   | Week 2 Day 5 PM   |
| Visitor capture agent     | Claude Code   | Week 2 Day 5 PM   |
| GitHub Actions visibility | Claude Code   | Week 3 Day 1      |
| Dashboard design system   | Claude Design | Week 2 Day 1      |
| Dashboard layout          | Claude Design | Week 2 Day 3      |
| Dashboard components      | Claude Code   | Week 3            |
| Product 1 agent           | Claude Code   | Week 4            |
| Product 1 lead capture    | Claude Code   | Week 4            |
| Product 1 email sequences | Claude Code   | Week 4 (approved) |
| Product 1 landing page    | Claude Design | Week 4            |
| Prompt versioning         | Claude Code   | Week 5            |
| Obsidian sync             | Claude Code   | Week 5            |
| Product N agent           | Claude Code   | Week 6+           |
| Product N lead capture    | Claude Code   | Week 6+ (template)|
| Product N email sequences | Claude Code   | Week 6+ (agent)   |
| Product N landing page    | Claude Design | Week 6+           |
| Finance/accounting agents | Claude Code   | Week 3 Day 1-2    |
| Revenue intelligence agent| Claude Code   | Week 3 Day 3      |
| Finance dashboard panel   | Claude Code   | Week 3 Day 3      |
| Document store setup      | Claude Code   | Week 3 Day 2      |
```
