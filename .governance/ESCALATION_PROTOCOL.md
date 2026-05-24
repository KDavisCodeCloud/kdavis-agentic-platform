# Escalation Protocol — KDavis Agentic Platform
# Version: 1.1.0
# Status: Active
# This file is read-only. Agents may never modify it.
#
# CHANGELOG
# v1.0.0 — Initial escalation format with 3 options
# v1.1.0 — Full approval message format. Six options.
#           API version assessment. Documentation references.
#           Pre-fix backup status. Rollback plan.
#           Environment promotion path. Cost evaluation.
#           Effects of not fixing.

---

## When to Escalate

An agent must escalate when any of the following are true:

1. Any remediation action is required — Rule 11
2. Two read-only diagnostic attempts have failed — Rule 2
3. The next required action is destructive — Rule 3
4. The agent needs permissions beyond its defined scope — Rule 4
5. A budget cap has been reached — Rule 5
6. Backup confirmation has failed — Rule 16
7. DR backup status exceeds RPO before a prod fix — Rule 19
8. License validation has failed — Rule 20
9. An ambiguous situation exists with no approved resolution path
10. Confidence level in proposed fix is below acceptable threshold

---

## The Standard Approval Message Format

Every escalation message must follow this exact format.
No deviation. No omitting sections. No summarizing sections.
An incomplete approval message is never sent.

---

═══════════════════════════════════════════════════════════
APPROVAL REQUIRED
Workflow:     {workflow_name}
Client:       {client_name}
Environment:  {environment}
Severity:     {p1 | p2 | p3}
Timestamp:    {timestamp}
Escalation ID: {escalation_id}
═══════════════════════════════════════════════════════════

SUMMARY
{What is broken. How long it has been broken.
What is currently impacted. Affected resources listed by name.
No vague language. Specific and factual only.}

Affected resources:
- {resource_name} — {resource_type} — {cloud_provider}

---

PROPOSED FIX
{Exact steps the agent will execute if approved.
Numbered. Specific. Nothing vague.}

1. {step}
2. {step}
3. {step}

---

API VERSION ASSESSMENT
Current version in environment:  {current_version}
Latest stable version available: {latest_version}
Versions behind:                 {delta}

Recommendation: {upgrade now | upgrade planned | stay on current}
Reason: {why this recommendation}

Breaking changes between versions:
{summary of breaking changes or "none identified"}

Migration guide: {official link}
Upgrade effort estimate: {low | medium | high} — {reason}
Risk of staying on current version: {none | low | medium | high}
Risk reason: {why}

---

DOCUMENTATION REFERENCES
Primary fix documentation:  {official link}
API reference:              {official link}
Verified against version:   {exact version}
Documentation date:         {date}
Freshness status:           {current | DOCUMENTATION AGING — verify before approving}
Known issues with version:  {link or "none identified"}
Alternative approaches:     {link or "none identified"}

---

PRE-FIX BACKUP STATUS
Configuration snapshot:       {confirmed {timestamp} | not applicable}
Database backup:              {confirmed {timestamp} | not applicable}
Terraform state backup:       {confirmed {timestamp} | not applicable}
Kubernetes manifests export:  {confirmed {timestamp} | not applicable}
Pipeline config export:       {confirmed {timestamp} | not applicable}
IAM/RBAC config export:       {confirmed {timestamp} | not applicable}
Backup location:              {vault path or storage location}

{If any required backup failed:}
BACKUP FAILED — Fix cannot proceed until backup is confirmed.
Failed backup: {what failed and why}

---

ROLLBACK PLAN
If this fix fails or causes unexpected behavior:

1. {exact rollback step}
2. {exact rollback step}
3. {exact rollback step}

Estimated rollback time:      {X minutes}
Data loss risk on rollback:   {none | low | medium | high}
Data loss detail:             {what could be lost and why}
Rollback documentation:       {official link}

Automated rollback trigger:
If the validate agent detects active degradation after this
fix executes, automated rollback will begin immediately using
the pre-fix snapshot. You will be notified when rollback
completes.

---

COST EVALUATION
Current monthly cost:          ${current_cost}/month
Projected cost after fix:      ${projected_cost}/month
Monthly delta:                 ${delta}/month
One-time cost of this change:  ${one_time_cost}
Annual impact:                 ${annual_impact}/year

{If no cost impact:}
No cost impact identified for this fix.

---

EFFECTS OF NOT FIXING
1 hour:   {specific impact}
24 hours: {specific impact}
1 week:   {specific impact}

Data loss risk:       {none | low | medium | high} — {reason}
Availability impact:  {none | low | medium | high} — {reason}
Compliance risk:      {none | low | medium | high} — {reason}
Security risk:        {none | low | medium | high} — {reason}
Cost accumulation:    ${estimated_cost} if unresolved for 30 days

---

ENVIRONMENT PROMOTION PATH
Current environment:        {dev | staging | prod}
Previous environment:       {N/A | dev passed {timestamp} | staging passed {timestamp}}
Validation evidence:        {what passed in previous environment}
Next promotion gate:        {staging approval | prod approval | final — no further gates}

Emergency prod bypass:      {yes — reason: {reason} | no}
Bypass approved by:         {name and role if applicable}

---

OPTIONS
Review the above and respond with one of the following:

(A) Apply proposed fix to {environment} as described
    Agent executes immediately upon receiving this response.

(B) Apply custom fix — provide your instructions below
    Describe exactly what you want done. Agent will execute
    your instructions and confirm before proceeding.

(C) Deny — no action taken
    Issue remains open. Escalation closed. No changes made.

(D) Defer — pause and re-evaluate
    Specify defer duration: [X hours / X days]
    Agent will re-assess and re-escalate at that time.

(E) Approve fix AND approve API version upgrade
    Agent applies the fix and initiates the version upgrade
    in the same operation. Both are logged separately.

(F) Approve fix only — defer API version upgrade
    Agent applies the fix. Version upgrade filed as a
    separate ticket for scheduling.

No action is taken until you respond with A, B, C, D, E, or F.
Response B requires your custom instructions in the same message.
Response D requires your defer duration in the same message.

---

APPROVAL RECORD
Your response will be recorded in:
{knowledge/clients/{client_slug}/escalations/{escalation_id}.md}

Recorded fields:
- Your choice (A through F)
- Your identity and timestamp
- Any custom instructions provided
- Time from escalation sent to response received
- Action taken after response

---

SLA WINDOW
{severity} SLA for this client: {sla_window}
If no response received by {sla_deadline}:
Secondary contact {secondary_contact} will be notified.

═══════════════════════════════════════════════════════════

---

## What Is Never Acceptable in an Escalation

- Vague language — "something went wrong" is never acceptable
- Missing sections — every section above is required
- Action before response — agent never proceeds before receiving choice
- Repeated escalation for same issue without new information
- Escalating without first writing to the knowledge vault
- Sending notification before vault entry is confirmed written
- Providing error details that help client bypass license check

---

## Response Handling

(A) Agent proceeds with proposed fix. Logs approval with
    responder identity and timestamp before executing.

(B) Agent confirms custom instructions with responder before
    executing. One confirmation exchange only — then executes.

(C) Workflow closes. Audit entry written. No further action.

(D) Workflow pauses. Timer set. Agent re-assesses at defer time
    and sends a fresh approval message with updated status.

(E) Agent applies fix first. Validates fix. Then initiates
    version upgrade as a separate logged operation.

(F) Agent applies fix. Files version upgrade as new GitHub
    issue with label upgrade:recommended for scheduling.

---

## Escalation Delivery Order

This sequence is non-negotiable per Rule 7:

1. Write escalation to knowledge vault — confirmed
2. Write to audit trail — confirmed
3. Send notification to escalation channel
4. Start SLA timer

If step 1 or 2 fails — notification is not sent.
The vault record always exists before any external notification.

---

## No Response Handling

P1 — no response after 15 minutes:
  Notify secondary contact defined in client config.

P2 — no response after 2 hours:
  Notify secondary contact.

P3 — no response after 24 hours:
  Send reminder. Remain paused.

If secondary contact also does not respond within double
the original SLA window — workflow remains paused.
Agent never acts without a response. Ever.
