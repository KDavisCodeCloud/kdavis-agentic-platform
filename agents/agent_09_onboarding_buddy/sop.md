# SOP — Agent 09: Context-Aware Onboarding & On-Call Buddy

**Version:** 1.0 | **Owner:** Platform / Engineering Enablement | **Tier:** Growth, Enterprise

---

## Purpose

Agent 09 synthesizes context-aware knowledge briefs for two audiences:

- **Onboarding engineers** — answers architecture, codebase, and process questions using the team's own GitHub documentation and runbooks
- **On-call engineers** — delivers rapid diagnostic briefs when someone is paged, surfacing relevant runbooks, past incident patterns, and specific commands to run

This agent **never publishes content autonomously**. All briefs are reviewed by an operator before being saved to GitHub Issues or posted to Slack (Governance Rule 11).

---

## Trigger

**Manual** — post a query via the API.

### Onboarding Example

```
POST /agents/agent_09_onboarding_buddy/run
Authorization: Bearer <workspace_token>
Content-Type: application/json

{
  "payload": {
    "query_type": "onboarding",
    "question": "How does the payment-service handle failed transactions? What retry logic is in place?",
    "service_name": "payment-service",
    "user_role": "new_engineer",
    "repository": "acme/backend",
    "slack_channel": "#eng-onboarding"
  },
  "cloud_provider": "aws"
}
```

### On-Call Example

```
POST /agents/agent_09_onboarding_buddy/run
Authorization: Bearer <workspace_token>
Content-Type: application/json

{
  "payload": {
    "query_type": "on_call",
    "question": "payment-service is returning 500s — error rate 23% over the last 5 minutes. Pod logs show DB connection pool exhaustion.",
    "service_name": "payment-service",
    "user_role": "on_call",
    "repository": "acme/backend",
    "slack_channel": "#incidents"
  },
  "cloud_provider": "aws"
}
```

---

## Payload Fields

**Required:**
| Field | Description |
|---|---|
| `question` | The user's question or alert text. Also accepted: `alert`, `incident_context` |

**Optional:**
| Field | Description |
|---|---|
| `query_type` | `"onboarding"` or `"on_call"` (auto-detected from question if omitted) |
| `service_name` | Service or component name — used for past incident lookup and GitHub search |
| `user_role` | `"new_engineer"` / `"on_call"` / `"manager"` / `"any"` (default: `"any"`) |
| `repository` | `"owner/repo"` — enables GitHub doc search and knowledge issue creation |
| `slack_channel` | `"#channel-name"` — optional Slack channel override for opt_2 |

---

## Query Type Auto-Detection

If `query_type` is not provided, the agent detects intent from the question text:
- Keywords like `alert`, `paged`, `down`, `degraded`, `latency`, `OOMKilled`, `timeout`, `error rate`, `pod failed` → `on_call`
- All other questions → `onboarding`

---

## Workflow

```
ingest → diagnose (knowledge retrieval + LLM) → hitl_gate [PAUSE] → execute → complete
```

### 1. Ingest
- Extracts query_type, question, service_name, user_role, repository
- Sanitizes the question via `shield.sanitize()` (removes secrets from alert text)
- Truncates question at 2,000 chars

### 2. Diagnose
- **Knowledge retrieval** (read-only, before LLM):
  - Searches GitHub for relevant files using `{service_name} {question}` as the query
  - Fetches up to 5 matching files (README, runbook, architecture docs)
  - Queries DB for past workspace incidents mentioning `service_name`
- **LLM synthesis** via `.llm/router.py` (`task_type="onboarding_support"`)
  - LLM receives: question, file contents, past incident summaries
  - Returns: `synthesized_response` (full Markdown), `key_findings` (2-3 sentences), `references`

### 3. HITL Gate (Governance Rule 11)
- Creates incident with question + key_findings as raw_log
- `interrupt()` pauses workflow — operator reviews synthesized brief in dashboard
- Approves via `POST /incidents/{id}/approve`

### 4. Execute (Post-Approval)
- **opt_1 — Save as Knowledge Issue**: Creates a GitHub issue with the full brief — searchable by future engineers and agents
- **opt_2 — Post to Slack**: Posts key findings + response to the configured Slack channel
- **hold**: No publishing; operator can copy-paste the response manually

### 5. Complete
- Marks incident as executed
- Writes final audit record

---

## Approval Options

| Option | When to Choose |
|---|---|
| **opt_1 — Save as Knowledge Issue** | For onboarding guides that should be preserved and searchable by the team |
| **opt_2 — Post to Slack** | For on-call briefs where speed matters and the team needs immediate visibility |
| **hold** | When the response needs editing before publishing, or publishing isn't needed |

---

## GitHub Integration — What Gets Searched

When a `repository` is provided, the agent searches for these patterns in the codebase:
- README files (`README.md`, `README.rst`)
- Architecture docs (`docs/`, `architecture.md`, `design.md`)
- Runbook files (`runbooks/`, `sre/`, `ops/`)
- Troubleshooting guides (`troubleshooting.md`, `debugging.md`)
- Service-specific docs (`{service_name}.md`, `services/{service}/`)

The GitHub Search API requires a `GITHUB_TOKEN` environment variable. Without it, knowledge retrieval is skipped (the LLM still runs without docs context).

---

## CI / Alertmanager Integration

For automated on-call triggers, configure your alerting system to POST directly to Agent 09:

**PagerDuty webhook mapping:**
```json
{
  "payload": {
    "query_type": "on_call",
    "question": "{{alert.summary}}: {{alert.description}}",
    "service_name": "{{alert.service}}",
    "user_role": "on_call",
    "repository": "acme/infra",
    "slack_channel": "#incidents"
  }
}
```

**Prometheus AlertManager webhook:**
```yaml
receivers:
  - name: cloud-decoded-buddy
    webhook_configs:
      - url: https://your-api.cloud-decoded.com/agents/agent_09_onboarding_buddy/run
        http_config:
          authorization:
            credentials: <workspace_token>
        send_resolved: false
```

---

## Security & Compliance

- **Sanitization**: Question/alert text passes through `shield.sanitize()` — secrets in alert text are redacted before reaching the LLM (Rule 6).
- **LLM Routing**: All LLM calls go through `.llm/router.py` (Rule 6).
- **Audit Trail**: Every node writes to `audit_log` table (Rule 9).
- **No Autonomous Publishing**: No issue is created and no Slack message is posted without operator approval (Rule 11).
- **Read-Only Knowledge Retrieval**: GitHub searches and file reads happen before the HITL gate — they are read-only operations that require no approval.

---

## Error Handling

| Error | Behavior |
|---|---|
| `GITHUB_TOKEN` missing | Knowledge retrieval skipped; LLM synthesizes with DB context only |
| GitHub Search API rate limit | Empty snippets; LLM proceeds without doc context |
| No past incidents found | LLM proceeds without incident context |
| `SLACK_WEBHOOK_URL` missing | opt_2 returns `skipped`; operator can use opt_1 instead |
| LLM parse failure | `error` set; HITL gate skipped; incident not created |
| Empty question | Defaults to no-context synthesis; LLM will note the missing input |
