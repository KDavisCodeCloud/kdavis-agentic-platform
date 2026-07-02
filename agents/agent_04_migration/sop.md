# SOP — Agent 04: Legacy Code & Infrastructure Migration

**Version:** 1.0 | **Owner:** Platform Engineering | **Tier:** Growth, Enterprise

---

## Purpose

Agent 04 analyzes legacy code or infrastructure files and produces:
1. A complete migration plan (always)
2. Migrated/transformed source code (when feasible in a single file)
3. Two actionable options: PR with migrated code, or tracking issue with plan

This agent does **not** execute any changes autonomously. All output is reviewed and approved by a human operator before any GitHub action is taken (Governance Rule 11).

---

## Trigger

**Manual only** — Agent 04 is not webhook-driven.

```
POST /agents/agent_04_migration/run
Authorization: Bearer <workspace_token>
Content-Type: application/json

{
  "payload": {
    "repository": "acme/backend",
    "file_path": "src/api/routes.py",
    "file_content": "<raw source code>",
    "source_version": "flask 1.x",
    "target_version": "fastapi",
    "migration_context": "Migrating legacy Flask API to async FastAPI for K8s sidecar deployment"
  },
  "cloud_provider": "github"
}
```

**Required payload fields:**
| Field | Description |
|---|---|
| `repository` | `"owner/repo"` — GitHub repository |
| `file_path` | Path within the repo (e.g. `"src/api/routes.py"`) |
| `file_content` | Raw source code or config content (max 10,000 chars) |
| `source_version` | What we're migrating FROM (e.g. `"flask"`, `"terraform 0.12"`, `"python 2.7"`) |
| `target_version` | What we're migrating TO (e.g. `"fastapi"`, `"terraform 1.x"`, `"python 3.11"`) |

**Optional payload fields:**
| Field | Description |
|---|---|
| `migration_context` | Free-text description of the business context or migration goal |
| `source_type` | Override auto-detection: `"code"` / `"terraform"` / `"kubernetes"` / `"docker"` |
| `source_language` | Override auto-detection: `"python"` / `"hcl"` / `"yaml"` / etc. |

---

## Workflow

```
ingest → diagnose (LLM) → hitl_gate [PAUSE] → execute → complete
```

### 1. Ingest
- Extracts fields from payload
- Detects `source_language` from file extension (e.g. `.py` → `python`, `.tf` → `hcl`)
- Detects `source_type` from language and filename (e.g. `hcl` → `terraform`, `deployment.yaml` → `kubernetes`)
- Sanitizes source code with `shield.sanitize()` to remove secrets before LLM call
- Truncates content to 10,000 characters if larger (appends `[truncated]`)

### 2. Diagnose (LLM)
- Calls LLM via `.llm/router.py` with `task_type="code_migration"`
- LLM produces: `parsed_error`, `migrated_code`, `migration_plan`, `options`, `estimated_duration_seconds`
- Validates required option fields: `id`, `title`, `description`, `impact`, `docs_url`

### 3. HITL Gate (Governance Rule 11)
- Creates incident record in `incidents` table
- Sends `interrupt()` signal — **workflow pauses here**
- Operator reviews via dashboard at `GET /incidents/{id}`
- Operator approves via `POST /incidents/{id}/approve` with `selected_option`

### 4. Execute (Post-Approval Only)
- **opt_1 (Create PR)**: Creates a branch, commits migrated file, opens GitHub PR
- **opt_2 (Create Issue)**: Opens a GitHub issue with the migration plan and `migration`, `technical-debt` labels
- **hold**: No action taken; incident status set to `held`

### 5. Complete
- Marks incident as executed
- Writes final audit record

---

## Approval Options

| Option | When to Choose |
|---|---|
| **opt_1 — Create Migration PR** | LLM produced complete migrated code; single-file migration; ready to review in PR |
| **opt_2 — Create Issue** | Multi-file migration; large refactor; team needs to plan and divide work |
| **hold** | Migration is too complex for automated output; operator will handle manually |

---

## Security & Compliance

- **Credential Sanitization**: Source code passes through `shield.sanitize()` before LLM. Any detected secrets are replaced with `<REDACTED>`.
- **LLM Routing**: All LLM calls go through `.llm/router.py` — never direct SDK calls (Rule 6).
- **Audit Trail**: Every node writes to `audit_log` table (Rule 9).
- **Budget Guard**: `check_budget()` called before LLM with `estimated_tokens=8000` — fails safe if budget exceeded (Rule 10).
- **No Autonomous Execution**: `execute` node is only reached after `interrupt()` is resumed with operator approval (Rule 11).

---

## Supported Migration Patterns

| Pattern | Source | Target |
|---|---|---|
| Python upgrade | Python 2.7 | Python 3.11 |
| Web framework | Flask 1.x | FastAPI |
| IaC upgrade | Terraform 0.12 | Terraform 1.x |
| K8s API deprecations | extensions/v1beta1, apps/v1beta1 | apps/v1, networking.k8s.io/v1 |
| Container upgrade | Dockerfile (legacy syntax) | Multi-stage Dockerfile |
| Compose | Compose v2 schema | Compose v3+ |
| JS modules | CommonJS (require) | ESM (import/export) |
| Async | Callback-style async | async/await |

---

## Error Handling

| Error | Behavior |
|---|---|
| Missing `file_content` | Ingest returns error; workflow short-circuits |
| LLM parse failure | `error` field set; HITL gate skipped; incident not created |
| `GITHUB_TOKEN` missing | `execute_option` raises `EnvironmentError`; logged as error |
| GitHub API 4xx/5xx | Raises `RuntimeError`; execution status set to `failed` |
| Budget exceeded | `check_budget()` raises; workflow pauses; operator alerted |

---

## Escalation

If the LLM output appears incorrect or the migration plan is incomplete:
1. Select **hold** at the HITL gate
2. Use the `migration_plan` as a starting reference for manual migration
3. File a bug at the Cloud Decoded support portal
