# Cloud Decoded — Agent Reference

What each agent does, what it needs connected, how it's triggered, and
what it requires your approval for before anything executes. Every agent
listed here is real and built — none of this is roadmap.

| # | Agent | Tier | Triggered by | Requires connected | Needs approval for |
|---|-------|------|---------------|---------------------|----------------------|
| 01 | **CI/CD Pipeline Failure Triage** | Starter | GitHub Actions / Azure DevOps webhook (failed run) | GitHub or Azure DevOps | Re-running the workflow, retrying a pipeline, opening a fix PR |
| 02 | **Kubernetes Alert Fatigue & Remediation** | Starter | Prometheus AlertManager or Azure Monitor webhook | Your cluster (API server + token) | Scaling, patching, or rolling back a deployment |
| 03 | **PR Review — Architecture & Security** | Starter | GitHub `pull_request` webhook | GitHub | Nothing — posts a review comment, never blocks or merges |
| 04 | **Legacy Code & Infrastructure Migration** | Growth+ | Manual, per file/module | GitHub or Azure DevOps | Opening the migration PR, or filing a tracking issue |
| 05 | **IAM Policy Minimization** | Growth+ | Manual or scheduled | AWS / Azure / GCP credentials | Applying the tightened policy |
| 06 | **FinOps Cost Optimization** | Growth+ | Manual, with a billing export | AWS / Azure cost data access | Stopping or deleting the specific idle resources found |
| 07 | **Interactive Runbook Automation** | Growth+ | Manual, against a written runbook | Whatever the runbook itself touches | Each step, individually — stop-on-failure by default |
| 08 | **Drift Detection & Auto-Correction** | Growth+ | Manual or scheduled | Terraform state / CloudFormation / Kubernetes | Opening a remediation PR, or `kubectl apply` if explicitly enabled |
| 09 | **Context-Aware Onboarding & On-Call Buddy** | Growth+ | Manual, chat-style questions | Your knowledge base / incident history (read-only) | Nothing — answers only, never takes action |
| 10 | **Dependency & Vulnerability Patching** | Growth+ | Manual or scheduled, per manifest | GitHub or Azure DevOps | Opening a patch PR, filing a tracking issue, or both |

## How every agent works, regardless of what it does

Every agent runs the same four-step shape:

1. **Ingest** — the triggering payload (a webhook, a manual request) is
   parsed and normalized.
2. **Diagnose** — an LLM call produces a diagnosis and a ranked list of
   remediation options. Anything sent to the LLM is sanitized first —
   credentials and PII are stripped before it leaves your workspace
   context.
3. **HITL gate** — the diagnosis and options are written to your
   approval queue. The agent pauses here. Nothing past this point
   happens without you.
4. **Execute** — only after you approve an option does the agent take
   the corresponding action, using credentials scoped to your workspace
   alone.

Every run — approved, held, or rejected — is written to an immutable
audit log with actor, action, outcome, and timestamp.

## Credential model, in one paragraph

Every credential you connect is scoped to your workspace and never
shared. GitHub access is a real App installation (fine-grained,
revocable from your own GitHub settings) or, for legacy connections, a
personal access token. AWS access is a cross-account role assumed fresh
on every call — never a stored access key. Azure access is a Service
Principal you control. Kubernetes access is a service-account token
scoped to what the agents actually need, verified against your real
cluster before it's ever stored.

---

**See also:** [Setup Guide](./setup-guide.md) · [Workflow How-Tos](./workflow-howtos.md)
