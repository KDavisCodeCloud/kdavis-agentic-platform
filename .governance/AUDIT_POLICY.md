# Audit Policy — KDavis Agentic Platform

**Version:** 1.0.0
**Status:** Active
**This file is read-only. Agents may never modify it.**

---

## Purpose

Every action taken by every agent in this system is logged.
This is not optional. It is not configurable per client.
The audit trail is what makes the system trustworthy, defensible, and sellable.

---

## What Is Always Logged

### Before Every Action
- Timestamp
- Agent identity and workflow name
- Client slug
- Action about to be taken (specific, not vague)
- Reasoning for the action
- Expected outcome
- Rollback path if action fails

### After Every Action
- Actual outcome (success, failure, partial)
- Duration
- Any unexpected results
- Next planned step

### For Every LLM Call
- Provider used
- Model used
- Task type and tier
- Token count (prompt + completion)
- Estimated cost
- Duration

### For Every Escalation
- Full escalation message text
- Timestamp sent
- Channel delivered to
- Response received (A, B, or C)
- Responder identity
- Time to response
- Action taken after response

### For Every Incident
- Detection timestamp
- Classification (P1, P2, P3)
- All remediation attempts with outcomes
- Resolution timestamp
- Total time to resolution
- Root cause determination

---

## Where Logs Are Written

| Log Type | Location |
|----------|----------|
| Per-action audit | knowledge/clients/[slug]/audit-trail/[date].md |
| Incidents | knowledge/clients/[slug]/incidents/[incident-id].md |
| Escalations | knowledge/clients/[slug]/escalations/[escalation-id].md |
| LLM usage | knowledge/operator/llm-audit.md |
| System alerts | knowledge/operator/alerts.md |

All logs are append-only. Existing entries are never modified or deleted.

---

## What Is Never Logged

- Credential values, API keys, tokens, or passwords
- Personal data beyond what is necessary for incident context
- Internal business information from client systems beyond
  what is required to document the action taken

---

## Log Retention

- Client logs: retained for the duration of the engagement plus 12 months
- LLM audit log: retained indefinitely (cost tracking and model performance)
- System alerts: retained indefinitely

---

## Audit Trail as Client Deliverable

The knowledge/clients/[slug]/ vault is delivered to the client
at the end of each engagement as their permanent record.
Every action taken on their infrastructure is documented.
No CTA, no black box. Full transparency.

This is a feature, not a burden.
It is how the system justifies its retainer every month.
