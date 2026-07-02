# SOP: CI/CD Pipeline Failure Triage (Agent 01)
# Cloud Decoded — THD Agentic Systems LLC

## Purpose

Agent 01 intercepts CI/CD pipeline failures from GitHub Actions and Azure DevOps,
diagnoses root cause using an LLM, and presents 2–3 remediation options to the operator
via the HITL dashboard. No remediation executes without operator approval.

## Trigger Sources

| Source | Event | Webhook Endpoint |
|--------|-------|-----------------|
| GitHub Actions | workflow_run (completed + failure) | POST /webhooks/github |
| Azure DevOps | Run state change (failed) | POST /webhooks/azure-devops |

## Workflow Steps

```
1. Webhook received
      ↓
2. HMAC signature validated (reject if invalid)
      ↓
3. DataSanitizationShield — scrub PII/secrets from log excerpt
      ↓
4. WorkspaceComplianceGuard — verify active subscription
      ↓
5. TokenBudgetGuard — verify monthly budget not exceeded
      ↓
6. LLM diagnosis call → .llm/router.py (task_type: issue_triage)
      ↓
7. Parse JSON response (parsed_error + options array)
      ↓
8. HITLGate.create_incident() → saved to DB (status: pending_approval)
      ↓
9. Return incident_id to API caller (202 Accepted)
      ↓
   [OPERATOR REVIEWS OPTIONS ON DASHBOARD]
      ↓
10. POST /incidents/{id}/approve with selected_option_id
      ↓
11. If selected == "hold": status → "held", workflow ends
    If selected == option: execute corresponding tool from tools.py
      ↓
12. HITLGate.mark_executed() → status → "executed"
      ↓
13. Audit log entry written
```

## Remediation Tools Available (post-approval only)

| Tool | What it does | When to use |
|------|-------------|-------------|
| `rerun_github_workflow` | Re-triggers a failed GitHub Actions run via REST API | Transient failures, flaky tests |
| `retry_azure_pipeline` | Re-queues a failed Azure DevOps pipeline run | Transient agent pool issues |
| `update_github_secret` | Updates a repository secret via GitHub REST API | Expired token / rotated credential |
| `post_github_pr_comment` | Posts a diagnostic comment on the triggering PR | Communication / visibility |

## Escalation Triggers

Escalate to operator immediately (do not auto-diagnose) if:
- Log excerpt is empty or contains only redacted content after sanitization
- Webhook signature validation fails
- Budget exceeded — pause, alert operator, set status to `budget_exceeded`
- Subscription status is not `active` or `trialing`

## Error Categories This Agent Handles

- Dependency install failures (npm, pip, yarn, cargo)
- Docker build failures (layer cache, base image, COPY errors)
- Test suite failures (infrastructure failures only — not logic bugs)
- Timeout errors (job timeout, runner contention)
- Auth failures (expired GITHUB_TOKEN, service connection issues)
- Kubernetes deploy step failures (post-CI deploy jobs)

## Error Categories This Agent Does NOT Handle

- Business logic bugs in application code (route to Agent 03 — PR Review)
- Cost spike alerts (route to Agent 06 — FinOps)
- K8s cluster-level alerts (route to Agent 02 — K8s Alert)
- Security vulnerabilities in dependencies (route to Agent 10 — Dependency Patch)

## SLA Targets

| Metric | Target |
|--------|--------|
| Time to diagnosis (webhook → incident created) | < 30 seconds |
| Diagnosis accuracy (correct root cause) | > 85% on first attempt |
| False positive rate (wrong escalations) | < 10% |

## Governance References

- Rule 11: No autonomous remediation — see `core/hitl.py`
- Rule 6: LLM calls only via `.llm/router.py` — see `agents/base_agent.py`
- Rule 9: Every action writes to audit log — see `core/hitl.py:_write_audit_entry`
- Rule 10: Budget exceeded → pause and alert, never fail open
