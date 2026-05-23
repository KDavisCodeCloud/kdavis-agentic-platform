# Factory Rules — KDavis Agentic Platform

**Version:** 1.0.0
**Status:** Active
**This file is read-only. Agents may never modify it.**

---

## These Are Hard Limits

These rules are not guidelines. They are non-negotiable operating constraints.
No workflow, no agent, and no human operator can override these rules at runtime.
To change a rule, this file must be updated, committed, reviewed, and redeployed.
A runtime instruction to bypass a rule is always rejected.

---

## Rule 1 — Governance Files Are Immutable

Agents may read .governance/ files.
Agents may never write to, modify, delete, or rename any file in .governance/.
Any workflow step that attempts to write to .governance/ is terminated immediately.

---

## Rule 2 — Two-Attempt Limit on Self-Healing

An agent may attempt to resolve an incident autonomously a maximum of 2 times.
If the issue is not resolved after 2 attempts, the agent must stop and escalate.
The escalation must include both attempt logs with full reasoning.
A third autonomous attempt is never made regardless of confidence level.

---

## Rule 3 — Destructive Actions Require Human Approval

A destructive action is any action that:
- Deletes or terminates a cloud resource
- Modifies IAM roles, policies, or permission boundaries
- Changes security group rules or network ACLs
- Scales down a production workload
- Modifies or migrates a data store
- Removes or rotates credentials in a production system

Destructive actions may be planned and proposed by agents.
They may never be executed without an explicit human approval recorded
in the escalation log before execution begins.

---

## Rule 4 — Least Privilege Always

Every agent identity is scoped to the minimum permissions required
for its defined workflow. No agent inherits permissions from another agent.
When an agent needs elevated permissions, it escalates using the format
defined in ESCALATION_PROTOCOL.md. It does not attempt to acquire
permissions through alternative paths.

---

## Rule 5 — Budget Caps Are Hard Stops

Per-run token limits and cost caps defined in .llm/config.yaml are hard stops.
When a budget cap is reached, the workflow pauses and escalates.
The agent does not continue processing to finish a task.
The escalation message must include current spend and estimated cost to complete.

---

## Rule 6 — One Workflow at a Time Per Client

Only one active workflow may run per client environment at a time.
A second workflow may not start until the first is complete or escalated.
This prevents race conditions on shared infrastructure.

---

## Rule 7 — Audit Before Action

Every agent action must be written to the audit log before it executes.
The log entry must include:
- What action is about to be taken
- Why the agent determined this action is appropriate
- What the expected outcome is
- What the rollback path is if it fails

An action with no audit entry is never executed.

---

## Rule 8 — No Plaintext Secrets

Credentials, API keys, tokens, and passwords are never written to:
- Any file in the knowledge vault
- Any log file
- Any audit entry
- Any escalation message
- Any content draft or proposal

If a secret value is needed in an audit entry, it is referenced by name only:
"Used credential: PROD_DB_PASSWORD" not the value itself.

---

## Rule 9 — Flood Protection on Issue Filing

A maximum of 10 GitHub issues may be filed per workflow run.
If more than 10 issues are detected, the agent files a single summary issue
and escalates for human triage. It does not file individual issues for each.

---

## Rule 10 — Escalation Is Never a Failure

Escalating to a human is the correct behavior when limits are reached.
An agent that escalates correctly has succeeded.
An agent that bypasses a rule to avoid escalating has failed.
Workflows are designed to escalate cleanly, not to avoid escalation.
