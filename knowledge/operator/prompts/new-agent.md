# PROMPT: new-agent
# Usage: Paste this entire block into a new Claude conversation
# to generate a complete new agent for the platform.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.
Private GitHub repo: KDavisCodeCloud/kdavis-agentic-platform

CONTEXT FILES IN EFFECT:
- .governance/FACTORY_RULES.md v1.1.0 (Rules 1-21)
- .governance/ESCALATION_PROTOCOL.md v1.1.0
- .governance/MISSION.md
- .governance/AUDIT_POLICY.md
- .llm/config.yaml (LLM routing layer)
- .llm/router.py (all LLM calls route through this)

BUILD ME A NEW AGENT:

Agent name:        [name] (e.g. monitoring, storage, iac)
Domain:            [kubernetes | azure | aws | sql | terraform |
                   pipeline | security | networking | storage |
                   monitoring | migration | dr | finops]
Primary problems:  [list the specific problems this agent solves]
Cloud provider:    [aws | azure | gcp | multi]
Client stack:      [what the client is running]
Environments:      [dev | staging | prod | all]

REQUIREMENTS — NON-NEGOTIABLE:
1. All LLM calls route through .llm/router.py only
   Import: sys.path.insert(0, str(ROOT / ".llm")) then from router import complete
2. Apply FACTORY_RULES.md Rules 1-21 — especially Rule 11
   No autonomous fixes. Every remediation requires human approval.
3. Every approval message follows ESCALATION_PROTOCOL.md v1.1.0
   All sections required — summary, proposed fix, API version
   assessment, documentation references, pre-fix backup status,
   rollback plan, cost evaluation, effects of not fixing,
   environment promotion path, six options A-F.
4. Calls docs agent before generating any approval message
5. Calls backup agent before any fix is proposed
6. Read-only diagnostics only — never touch state without approval
7. Returns structured JSON output for orchestrator consumption
8. Full audit logging before every action

BUILD THE FOLLOWING — IN ORDER:
1. agents/devops/[name]-agent/agent.py — full working code
2. Add task_type entry to .llm/config.yaml
3. Workflow YAML step definition snippet
4. knowledge/sops/devops/[name]-agent.md — SOP in Markdown
5. SOP compiled as .docx to sops/devops/
6. LinkedIn post explaining what was built and why
7. Client quote (see quote format below)

QUOTE FORMAT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLIENT QUOTE
Client:       [Client Name]
Date:         [Date]
Prepared by:  Kelvin Davis — KDavis Agentic Platform
Quote ref:    [SLUG-YYYYMMDD-001]

SCOPE OF WORK
[What this agent does in plain business language]

LINE ITEMS
Initial Build Fee
[Agent name] agent deployment     $[X]
Configuration and testing         $[X]
SOP documentation                 $[X]
                        Subtotal: $[X]

Monthly Retainer (included in platform retainer)
[Agent name] monitoring           $[X]/mo
Incident response                 $[X]/mo
                        Subtotal: $[X]/mo

ROI REFERENCE
Without this agent:    [cost of the problem going undetected]
With this agent:       [what it catches and prevents]
Monthly savings:       $[X]/mo estimated

VALIDITY: 30 days. 50% deposit required to proceed.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
