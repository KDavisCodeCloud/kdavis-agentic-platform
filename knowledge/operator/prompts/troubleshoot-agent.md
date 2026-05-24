# PROMPT: troubleshoot-agent
# Usage: Paste this entire block into a new Claude conversation
# when an agent is behaving unexpectedly or failing.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.
Private GitHub repo: KDavisCodeCloud/kdavis-agentic-platform

TROUBLESHOOT THIS AGENT:

Agent name:        [name]
Agent file:        [agents/devops/[name]-agent/agent.py]
Problem:           [describe exactly what is going wrong]
Error message:     [paste the full error or unexpected output]
Expected behavior: [what should have happened]
Actual behavior:   [what actually happened]
Last working:      [when did it last work correctly]

ENVIRONMENT:
- OS: WSL Ubuntu 22.04
- Python: 3.x
- Active provider: anthropic
- ANTHROPIC_API_KEY: set

AUDIT TRAIL:
[Paste relevant entries from knowledge/clients/[slug]/audit-trail/]

PROVIDE:
1. Root cause analysis
2. Exact fix with commands to run
3. Verification step to confirm fix worked
4. Whether governance rules were violated
5. Whether the issue needs a rule update in FACTORY_RULES.md
6. Updated agent code if needed
7. Test to prevent recurrence
