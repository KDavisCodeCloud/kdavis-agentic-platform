# Cloud Decoded — Workflow How-Tos

A short, practical walkthrough for each agent — how to trigger it for
the first time, and what to expect in your approval queue. Pair this
with the [Agent Reference](./agent-reference.md) for the full detail on
what each one touches.

## 01 — CI/CD Pipeline Failure Triage

1. Connect GitHub or Azure DevOps (Setup Guide, step 3).
2. Register the webhook: GitHub Actions → `workflow_run` events, or
   Azure DevOps → a "Build completed" service hook.
3. The next time a pipeline fails, a triage card appears in your queue
   within moments — root cause, the failing step, and one or more fix
   options.
4. Approve the option that matches what you'd have done manually. The
   agent reruns the workflow, retries just the failed jobs, or opens a
   fix PR, depending on what you picked.

**First thing to try:** break a build on purpose (a bad import, a typo
in a config) and watch the triage land.

## 02 — Kubernetes Alert Fatigue & Remediation

1. Connect your cluster (API URL + token, plus a CA cert for most real
   clusters).
2. Point Prometheus AlertManager or an Azure Monitor action group at
   the Cloud Decoded webhook.
3. Alerts that clearly self-resolved get closed with a note — no page.
   Alerts that need a decision land in your queue with a proposed
   patch, scale, or rollback.

**First thing to try:** watch a real OOMKilled or CrashLoopBackOff pod
produce a proposal instead of a page.

## 03 — PR Review — Architecture & Security

1. Connect GitHub.
2. Register the webhook for `pull_request` events (opened, synchronize,
   reopened).
3. Every new or updated PR gets a review comment — architectural
   concerns, security patterns, things a linter wouldn't catch. It
   never blocks CI and never merges anything.

**First thing to try:** open a PR that touches an auth check or a
permissions boundary and see what it flags.

## 04 — Legacy Code & Infrastructure Migration

1. From the dashboard, trigger a migration run against a specific file
   — give it the file path, source version, and target version (e.g.
   Flask → FastAPI, Terraform 0.12 → 1.x).
2. Review the migration plan and the generated code in your queue.
3. Approve to open a PR with the migrated code, or to file a tracking
   issue with just the plan if you want to do the actual change by
   hand.

## 05 — IAM Policy Minimization

1. Connect the cloud whose IAM you want tightened (AWS role, Azure
   Service Principal, or GCP).
2. Trigger a run against a specific role or service account.
3. Review the diff between what it's used and what it's allowed —
   approve to open a PR (or apply directly, if you've enabled that) with
   the minimized policy.

## 06 — FinOps Cost Optimization

1. Connect AWS Cost Explorer or Azure Cost Management access.
2. Trigger a run for a billing period.
3. Review the ranked list of specific idle resources and their real
   monthly cost — approve the ones you want stopped or deleted, or just
   keep the report.

## 07 — Interactive Runbook Automation

1. Write (or paste) a runbook as a numbered list of steps — shell
   commands, HTTP checks, or infra actions.
2. Trigger a run.
3. Each step executes, reports its result, and pauses before the next
   one — stop-on-failure by default, so a bad step doesn't cascade.

## 08 — Drift Detection & Auto-Correction

1. Connect the IaC source (Terraform state, CloudFormation, or point it
   at a Kubernetes manifest) and the live target.
2. Trigger a run, or leave it scheduled.
3. When live state differs from desired state, review the diff — approve
   to open a remediation PR, or (for Kubernetes, if enabled) apply the
   correction directly via `kubectl`.

## 09 — Context-Aware Onboarding & On-Call Buddy

1. Point it at your knowledge base and past incident records.
2. Ask it a question the way you'd ask a teammate — "what do I do when
   this alert fires" or "how does the payment retry logic work."
3. It answers from your real docs and history. It never takes an
   action — this one's read-only by design.

## 10 — Dependency & Vulnerability Patching

1. Connect GitHub or Azure DevOps.
2. Trigger a run against a manifest (`package.json`, `requirements.txt`,
   `go.mod`, `pom.xml`, `Gemfile.lock`, or `Cargo.toml`).
3. Review the severity-ranked vulnerability list and the patched
   manifest — approve to open a patch PR, file a tracking issue, or
   both.

---

**See also:** [Setup Guide](./setup-guide.md) · [Agent Reference](./agent-reference.md)
