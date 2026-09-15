# Cloud Decoded — THD Agentic Systems LLC

**Autonomous DevOps agents for mid-market engineering teams.**

A multi-tenant B2B SaaS platform (`theclouddecoded.com`) that intercepts cloud/DevOps failures,
automatically diagnoses root cause, and presents remediation options on a Human-in-the-Loop
dashboard. No agent executes a fix autonomously — every change requires explicit operator
approval, tracked through to a real audit trail.

This repo is also the shared infrastructure layer for the rest of the THD Agentic Systems /
Decoded Empire portfolio (see [Other products in this repo](#other-products-in-this-repo)
below) — Cloud Decoded is the primary, currently-paid product built on top of it.

---

## Product Tiers

| Tier       | Price/mo | Agents | Repos | Cloud Providers |
|------------|----------|--------|-------|-----------------|
| Starter    | $299     | 3      | 2     | 1               |
| Growth     | $699     | 11     | 15    | AWS + Azure     |
| Enterprise | $2,499+  | Custom | Custom| VPC-deployed    |

BYOK (Bring Your Own provider Key) is required on all tiers. Tier limits are enforced centrally in
`core/compliance.py`'s `TIER_LIMITS` — never re-checked ad hoc elsewhere.

---

## The 11 Agents

| # | Agent | Category | Tier |
|---|-------|----------|------|
| 01 | CI/CD Pipeline Failure Triage | Reliability | Starter+ |
| 02 | Kubernetes Alert Fatigue & Remediation | Reliability | Starter+ |
| 03 | Automated PR Review (Architecture & Security) | Quality | Starter+ |
| 04 | Legacy Code & Infrastructure Migration | Modernization | Growth+ |
| 05 | IAM Policy Minimization — Least Privilege | Security | Growth+ |
| 06 | FinOps Cost Optimization | Cost | Growth+ |
| 07 | Interactive Runbook Automation | Operations | Growth+ |
| 08 | Drift Detection & Auto-Correction | Compliance | Growth+ |
| 09 | Context-Aware Onboarding & On-Call Buddy | DX | Growth+ |
| 10 | Automated Dependency & Vulnerability Patching | Security | Growth+ |
| 11 | Cloud Resource Health Monitoring (Azure Monitor Action Groups) | Reliability | Growth+ |

Each agent lives at `agents/agent_XX_<name>/` and implements a `workflow.py` resumable state
machine extending `agents/base_agent.py`.

---

## Architecture

```
Webhook/API event (api/routes/webhooks.py, incidents.py)
      │
      ▼
security/sanitizer.py (DataSanitizationShield — scrub PII/secrets before storage or use)
      │
      ▼
core/compliance.py (WorkspaceComplianceGuard — tier/seat/agent-permission check)
      │
      ▼
core/token_budget.py (TokenBudgetGuard — per-run spend/call circuit breaker)
      │
      ▼
agents/agent_XX/workflow.py (resumable state machine, checkpointed via
                              core/checkpointer_lock.py's LockedAsyncPostgresSaver)
      │
      ▼
providers/router.py (model provider call — NEVER import a provider SDK directly in agent code)
      │
      ▼
core/hitl.py (HITL gate — interrupt(), incident row written, await operator approval)
      │
 [Operator approves / resolves manually / holds via dashboard or POST /incidents/{id}/approve]
      │
      ▼
agents/agent_XX/workflow.py (Command(resume=...) re-enters at the exact checkpoint)
      │
      ▼
Execution + core/audit.py write_audit_event() (real audit_events DB row, per-tenant queryable)
      │
      ▼
core/notifications.py / core/ticketing.py (Slack/email + optional ticket creation on resolution)
```

The checkpoint's `thread_id` and the `incidents` table row's `id` are always the same
UUID — this is required for `Command(resume=...)` to find its checkpoint on approval. See
`tests/test_agent_workflow_conventions.py` for the static regression guard on this invariant.

---

## Governance Rules (non-negotiable)

- **Rule 3**: Options not orders — present choices, never execute unilaterally
- **Rule 6**: Provider-agnostic — all calls route through `providers/router.py`
- **Rule 9**: Audit trail — every agent/HITL action writes a real row to the `audit_events`
  table (`core/audit.py`), in addition to the legacy `knowledge/operator/llm-audit.md` markdown
  log kept for operator debugging
- **Rule 10**: Fail safe not fail open
- **Rule 11**: No autonomous remediation — HITL gate on every fix, including the "Handle
  manually" resolution path, which is an acknowledgment that a human handled it outside the
  platform — the platform still executes nothing itself

See `.governance/FACTORY_RULES.md` for the full rule set (read-only).

---

## Key backend subsystems

- **`core/hitl.py`** — the HITL gate: creates/dedupes incidents, pauses the graph, resolves via
  approve / hold / handle-manually, fires notifications and ticket creation on resolution.
- **`core/audit.py`** — writes real, per-tenant-queryable rows to the `audit_events` table
  (fire-and-forget via `asyncio.create_task()`, never raises back into a caller).
- **`core/ticketing.py`** — on incident resolution, optionally opens/updates a ticket in Jira,
  Linear, GitHub Issues, or ServiceNow (Enterprise), and resolves PagerDuty events.
- **`core/checkpointer_lock.py`** — `LockedAsyncPostgresSaver`, a single-connection,
  asyncio.Lock-guarded state checkpointer. Async-only — never call the sync
  `get_state()`/`get_tuple()` methods against it, only the `a*` variants.
- **`security/sanitizer.py`** — DataSanitizationShield; scrubs PII/secrets before anything
  touches storage or a model prompt.
- **`security/tenant_isolation.py`** — enforces `workspace_id` scoping on every query.
- **`db/migrate.py`** — runs `db/migrations/*.sql` automatically on every app boot (inside a
  `pg_advisory_xact_lock`-guarded transaction, tracked via a `schema_migrations` table). There is
  no manual migration step — do not run migration files by hand.
- **Workspace membership/RBAC/SSO/SCIM** (`api/routes/workspace_members.py`, `scim.py`,
  `db/migrations/034-036`) — per-workspace human members, roles, SSO config, and SCIM
  provisioning, layered on top of the original single `workspace_token` auth (which remains the
  path for webhooks/CI/MCP service-to-service calls).

---

## Local Dev Setup

Requires **Python 3.11+** specifically — the workflow engine's async node execution needs 3.11's
`contextvars` propagation into `asyncio.create_task()`; on 3.10 every agent's HITL `interrupt()`
call fails silently. See the top of `requirements.txt` for the full explanation.

```bash
# Clone and set up Python environment
git clone https://github.com/KDavisCodeCloud/kdavis-agentic-platform
cd kdavis-agentic-platform
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your keys — see inline comments in .env.example for where each
# credential comes from (Stripe dashboard, LinkedIn app, Supabase project, etc.)

# Start API server — applies pending db/migrations/*.sql automatically on boot
uvicorn api.main:app --reload --port 8000

# Start frontend
cd frontend && npm install && npm run dev

# Run the test suite (101 test files)
pytest
```

Production runs via `Procfile`: `uvicorn api.main:app --host 0.0.0.0 --port $PORT --workers 4`,
deployed on Railway. Frontend deploys on Vercel.

---

## Directory structure (top level, selective)

```
agents/            # 11 agent workflow.py state machines + base_agent.py
api/               # FastAPI app; api/routes/ has one file per resource
core/              # HITL, audit, checkpointing, compliance, ticketing, notifications
security/          # Sanitizer, tenant isolation
providers/         # Model provider adapters + providers/router.py (never import an SDK elsewhere)
db/                # migrate.py (auto-runner), migrations/*.sql, models.py
frontend/          # Next.js customer-facing dashboard (theclouddecoded.com)
mcp/               # Enterprise MCP server (OAuth-gated, per-workspace scoped)
tests/             # pytest — 101 files, asyncio_mode=auto
.governance/       # Non-negotiable rule set (read-only)
.llm/              # Provider router/config directory (swap providers in .llm/config.yaml only)
knowledge/operator/llm-audit.md  # Legacy append-only markdown audit log (kept alongside audit_events)
legal/             # License, proprietary notice, data processing terms
docs/customer/     # Security questionnaire response, DPA outline
GAPS.md            # Tracked gaps/future work, human-approved before being built
DECISIONS.md       # Architectural decisions log
```

---

## Other products in this repo

Two paid satellite products share this platform's core/security/providers layer and each have
their own top-level directory: `kdavis-finops-agent` and `kdavis-compliance-agent` (continuous
AWS/Azure cost and CIS-compliance monitoring). Several additional internal/portfolio tools also
live as sibling directories under `/mnt/c/Users/Kelvin/projects/` (empire dashboard, orchestrator,
DecodedSix, etc.) — each has its own README.

---

## DO NOT MODIFY

The following are read-only or managed by the platform engine:

- `.llm/` — provider router and provider configs (swap providers in `.llm/config.yaml` only)
- `.governance/` — Governance rules, escalation protocol, audit policy
- `knowledge/operator/llm-audit.md` — Append-only audit log

---

## Legal

This repository's source code is licensed under the **Business Source License 1.1** — see
`LICENSE` at the repo root. In short: free to read, copy, and modify for non-commercial or
evaluation use; you may not use it to run a competing commercial product or service. It converts
to Apache 2.0 on 2030-09-15.

The hosted Cloud Decoded product itself is governed separately by `legal/LICENSE.md` (the
customer EULA), `legal/PROPRIETARY_NOTICE.md`, and `legal/DATA_PROCESSING.md`.

Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

---

**Built by** [Kelvin Davis](https://www.linkedin.com/in/kelvin-davis) — flagship product: [Cloud Decoded](https://theclouddecoded.com)
