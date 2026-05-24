# PROMPT: generate-sop
# Usage: Paste this entire block into a new Claude conversation
# to generate a SOP document for any platform component.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.
Private GitHub repo: KDavisCodeCloud/kdavis-agentic-platform

GENERATE A SOP DOCUMENT:

Component name:    [name]
Category:          [devops | content | sales | business-ops]
Version:           [1.0.0]
Audience:          [operator | client | both]
Related components:[list what this connects to]

Component description:
[Describe exactly what this component does, why it exists,
and what problems it solves.]

SOP REQUIREMENTS:
Every SOP must include all of the following sections:
1. Purpose
2. Prerequisites
3. Component files reference
4. Step-by-step instructions (numbered, specific, reproducible)
5. Configuration options table
6. Troubleshooting (top 5 failure modes with exact fixes)
7. Maintenance schedule table
8. Related components

FORMATTING:
- Navy and gold color scheme (#1B3A6B and #C9A84C)
- Title page with version, owner, component, date
- Page numbers in footer
- Tables for reference sections
- Warning boxes for critical notes
- Note boxes for important tips
- Arial font throughout
- Professional document suitable for client delivery

BUILD THE FOLLOWING:
1. knowledge/sops/[category]/[name].md — Markdown source
2. sops/[category]/[name].docx — compiled Word document
   ready for client delivery
