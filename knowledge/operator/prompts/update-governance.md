# PROMPT: update-governance
# Usage: Paste this entire block into a new Claude conversation
# to update a governance file with new rules or changes.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.
Private GitHub repo: KDavisCodeCloud/kdavis-agentic-platform

UPDATE GOVERNANCE FILE:

File to update:    [FACTORY_RULES.md | ESCALATION_PROTOCOL.md |
                   MISSION.md | AUDIT_POLICY.md]
Current version:   [X.X.X]
New version:       [X.X.X]
Change reason:     [why this update is needed]

Changes to make:
[Describe exactly what needs to change — new rules, modified
rules, updated formats, new sections, etc.]

REQUIREMENTS:
1. Preserve all existing rules — never remove without explicit instruction
2. Update version number and changelog at top of file
3. File remains read-only after update — chmod 444
4. All active clients must be notified of governance changes

BUILD THE FOLLOWING — IN ORDER:
1. Updated governance file with changelog entry
2. Git commit message for the change
3. Notification message to send to all active clients
4. Updated SOP reflecting the governance change
5. Updated .docx SOP compiled to sops/
