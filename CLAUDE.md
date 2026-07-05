# CLAUDE.md — KDavis Agentic Platform
# Master context file. Read this at the start of every Claude Code session.
# Last updated: 2026-07-01
# Version: 1.0.0

---

## WHAT THIS IS

KDavis Agentic Platform is a shared infrastructure layer that powers:
1. A portfolio of micro-SaaS agent products (primary revenue engine)
2. An internal business operating system (personal + team ops)
3. Cloud Decoded (enterprise DevOps SaaS — longer sales cycle, same foundation)

Built once. Never rebuilt. Every product, agent, and workflow inherits from
this foundation. The competitive advantage is the infrastructure depth —
security-first, LLM-agnostic, multi-tenant, SOC 2-ready from day one.

---

## CORE PRINCIPLES (non-negotiable)

1. LLM-agnostic always. No hard coupling to any model. All LLM calls route
   through providers/router.py. Never import anthropic, openai, or deepseek
   directly in business logic.

2. HITL gates before any execution that touches external systems, sends
   communications, writes to production databases, or executes infrastructure
   changes. No exceptions.

3. SOC 2-ready from day one: per-tenant isolation, audit logging,
   DataSanitizationShield before any data touches storage, HITL before any
   agent-derived pattern becomes permanent.

4. product_id namespaces everything in Supabase. Every table, every query,
   every RLS policy. Tenant A never sees Tenant B's data. Ever.

5. Prompt versioning = code versioning. Semver, git-tracked, CHANGELOG.md
   required per prompt. PR gate blocks merge without version bump.

6. Every completed task generates a SOP entry pushed to Obsidian vault.
   Agents document themselves. You don't document manually.

7. CI/CD pushes to GitHub (public portfolio) AND Gitea (private internal)
   simultaneously on every merge to main.

8. Token circuit breaker on every agent: 50-call loop limit, $2 spend cap
   per trial run. Hard stop, not a warning.

9. Hold is always an option. No agent alert or recommendation forces a
   binary approve/reject. Every decision card has a Hold + remind option.

10. When you identify a gap that needs a new agent, write it to GAPS.md.
    Do not build it mid-session. Surface it for human approval first.

---

## FOLDER STRUCTURE

```
kdavis-agentic-platform/
├── CLAUDE.md                         # This file — read every session
├── GAPS.md                           # Pending agent recommendations
├── DECISIONS.md                      # Architectural decisions log
├── .github/
│   └── workflows/
│       ├── deploy.yml                # Main CI/CD: test → build → Fargate → notify
│       ├── prompt-version-check.yml  # Blocks PR if prompt has no version bump
│       ├── code-quality-gate.yml     # Blocks PR if code_quality_agent flags issues
│       ├── gitea-mirror.yml          # Mirrors every push to internal Gitea
│       ├── sop-sync.yml              # Syncs completed SOPs to Obsidian vault
│       ├── weekly-sweep.yml          # Cron: runs code_quality + gap_detector weekly
│       ├── email-sequence-deploy.yml # Deploys approved email sequences to Systeme.io
│       └── WORKFLOWS.md              # Plain-English guide to every workflow file
├── config/
│   ├── platform.yaml                 # Global settings, feature flags
│   ├── products.yaml                 # Registry: id, name, subdomain, status, pricing
│   └── schema_validations/           # Per-agent input/output JSON schemas
├── core/
│   ├── engine.py                     # LangGraph state machine, master orchestrator
│   ├── hitl_manager.py               # Pause/resume, approval queue, confidence scoring
│   ├── assertion.py                  # Deterministic output validation layer
│   ├── token_breaker.py              # Circuit breaker: $2 cap, 50-call loop limit
│   └── sop_writer.py                 # Post-task SOP generator → Obsidian
├── providers/
│   ├── base.py                       # Unified LLM interface: prompt_in → completion_out
│   ├── deepseek.py                   # Primary: cheap, fast, high volume
│   ├── openrouter.py                 # Secondary: model flexibility
│   ├── anthropic.py                  # Fallback + think tank: complex reasoning
│   └── router.py                     # Routes by: cost, latency, task type, fallback
├── security/
│   ├── sanitizer.py                  # DataSanitizationShield — scrubs PII before storage
│   ├── tenant_isolation.py           # KMS per tenant, product_id enforcement
│   └── audit_log.py                  # Immutable audit trail: actor, action, timestamp
├── agents/
│   ├── base_agent.py                 # Base class: lifecycle, HITL, logging, SOP trigger
│   ├── internal/                     # Business OS agents
│   │   ├── research_agent.py         # Scrapes ICP, pain, language, design brief vars
│   │   ├── content_agent.py          # Drafts AEO page, LinkedIn, demo script
│   │   ├── sop_agent.py              # Writes SOPs, syncs to Obsidian
│   │   ├── gap_detector_agent.py     # Identifies missing agents, recommends builds
│   │   ├── portfolio_monitor.py      # MRR, churn, signups per product — flags decisions
│   │   ├── release_notes_agent.py    # Auto-documents every deploy
│   │   ├── chat_router_agent.py      # Routes dashboard chat to correct agent or Claude
│   │   ├── code_quality_agent.py     # DRY enforcer, bloat detector, readability overseer
│   │   ├── email_sequence_agent.py   # Drafts nurture sequences, submits for HITL approval
│   │   ├── visitor_capture_agent.py  # Processes visitor/lead data, enriches, routes to CRM
│   │   └── revenue_intelligence_agent.py # Finds money left on table, ad-ready signals, opportunities
│   └── products/                     # Product agents
│       └── _template/                # Clone this for every new product
├── mcp_servers/
│   └── _template/                    # Base MCP server — add per product when needed
├── prompts/
│   ├── VERSIONING.md                 # Prompt versioning rules
│   └── internal/                     # Versioned prompt files per agent
│       ├── research_agent/
│       │   ├── v1.0.0.md
│       │   └── CHANGELOG.md
│       ├── content_agent/
│       │   ├── v1.0.0.md
│       │   └── CHANGELOG.md
│       ├── gap_detector_agent/
│       │   ├── v1.0.0.md
│       │   └── CHANGELOG.md
│       └── chat_router_agent/
│           ├── v1.0.0.md
│           └── CHANGELOG.md
├── infra/
│   ├── terraform/
│   │   ├── shared/                   # Shared modules: VPC, SQS, KMS, API Gateway
│   │   └── products/                 # Per-product: new product = new tfvars only
│   ├── bicep/                        # Azure equivalent for Cloud Decoded path
│   └── docker/
│       ├── Dockerfile.base           # Shared base image
│       └── Dockerfile.product        # Product overlay
├── queue/
│   └── worker.py                     # SQS consumer, throttled, exponential backoff
├── dashboard/
│   ├── internal/                     # Business OS — command center
│   │   ├── design/                   # Claude Design outputs live here
│   │   │   ├── DESIGN_BRIEF.md       # Master design brief (see below)
│   │   │   └── design-system.css     # Design tokens from Claude Design output
│   │   ├── components/
│   │   │   ├── CommandHeader.tsx     # MRR, active counts, alert badge, cmd palette
│   │   │   ├── HITLQueue.tsx         # Decision cards with options/impact/hold
│   │   │   ├── AgentChat.tsx         # Strategic chat with router + Claude think tank
│   │   │   ├── AgentRoster.tsx       # Team of agents: active/inactive/recommended
│   │   │   ├── PortfolioHealth.tsx   # Per-product rows with sparklines, kill switch
│   │   │   ├── Analytics.tsx         # Combined + per-product graphs, product switcher
│   │   │   ├── ResearchPipeline.tsx  # Kanban: researching/deciding/approved to build
│   │   │   ├── SOPFeed.tsx           # Recent SOPs, Obsidian deep links
│   │   │   └── DecisionCard.tsx      # Reusable: options, impact, hold, custom input
│   │   ├── hooks/
│   │   │   ├── useAgentStream.ts     # Streams agent updates to dashboard in real time
│   │   │   ├── useDecisionQueue.ts   # Manages HITL card state, hold timers, expiry
│   │   │   └── usePortfolioData.ts   # Pulls combined + per-product metrics
│   │   └── app.tsx                   # Root: layout, keyboard shortcuts, cmd palette
│   └── product_template/             # Landing page template per product
│       ├── LANDING_BRIEF_TEMPLATE.md # Claude Design brief with ICP variable slots
│       └── design/                   # Claude Design outputs per product
├── obsidian/
│   └── vault_sync.py                 # Pushes SOPs, decisions, changelogs to vault
├── leads/
│   ├── capture/
│   │   ├── pixel.js                  # Lightweight visitor tracking script (self-hosted)
│   │   ├── signup_handler.py         # Processes signup form submissions per product
│   │   └── trial_handler.py          # Processes trial starts, writes to leads table
│   └── integrations/
│       ├── systeme_io.py             # Systeme.io API wrapper: contacts, tags, sequences
│       └── webhook_receiver.py       # Receives Systeme.io webhooks back into platform
├── cicd/
│   ├── PIPELINE.md                   # CI/CD workflow documentation
│   └── release_workflow.md           # How to apply new releases, rollback procedure
└── docs/
    ├── ARCHITECTURE.md               # Full system architecture — AEO content asset
    ├── ONBOARDING.md                 # How to spin up a new product
    └── PROMPT_VERSIONING.md          # Prompt version rules, how to bump
```

---

## BUILD SEQUENCE

### PHASE 1 — Foundation (weeks 1–2)
Do not skip steps. Do not reorder.

1. Scaffold full folder structure
2. `providers/base.py` — unified LLM interface, abstract class
3. `providers/deepseek.py`, `openrouter.py`, `anthropic.py` — concrete implementations
4. `providers/router.py` — routing logic: primary deepseek, fallback anthropic
5. `core/engine.py` — LangGraph state machine, stateless per run, serializable state
6. `core/hitl_manager.py` — pause on confidence < 0.85, serialize to Supabase,
   resume from exact state, confidence scoring per agent output
7. `core/assertion.py` — deterministic validation, type checking, range checking,
   blocklist of dangerous tool calls (delete_*, drop_*, send_* without approval)
8. `core/token_breaker.py` — hard stop at 50 calls OR $2.00 spend per execution,
   logs reason, fires HITL alert, does not retry
9. `security/sanitizer.py` — PII patterns: email, SSN, card numbers, phone,
   custom patterns per product configurable in products.yaml
10. `security/tenant_isolation.py` — KMS key per tenant, product_id middleware
    that wraps every Supabase query
11. `security/audit_log.py` — immutable append-only log: actor, action, resource,
    timestamp, product_id, outcome
12. Supabase schema — all tables:
    - products (id, name, subdomain, status, pricing_tier, created_at)
    - tenants (id, product_id, stripe_customer_id, created_at)
    - agent_runs (id, product_id, tenant_id, agent_name, status, started_at,
      completed_at, token_count, cost_usd, confidence_score)
    - hitl_queue (id, product_id, agent_run_id, status, options_json,
      selected_option, hold_until, created_at, resolved_at)
    - audit_log (id, product_id, actor, action, resource, outcome, created_at)
    - sops (id, product_id, agent_name, task_summary, content_md,
      obsidian_path, created_at)
    - prompts (id, agent_name, version, content, changelog, active, created_at)
    - tech_debt (id, product_id, file, line, issue_type, description,
      severity, pr_number, created_at, resolved_at)
    - leads (id, product_id, email, name, company, role, source,
      utm_source, utm_medium, utm_campaign, ip_country, page_path,
      signup_type, systeme_contact_id, created_at)
    - visitor_sessions (id, product_id, session_id, ip_country,
      referrer, utm_source, utm_medium, utm_campaign, pages_viewed,
      time_on_site_seconds, converted_to_lead, created_at)
    - email_sequences (id, product_id, name, status, systeme_sequence_id,
      approved_by, approved_at, created_at)
    - email_sequence_steps (id, sequence_id, step_number, subject,
      body_md, delay_days, approved, created_at)
    Apply RLS: all policies filter on product_id AND tenant_id
13. Stripe setup — one account, product catalog:
    - Create product entry per micro-SaaS in Stripe dashboard
    - Webhook endpoint: /api/stripe/webhook handles checkout, subscription events
    - Map Stripe product_id → platform product_id in products.yaml
14. GitHub repo init + Gitea mirror:
    ```bash
    git remote add origin git@github.com:KDavisCodeCloud/agentic-platform.git
    git remote set-url --add origin git@your-gitea-server.com:kdavis/agentic-platform.git
    ```
15. `.github/workflows/deploy.yml`:
    - Trigger: push to main
    - Steps: lint → type check → pytest → docker build → push to ECR →
      update Fargate task definition → notify via webhook
16. `.github/workflows/gitea-mirror.yml`:
    - Trigger: push to any branch
    - Step: push identical ref to Gitea remote
17. `.github/workflows/prompt-version-check.yml`:
    - Trigger: PR to main touching prompts/**
    - Step: check that CHANGELOG.md updated and version bumped, block if not

### PHASE 2 — Internal Business OS Agents (weeks 3–4)

18. `agents/base_agent.py` — base class all agents extend:
    - Properties: agent_name, product_id, version, confidence_threshold
    - Methods: run(), pause(), resume(), emit_sop(), emit_alert()
    - Lifecycle: validate_input → sanitize → execute → assert_output →
      emit_audit → emit_sop
    - Every agent auto-logs to audit_log on start and completion
    - Every agent calls sop_writer on completion

19. `agents/internal/research_agent.py`:
    Input: niche keyword or ICP hypothesis
    Process:
    - Scrape Reddit (relevant subs), LinkedIn posts, G2 reviews, Quora
    - Extract: pain language (exact quotes), ICP job titles, company sizes,
      tools mentioned, competitor gaps, search queries used
    - Score niche viability: search volume proxy, competitor count, price sensitivity
    Output (structured JSON):
    ```json
    {
      "niche": "string",
      "icp": {
        "job_title": "string",
        "company_size": "string",
        "tools_daily": ["string"],
        "visual_environment": "string",
        "emotional_register": "URGENT|ANALYTICAL|OPERATIONAL|ASPIRATIONAL",
        "trust_blockers": ["string"],
        "proof_format": "METRICS|ARCHITECTURE|PEER|CASE_STUDY"
      },
      "pain_language": ["exact quotes"],
      "top_llm_queries": ["string"],
      "competitor_gaps": ["string"],
      "estimated_build_days": number,
      "estimated_mrr_range": {"low": number, "high": number},
      "viability_score": number,
      "design_brief_vars": {
        "pain_headline_options": ["string"],
        "roi_number": "string",
        "proof_stat_1": "string",
        "proof_stat_2": "string",
        "proof_stat_3": "string",
        "faq_questions": ["string"]
      }
    }
    ```
    Routes to HITL queue: approve to build / kill / hold

20. `agents/internal/content_agent.py`:
    Input: approved research_agent JSON output
    Output (one structured package):
    - AEO page draft (markdown, FAQPage schema included)
    - Landing page headline options (5, ranked by conversion likelihood)
    - LinkedIn post (before/after format, no buzzwords)
    - Demo script outline (60-second structure, pain → workflow → outcome)
    - Claude Design brief (populated from design_brief_vars in research output)
    Routes all outputs to HITL queue as one approval card with preview

21. `agents/internal/sop_agent.py`:
    Triggers: automatically after every agent run completes
    Input: agent_run record from Supabase
    Process: generates SOP in Obsidian-compatible markdown:
    ```markdown
    # SOP: [agent_name] — [task_summary]
    Date: [timestamp]
    Agent version: [version]
    Product: [product_id]

    ## What was done
    ## Why it was done
    ## Input received
    ## Output produced
    ## Decisions made (HITL approvals)
    ## Outcome
    ## If this fails next time
    ```
    Pushes via obsidian/vault_sync.py to correct vault folder

22. `agents/internal/gap_detector_agent.py`:
    Runs: weekly, triggered by cron in deploy.yml
    Process:
    - Analyzes agent_runs for tasks that had low confidence or failed
    - Analyzes HITL queue for patterns of repeated manual corrections
    - Analyzes agent_chat for questions routed to Claude think tank
      (these signal missing agents)
    - Compares against agent roster to identify coverage gaps
    Output: recommendation cards in dashboard gap detector panel
    Each card includes: gap description, why it exists, suggested agent name,
    estimated build effort, estimated business impact

23. `agents/internal/portfolio_monitor.py`:
    Runs: daily at 6am local
    Process:
    - Pulls Stripe MRR, new subscriptions, cancellations per product
    - Pulls trial signups, trial-to-paid conversion rate per product
    - Pulls agent run counts, error rates, token costs per product
    - Calculates: gross margin per product, MoM growth rate, churn rate
    Output: daily digest card in command header alert badge
    Flags: products below $500 MRR after 60 days → kill switch review card

24. `agents/internal/chat_router_agent.py`:
    Purpose: routes dashboard chat input to correct handler
    Routing logic:
    - Contains metrics/product name keywords → portfolio_monitor
    - Contains content/post/write keywords → content_agent
    - Contains research/niche/icp keywords → research_agent
    - Contains build/agent/new product keywords → gap_detector (creates card)
    - Contains anything else → Claude anthropic.py think tank
    When routing to Claude think tank:
    - Passes full platform context: current products, MRR, active agents
    - Response labeled clearly as "Claude" in chat UI
    - Appends option: "Create agent recommendation from this response"
    All chat history stored in Supabase with product_id = "internal"

25. `agents/internal/release_notes_agent.py`:
    Triggers: on successful deploy.yml completion
    Input: git diff summary, updated files list, version tags
    Output: release notes in Obsidian vault + Supabase releases table
    Format: version, date, what changed, which products affected,
    any prompt version bumps, any new agents deployed

26. `agents/internal/code_quality_agent.py`:
    Purpose: overseer of all code across the entire platform including
    Cloud Decoded. Runs on every PR and on-demand via dashboard chat.

    Triggers:
    - Automatically on every PR via code-quality-gate.yml CI gate
    - On-demand: type "review [filename or module]" in agent chat
    - Weekly scheduled sweep of entire codebase

    Scope:
    - ALL code in this repo: agents, core, providers, security, infra,
      dashboard, queue, mcp_servers
    - Cloud Decoded repo: wired as a second remote or submodule so the
      same agent oversees both codebases from one place

    What it checks (in priority order):
    1. DRY violations — duplicated logic across files. If the same
       pattern appears in 2+ places, it flags for extraction to a
       shared utility. Never flags cosmetic similarity, only logic duplication.
    2. Bloat — functions over 40 lines, files over 300 lines, classes
       doing more than one thing. Flags with suggested refactor scope.
    3. Dead code — functions defined but never called, imports never used,
       config keys never referenced. Flags for removal.
    4. Readability — unclear variable names (x, tmp, data2), missing
       docstrings on public functions, complex one-liners that should be
       broken up. Suggests specific rewrites, does not vaguely flag.
    5. Dependency bloat — packages imported for one function that could
       be replaced with stdlib. Flags the specific import and the stdlib
       equivalent.
    6. Inconsistency — same operation done differently in different files
       (e.g. error handling pattern A in core/, pattern B in agents/).
       Flags and recommends which pattern wins and why.

    What it does NOT do:
    - Does not auto-fix without HITL approval
    - Does not flag style preferences (tabs vs spaces handled by linter)
    - Does not rewrite working logic unless there is a clear DRY or
      bloat violation
    - Does not touch test files unless the test itself has dead assertions

    Output per PR (structured report):
    ```
    CODE QUALITY REPORT — PR #[number]
    Files reviewed: [count]
    Issues found: [count]

    BLOCKING (must fix before merge):
      - [file:line] DRY violation: [description] → suggested extraction
      - [file:line] Dead code: [function name] never called

    NON-BLOCKING (recommended):
      - [file:line] Bloat: [function] is 67 lines → suggested split
      - [file:line] Readability: variable 'x' in [context] → suggest [name]

    CLEAN: [list of files with no issues]
    ```

    CI gate behavior:
    - BLOCKING issues: PR cannot merge until resolved or explicitly
      overridden by you via dashboard HITL card with documented reason
    - NON-BLOCKING issues: PR can merge, issues added to tech debt
      backlog in Supabase, surface in dashboard weekly digest

    Dashboard integration:
    - Every PR report creates a decision card in HITL queue
    - Blocking issues: ACTION REQUIRED card, amber border
    - Non-blocking: INFO card, collapsible, auto-expires in 7 days
    - Weekly sweep: summary card with top 5 tech debt items ranked
      by estimated cleanup effort vs code health impact
    - On-demand review via agent chat: response inline in chat thread
      with option to create HITL card for any flagged item

    Tech debt tracking:
    - All non-blocking issues written to Supabase tech_debt table:
      (id, file, line, issue_type, description, severity, created_at,
      resolved_at, product_id)
    - Dashboard shows running tech debt count per product
    - Resolving a flagged item auto-closes the tech_debt record

### PHASE 3 — Dashboard Build (weeks 4–5, parallel with Phase 2 end)

NOTE: Claude Code builds the component logic and data layer.
Claude Design builds the visual design system and component appearance.
These run in parallel. See EXECUTION ORDER section below.

27. `dashboard/internal/hooks/useAgentStream.ts`:
    - WebSocket connection to Supabase Realtime
    - Streams: new HITL cards, agent completions, portfolio metric updates
    - Updates component state without full re-render

27. `dashboard/internal/hooks/useDecisionQueue.ts`:
    - Manages HITL card state machine: pending → held/approved/rejected/expired
    - Hold timer: stores hold_until in Supabase, fires reminder at expiry
    - Bulk action: apply same decision to multiple cards of same type
    - Keyboard binding: A/M/H/R act on focused card

28. `dashboard/internal/hooks/usePortfolioData.ts`:
    - Fetches combined metrics (all products) and per-product metrics
    - Exposes: switchProduct(id), currentProduct, combinedView toggle
    - Caches with SWR, revalidates every 60 seconds

29. `dashboard/internal/components/DecisionCard.tsx`:
    Core reusable component. Props:
    - agent: string, type: RECOMMENDATION|ACTION_REQUIRED|FLAGGED|INFO
    - what_happened: string, why_it_matters: string
    - confidence_score: number
    - options: Array<{label, action, impact_summary}>
    - onApprove(option), onModify(custom_text), onHold(remind_at), onReject(reason)
    States: pending (amber border) / held (gray, reduced opacity) /
    approved (green flash → collapse) / rejected (red flash → collapse) /
    expired (gray, history)
    Mobile: swipe right = approve, swipe left = reject, swipe up = hold

30. `dashboard/internal/components/Analytics.tsx`:
    - Product switcher: pill tabs, "All" default + one per live product
    - Switching updates all graphs in place, no reload
    - Combined view: MRR line (90d default), trial signups bar (daily,
      color per product), churn line with threshold marker
    - Per-product view adds: agent run frequency, HITL approval rate,
      avg time-to-approval, token cost vs revenue ratio
    - Every graph: plain-English insight line below it
    - Hover state: date, value, agent runs that day, approvals made

31. `dashboard/internal/components/AgentRoster.tsx`:
    - Full-width list, scannable rows (not cards)
    - Each row: agent_name (mono) | description | status pill |
      last_run timestamp | product_scope | quick actions
    - Status pills: ACTIVE (teal) / INACTIVE (gray) / RECOMMENDED (amber)
    - Recommended rows: include why_recommended, est_build_time, est_impact
    - Action buttons: Run now / Configure / Deactivate / View logs
    - Recommended actions: Add to build queue / Dismiss / Ask Claude
    - "Ask Claude" pre-populates AgentChat with recommendation context
    - Searchable, filterable by status/scope/type
    - Tech debt count badge per agent: how many open issues that agent's
      code currently has flagged by code_quality_agent

32. `dashboard/internal/components/AgentChat.tsx`:
    - Persistent panel, collapsible to icon, session history preserved
    - Input → chat_router_agent → correct handler or Claude think tank
    - Agent responses: labeled with agent name badge, different style
    - Claude think tank responses: "Claude" label, visually distinct
    - Inline approval cards when agent response requires HITL
    - Pin message to top of chat
    - Export thread to Obsidian: one button → vault_sync.py

33. `dashboard/internal/components/CommandHeader.tsx`:
    - Portfolio MRR: large, monospace, live via useAgentStream
    - Active products | Trial signups today | Agent runs today
    - Alert badge: count of pending HITL cards + urgent flags
    - Command palette (Cmd+K): fuzzy search across all dashboard actions

34. `dashboard/internal/components/PortfolioHealth.tsx`:
    - One row per product: name | MRR | 30d sparkline | trials | status pill
    - Click row → expands to full product metrics inline
    - Kill switch toggle: requires confirmation modal, archives product
    - Row click also switches Analytics.tsx to that product's view

35. `dashboard/internal/app.tsx`:
    - Root layout: CommandHeader top, main grid below
    - Left column (30%): HITL queue + on-hold cards
    - Center column (40%): Agent chat + research pipeline
    - Right column (30%): Portfolio health + agent roster
    - Bottom drawer: Analytics (collapsed by default, expands on click)
    - Global keyboard shortcuts registered here
    - PWA manifest for mobile spot-check access

### PHASE 4 — Product Factory Template (week 6)

36. `agents/products/_template/` — complete product agent scaffold:
    - agent.py extending base_agent.py
    - config.yaml: product_id, pricing_tier, token_cap, mcp_required
    - prompts/v1.0.0.md: blank prompt template with versioning header
    - README.md: 5-step setup guide for new product

37. `dashboard/product_template/LANDING_BRIEF_TEMPLATE.md`:
    See LANDING PAGE DESIGN BRIEF section below.
    Research agent auto-populates the ICP variable slots.

38. `infra/terraform/products/` — parameterized Fargate module:
    - main.tf: Fargate task, SQS queue, KMS key, subdomain DNS record
    - variables.tf: product_id, subdomain, container_image, env_vars
    - New product = copy _template folder, fill variables.tf only

### PHASE 5 — Versioning + CI/CD Hardening (week 6, parallel)

39. `prompts/VERSIONING.md` — rules:
    - Patch (1.0.X): wording fixes, no behavior change
    - Minor (1.X.0): new instruction added, behavior extended
    - Major (X.0.0): intent changed, output format changed, model changed
    - Every version file must have a paired CHANGELOG.md entry
    - PR gate enforces: cannot merge prompts/** without version bump

40. `cicd/release_workflow.md` — step by step:
    ```
    1. Make changes in feature branch
    2. If prompt changed: bump version in filename, update CHANGELOG.md
    3. Run: pytest tests/ to confirm assertion layer passes
    4. Open PR to main:
       - prompt-version-check.yml runs (blocks if no version bump on prompts)
       - code-quality-gate.yml runs (blocks if BLOCKING issues found)
    5. Review code_quality_agent decision card in dashboard HITL queue
       - Fix blocking issues OR approve override with documented reason
    6. Merge PR → deploy.yml triggers automatically
    6. Fargate pulls new image, zero-downtime rolling deploy
    7. release_notes_agent.py fires, documents deploy to Obsidian
    8. Monitor: dashboard shows agent run status for 30 min post-deploy
    9. Rollback if needed: git revert + push, deploy.yml re-triggers
    ```

41. `obsidian/vault_sync.py`:
    - Folder structure mirrors platform:
      /KDavis Platform/SOPs/{agent_name}/{date}-{task}.md
      /KDavis Platform/Decisions/{date}-{decision}.md
      /KDavis Platform/Architecture/{component}.md
      /KDavis Platform/Products/{product_name}/brief.md
      /KDavis Platform/Releases/{version}.md
    - Sync method: Obsidian Local REST API plugin or direct file write
      if vault is on local machine accessible via mounted path
    - Triggered by: sop_agent, release_notes_agent, AgentChat export

---

## DASHBOARD DESIGN SYSTEM

### Source of truth

The CEO Decoded design handoff (`design_handoff_ceo_decoded/CEO Decoded.dc.html`)
is the canonical design reference for ALL internal dashboards:
- app.thdstack.com (owner dashboard)
- team.thdstack.com (team dashboard — slight variation)
- CEO Decoded, MSE, and any future internal tools

The HTML file is a design prototype only — do NOT copy its inline
styles into production. Extract all values into a shared design token
file and use the codebase's normal styling approach (CSS modules,
Tailwind, or styled-components — confirm with Claude Code session).

### Three surfaces, one system

Same components, same typography, same status colors.
Background shifts per context for instant visual distinction.

```
OWNER / CEO DECODED / MSE DASHBOARDS
app.thdstack.com
  --bg-base:          #0b0e13   main content area
  --bg-sidebar:       #0e1218   icon rail + labeled sidebar
  --bg-card:          #141a22   section cards
  --bg-tile:          #10151b   nested tiles inside cards
  --border:           #1c222b   all cards, dividers, borders
  Accent (primary):   #5eead4   mint — brand accent

TEAM DASHBOARD
team.thdstack.com — same system, blue-shifted background
  --bg-base:          #0d1117   slightly blue-cast near-black
  --bg-sidebar:       #0f1520   blue-shifted sidebar
  --bg-card:          #141c28   blue-shifted cards
  --bg-tile:          #111825   blue-shifted tiles
  --border:           #1c2535   blue-shifted borders
  Accent (primary):   #5eead4   same mint — consistent brand
  Feeling: calmer, collaborative. Instantly distinct from owner view.

PRODUCT LANDING PAGES
[product].thdstack.com — ICP-derived per research agent output
  Colors, surface, accent: all from DESIGN_[product_id].md
  Never generic. Always industry-native.
```

### Exact design tokens (from CEO Decoded handoff)

```
BACKGROUNDS
  App/base:               #0b0e13
  Sidebar/rail:           #0e1218
  Section card:           #141a22
  Nested tile:            #10151b
  Borders (all):          #1c222b
  Exit-gate card:         radial-gradient(circle at 15% 15%,
                            #6fce8f22, #10201a 70%)
                          border: #1f3d2e
  Legal disclaimer:       #241a10  border: #3d2e1f

TEXT
  Primary heading/value:  #eef2f5
  Section label:          #c7cfd6
  Secondary/body:         #aab4bd
  Muted mono metadata:    #5b6673
  Slightly brighter muted: #8b96a3

ACCENT PALETTE (status, product color coding, metric card tints)
  Mint (brand primary):   #5eead4
  Blue (pending/queued):  #7ea6f5   badge bg: #5b8def22
  Green (active/pass):    #6fce8f   badge bg: #6fce8f22
  Amber (warning/flagged): #e8963f  badge bg: #e8963f22
  Red (error/reject):     #e05d5d   badge bg: #e05d5d22
  Neutral/backlog:        #9aa2ab   on bg: #2a2a2a

TYPOGRAPHY
  Body/headings:   Inter (400/500/600/700/800)
  Data/mono:       JetBrains Mono (400/500/600/700)
  Scale:
    24px/800  metric values (MRR numbers, key figures)
    19px/700  page title (department heading in top bar)
    14-15px/600-700  card titles, names
    13px/700  section labels (ALL CAPS in mockup — use sentence
              case in production per design system rules)
    12-12.5px/400-600  body, table text
    10-11.5px  mono metadata, timestamps, badges

RADIUS
  Cards/sections:   14px
  Nested tiles:     10-12px
  Badges/pills:     5-6px (or 20px fully rounded)
  Avatars:          50% (circle) or 10px (square-ish)

SPACING
  Section gap:      16-18px
  Card padding:     20px (16-18px for metric cards)
  Row padding:      8-13px
  Row divider:      1px solid #1c222b top border between rows

METRIC CARD (exact pattern from handoff)
  Background: linear-gradient(150deg, [accent+24 alpha], #141a22 75%)
  Border: 1px solid #1c222b
  Radius: 14px, padding: 16px 18px
  Label: 11px mono #8b96a3 uppercase letter-spacing 0.04em
  Value: 24px/800 in accent color
  Sub:   11px mono #5b6673

SECTION CARD (exact pattern)
  Background: #141a22
  Border: 1px solid #1c222b
  Radius: 14px, padding: 20px
  Header label: 13px/700/#c7cfd6, margin-bottom 14px

AGENT ROSTER CARD (exact pattern)
  Name: 13px/700
  Status badge: pill, 9.5-10px mono, tinted bg/text per status
  Last-run: mono, muted
  Output summary: 1-2 lines, mono, muted

STATUS/VERDICT BADGE (exact pattern)
  Shape: border-radius 5-6px or 20px fully rounded
  Font: mono 9-10.5px
  Background: accent at ~13% alpha
  Text: full accent color
  Standard mapping (match exactly):
    Green  #6fce8f  bg #6fce8f22 = active/pass/healthy
    Blue   #7ea6f5  bg #5b8def22 = building/pending/queued-ok
    Amber  #e8963f  bg #e8963f22 = planning/flagged/caution
    Red    #e05d5d  bg #e05d5d22 = error/reject/critical
    Gray   #9aa2ab  bg #2a2a2a   = future/backlog/neutral

HITL APPROVAL ROW (exact pattern)
  Agent name + blast-radius badge (one line)
  Plain-language action (below)
  Confidence bar: 5px track #1c222b, fill #5eead4 + percentage
  Approve button: mint outline
  Reject button: gray outline

ACTIVITY FEED ROW (exact pattern)
  Colored dot (verdict color) + agent name (max ~100px, truncate)
  + department (~70px, truncate) + action text (flex, truncate)
  + verdict badge + timestamp
  CRITICAL: action column must truncate with ellipsis — never
  force horizontal overflow. Use min-width:0 on flex children.

LAYOUT RULES (from handoff — preserve exactly)
  Grid columns: repeat(auto-fit, minmax(Npx, 1fr))
  Two-col splits: minmax(0, Nfr) — never bare Nfr
  Flex children with truncating text: always min-width:0
  Outer frame: no page scroll — only main content column scrolls
  Three-part layout: icon rail (60px) + sidebar (196px) + main (flex)
  Icon rail border: 1px solid #1c222b right
  Sidebar border:   1px solid #1c222b right

SIDEBAR NAV ITEM (exact pattern)
  12×12px square outline icon + label
  Font: 12.5px, padding: 9px 10px, radius: 8px
  Active:   bg #5eead41a, text #5eead4, weight 600
  Inactive: bg transparent, text #8b96a3, weight 400

TOP BAR (exact pattern)
  Dept title: 19px/700/#eef2f5 left
  Right: sync timestamp (11px mono #5b6673) + 30px circular avatar
  Avatar K: bg #5eead4, text #0b0e13, 12px/700
  Border-bottom: 1px solid #1c222b
  Padding: 20px 30px

SCROLLBAR (exact pattern)
  Width: 8px
  Thumb: #1c222b, radius: 4px
```

### Team dashboard variation

Same system. Apply these overrides only — nothing else changes:

```css
/* team.thdstack.com overrides only */
--bg-base:     #0d1117;
--bg-sidebar:  #0f1520;
--bg-card:     #141c28;
--bg-tile:     #111825;
--border:      #1c2535;
```

All other tokens — accent, text, status colors, typography,
spacing, radius, components — inherit from the main system unchanged.

The blue-shifted background is the only distinction.
It is enough. Instant recognition. No confusion.

### Mobile requirements (all dashboards)

The CEO Decoded handoff notes this is desktop-only currently.
The team and owner dashboards for thdstack.com must be mobile-ready.
Product landing pages must be mobile-first.

Mobile rules for team and owner dashboards:
  Touch targets: minimum 44px height
  Bottom tab bar replaces sidebar on mobile (≤768px)
  PWA manifest: add to home screen iOS + Android
  Font size minimum 16px on inputs (prevents iOS auto-zoom)
  Offline: show last-cached state, never blank screens
  No hover-only interactions

### Design files location in repo

```
design_handoff/
├── ceo_decoded/
│   ├── CEO Decoded.dc.html    # Source of truth prototype
│   ├── README.md              # Full handoff spec
│   └── screenshots/           # 10 department PNGs
└── team_dashboard/
    └── (Claude Design output goes here — Brief 2)
```

Claude Code reads CEO Decoded.dc.html and README.md as the
authoritative design reference before building any dashboard
component. README.md contains every exact pixel value needed.



---

## LANDING PAGE DESIGN BRIEF TEMPLATE

(Research agent auto-populates [VARIABLE] slots)

```
PRODUCT CONTEXT
Product name:             [PRODUCT_NAME]
One sentence:             [ONE_SENTENCE_DESCRIPTION]
Workflow replaced:        [OLD_WORKFLOW]
Specific pain eliminated: [PAIN_STATEMENT]
ROI number:               [ROI_NUMBER]

ICP PROFILE (from research_agent output)
Job title:                [JOB_TITLE]
Company size:             [COMPANY_SIZE]
Tools used daily:         [TOOL_LIST]
Visual environments:      [VISUAL_REFERENCE]
Emotional register:       [URGENT|ANALYTICAL|OPERATIONAL|ASPIRATIONAL]
Trust blockers:           [TRUST_BLOCKER]
Proof format:             [METRICS|ARCHITECTURE|PEER|CASE_STUDY]

DESIGN DIRECTION
- Reflect the visual language of [VISUAL_REFERENCE] — design should feel
  like something those tools would build if they had great taste
- Emotional register [REGISTER] drives: typography weight, whitespace,
  color temperature, CTA urgency
- Do not use: generic SaaS blue, hero illustrations, gradient blobs,
  stock photography, "AI-powered" anywhere on the page
- Mobile first: above fold converts on 390px viewport without scrolling

PAGE STRUCTURE (strict order)
1. Above fold
   Headline: names the pain, not the product — from pain_language in research
   Subheadline: specific outcome in measurable terms ([ROI_NUMBER])
   CTA: "Start free trial" — sole primary action. Nothing else above fold.

2. Proof strip
   Three numbers: [proof_stat_1], [proof_stat_2], [proof_stat_3]
   Not features. Outcomes. Numbers only.

3. Problem articulation
   Show the broken workflow they live in today.
   Make them feel seen before showing the solution.
   Use their exact language from pain_language research output.

4. Live demo embed
   Actual interactive workflow. Not a video.
   Auto-plays on scroll into view. Touch-navigable on mobile.

5. How it works
   Three steps maximum.
   Each step: what the agent does, not how it works technically.

6. Security block
   Architecture diagram (simplified, non-technical).
   One paragraph. Lead with: "Your data never leaves your infrastructure."

7. Pricing
   All tiers visible. No "contact sales" for first two tiers.
   Free trial prominently on each tier.

8. FAQ
   Five questions written in [JOB_TITLE] language.
   Each answer: lead with the answer in sentence one. AEO-optimized.
   Include FAQPage JSON-LD schema in page head.

TYPOGRAPHY RULES
Variable fonts where supported.
Heavy weight for pain statements.
Light weight for explanatory copy.
Never same weight twice in sequence — create rhythm.

MOTION RULES
Page load: content reveals by section, not all at once.
Demo section: auto-plays on scroll into view.
CTA button: subtle pulse every 8 seconds.
Nothing loops continuously above the fold.

TECHNICAL OUTPUT REQUIREMENTS
Single HTML file with embedded CSS and JS.
FAQPage JSON-LD schema in <head>.
og:image meta: 1200x630 placeholder.
Canonical URL placeholder.
data-section attribute on every section for analytics tracking.
Structured for AEO: semantic heading hierarchy, direct answer sentences.
```

---

## CLAUDE CODE SESSION RULES

Start of every session:
1. Read CLAUDE.md (this file)
2. Read docs/ARCHITECTURE.md
3. Read GAPS.md for pending recommendations
4. Check cicd/PIPELINE.md for current release state
5. Never assume prior session context. All context lives in these files.

During every session:
- Never import a model provider directly in business logic
- Never skip the sanitizer before storing data
- Never write a DB query without product_id in the WHERE clause
- Never build a new agent mid-session — add to GAPS.md, surface for approval
- Every function over 40 lines: flag in GAPS.md for code_quality_agent review
- Every file over 300 lines: add a comment at top — # REFACTOR CANDIDATE
- Every duplicated pattern spotted: extract to shared utility immediately,
  do not leave duplication for code_quality_agent to catch later
- Every function that calls an LLM: add confidence score to return value
- Every new file: add corresponding test file in tests/

End of every session:
1. Update DECISIONS.md with any architectural choices made
2. Trigger SOP generation for what was built
3. Commit with conventional commit format:
   feat(core): add token circuit breaker with $2 spend cap
   fix(security): sanitizer now catches phone number patterns
   chore(infra): add product B Fargate module
4. Push: git push (triggers both GitHub and Gitea via mirror workflow)
5. Note in CLAUDE.md what phase you're in and what comes next

---

## EXECUTION ORDER — CLAUDE CODE VS CLAUDE DESIGN

See bottom of this file for the full sequenced schedule.

---

---

## GITHUB ACTIONS — DAILY VISIBILITY AND WORKFLOW GUIDE

GitHub Actions is the engine behind every automated process in this platform.
Every workflow file in .github/workflows/ has one job and one trigger.
You approve work in the dashboard. GitHub Actions executes it.

### How to see what's happening daily

Go to: github.com/KDavisCodeCloud/agentic-platform → Actions tab
Every workflow run appears here with: status, trigger, duration, logs.
Bookmark this. Check it the same way you check the dashboard.

The Actions tab shows you:
- Every deploy that ran and whether it passed or failed
- Every PR that was blocked by a quality gate and why
- Every scheduled job (weekly sweep, email deploy) and its outcome
- Every Gitea mirror push confirmation

Set up GitHub Actions notifications:
- Go to Settings → Notifications → Actions
- Enable: failed workflow runs (immediate), successful deploys (digest)
- This gives you a daily email digest of what ran without noise

### Every workflow file explained in plain English

`deploy.yml`
Trigger: push to main branch
What it does:
  1. Runs pytest — if any test fails, deploy stops here
  2. Builds Docker image from Dockerfile.product
  3. Pushes image to AWS ECR
  4. Updates Fargate task definition to use new image
  5. Fargate does rolling deploy — zero downtime
  6. Fires webhook to dashboard: "Deploy complete, release_notes_agent running"
You see it in: Actions tab → deploy.yml → latest run
You interact with it: every time you merge a PR, this runs automatically

`code-quality-gate.yml`
Trigger: any PR opened or updated targeting main
What it does:
  1. Checks out the PR branch
  2. Runs code_quality_agent against changed files only (fast)
  3. If BLOCKING issues found: posts comment on PR with full report,
     sets PR status to failed (cannot merge)
  4. Creates decision card in dashboard HITL queue
  5. If only NON-BLOCKING: PR status passes, issues written to tech_debt table
You see it in: Actions tab → code-quality-gate.yml
You interact with it: review the dashboard decision card, fix issues or
  approve override, then re-push to re-trigger the gate

`prompt-version-check.yml`
Trigger: any PR touching prompts/** files
What it does:
  1. Reads changed prompt files
  2. Verifies version bumped in filename (v1.0.0 → v1.0.1 minimum)
  3. Verifies CHANGELOG.md updated in same PR
  4. Blocks merge if either check fails
You see it in: Actions tab → prompt-version-check.yml
You interact with it: bump the version in your prompt filename before PR

`gitea-mirror.yml`
Trigger: every push to any branch
What it does: pushes identical ref to internal Gitea server simultaneously
You see it in: Actions tab → gitea-mirror.yml (should always be green)
You interact with it: you don't — it's fully automatic

`weekly-sweep.yml`
Trigger: cron every Monday 6am local time
What it does:
  1. Runs code_quality_agent full sweep of entire codebase
  2. Runs gap_detector_agent to find missing coverage
  3. Runs portfolio_monitor for weekly digest
  4. All three create dashboard cards for your Monday morning review
You see it in: Actions tab → weekly-sweep.yml → Monday runs
You interact with it: Monday morning dashboard review session

`email-sequence-deploy.yml`
Trigger: manual dispatch (you trigger it from Actions tab after approving
  an email sequence in the dashboard HITL queue)
What it does:
  1. Reads approved email sequence from Supabase email_sequences table
  2. Calls Systeme.io API to create or update the sequence
  3. Creates contacts tag in Systeme.io matching the product
  4. Confirms deployment back to dashboard
You see it in: Actions tab → email-sequence-deploy.yml → manual runs
You interact with it: after approving an email sequence in the dashboard,
  go to Actions → email-sequence-deploy.yml → Run workflow → select product

`sop-sync.yml`
Trigger: new SOP written to Supabase sops table
What it does: calls vault_sync.py to push SOP to Obsidian vault folder
You see it in: Actions tab → sop-sync.yml

### .github/workflows/WORKFLOWS.md
This file lives in the repo and explains every workflow in plain English
exactly as above. When your son comes on board, this is his starting point.
Update it whenever a new workflow is added.

---

## LEAD CAPTURE AND EMAIL NURTURE SYSTEM

Every landing page collects three types of data:
1. Anonymous visitor behavior (everyone who lands on the page)
2. Email opt-ins (anyone who enters their email without buying)
3. Trial signups (anyone who starts a free trial)

All three feed into Systeme.io for nurture. All three are stored in
Supabase. You approve the content of every email before it sends.

### Visitor tracking (anonymous)

Every landing page includes pixel.js — a lightweight self-hosted
tracking script, not a third-party pixel. It captures:
- Session ID (anonymous, no PII)
- Country (from IP geolocation, country level only)
- Referrer URL
- UTM parameters (utm_source, utm_medium, utm_campaign)
- Pages viewed during session
- Time on site
- Whether session converted to a lead or trial

Stored in: Supabase visitor_sessions table
Visible in: dashboard Analytics panel — traffic source breakdown,
  conversion funnel per product, top referrers
No cookies required. No GDPR consent banner needed for anonymous
  session data at country-level granularity only.

### Email capture (opt-in leads)

Every landing page has two email capture points:
1. Above-fold CTA area: "Start free trial" — goes to /signup/[product]
2. Exit-intent or scroll-depth trigger: "Get the workflow overview"
   — lightweight email-only form, no friction

/signup/[product] page:
- Collects: email (required), first name (optional), company (optional),
  role (optional)
- On submit: writes to Supabase leads table, fires webhook to
  visitor_capture_agent.py, adds contact to Systeme.io with product tag,
  enrolls in nurture sequence for that product
- Redirect: to /welcome/[product] with next steps

Email-only capture form:
- Collects: email only
- On submit: writes to leads table with signup_type = 'email_only',
  adds to Systeme.io with tag 'interested_not_converted',
  enrolls in a shorter nurture sequence

Both capture points: UTM parameters carry through from the session
  so you know exactly which traffic source produced each lead.

### Trial signup

/trial/[product] page (or same as /signup with trial flag):
- Same fields as signup
- Stripe: creates customer, starts 14-day free trial subscription
- Supabase: writes lead with signup_type = 'trial'
- Systeme.io: adds tag 'trial_active', enrolls in trial nurture sequence
  (onboarding emails, usage tips, conversion nudge before day 14)

### Systeme.io integration (leads/integrations/systeme_io.py)

Wraps the Systeme.io API for:
- create_contact(email, name, tags, product_id)
- add_tag(contact_id, tag)
- enroll_sequence(contact_id, sequence_id)
- update_contact(contact_id, fields)
- get_sequence_stats(sequence_id) — open rates, click rates per step

Tags used (consistent naming convention):
- product_{product_id}_interested
- product_{product_id}_trial_active
- product_{product_id}_trial_expired
- product_{product_id}_paid
- product_{product_id}_churned
- email_only (didn't start trial, just gave email)
- visited_pricing (viewed pricing section, didn't convert)

### email_sequence_agent.py

Purpose: drafts email nurture sequences for each product.
Never sends anything. Drafts only. You approve every email.

Triggers:
- Automatically when content_agent completes for a new product
- On-demand via dashboard chat: "draft nurture sequence for [product]"

For each product it drafts three sequences:

SEQUENCE 1 — Trial nurture (14 emails over 14 days)
Day 0:  Welcome + what to do first (onboarding)
Day 1:  The one thing to set up today
Day 2:  Here's what the agent did for someone like you (social proof)
Day 3:  Check-in: have you hit your first win yet?
Day 5:  The workflow problem most people miss (education)
Day 7:  Halfway through your trial — here's what to look at
Day 9:  A specific result the agent produces (concrete, no buzzwords)
Day 11: Your trial ends in 3 days — here's what happens next
Day 12: Side-by-side: what the manual workflow costs vs. this
Day 13: Last day — trial ends tomorrow
Day 14: Your trial ended. Here's how to keep access.
Day 16: Still thinking? Here's the one question to ask yourself
Day 21: Re-engagement: did something get in the way?
Day 30: Final follow-up — door stays open

SEQUENCE 2 — Email-only nurture (5 emails over 14 days)
Day 0:  The workflow overview they asked for (deliver the value)
Day 3:  The specific problem this solves (education, no pitch)
Day 7:  A real result (social proof, still no hard pitch)
Day 10: Here's what a trial looks like (soft CTA)
Day 14: Last nudge — free trial, no card required

SEQUENCE 3 — Post-churn win-back (4 emails over 30 days)
Day 1:  We noticed you left — no pitch, just acknowledgment
Day 7:  What changed since you left (new features or improvements)
Day 21: Would this change your mind? (specific objection addressed)
Day 30: Final check-in — always welcome back

Output format (HITL approval card in dashboard):
- Shows all emails in sequence: subject, body, send day
- Each email individually editable before approving the sequence
- Approve individual email / Modify / Hold that email / Reject
- Can approve sequence with some emails held for later revision
- After full sequence approved: triggers email-sequence-deploy.yml
  GitHub Actions workflow to push to Systeme.io

Email writing rules for this agent:
- Subject lines: specific, no clickbait, reflect the email content exactly
- Body: plain text first, no heavy HTML — reads like a person sent it
- No buzzwords: no "AI-powered", no "revolutionary", no "game-changing"
- Every email: one point, one CTA maximum
- CTA: always the same action appropriate to that day in the sequence
- Length: under 200 words for nurture emails. Under 150 for re-engagement.
- Tone: same tone as the landing page for that product — matches ICP register

### visitor_capture_agent.py

Purpose: processes all inbound lead and visitor data,
enriches it where possible, routes it correctly.

Triggers: webhook from signup_handler.py and trial_handler.py on
every new lead or trial signup

Process:
1. Receives lead record from Supabase
2. Enrichment (optional, lightweight):
   - Company domain from email → look up company size estimate
   - LinkedIn company search if domain available
   - Writes enrichment fields back to leads table
3. Scoring: assigns lead score based on:
   - signup_type (trial = higher score than email_only)
   - company_size if enriched
   - UTM source (direct or organic = higher intent than paid)
   - pages_viewed before converting
4. Tags Systeme.io contact with score bucket:
   high_intent / medium_intent / low_intent
5. Routes high_intent leads to dashboard decision card:
   "New high-intent trial: [email], [company], [source]"
   Options: reach out personally / let nurture run / flag for follow-up
6. All others: let nurture sequence run automatically

---

---

## FINANCE, ACCOUNTING, AND WEALTH MANAGEMENT SYSTEM

### Important boundary (read once, built into every agent)

These agents organize, track, categorize, surface, and remind.
They do not give tax advice, make investment decisions, or act as
a CPA or licensed financial advisor. Every output is labeled:
"For review with your CPA" or "For informational purposes only."
Your brother (accountant) and your CPA are the decision-makers.
These agents make their job frictionless and your records bulletproof.

### What this system does

- Organizes every receipt, invoice, expense, and revenue event
  the moment it happens — nothing to file manually
- Prepares clean financial summaries your CPA can open and use
  directly, formatted the way they actually want to receive data
- Tracks business expenses against IRS categories so nothing
  deductible gets missed
- Surfaces salary recommendations based on your entity structure,
  revenue, and reasonable compensation benchmarks — flagged for
  CPA review before any action
- Tracks brokerage contribution opportunities and growth targets
  based on actual cash flow — flagged for licensed advisor review
- Keeps a running document of every financial decision made so
  audit risk is near zero

### New folder structure additions

```
finance/
├── accounting/
│   ├── receipt_processor.py          # OCR + categorize receipts from email/upload
│   ├── invoice_tracker.py            # Tracks all invoices sent, received, status
│   ├── expense_categorizer.py        # Maps expenses to IRS Schedule C categories
│   ├── revenue_ledger.py             # Records all revenue events from Stripe + manual
│   └── document_organizer.py        # Files all docs to correct folder structure
├── tax/
│   ├── quarterly_estimator.py        # Estimates quarterly tax liability — CPA review
│   ├── deduction_tracker.py          # Tracks potential deductions by category + year
│   └── year_end_packager.py          # Packages full year docs for CPA handoff
├── wealth/
│   ├── cash_flow_monitor.py          # Tracks inflows vs outflows, surplus calculation
│   ├── salary_advisor.py             # Reasonable comp benchmarks — CPA review flag
│   └── investment_tracker.py         # Tracks brokerage allocations — advisor review
└── integrations/
    ├── stripe_revenue.py             # Pulls revenue events from Stripe API
    ├── quickbooks_sync.py            # Optional: syncs to QuickBooks if CPA uses it
    └── document_store.py             # Google Drive or S3 organized filing system
```

### New Supabase tables

```sql
-- All expenses with IRS category mapping
expenses (
  id, product_id, amount, vendor, description, date,
  irs_category, receipt_url, receipt_ocr_text,
  tax_year, deductible, approved_by_cpa, created_at
)

-- All revenue events
revenue_events (
  id, product_id, source, amount, stripe_event_id,
  customer_email, description, date, tax_year, created_at
)

-- Invoices sent and received
invoices (
  id, product_id, type, vendor_or_client, amount,
  status, due_date, paid_date, document_url, created_at
)

-- Quarterly tax estimates
tax_estimates (
  id, tax_year, quarter, estimated_income, estimated_tax,
  safe_harbor_amount, status, cpa_reviewed, created_at
)

-- Deduction tracking
deductions (
  id, tax_year, category, description, amount,
  supporting_doc_url, confidence, cpa_reviewed, created_at
)

-- Wealth and salary tracking
salary_records (
  id, tax_year, recommended_amount, actual_amount,
  entity_revenue, basis_for_recommendation,
  cpa_reviewed, effective_date, created_at
)

investment_allocations (
  id, account_type, institution, amount, date,
  purpose, advisor_reviewed, created_at
)

revenue_opportunities (
  id, product_id, opportunity_type, description,
  estimated_impact_mrr, confidence, status,
  data_snapshot_json, created_at, actioned_at
)
```

### IRS document folder structure (Google Drive or S3)

```
KDavis Business Financials/
├── [YEAR]/
│   ├── Revenue/
│   │   ├── Stripe_Exports/           # Monthly CSV exports, auto-filed
│   │   ├── Invoices_Sent/            # PDF invoices you issued
│   │   └── Other_Income/             # Any non-Stripe revenue
│   ├── Expenses/
│   │   ├── Advertising/              # Ad spend, Systeme.io, marketing tools
│   │   ├── Software_Subscriptions/   # Supabase, GitHub, AWS, Anthropic, etc.
│   │   ├── Home_Office/              # If applicable — CPA confirms eligibility
│   │   ├── Education_Training/       # Courses, books, certifications
│   │   ├── Professional_Services/    # CPA fees, legal, contractors
│   │   ├── Equipment/                # Hardware, peripherals
│   │   ├── Travel_Business/          # Business travel only
│   │   └── Other_Business/           # Catch-all, agent flags for categorization
│   ├── Payroll/
│   │   ├── Owner_Salary/             # Your draws or W-2 if S-Corp
│   │   └── Contractor_1099s/         # Any 1099-NEC issued
│   ├── Tax_Filings/
│   │   ├── Quarterly_Estimates/      # Q1–Q4 payment records
│   │   └── Annual_Returns/           # Filed returns, archived
│   └── CPA_Handoff/
│       └── [MONTH]_Package/          # Clean package ready for CPA review
```

---

### Agent specs

#### `agents/internal/accounting_agent.py`

Purpose: keeps all financial records organized, categorized, and
retrievable. The business never has a shoebox of receipts.

Triggers:
- New Stripe payment event → auto-records to revenue_events
- Email receipt detected (forwarded to a dedicated address) →
  OCR, categorize, file to correct folder, write to expenses table
- Manual upload via dashboard → same processing pipeline
- Monthly: generates revenue vs expense summary, posts to dashboard
- Quarterly: packages all docs for CPA handoff folder

What it does:

1. Receipt processing:
   - Accepts receipts forwarded to receipts@yourdomain.com
   - OCR extracts: vendor, amount, date, line items
   - Maps to IRS expense category using categorizer.py
   - Uploads to correct Google Drive / S3 folder
   - Writes to expenses table with confidence score on category
   - Low-confidence categorizations → HITL card for your review:
     "Received receipt from [vendor] $[amount] — category unclear.
      Is this Software Subscription or Professional Services?"

2. Invoice tracking:
   - Tracks every invoice you issue (from your billing flow)
   - Tracks invoices you receive from contractors or vendors
   - Flags overdue invoices in dashboard: "Invoice #[X] to [client]
     is 14 days past due — [amount]"
   - Options: send reminder / mark paid / write off

3. Monthly financial summary (auto, no input required):
   Revenue this month: $[amount] (breakdown by product)
   Expenses this month: $[amount] (breakdown by category)
   Net: $[amount]
   YTD revenue: $[amount]
   YTD expenses: $[amount]
   YTD net: $[amount]
   Largest expense categories: [list]
   Posted to dashboard as INFO card, always visible in Analytics panel

4. Stripe revenue sync:
   - Polls Stripe API daily for new payment events
   - Records each to revenue_events with product_id mapping
   - Monthly: exports CSV matching Stripe's format, files to
     Revenue/Stripe_Exports/ folder

Output label on all summaries:
"Prepared for CPA review. Not tax advice.
 Share with your licensed CPA before filing."

---

#### `agents/internal/tax_agent.py`

Purpose: tracks potential deductions, estimates quarterly liability,
packages year-end documents. Prevents surprises. Never files anything.

Triggers:
- Quarterly (15th of Jan, Apr, Jun, Sep): generates estimate card
- Ongoing: monitors expenses table for potential deductions
- Year-end (December 1): generates full year-end package
- On-demand via dashboard chat: "what deductions do I have so far this year"

What it does:

1. Deduction tracking (ongoing):
   Monitors expenses table and flags potential deductions:
   - Home office: if you have dedicated workspace — surfaces for CPA
     to confirm eligibility and calculate square footage method
   - Vehicle: if business travel recorded — logs mileage, surfaces
     standard mileage vs actual cost comparison for CPA
   - Software subscriptions: all SaaS tools used for business
     (Supabase, GitHub Pro, Anthropic API, Systeme.io, etc.)
   - Education and training: courses, books, certifications
   - Health insurance premiums: if self-employed, potentially deductible
   - Retirement contributions: SEP-IRA or Solo 401k if applicable
   - Home internet: percentage used for business
   - Equipment depreciation: Section 179 or bonus depreciation
   Each deduction flagged with:
   - Category, estimated amount, confidence level
   - "Confirm with CPA before claiming" on every single one

2. Quarterly estimate card (4x per year):
   Shows:
   - Estimated net income YTD
   - Estimated self-employment tax
   - Estimated income tax based on prior year safe harbor
   - Recommended quarterly payment amount
   - Payment due date and IRS payment link
   Options: I've paid this / I need to adjust / Flag for CPA review
   ALWAYS labeled: "Estimate only. Confirm with your CPA."

3. Year-end package (December 1):
   Compiles into CPA_Handoff/[YEAR]_Complete/:
   - Revenue summary by month and by product (CSV + PDF)
   - Expense summary by IRS category (CSV + PDF)
   - All receipts organized by category (folder of files)
   - All invoices sent and received (folder + summary CSV)
   - Deduction tracker export with supporting docs linked
   - Quarterly estimate payment records
   - 1099-NEC tracking if you paid contractors over $600
   Dashboard card: "Year-end package ready for CPA.
     [X] revenue records, [Y] expense records, [Z] deductions tracked.
     Share CPA_Handoff/[YEAR]_Complete/ folder with your CPA."

---

#### `agents/internal/wealth_agent.py`

Purpose: monitors cash flow surplus, surfaces salary and investment
recommendations for CPA and advisor review. Never moves money.
Never gives financial advice. Surfaces information and benchmarks.

Triggers:
- Monthly: reviews cash flow after accounting_agent monthly summary
- Quarterly: salary review after quarterly estimate
- On-demand: "what should I be thinking about with my money right now"

Important disclaimer built into every output:
"These are informational benchmarks only, not financial advice.
 Review all salary decisions with your CPA.
 Review all investment decisions with a licensed financial advisor."

What it does:

1. Cash flow surplus tracking:
   After accounting_agent posts monthly summary:
   Calculates: revenue - expenses - estimated_tax_reserve = available surplus
   Tax reserve: automatically sets aside estimated_tax / 4 each quarter
     in a mental accounting bucket (does not move actual money —
     surfaces as "recommended reserve" for you to action manually)
   Dashboard widget: always-visible surplus number
   "Available surplus this month after estimated tax reserve: $[amount]"

2. Salary recommendation (quarterly):
   For S-Corp or LLC owners, reasonable compensation is an IRS requirement
   Surfaces benchmark based on:
   - Your entity type (from config)
   - Business revenue and net
   - Comparable role salary data (DevOps/Platform Engineer market rate)
   - Prior year salary if recorded
   Output card: "Reasonable compensation benchmark for your role
     and revenue level: $[range]. Current salary: $[amount].
     Discuss adjustment with your CPA before changing payroll."
   Options: Flag for CPA / Already reviewed / Hold for next quarter

3. Investment opportunity surfacing (monthly, when surplus > threshold):
   When monthly surplus exceeds a threshold you set (e.g. $2,000):
   Surfaces a card: "You have an estimated $[surplus] available
     this month after expenses and tax reserve.
     Common allocation priorities at this stage:
     - Emergency fund (target: 6 months expenses = $[amount] —
       current estimate: $[status])
     - SEP-IRA or Solo 401k contribution (2024 limit: $69,000 or
       25% of net self-employment income — whichever is less)
     - Taxable brokerage account (index funds, low-cost ETFs)
     - Business reinvestment
     Review with a licensed financial advisor before allocating."
   Options: Log a decision / Flag for advisor / Hold / Dismiss

4. Brokerage tracking (manual input):
   You record allocations you've made via the dashboard
   Agent tracks: total invested, by account type, by year
   Surfaces annually: total invested vs total revenue — wealth-building ratio
   "You invested [X]% of gross revenue this year. [Benchmark context]."
   No buy/sell recommendations. Only tracking and context.

5. Tax writeoff surface (on-demand and year-end):
   Pulls from deductions table, shows running total by category
   Compares to prior year if available
   Flags categories where you may be under-utilizing:
   "You have $[amount] in software subscriptions tracked.
    Home office deduction not yet documented this year —
    confirm eligibility with your CPA."

---

#### `agents/internal/finance_assistant_agent.py`

Purpose: the retrieval and coordination layer. When you or anyone
on the team needs to find a document, check a number, or understand
where something is — this agent answers immediately.

Triggers: on-demand only, via dashboard chat

Example queries it handles:
- "Where is my Q2 estimated tax payment receipt?"
  → Returns: file path in Drive/S3, upload date, amount, confirmation
- "What did I spend on software last year?"
  → Returns: total, breakdown by vendor, links to receipts
- "Do I have all my receipts for this month?"
  → Returns: list of recorded expenses, flags any gaps
- "What's my revenue so far this year?"
  → Returns: YTD figure, by product, by month chart
- "Has [vendor] been paid this month?"
  → Checks invoices table, returns status
- "What deductions am I tracking for this year?"
  → Returns: full list from deductions table with amounts and confidence
- "What does my CPA need from me?"
  → Checks CPA_Handoff folder status, lists what's complete and missing
- "What's my current tax reserve?"
  → Returns: recommended reserve amount, what's been mentally allocated

Response format: always returns:
  1. Direct answer first (the number or location)
  2. Source (which table or file it came from)
  3. Last updated timestamp
  4. Related action if relevant ("Year-end package is ready to share")

This agent has read-only access to all finance tables.
It cannot write, update, or modify any records.
It surfaces. You or the appropriate agent acts.

---

### Dashboard additions for finance

New panel: Finance Command Center (collapsible section in dashboard)

Always-visible header metrics:
- YTD Revenue (mono, large)
- YTD Expenses (mono)
- YTD Net (mono, colored: green if positive, amber if tight)
- Tax Reserve (mono) — recommended amount set aside
- Available Surplus (mono) — what's left after reserve

Sub-panels:
1. Recent transactions (last 5 revenue + expense events, with category)
2. Pending items (overdue invoices, uncategorized receipts, missing docs)
3. Upcoming (next quarterly estimate due date + recommended payment)
4. Deduction tracker (running total by category, YTD)
5. Wealth targets (emergency fund status, brokerage YTD, salary current)

CPA handoff button: one click opens the year-end package folder
  and generates a summary email draft via content_agent for your CPA

Finance chat: same AgentChat interface, routed to finance_assistant_agent
  for retrieval queries and wealth_agent for surplus/investment questions

---

### What to tell your CPA

When you bring your CPA in, give them this:
- "All receipts are organized by IRS category in [Drive/S3 folder]"
- "Revenue is exported from Stripe monthly as CSV"
- "I track deductions ongoing — here's the deduction summary"
- "Quarterly estimates are logged with payment confirmations"
- "Year-end package is in CPA_Handoff/[YEAR]_Complete/"
- "I have an LLC/S-Corp [confirm with your brother] — here's the structure"

Your CPA's job becomes review and filing, not hunting for documents.
That is how you get maximum value from CPA hours and minimize fees.

---

## REVENUE INTELLIGENCE SYSTEM

### `agents/internal/revenue_intelligence_agent.py`

Purpose: finds money already within reach that the platform isn't
capturing. Not forecasting. Not general advice. Specific, ranked,
actionable opportunities with estimated MRR impact behind each one.

Reads from: visitor_sessions, leads, revenue_events, email_sequence_steps,
agent_runs, expenses, products — all tables already in the schema.
Writes to: revenue_opportunities table.
Never moves money. Never triggers campaigns. Surfaces and ranks.
Every output is a decision card. You act or hold.

Triggers:
- Weekly: full portfolio scan, Sunday night so Monday dashboard
  opens with a ranked opportunity list
- On-demand via dashboard chat:
  "where is money being left on the table"
  "is Product B ready for ads"
  "which products should I cross-sell"
- After any product hits 30-day mark: first opportunity scan
  for that specific product

---

### What it watches and surfaces

#### 1. Expired trials still engaging
Reads: leads table where signup_type = 'trial' and trial_expired
  but last_login within 14 days
Signals: person wants the product, didn't convert, isn't gone
Decision card:
  "Product A: 7 expired trial users logged in this week.
   Avg days since trial ended: 11. They haven't left.
   Estimated conversion if offered 30% discount: 2-3 users = $[MRR]"
Options:
  Trigger win-back sequence with discount offer /
  Trigger win-back sequence no discount — just re-engagement /
  Flag for personal outreach (high-intent users only) /
  Hold

#### 2. High trial signup, low conversion gap
Reads: leads per product (trial signups) vs revenue_events (conversions)
  over rolling 30 days
Flags: any product where trial signups > 15 and conversion < 3%
Decision card:
  "Product C: 28 trials started this month, 1 converted (3.6%).
   Portfolio avg conversion: 5.2%. Gap = ~$[estimated lost MRR]/mo.
   Most common drop-off: day 3 (no activity after onboarding email)."
Options:
  Rewrite day-3 nurture email (routes to content_agent) /
  Review and update demo (flags for Claude Design brief update) /
  Adjust pricing page (routes to landing page revision) /
  Ask Claude to diagnose /
  Hold

#### 3. Underpriced product signal
Reads: revenue_events for MRR per product, churn rate from
  leads table (trial_expired vs cancelled vs still_active)
Flags: any product where monthly churn < 5% for 60+ days
  at current price point
Decision card:
  "Product D: 3.8% monthly churn over 63 days at $99/mo.
   Portfolio churn avg: 8.1%. Customers are keeping this.
   If repriced to $149 for new signups: estimated +$[delta] MRR
   over 90 days without touching existing customers."
Options:
  Test $149 for new signups only, grandfather existing /
  Raise price for all (higher impact, higher risk) /
  Add a higher tier above current price instead /
  Hold — want more data /
  Ask Claude for pricing strategy

#### 4. Ad-readiness signal (three gates must all be green)
Reads:
  Gate 1 — Conversion: leads conversion rate > 4% for 30 days
  Gate 2 — AEO: confirmed citation (manual flag or automated check
    via search query monitoring in content_agent)
  Gate 3 — Retention: churn < 6% for 60 days
All three green = ad-ready flag fires
Decision card:
  "Product B is ad-ready.
   Conversion: 5.2% (gate: >4%) ✓
   AEO: cited on 2 queries ✓
   Churn: 4.8% (gate: <6%) ✓
   Estimated CAC at $50 CPL: $1,000
   Estimated CAC payback period: 3.1 months at $[price]/mo
   Suggested starting budget: $500/mo
   Suggested channel: [LinkedIn / Google Search / Reddit]
   based on where current organic signups are coming from."
Options:
  Start $500/mo test campaign on suggested channel /
  Start smaller — $200/mo test first /
  Ask Claude for channel strategy /
  Hold — not ready to spend yet

If any gate is not yet green, agent shows which gate is blocking
and what needs to happen to clear it. Not a dead end — a roadmap.

#### 5. Traffic-to-trial mismatch
Reads: visitor_sessions (traffic by source) vs leads (trial starts
  by source UTM) per product
Flags: any source sending > 50 visits/month with < 1% trial conversion
Decision card:
  "Product A: LinkedIn sending 180 visits/mo, 0.4% trial conversion.
   Google organic: 40 visits/mo, 6.2% trial conversion.
   LinkedIn traffic is not converting. Possible causes:
   - Landing page messaging doesn't match LinkedIn ICP
   - LinkedIn content attracting wrong job title
   - Above-fold CTA not visible on mobile (LinkedIn traffic is 73% mobile)"
Options:
  Review landing page for LinkedIn traffic (routes to Claude Design) /
  Audit LinkedIn content ICP targeting (routes to content_agent) /
  Add mobile-specific above-fold layout test /
  Redirect LinkedIn CTA to a different product /
  Hold

#### 6. Cross-sell opportunities
Reads: leads table — customers who bought Product A, their ICP
  profile fields (role, company_size, source)
Compares: ICP overlap with other products in portfolio
Flags: when 10+ existing customers match the ICP of another product
Decision card:
  "14 Product A customers match the ICP for Product C.
   Product C solves an adjacent pain for the same role.
   Estimated cross-sell conversion based on ICP overlap: 20-30%.
   If 4 convert at $[price]: +$[MRR] from existing customer base."
Options:
  Trigger cross-sell email sequence to matched customers /
  Add in-product recommendation inside Product A dashboard /
  Hold until Product C has more traction /
  Ask Claude to write the cross-sell angle

#### 7. Seasonal and timing patterns
Reads: leads and revenue_events timestamps over 90+ days per product
Surfaces (once enough data exists, typically month 4-5):
  - Day of week with highest trial starts
  - Day of week with highest trial-to-paid conversion
  - Time of day most conversions happen
  - Any month-over-month patterns
Decision card (informational, not action-required):
  "Product B conversion pattern: 67% of paid conversions happen
   Tuesday-Thursday. Day-7 nurture email sent on weekends converts
   at half the rate of weekday sends. Suggested: shift day-7 email
   send to Tuesday morning."
Options:
  Update nurture sequence timing (routes to email_sequence_agent) /
  Hold — want more data /
  Noted — no action needed

#### 8. MRR concentration risk + expansion signal
Reads: revenue_events per customer per product
Flags: any single customer representing > 30% of a product's MRR
Decision card:
  "Product D: Customer [domain] represents 38% of product MRR ($[amount]).
   Concentration risk: if they churn, MRR drops significantly.
   This customer is also a candidate for expansion:
   - They've used the product daily for 4 months
   - They haven't hit any usage limits
   - Their company size suggests they may have a team that could use this"
Options:
  Flag for personal expansion outreach /
  Build enterprise tier for this product /
  Generate case study request to this customer /
  Document as churn risk — monitor closely /
  Hold

---

### Revenue intelligence dashboard panel

Position: sits alongside Portfolio Health in the right column.
Always-visible badge: "6 opportunities — est. $4,200 MRR available"
Badge color: amber when opportunities exist, gray when none pending.

Panel layout:
- Ranked list by estimated_impact_mrr descending
- Each row: opportunity type icon | product name | one-line description |
  estimated MRR impact | status pill | action button
- Click row: expands to full decision card with all options
- Filter by: type / product / status (new/held/actioned/dismissed)
- Summary at bottom: total estimated MRR across all open opportunities

Keyboard shortcut: O opens opportunity panel from anywhere in dashboard.

Weekly digest card (Monday, auto-generated):
  "This week's revenue opportunities:
   Total estimated MRR available: $[sum]
   Highest impact: [opportunity description] — $[MRR]
   Ad-ready products: [count]
   Expired trials re-engaging: [count]
   New cross-sell opportunities: [count]"

---

### Build placement

Build after: portfolio_monitor (needs its data),
  visitor_capture_agent (needs visitor + conversion data),
  email_sequence_agent (routes some actions there)
Build in: Week 3, Session 13 alongside finance agents
  Same session as cash_flow_monitor — both are analysis agents
  that read existing data and surface actionable intelligence.

No new infrastructure required.
All data sources already exist in the schema.
New table: revenue_opportunities — add to Phase 1 Supabase schema.

---
Next action: Scaffold folder structure (Phase 1, Step 1)
Last session: —
Last deploy: —
Active products: 0
Platform MRR: $0

---

---

## DOMAIN AND BRAND ARCHITECTURE

### One root domain. Everything inherits from it.

No separate domains per product. No portfolio of unrelated URLs.
One umbrella domain. Products live at subdomains.
Subdomains feel like distinct products to customers.
The platform underneath is one system.

```
[UMBRELLA_DOMAIN].com                    # Root: portfolio overview or redirect
├── app.[UMBRELLA_DOMAIN].com            # Internal dashboard (you only)
├── [product-a].[UMBRELLA_DOMAIN].com    # Product A landing + trial
├── [product-b].[UMBRELLA_DOMAIN].com    # Product B landing + trial
├── [product-n].[UMBRELLA_DOMAIN].com    # Product N landing + trial
└── [UMBRELLA_DOMAIN].com/blog           # AEO content hub, shared SEO authority
```

### Brand decision (resolve before first product ships)

OPTION A — Decoded umbrella
All products live under the Decoded brand.
Continuity with Cloud Decoded, Hustle Decoded, CEO Decoded.
Domain examples: decodedops.com, decodedplatform.com, decoded.run
Compounds one brand equity. Better if keeping portfolio long-term.

OPTION B — Neutral platform name
Separate brand for micro-SaaS portfolio.
No connection to personal brand or Cloud Decoded.
Cleaner if selling the portfolio as a standalone asset later.
More marketing surface area to build from scratch.

DECISION: thdstack.com — decided 2026-07-04
Record in platform.yaml under root_domain: thdstack.com

Subdomain structure:
  app.thdstack.com                  # Internal dashboard (private)
  [product-name].thdstack.com       # Per product landing + trial
  thdstack.com/blog                 # AEO content hub

Example product URLs:
  freightaudit.thdstack.com
  leadsequencer.thdstack.com
  rfpdrafter.thdstack.com

Canonical URL format for Claude Design Brief 3:
  https://[product-name].thdstack.com

Wildcard SSL cert covers: *.thdstack.com
One cert. Every subdomain. Never provisioned manually.

### What prevents the slop look across all products

1. Consistent design system — same font stack, spacing, component
   library across every landing page. Visual family cohesion.
   What changes: color temperature, ICP-specific language, demo.
   What stays: typography, spacing, component structure, security claim.

2. ICP-specific copy from research agent — exact pain language,
   not generic "automate your workflows" filler.

3. Interactive demo per product — live workflow, not screenshots.
   Anyone can screenshot. A clickable demo means the product works.

4. Credible security claim — "Your data never leaves your
   infrastructure" backed by architecture diagram. You can make
   this claim because you built the infrastructure to support it.

5. No buzzwords anywhere — not on the page, not in the demo,
   not in the emails. The research agent writing rules enforce this.

### DNS configuration (per product launch)

When a new product goes live:
1. Add subdomain A record pointing to Fargate load balancer
2. Add SSL certificate via AWS Certificate Manager (wildcard cert
   *.yourdomain.com covers all subdomains automatically)
3. Add subdomain to products.yaml with status: live
4. Confirm subdomain routing in Terraform products module

Wildcard SSL cert means you never manually provision SSL per product.
One cert covers every subdomain you ever create.

---

## PROMPT ROUTING GUIDE — CLAUDE CODE VS CLAUDE DESIGN

### The rule in one sentence

Claude Code builds anything that runs, stores, processes, or deploys.
Claude Design builds anything a human looks at and makes decisions from.

### What goes into Claude Code — complete list

Paste CLAUDE.md into Claude Code at session start.
Then give the session-specific prompt from the list below.

PHASE 1 — FOUNDATION

Session 1: Folder scaffold + providers
```
Read CLAUDE.md in full. Confirm complete context.
We are starting Phase 1.
Step 1: Scaffold the complete folder structure exactly as specified
in the FOLDER STRUCTURE section. Create every file as an empty
stub with a docstring describing its purpose. Do not write
implementation yet — structure only.
Step 2: Build providers/base.py — abstract base class with methods:
complete(prompt, system, model, max_tokens) → str
embed(text) → list[float]
All implementations must extend this class.
Step 3: Build providers/deepseek.py, openrouter.py, anthropic.py
— concrete implementations of base.py.
Step 4: Build providers/router.py — routes by task_type:
primary: deepseek for all standard agent tasks
fallback: anthropic for complex reasoning and think tank
Override: any agent can request a specific provider via config.
Run a test: call router.py with a simple prompt, confirm it returns
a completion from DeepSeek. Log the provider used.
Commit: feat(providers): LLM-agnostic router with DeepSeek primary,
Claude fallback
```

Session 2: Core engine + HITL + assertion + token breaker
```
Read CLAUDE.md. We are on Phase 1, Steps 5-8.
Build core/engine.py — LangGraph state machine:
- Stateless per run (no in-memory state between runs)
- State serializable to JSON for Supabase persistence
- Nodes: validate_input, sanitize, execute, assert_output,
  emit_audit, emit_sop
- Edges: linear with conditional branch to HITL pause node
  when confidence < threshold
Build core/hitl_manager.py:
- pause(state, reason, confidence) → serializes state to
  Supabase hitl_queue, returns queue_id
- resume(queue_id) → deserializes state, re-enters engine
  at exact pause point
- confidence threshold: 0.85 default, configurable per agent
Build core/assertion.py:
- validate_output(output, schema) → bool
- blocklist: ['delete_', 'drop_', 'truncate_', 'send_',
  'publish_'] — any tool call containing these strings
  requires HITL regardless of confidence
- Type checking against schema_validations/ per agent
Build core/token_breaker.py:
- Hard stop at 50 LLM calls OR $2.00 spend per execution
- On breach: log to audit_log, serialize state, fire HITL alert
- No retry after breach — requires human review
Test all four: write a simple agent loop that hits the token
breaker at call 5 (set limit to 5 for test). Confirm it
serializes state and fires alert correctly.
Commit: feat(core): engine, HITL, assertion, token breaker
```

Session 3: Security layer
```
Read CLAUDE.md. Phase 1, Steps 9-11.
Build security/sanitizer.py — DataSanitizationShield:
Patterns to detect and redact before any data touches storage:
- Email addresses → [REDACTED_EMAIL]
- SSN patterns → [REDACTED_SSN]
- Credit card numbers (Luhn check) → [REDACTED_CARD]
- Phone numbers (US + international) → [REDACTED_PHONE]
- Custom patterns: load from config/products.yaml per product
sanitize(text, product_id) → sanitized_text, redaction_log
redaction_log: list of what was found and redacted, for audit
Build security/tenant_isolation.py:
- Middleware that wraps every Supabase query
- Injects WHERE product_id = ? AND tenant_id = ? automatically
- Raises IsolationViolationError if query attempts cross-tenant
  access (no product_id in WHERE clause)
Build security/audit_log.py:
- append(actor, action, resource, outcome, product_id, tenant_id)
- Immutable: no update or delete methods
- Writes to Supabase audit_log table
- Every agent start and completion calls this automatically
  via base_agent.py lifecycle (build that next session)
Test: write a test that attempts a cross-tenant query.
Confirm IsolationViolationError is raised.
Test sanitizer: pass text containing email + phone.
Confirm both are redacted and redaction_log is accurate.
Commit: feat(security): sanitizer, tenant isolation, audit log
```

Session 4: Supabase schema + Stripe + Git remotes
```
Read CLAUDE.md. Phase 1, Steps 12-14.
Generate the complete Supabase SQL migration file at:
infra/supabase/migrations/001_initial_schema.sql
Include ALL tables from the SUPABASE SCHEMA section of CLAUDE.md:
products, tenants, agent_runs, hitl_queue, audit_log, sops,
prompts, tech_debt, leads, visitor_sessions, email_sequences,
email_sequence_steps, revenue_events, invoices, tax_estimates,
deductions, salary_records, investment_allocations,
revenue_opportunities, expenses, dispute_evidence
Apply RLS policies on every table:
- SELECT: auth.uid() matches tenant_id AND product_id matches
- INSERT: product_id and tenant_id required, non-nullable
- UPDATE/DELETE: same as SELECT
Generate Stripe setup script at infra/stripe/setup.py:
- Creates webhook endpoint for: checkout.session.completed,
  customer.subscription.updated, customer.subscription.deleted,
  invoice.payment_failed, charge.dispute.created
- Maps Stripe events to internal platform events
- Reads product catalog from config/products.yaml
Generate git remote configuration at cicd/git_remotes.sh:
git remote add origin [GITHUB_URL]
git remote set-url --add origin [GITEA_URL]
Confirm: both remotes receive pushes with one git push command.
Commit: feat(infra): Supabase schema, Stripe setup, dual git remotes
```

Session 5: CI/CD pipeline
```
Read CLAUDE.md. Phase 1, Steps 15-17.
Build .github/workflows/deploy.yml:
Trigger: push to main
Jobs:
  test: run pytest tests/ — fail fast
  build: docker build -t $ECR_REGISTRY/$IMAGE_NAME:$SHA .
  push: docker push to AWS ECR
  deploy: update Fargate task definition with new image tag,
    trigger rolling deploy, wait for stability
  notify: webhook to dashboard deploy endpoint
Build .github/workflows/code-quality-gate.yml:
Trigger: pull_request targeting main
Jobs:
  quality: run code_quality_agent against changed files only
    Post PR comment with full report
    Set status check: failed if BLOCKING issues found
    Create Supabase hitl_queue record for dashboard card
Build .github/workflows/prompt-version-check.yml:
Trigger: pull_request targeting main, paths: prompts/**
Jobs:
  version-check: read changed prompt files
    Verify filename contains bumped version (semver)
    Verify CHANGELOG.md updated in same PR
    Block merge if either fails
Build .github/workflows/gitea-mirror.yml:
Trigger: push to any branch
Jobs:
  mirror: push identical ref to Gitea remote
Build .github/workflows/weekly-sweep.yml:
Trigger: cron 0 6 * * 1 (Monday 6am)
Jobs:
  sweep: run code_quality_agent full codebase scan
    run gap_detector_agent
    run portfolio_monitor weekly digest
    All outputs create Supabase hitl_queue records
Build .github/workflows/email-sequence-deploy.yml:
Trigger: workflow_dispatch (manual) with input: product_id
Jobs:
  deploy: read approved sequence from Supabase
    call Systeme.io API to create/update sequence
    confirm back to dashboard
Write .github/workflows/WORKFLOWS.md:
Plain-English explanation of every workflow above.
What triggers it, what it does, how you interact with it.
Commit: feat(cicd): all GitHub Actions workflows + documentation
```

Session 6: base_agent + research_agent
```
Read CLAUDE.md. Phase 2, Steps 18-19.
Build agents/base_agent.py:
Properties: agent_name, product_id, version, confidence_threshold
Lifecycle methods (all agents inherit these in order):
  1. validate_input(input) → validated_input or raises
  2. sanitize(validated_input) → sanitized_input via sanitizer.py
  3. execute(sanitized_input) → raw_output (implemented per agent)
  4. assert_output(raw_output) → assertion.py validates
  5. emit_audit() → audit_log.py records completion
  6. emit_sop() → sop_writer.py generates SOP → Obsidian
HITL integration: if confidence < threshold after execute(),
  call hitl_manager.pause() before assert_output
Token tracking: wrap every provider call, accumulate spend,
  call token_breaker.check() after each call
Build agents/internal/research_agent.py extending base_agent:
Input: {"niche": str, "hypothesis": str (optional)}
Execute method:
  - Scrape Reddit (pushshift or reddit API): top pain posts
    in relevant subs for the niche
  - Scrape G2 reviews: competitor products, negative reviews
  - Search LinkedIn posts: job titles, pain language
  - Quora: questions about the niche problem
  - Extract: exact pain quotes, job titles, company sizes,
    tools mentioned, competitor gaps, search queries
Output: complete research JSON matching schema in CLAUDE.md
Routes to hitl_queue on completion — you approve/kill/hold
Test: run against niche "freight invoice reconciliation"
Review JSON output. Confirm all fields populated.
Commit: feat(agents): base_agent lifecycle + research_agent
```

Session 7: content_agent + sop_agent
```
Read CLAUDE.md. Phase 2, Steps 20-21.
Build agents/internal/content_agent.py:
Input: approved research_agent JSON from hitl_queue
Execute method produces one package:
  - AEO page draft (markdown):
    H1: direct answer to top LLM query
    FAQ section: 5 questions in ICP language, answer-first
    FAQPage JSON-LD schema block
  - Landing page headlines: 5 options ranked by
    specificity and pain-naming directness
  - LinkedIn post: before/after workflow format,
    under 150 words, no buzzwords, one CTA
  - Demo script outline: 60-second structure
    0-10s: show the broken workflow
    10-40s: show the agent running
    40-60s: show the outcome metric
  - Claude Design brief: populate LANDING_BRIEF_TEMPLATE
    with all [VARIABLE] slots filled from research JSON
All outputs submitted as one HITL approval card
Each section individually editable before approval
Build agents/internal/sop_agent.py:
Triggered automatically by base_agent.emit_sop()
Input: agent_run record from Supabase
Generates SOP markdown per template in CLAUDE.md
Calls obsidian/vault_sync.py to push to vault
Folder: /KDavis Platform/SOPs/{agent_name}/{date}-{task}.md
Test: complete a research_agent run. Confirm SOP
auto-generates and appears in Obsidian vault.
Commit: feat(agents): content_agent + sop_agent
```

Session 8: gap_detector + portfolio_monitor
```
Read CLAUDE.md. Phase 2, Steps 22-23.
[Paste full agent specs from CLAUDE.md Phase 2 steps 22-23]
Commit: feat(agents): gap_detector + portfolio_monitor
```

Session 9: chat_router + release_notes
```
Read CLAUDE.md. Phase 2, Steps 24-25.
[Paste full agent specs from CLAUDE.md Phase 2 steps 24-25]
Test chat routing: send 5 different message types,
confirm each routes to the correct handler.
Commit: feat(agents): chat_router + release_notes_agent
```

Session 10 AM: code_quality_agent + CI gate
```
Read CLAUDE.md. Phase 2, Step 26.
[Paste full code_quality_agent spec from CLAUDE.md]
Wire to code-quality-gate.yml CI workflow.
Run first sweep: point at entire codebase built so far.
Review output. This is your baseline quality benchmark.
Commit: feat(agents): code_quality_agent + CI gate wired
```

Session 10 PM: Lead capture infrastructure
```
Read CLAUDE.md. Lead Capture section.
Build in this order:
1. leads/capture/pixel.js — anonymous visitor tracking
2. leads/capture/signup_handler.py
3. leads/capture/trial_handler.py
4. leads/integrations/systeme_io.py
5. leads/integrations/webhook_receiver.py
6. payments/base.py + stripe_provider.py
7. payments/lemon_squeezy_provider.py (stub, activate month 3)
8. payments/router.py
9. payments/dispute_handler.py
10. payments/radar_config.py
11. payments/health_monitor.py
12. payments/webhook_receiver.py (normalizes all processor events)
Build email_sequence_agent.py and visitor_capture_agent.py.
Commit: feat(leads): capture, payments, email sequence agent
```

Session 11: Finance agents
```
Read CLAUDE.md. Finance section.
Build in this order:
1. finance/accounting/ — all files
2. finance/tax/ — all files
3. finance/wealth/ — all files
4. finance/banking/mercury.py
5. finance/banking/desert_financial.py (CSV import)
6. finance/banking/relationship_tracker.py
7. finance/integrations/stripe_revenue.py
8. finance/integrations/document_store.py
9. revenue_intelligence_agent.py — last, reads all other data
Confirm every finance agent output carries CPA/advisor
disclaimer label. Build into base output format.
Commit: feat(finance): accounting, tax, wealth, banking, revenue intel
```

Session 12: Dashboard hooks + DecisionCard
```
Read CLAUDE.md. Phase 3.
Apply Claude Design output from dashboard/internal/design/
to the component implementation.
Build in this order:
1. dashboard/internal/hooks/useAgentStream.ts
2. dashboard/internal/hooks/useDecisionQueue.ts
3. dashboard/internal/hooks/usePortfolioData.ts
4. dashboard/internal/components/DecisionCard.tsx
   Test all card states: pending/held/approved/rejected/expired
   Test keyboard shortcuts: A/M/H/R
   Test hold with timer — confirm reminder fires
   Test mobile swipe: right=approve, left=reject, up=hold
Commit: feat(dashboard): core hooks + DecisionCard all states
```

Session 13: Remaining dashboard components
```
Read CLAUDE.md. Phase 3 continued.
Build in this order:
1. CommandHeader.tsx
2. Analytics.tsx — product switcher, combined + per-product
3. AgentRoster.tsx — active/inactive/recommended with tech debt badge
4. AgentChat.tsx — router wired, Claude think tank labeled
5. PortfolioHealth.tsx — sparklines, kill switch, row expand
6. HITLQueue.tsx — active queue + on-hold section
7. ResearchPipeline.tsx — three-column kanban
8. SOPFeed.tsx — Obsidian deep links
9. Finance Command Center panel
10. Revenue Opportunities panel
11. app.tsx — root layout, keyboard shortcuts, PWA manifest
Commit: feat(dashboard): all components wired, PWA ready
```

Session 14: Product factory template + Terraform
```
Read CLAUDE.md. Phase 4.
Build agents/products/_template/
Build infra/terraform/products/ parameterized module
Build dashboard/product_template/ landing page template
Configure wildcard SSL cert in Terraform shared module
Test: spin up a fake Product X using the template
Confirm subdomain routes correctly with SSL
Commit: feat(product-factory): template, terraform, subdomain routing
```

Session 15: Versioning + Obsidian + release workflow
```
Read CLAUDE.md. Phase 5.
Build prompt versioning system
Configure Obsidian vault sync
Write cicd/release_workflow.md step by step
Write docs/ARCHITECTURE.md — full system, AEO content asset
Write docs/ONBOARDING.md — how to spin up a new product
Test full release cycle: change → PR → gates → merge → deploy
→ release notes → Obsidian sync
Commit: feat(versioning): prompt versions, Obsidian sync, release docs
```

---

### What goes into Claude Design — complete list

Each brief below is a standalone prompt. Paste it directly into
Claude Design. No CLAUDE.md needed — the brief is self-contained.

---

CLAUDE DESIGN BRIEF 1 — Team dashboard (variation of CEO Decoded)
Run: Week 2 Day 1 (no dependencies, start immediately)
NOTE: The owner dashboard (app.thdstack.com) is implemented directly
from the CEO Decoded handoff file by Claude Code — no Claude Design
brief needed for it. Claude Design Brief 1 produces only the TEAM
dashboard variation. Claude Code reads README.md + the HTML prototype
and recreates it pixel-for-pixel in React/Next.js for the owner view.

```
You are a senior product designer at a world-class design studio
in 2026. Design the team dashboard for team.thdstack.com.

This is a variation of the CEO Decoded dashboard design. The
CEO Decoded design is the source of truth — it uses these tokens:

BASE SYSTEM (from CEO Decoded handoff — inherit all of these):
  Body font: Inter (400/500/600/700/800)
  Mono font: JetBrains Mono (400/500/600/700)
  Border color: #1c222b
  Card bg: #141a22, tile bg: #10151b
  Text primary: #eef2f5, section label: #c7cfd6
  Text secondary: #aab4bd, muted mono: #5b6673
  Brand accent (mint): #5eead4
  Status green: #6fce8f, blue: #7ea6f5, amber: #e8963f
  Red: #e05d5d, neutral: #9aa2ab
  Card radius: 14px, tile radius: 10-12px, badge radius: 5-6px
  Section gap: 16-18px, card padding: 20px
  Scrollbar: 8px wide, thumb #1c222b radius 4px
  Metric card: 24px/800 value in accent, 11px mono label/sub
  Section card: #141a22 bg, 13px/700/#c7cfd6 header
  Status badge: mono 9-10.5px, accent at 13% alpha bg

TEAM DASHBOARD VARIATION (only these values change):
  --bg-base:    #0d1117   (blue-shifted, not pure near-black)
  --bg-sidebar: #0f1520   (blue-shifted sidebar)
  --bg-card:    #141c28   (blue-shifted cards)
  --bg-tile:    #111825   (blue-shifted tiles)
  --border:     #1c2535   (blue-shifted borders)
  Everything else: identical to CEO Decoded system above.

WHY: The blue-shifted background creates instant visual distinction.
Anyone using both dashboards knows immediately which context they
are in. No labels needed. The color does the work.

LAYOUT (same three-part structure as CEO Decoded):
  Icon rail: 60px fixed, --bg-sidebar, right border
  Labeled sidebar: 196px fixed, --bg-sidebar, right border
    Shows: THD STACK (wordmark) + team member name + role
    Nav items: My Tasks, Current Task, Resources
    (not 10 departments — stripped to what team members need)
  Main content: flex, --bg-base, scrollable

TEAM MEMBER HEADER (replaces CEO Decoded top bar):
  Left: current task name (19px/700/#eef2f5)
  Right: task status badge + team member avatar (initials)

MAIN CONTENT — two views, switch via sidebar:

MY TASKS VIEW:
  Task list: one row per assigned task
    Row: product name | task type badge | status badge |
    priority badge | due date (mono) | Submit button
    Active task row: left border 3px #5eead4
    Completed: dimmed, no submit button
  Empty state: "No tasks assigned yet" (mint text, centered)

CURRENT TASK VIEW:
  Task header card: product name + task type + assigned date
  Step list: numbered steps from task file
    Each step: checkbox (tap to mark complete) + step title
    + brief description + status pill
    Completed step: checkbox checked, text dimmed
    Current step: highlighted, left border mint
  File checklist: files required before submission
    Each file: filename + checkbox + location path (mono, muted)
  Submit section (bottom, always visible on mobile):
    Notes textarea (placeholder: "Anything unusual to note?")
    Submit for review button (full width, mint, 48px height)
    Disabled until all checklist items checked

MOBILE LAYOUT (390px — mobile first for team members):
  Bottom tab bar: My Tasks | Current Task | Help
  48px tab height, mint active indicator
  Each tab: full screen, single context
  Current Task: step checkboxes must be easy to tap (48px min)
  Submit button: sticky at bottom of screen, always reachable

COMPONENTS TO PRODUCE:
  1. Task list row (all states: active/pending/submitted/approved
     /revision-needed/completed)
  2. Step item (states: upcoming/current/complete)
  3. File checklist item (checked/unchecked)
  4. Submit panel (locked/unlocked states)
  5. Status badge (all variants matching CEO Decoded system)
  6. Empty state

OUTPUT: Complete React component set with CSS using the token
values above. Dark mode only. Show all states with mock data.
Mock data: 2 assigned tasks, one in progress (step 3 of 6),
one pending review. Task is for a product named "FreightAudit".
```

MOTION (all under 200ms, information not decoration):
New HITL card: slide from right + 2s amber pulse border
Approved card: green flash 300ms → collapse to one line
Rejected card: red flash 300ms → collapse with reason
MRR number update: count-up animation, never jumps
Chat message: smooth append, no full re-render

COMPONENTS TO DESIGN (all dark mode, all states shown):

1. Decision card — the most important component
   States: pending (amber left border) / held (gray, reduced
   opacity, HELD badge) / approved (green flash → collapsed) /
   rejected (red flash → collapsed with reason) /
   expired (gray, EXPIRED badge)
   Anatomy: agent name + type badge | headline | why it matters |
   confidence bar | options block (2-3 options each with impact) |
   custom input field | A/M/H/R action buttons with key labels

2. Status pill
   Variants: ACTIVE (teal) / INACTIVE (gray) / RECOMMENDED (amber)
   / HELD (violet) / EXPIRED (gray) / BLOCKING (red) / INFO (muted)

3. Metric display
   Large mono number + small label below + optional sparkline
   Variants: positive / negative / neutral / loading skeleton

4. Agent roster row
   Full width: agent_name (mono) | description | status pill |
   last_run timestamp | product scope tags | tech_debt badge |
   action buttons

5. Command header bar
   MRR (large mono, live) | active products | signups today |
   agent runs today | alert badge | Cmd+K search trigger

6. Chat message bubble
   Three variants: user input / agent response (with agent badge) /
   Claude think tank (distinct color, "Claude" label)
   Inline approval card variant for HITL in chat

7. Portfolio health row
   Expandable: product name | MRR | sparkline 30d | trial count |
   status pill | kill switch toggle
   Expanded state: full metrics inline, last agent run

8. Analytics container
   Product switcher: pill tabs (All + one per product)
   Graph area: line graph with insight text below
   Hover state: tooltip with context

9. Kanban card (research pipeline)
   Three column states: researching / deciding / approved
   Card: niche name | ICP summary | viability score | MRR range

10. Revenue opportunity row
    Ranked list: opportunity icon | product | description |
    estimated MRR impact (mono, large) | confidence | action button

OUTPUT: Complete React component library with CSS custom properties.
Dark mode only. Show every component in every state.
Include a mock dashboard screenshot showing all components together.
```

---

DASHBOARD DESIGN — NO CLAUDE DESIGN BRIEF NEEDED
Owner dashboard and all internal dashboards (CEO Decoded, MSE):
Already built. Design is locked. Do not redesign.

OWNER DASHBOARD (app.thdstack.com):
Claude Code builds this directly from the CEO Decoded handoff.
Read these files before any session touching dashboard components:
  design_handoff/design_handoff_ceo_decoded/README.md
  design_handoff/design_handoff_ceo_decoded/CEO Decoded.dc.html
  design_handoff/design_handoff_ceo_decoded/screenshots/ (01-10)
Recreate pixel-for-pixel in React/Next.js.
Extract inline styles into CSS tokens. Do not copy them as-is.

TEAM DASHBOARD (team.thdstack.com):
Claude Code builds this from the team dashboard brief.
Read before any team dashboard session:
  design_handoff/TEAM_DASHBOARD_BRIEF.md
Same CEO Decoded design. Five background color overrides only.
No Claude Design needed — the handoff is the design.

---

CLAUDE DESIGN BRIEF 3 — Product landing page
Run: Week 4, after research_agent output is approved
One brief per product. Research agent auto-populates [VARIABLES].

```
You are a senior product designer at a world-class design studio
in 2026. Design a conversion landing page for a specific product
sold to a specific person with a specific problem.

This is not a template. This is a designed experience for one ICP.

PRODUCT CONTEXT
Product name:             [PRODUCT_NAME]
One sentence:             [ONE_SENTENCE]
Workflow replaced:        [OLD_WORKFLOW]
Pain eliminated:          [PAIN_STATEMENT]
ROI number:               [ROI_NUMBER]

ICP PROFILE
Job title:                [JOB_TITLE]
Company size:             [COMPANY_SIZE]
Tools used daily:         [TOOL_LIST]
Visual environment:       [VISUAL_REFERENCE]
Emotional register:       [URGENT|ANALYTICAL|OPERATIONAL|ASPIRATIONAL]
Trust blockers:           [TRUST_BLOCKER]
Proof format:             [METRICS|ARCHITECTURE|PEER|CASE_STUDY]

DESIGN DIRECTION
Reflect the visual language of [VISUAL_REFERENCE].
Design should feel like something those tools would build
if they had great taste and cared about this specific user.

Do NOT use: generic SaaS blue, hero illustrations, gradient blobs,
stock photography, "AI-powered" anywhere on the page, buzzwords.

COLOR: derive from ICP emotional register:
  URGENT: high contrast, tight spacing, direct type
  ANALYTICAL: data-forward, monospace accents, structured grid
  OPERATIONAL: clean, spacious, process-oriented layout
  ASPIRATIONAL: premium feel, generous whitespace, editorial type

PAGE STRUCTURE (strict order, no reordering):

1. Above fold (converts on 390px mobile without scrolling)
   H1: names the pain, not the product
   Uses exact language from [PAIN_LANGUAGE] research output
   Sub: specific outcome + [ROI_NUMBER]
   CTA: "Start free trial — cancel anytime before day 14"
   Trust line: "Card required. No charge for 14 days."
   Social proof: [X] companies | [Y] workflows automated

2. Proof strip (3 numbers, outcomes not features)
   [PROOF_STAT_1] | [PROOF_STAT_2] | [PROOF_STAT_3]

3. Problem section
   Show the broken workflow they live in today.
   Use their exact language. Make them feel seen.
   Visual: before workflow diagram or timeline

4. Interactive demo embed
   Clickable workflow walkthrough — not a video.
   Auto-plays on scroll into view.
   Touch-navigable on mobile.

5. How it works (3 steps maximum)
   What the agent does. Not how it works technically.
   Each step: icon + headline + one sentence.

6. Security block
   Architecture diagram (simplified, non-technical).
   Lead: "Your data never leaves your infrastructure."
   Sub: explain ZDR processing in one plain paragraph.

7. Pricing (all tiers visible)
   Starter / Growth / Enterprise
   Free trial on each tier.
   No "contact sales" for first two tiers.
   Card required callout with easy cancellation promise.

8. FAQ (5 questions in [JOB_TITLE] language)
   Each answer: direct answer in sentence one.
   AEO-optimized: complete answer without needing context.
   Include FAQPage JSON-LD in page head.

TYPOGRAPHY:
Variable fonts where supported.
Heavy weight for pain statements.
Light weight for explanatory copy.
Never same weight twice in sequence — create rhythm.

MOTION:
Page load: section-by-section reveal, not all at once.
Demo: auto-plays on scroll into view.
CTA button: subtle pulse every 8 seconds.
Nothing loops above the fold.

TECHNICAL OUTPUT:
Single HTML file, embedded CSS and JS.
FAQPage JSON-LD schema in <head>.
og:image meta: 1200x630.
Canonical URL: https://[PRODUCT_SUBDOMAIN].thdstack.com
data-section attribute on every section.
All sections: semantic HTML5 elements.
Mobile first. Above fold works at 390px without scrolling.
```

---

CLAUDE DESIGN BRIEF 4 — Product interactive demo
Run: Week 4, same time as Brief 3 (parallel)
One per product. Built separately from landing page.

```
Design an interactive product demo for embedding in the
landing page of [PRODUCT_NAME].

The demo shows one complete workflow execution from start to finish.
It is clickable, not a video. Each click advances one step.
It must work on mobile (touch) and desktop (click/keyboard).

WORKFLOW TO SHOW:
Step 1: [INPUT — what goes in. Show the messy reality.]
Step 2: [AGENT RUNNING — show processing, not a spinner.
         Show what the agent is actually checking/doing.]
Step 3: [HITL MOMENT — show the approval card if applicable.
         This builds trust — shows a human is in the loop.]
Step 4: [OUTPUT — show the clean, specific result.
         Show the metric. Show the time saved.]

DESIGN RULES:
- Looks like a real product UI, not a mockup frame
- Terminal or dashboard aesthetic matching [VISUAL_REFERENCE]
- Progress indicator: step X of 4, dots or bar
- Each step: title + what's happening + visual representation
- Realistic fake data — specific enough to feel real
- Monospace for data, values, agent outputs
- "Next" button or auto-advance after 3 seconds
- Last step: CTA — "See this running on your data →"
  Links to /signup/[product] with trial initiation

OUTPUT: Self-contained HTML/JS component.
No external dependencies except the design system CSS variables
from Brief 1.
Embeds as an iframe or web component in the landing page.
Must render at 320px minimum width for mobile.
```

---

### The prompt routing decision tree

When you're about to start a new build task, ask:

Does it run, store, process, route, deploy, or integrate?
→ Claude Code. Use session prompts above.

Does a human look at it, read it, click it, or decide from it?
→ Claude Design. Use design briefs above.

Is it a new product being launched?
→ Both in parallel. Claude Code: clone product template.
  Claude Design: Brief 3 + Brief 4 with research agent output.

Is it a prompt file being updated?
→ Claude Code. Bump version, update CHANGELOG.md, open PR.
  Prompt-version-check.yml gate runs automatically.

Is it a content piece (LinkedIn post, AEO page, email)?
→ Neither. content_agent produces it. You approve in dashboard.

---

See DECISIONS.md for full log.
Key decisions recorded here:
- LLM primary: DeepSeek via OpenRouter (cost). Fallback: Claude (quality).
- Database: Supabase (Postgres + RLS + Realtime). Not custom Postgres.
- Queue: AWS SQS (managed, scales to zero). Not RabbitMQ.
- Compute: AWS Fargate (serverless containers). Not EC2.
- Dashboard: Next.js 14 + custom design system from Claude Design.
  Source of truth: design_handoff/ceo_decoded/CEO Decoded.dc.html
  Claude Code recreates owner dashboard pixel-for-pixel from README.md.
  Claude Design Brief 1 produces only team dashboard variation.
  Team variation: blue-shifted bg only (#0d1117 base vs #0b0e13).
  NOT standard Tailwind UI components.
- Dual repo: GitHub (public portfolio) + Gitea (private IP).
- Obsidian sync: Local REST API plugin or direct file mount.
- Prompt versioning: semver in filename, CHANGELOG.md alongside.
- No hard-coded model names anywhere in business logic.
- Root domain: thdstack.com (decided 2026-07-04)
  Subdomain per product: [product-name].thdstack.com
  Dashboard: app.thdstack.com
  Wildcard SSL: *.thdstack.com
  Brand: THD Stack — connects to THD Agentic Systems LLC
```

---

## TEAM MANAGEMENT SYSTEM

### Communication stack (final decision)

Agent chat (AgentChat.tsx): agents only.
You talk to agents. Agents talk to each other.
No human-to-human chat built here.

Slack: human team communication.
You, your son, your daughter, any future employee.
Slack invite sent automatically on onboarding approval.
Slack channel per role: #code-team, #design-team, #general.
Owner (#general + all channels).

This separation is intentional and clean.
Never conflate the two.

---

### Team dashboard subdomain

team.thdstack.com — separate from app.thdstack.com
Owner dashboard: app.thdstack.com (full access)
Team member dashboard: team.thdstack.com (role-scoped)
Both use the same Supabase Auth instance.
Same design system. Different permission layers.

---

### Roles and permissions

```
OWNER (you)
  app.thdstack.com
  All panels: command center, HITL queue, agent chat,
  portfolio health, analytics, research pipeline,
  revenue intelligence, finance, banking, wealth,
  team management, agent roster, SOP feed
  Can: invite, approve, reject, offboard team members
  Can: assign tasks, approve submissions, deploy products

CLAUDE_CODE_EMPLOYEE (your son, future devs)
  team.thdstack.com
  Panels: assigned tasks, product build queue,
  QA checklist, changes feed, practice sandbox
  Cannot see: finance, revenue, banking, wealth,
  agent internals, owner command center
  Can: view assigned tasks, submit work for review,
  comment on tasks, view task history

CLAUDE_DESIGN_EMPLOYEE (your daughter, future designers)
  team.thdstack.com
  Panels: assigned tasks, design brief queue,
  design feedback, changes feed, asset library
  Cannot see: finance, revenue, banking, wealth,
  agent internals, owner command center
  Can: view assigned tasks, submit designs for review,
  comment on tasks, view design history
```

---

### New Supabase tables

```sql
team_members (
  id uuid primary key default gen_random_uuid(),
  supabase_user_id uuid references auth.users(id),
  name varchar not null,
  email varchar not null unique,
  role varchar not null,
  status varchar default 'invited',
  phone varchar,
  slack_user_id varchar,
  github_username varchar,
  personal_folder_path varchar,
  invited_by uuid,
  invited_at timestamp,
  onboarded_at timestamp,
  approved_at timestamp,
  deactivated_at timestamp,
  created_at timestamp default now()
)

tasks (
  id uuid primary key default gen_random_uuid(),
  product_id varchar references products(id),
  assigned_to uuid references team_members(id),
  task_type varchar,
  title varchar not null,
  description text,
  brief_file_path varchar,
  status varchar default 'assigned',
  priority varchar default 'normal',
  due_date date,
  submitted_at timestamp,
  submission_notes text,
  approved_at timestamp,
  rejected_at timestamp,
  rejection_reason text,
  created_by uuid,
  created_at timestamp default now()
)

task_comments (
  id uuid primary key default gen_random_uuid(),
  task_id uuid references tasks(id),
  author_id uuid,
  author_type varchar,
  content text not null,
  created_at timestamp default now()
)

onboarding_steps (
  id uuid primary key default gen_random_uuid(),
  team_member_id uuid references team_members(id),
  step_name varchar,
  status varchar default 'pending',
  completed_at timestamp
)

slack_channels (
  id uuid primary key default gen_random_uuid(),
  channel_name varchar,
  role varchar,
  slack_channel_id varchar,
  created_at timestamp default now()
)
```

RLS policies:
- team_members: owner sees all, members see only own row
- tasks: owner sees all, assigned member sees own tasks only
- task_comments: visible to task owner + assigned member + owner

---

### Auth flow (Supabase Auth)

#### Invitation (triggered by owner)

Owner types in dashboard agent chat:
"Invite [NAME] as [ROLE] — email [EMAIL]"

System does automatically:
1. Creates team_members record: status = 'invited'
2. Creates personal folder: team/[name]/
   Generates: ONBOARDING.md, ROLE.md,
   HOW_TO_USE_[TOOL].md, PRACTICE_TASK.md
3. Calls Supabase Admin API: inviteUserByEmail()
   Custom redirect: team.thdstack.com/onboarding
   Invite link expires: 48 hours
4. Owner gets confirmation card in dashboard:
   "Invite sent to [EMAIL]. Expires in 48 hours."

#### Onboarding gate (team.thdstack.com/onboarding)

They click the invite link. Before dashboard access:

Page 1 — Welcome
  Their name, their role, what they'll be doing.
  Plain English. No jargon.
  "Before you get access, complete these steps."

Page 2 — Set password
  Password field (minimum 12 characters)
  Confirm password field
  Supabase Auth updateUser() sets password.
  This replaces the magic link — they now have
  email + password login going forward.

Page 3 — Your information
  Legal name (pre-filled from invite, editable)
  Phone number (for Slack and notifications)
  All fields required before continuing.

Page 4 — Read your role document
  Renders their ROLE.md inline.
  Checkbox: "I have read and understand my role."
  Required before continuing.

Page 5 — Agreement
  One paragraph: company expectations, data handling,
  confidentiality, what happens if they leave.
  Checkbox: "I agree to the team member terms."
  Submit button: "Complete onboarding"

On submit:
  - team_members record updated: status = 'onboarding_complete'
  - All onboarding_steps marked complete
  - Owner gets HITL decision card:
    "[NAME] completed onboarding. Approve dashboard access?"
    Options: Approve / Reject / Review first

#### Owner approval

Approve:
  - team_members status → 'active'
  - Supabase user role set via custom claims
  - Slack invite sent automatically via Slack API
  - Practice task created and assigned
  - Welcome email sent: "You're in. Here's how to start."
  - Owner gets confirmation: "[NAME] is now active."

Reject:
  - team_members status → 'rejected'
  - Supabase account disabled immediately
  - Notification email: "Access not approved at this time."
  - No reason required in the email (owner's discretion)

#### Daily login (after onboarding)

URL: team.thdstack.com
Fields: email + password
Supabase Auth handles session.
Wrong role trying to access owner dashboard:
  Redirected to team.thdstack.com automatically.
Expired session: redirected to login, no data exposed.

#### Offboarding (when someone leaves)

Owner types in dashboard chat:
"Remove team member [NAME]"

System does automatically:
1. Confirmation card in HITL queue:
   "Remove [NAME] ([ROLE])? This cannot be undone."
   Options: Confirm removal / Cancel
2. On confirm:
   - Supabase Auth: deleteUser() — account gone
   - team_members status → 'deactivated',
     deactivated_at timestamp recorded
   - All assigned incomplete tasks: status → 'unassigned'
   - Owner gets task list: "These tasks need reassignment"
   - Slack API: kick user from all channels
   - GitHub: remove from repo collaborators if applicable
   - Personal folder in repo: archived, not deleted
     (task history preserved for reference)
3. Owner gets confirmation with summary:
   "[NAME] removed. [X] tasks need reassignment."
   Task reassignment cards appear in HITL queue.

Data retention: their task history, submissions, and
comments stay in the database for audit purposes.
Only their auth account and active access are deleted.

---

### Team folder structure

```
team/
├── _template/                    # Copy for every new hire
│   ├── ONBOARDING.md             # Welcome + first steps
│   ├── ROLE.md                   # What this role does
│   ├── HOW_TO_USE_TOOL.md        # Tool-specific guide
│   └── PRACTICE_TASK.md          # First task on dummy product
├── [son-name]/
│   ├── ONBOARDING.md             # Generated on invite
│   ├── ROLE.md                   # Claude Code Employee role
│   ├── HOW_TO_USE_CLAUDE_CODE.md # Plain-English Claude Code guide
│   ├── PRACTICE_TASK.md          # Practice build task
│   └── tasks/                    # Auto-generated per product
│       └── TASK_[product_id].md  # Their specific task file
├── [daughter-name]/
│   ├── ONBOARDING.md
│   ├── ROLE.md                   # Claude Design Employee role
│   ├── HOW_TO_USE_CLAUDE_DESIGN.md
│   ├── PRACTICE_TASK.md
│   └── tasks/
│       └── TASK_[product_id].md
└── [future-employee]/
    └── (same structure, generated on invite)
```

---

### Team dashboard — what they see

team.thdstack.com — role-scoped, same design system as
owner dashboard but stripped to their lane only.

CLAUDE_CODE_EMPLOYEE view:
```
Header: [NAME] | Role: Builder | [X] tasks active

Main panels:
  Left (40%):
    My Tasks (assigned to me, sorted by priority)
    Each task: product name | step I'm on | status |
    due date | Submit for review button

  Right (60%):
    Current task detail:
      Product brief summary
      Step-by-step task file rendered inline
      Mark step complete buttons
      File checklist (what to commit before submitting)
      Comments thread with owner

Footer bar:
  Practice sandbox link | How-to guide | Slack link
```

CLAUDE_DESIGN_EMPLOYEE view:
```
Header: [NAME] | Role: Designer | [X] tasks active

Main panels:
  Left (40%):
    My Tasks (assigned to me, sorted by priority)
    Each task: product name | which brief | status |
    due date | Submit for review button

  Right (60%):
    Current task detail:
      Design brief rendered inline (from DESIGN_[id].md)
      Output checklist (files to save before submitting)
      Design feedback from owner (if revision needed)
      Comments thread with owner

Footer bar:
  Asset library | How-to guide | Slack link
```

---

### Task submission and approval loop

#### They submit work

When they finish a task:
1. They click "Submit for review" in their dashboard
2. Submission form appears:
   - Notes field: "What did you do? Anything unusual?"
   - File checklist: confirm all required files saved
   - Submit button
3. Task status → 'submitted'
4. Owner gets HITL decision card:
   "[NAME] submitted [PRODUCT_NAME] [task_type] work.
    Notes: [their notes]
    Files: [checklist of what they submitted]"
   Options: Approve / Request revision / Reject

#### Owner approves

Task status → 'approved'
Next step activates:
  Code approved → triggers design file wait (if needed)
    or deploy step if design already done
  Design approved → notifies Employee 1 to implement
System posts in Slack: "@[name] your [task] was approved."

#### Owner requests revision

Task status → 'revision_needed'
Owner must provide specific feedback:
  "The landing page headline uses the word 'AI-powered'.
   Remove that and use the pain language from the brief.
   Specifically: use '[EXACT_PHRASE]'."
Feedback appears in their task dashboard with red border.
System posts in Slack: "@[name] revision needed on [task].
  Check your dashboard for feedback."
They revise and resubmit. Loop repeats.

#### Owner rejects entirely

Task status → 'rejected'
Owner provides reason.
Task reassigned or rebuilt from scratch.
Owner decides whether to reassign to same person or not.

---

### Onboarding agent spec

#### `agents/internal/onboarding_agent.py`

Triggers:
- "Invite [NAME] as [ROLE] — email [EMAIL]" in dashboard chat
- New team_members record created with status = 'invited'

Process:
1. Generate personal folder from _template:
   - Populate ONBOARDING.md with name, role, start date
   - Populate ROLE.md with role-specific content
   - Generate HOW_TO_USE_[TOOL].md from role type
   - Generate PRACTICE_TASK.md for a dummy product
   - Commit to repo under team/[name]/
2. Call Supabase Admin API to send invite email
3. Create onboarding_steps records for tracking
4. Post confirmation card to owner dashboard
5. Set 48-hour expiry reminder — if not completed,
   owner gets alert: "Invite to [NAME] expires in 4 hours"

On onboarding completion:
1. Create HITL approval card for owner
2. Prepare Slack invite (fire on owner approval)
3. Prepare practice task record (fire on owner approval)
4. Prepare welcome email (fire on owner approval)

On offboarding trigger:
1. Create confirmation HITL card
2. On owner confirm: execute full offboarding sequence
3. Generate task reassignment cards for all open tasks
4. Archive personal folder: team/[name]/archived/
5. Post summary to owner dashboard

---

### Slack integration

`leads/integrations/slack.py` (new file):
- invite_user(email, channels) → Slack API
- remove_user(slack_user_id) → Slack API
- post_message(channel, text) → Slack API
- create_channel(name) → Slack API if not exists

Channels created on first team member onboarding:
  #general — everyone
  #code-team — Claude Code Employees + Owner
  #design-team — Claude Design Employees + Owner
  #product-launches — all, for product go-live announcements

Automated Slack messages (never manual):
  "@[name] you've been assigned [PRODUCT] [task_type]"
  "@[name] your [task] was approved. Next step: [X]"
  "@[name] revision needed on [task]. Check dashboard."
  "#product-launches [PRODUCT_NAME] is live at [URL]"

Human messages: everything else. You handle in Slack.

---

### Build placement

Week 3, Session 12 — after dashboard hooks, before components:
1. Add team Supabase tables to 001_initial_schema.sql
2. Build team.thdstack.com Next.js app (separate from app.thdstack.com)
3. Build onboarding flow pages (5 pages, Supabase Auth)
4. Build role-scoped team dashboard (two views: Code + Design)
5. Build task submission and approval loop
6. Build onboarding_agent.py
7. Wire Slack integration
8. Build offboarding flow

Architectural note:
team.thdstack.com is a separate Next.js app in the monorepo.
It shares the Supabase instance and design system.
It does NOT share the owner dashboard components.
Keep them completely separate — different layouts,
different data access, different session handling.
A bug in team.thdstack.com must never expose
app.thdstack.com data.

---

Phase: NOT STARTED
Next action: Scaffold folder structure (Phase 1, Step 1)
Last session: —
Last deploy: —
Active products: 0
Platform MRR: $0

## CURRENT STATUS

Phase: NOT STARTED
Next action: Scaffold folder structure (Phase 1, Step 1)
Last session: —
Last deploy: —
Active products: 0
Platform MRR: $0
Team members: 0
