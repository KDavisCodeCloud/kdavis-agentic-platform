# KDavis Agentic Platform — Knowledge Vault

This is the second brain and memory layer for the KDavis Agentic Platform.
Agents read from and write to this vault between sessions.
All files are plain Markdown — platform independent, Git tracked, always yours.

## Structure

| Folder | Purpose |
|--------|---------|
| _templates/ | Agent-readable templates for every document type |
| clients/ | One folder per client — onboarding, incidents, decisions, audit trail |
| operator/ | Personal brain — architecture decisions, pipeline, reviews, lessons |
| products/ | Product-specific notes and build logs |
| sops/ | Markdown source for all SOPs (compiled to .docx in /sops/) |

## Rules

1. Agents append, never overwrite existing entries
2. Every agent action is logged before it executes
3. Escalation logs are written before the human is contacted
4. This vault is backed up on every git commit — run scripts/backup-vault.sh weekly

## LLM Audit Log
Live at: operator/llm-audit.md
Every LLM call logged with provider, model, task type, and duration.
