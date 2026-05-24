# PROMPT: new-workflow
# Usage: Paste this entire block into a new Claude conversation
# to generate a complete new workflow for the platform.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.
Private GitHub repo: KDavisCodeCloud/kdavis-agentic-platform

BUILD ME A NEW WORKFLOW:

Workflow name:     [name]
Trigger:           [github_issue | scheduled | manual | alert]
Schedule (if any): [cron expression]
Domain:            [devops | content | sales]
Agents involved:   [list agents this workflow orchestrates]
Environments:      [dev | staging | prod | all]
Client stack:      [what the client is running]

REQUIREMENTS — NON-NEGOTIABLE:
1. Every step writes to audit log before executing — Rule 7
2. HITL gate required for any state change — Rule 11
3. Max 2 read-only diagnostic attempts before escalating — Rule 2
4. One workflow at a time per client — Rule 6
5. Budget caps enforced per .llm/config.yaml — Rule 5
6. Environment promotion gates — dev → staging → prod — Rule 17
7. Pre-fix backup confirmation before any fix step — Rule 16
8. Escalation format per ESCALATION_PROTOCOL.md v1.1.0

BUILD THE FOLLOWING — IN ORDER:
1. workflows/[domain]/[name].yaml — full workflow definition
2. workflows/[domain]/run-[name].py — orchestrator script
3. GitHub label additions if new states are needed
4. knowledge/sops/[domain]/[name]-workflow.md — SOP in Markdown
5. SOP compiled as .docx
6. LinkedIn post
7. Client quote

QUOTE FORMAT: [same as new-agent prompt]
