# Agent 03 — PR Review for Architecture & Security
## Standard Operating Procedure

### Purpose
Agent 03 reviews GitHub pull requests for security vulnerabilities (OWASP Top 10),
architecture anti-patterns, and operational risk. It presents findings to the operator
and posts the approved review action (REQUEST_CHANGES, COMMENT, or APPROVE) to GitHub.

### Trigger Source
| Source | Webhook Endpoint | Event |
|--------|-----------------|-------|
| GitHub PR opened/updated | `POST /webhooks/github?token=<ws_token>` | `pull_request` (opened/synchronize/reopened) |

Agent 01 and Agent 03 share the same webhook URL — routing is based on X-GitHub-Event header.

### Workflow
```
PR webhook received
  └─ ingest_node      extract: owner, repo, pr_number, pr_title, author; fetch PR diff
  └─ diagnose_node    LLM review via .llm/router.py (task_type: code_review)
  └─ hitl_gate        INTERRUPT — operator approves one of 2-3 options
  └─ execute_node     approved option dispatched to PRReviewTools
  └─ complete_node    incident marked executed, audit trail finalized
```

### Review Options (post-approval execution)
| Option ID | GitHub Event | Description |
|-----------|-------------|-------------|
| opt_1 | REQUEST_CHANGES | Blocks the PR from merging |
| opt_2 | COMMENT | Informational — does not block merge |
| opt_3 | APPROVE | Approve with review comments attached |
| hold | — | No action, operator reviews manually |

### Required Workspace Configuration
| Env Variable | Purpose |
|-------------|---------|
| `GITHUB_TOKEN` | GitHub PAT with `pull-requests:write` permission |

### Governance
- Rule 11: No autonomous remediation — operator approves before any review is posted
- Rule 9: All actions logged to knowledge/operator/llm-audit.md
- Rule 6: All LLM calls route through .llm/router.py (task_type: code_review)
- Rule 10: On error, incident is marked failed — never posts to GitHub without approval
