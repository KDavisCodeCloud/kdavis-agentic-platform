# Cloud Decoded — THD Agentic Systems LLC

**Autonomous DevOps agents for mid-market engineering teams.**

A multi-tenant B2B SaaS platform that intercepts cloud/DevOps failures, diagnoses root cause using
AI, and presents remediation options on a Human-in-the-Loop dashboard. No agent executes a fix
autonomously — every change requires explicit operator approval.

---

## Product Tiers

| Tier       | Price/mo | Agents | Repos | Cloud Providers |
|------------|----------|--------|-------|-----------------|
| Starter    | $299     | 3      | 2     | 1               |
| Growth     | $699     | 10     | 15    | AWS + Azure     |
| Enterprise | $2,499+  | Custom | Custom| VPC-deployed    |

BYOK (Bring Your Own LLM Key) is required on all tiers.

---

## The 10 Agents

| # | Agent | Category |
|---|-------|----------|
| 01 | CI/CD Pipeline Failure Triage | Reliability |
| 02 | Kubernetes Alert Fatigue & Remediation | Reliability |
| 03 | Automated PR Review (Architecture & Security) | Quality |
| 04 | Legacy Code & Infrastructure Migration | Modernization |
| 05 | IAM Policy Minimization — Least Privilege | Security |
| 06 | FinOps Cost Optimization | Cost |
| 07 | Interactive Runbook Automation | Operations |
| 08 | Drift Detection & Auto-Correction | Compliance |
| 09 | Context-Aware Onboarding & On-Call Buddy | DX |
| 10 | Automated Dependency & Vulnerability Patching | Security |

---

## Architecture

```
Webhook/API event
      │
      ▼
core/security.py (DataSanitizationShield — scrub PII/secrets)
      │
      ▼
core/compliance.py (WorkspaceComplianceGuard — subscription check)
      │
      ▼
core/token_budget.py (TokenBudgetGuard — circuit breaker)
      │
      ▼
agents/agent_XX/workflow.py (LangGraph state machine)
      │
      ▼
.llm/router.py (LLM call — NEVER direct SDK import in agent code)
      │
      ▼
core/hitl.py (HITL gate — pause, save to DB, await approval)
      │
 [Operator approves via dashboard]
      │
      ▼
agents/agent_XX/workflow.py (resume with selected option)
      │
      ▼
Execution + audit log write
```

---

## Governance Rules (non-negotiable)

- **Rule 3**: Options not orders — present choices, never execute unilaterally
- **Rule 6**: LLM-agnostic — all calls route through `.llm/router.py`
- **Rule 9**: Audit trail — every action writes to `knowledge/operator/llm-audit.md`
- **Rule 10**: Fail safe not fail open
- **Rule 11**: No autonomous remediation — HITL gate on every fix

See `.governance/FACTORY_RULES.md` for the full rule set (read-only).

---

## Local Dev Setup

```bash
# Clone and set up Python environment
git clone https://github.com/KDavisCodeCloud/kdavis-agentic-platform
cd kdavis-agentic-platform
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your keys

# Apply database schema
psql $DATABASE_URL -f db/schema.sql

# Start API server
uvicorn api.main:app --reload --port 8000

# Start frontend
cd frontend && npm install && npm run dev
```

---

## DO NOT MODIFY

The following directories are read-only or managed by the platform engine:

- `.llm/` — LLM router and provider configs (swap providers in `.llm/config.yaml` only)
- `.governance/` — Governance rules, escalation protocol, audit policy
- `knowledge/operator/llm-audit.md` — Append-only audit log

---

## Legal

Proprietary and confidential. See `legal/LICENSE.md`, `legal/PROPRIETARY_NOTICE.md`, and
`legal/DATA_PROCESSING.md`.

Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
