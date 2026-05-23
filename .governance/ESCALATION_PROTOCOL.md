# Escalation Protocol — KDavis Agentic Platform

**Version:** 1.0.0
**Status:** Active
**This file is read-only. Agents may never modify it.**

---

## When to Escalate

An agent must escalate when any of the following conditions are met:

1. Two autonomous fix attempts have failed (Rule 2)
2. The next required action is destructive (Rule 3)
3. The agent needs permissions beyond its defined scope (Rule 4)
4. A budget cap has been reached (Rule 5)
5. An ambiguous situation exists with no approved resolution path
6. A confidence level in a proposed fix is below acceptable threshold
7. Any condition not covered by approved operating procedures

---

## The Escalation Message Format

Every escalation message must follow this exact format.
No deviation. No summarizing. No omitting sections.

---

ESCALATION — [Workflow Name] — [Client Slug] — [Timestamp]

I need [specific permission or approval].

Here is why:
[One paragraph. Exact technical reason. No vague language.]

Without it:
[Exactly what breaks or stays broken. Specific impact.]

What I have already tried:
[Numbered list of attempts made, with outcomes.]

Options:
(A) [Grant the permission or approve the action] — [what the agent will do next]
(B) [Alternative path that avoids the blocker] — [tradeoffs of this path]
(C) Pause this workflow and escalate further — [who should be contacted]

Your choice determines next action. No action is taken until you respond.

---

## Where Escalations Are Sent

1. Written to knowledge/clients/[client-slug]/escalations/ immediately
2. Written to the audit trail at knowledge/clients/[client-slug]/audit-trail/
3. Delivered via the configured notification channel for the client
   (Slack, email, or PagerDuty — set in clients/[client-slug]/config.yaml)

The escalation is written to the vault BEFORE the notification is sent.
If the notification fails, the escalation record still exists.

---

## Response Handling

When the human responds with A, B, or C:

- Response A: Agent proceeds with the approved action. Logs approval with
  responder identity and timestamp before executing.
- Response B: Agent takes the alternative path. Logs the chosen alternative
  and begins execution.
- Response C: Workflow pauses. Agent writes final status to vault.
  No further autonomous action is taken until a human restarts the workflow.

If no response is received within the client SLA window:
- P1 incidents: escalate to secondary contact after 15 minutes
- P2 incidents: escalate to secondary contact after 2 hours
- P3 incidents: remain paused, reminder sent at 24 hours

---

## What Is Never Acceptable in an Escalation

- Vague language: "something went wrong" — always be specific
- Missing options: every escalation has exactly 3 options
- Action before response: the agent never proceeds before receiving a choice
- Repeated escalation for the same issue without new information
- Escalating without first writing to the knowledge vault
