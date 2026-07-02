# SOP — Agent 07: Interactive Runbook Automation

**Version:** 1.0 | **Owner:** Platform / SRE | **Tier:** Growth, Enterprise

---

## Purpose

Agent 07 automates runbook execution by interpreting a runbook definition in the context of a triggering incident. The LLM filters irrelevant steps, flags high-risk operations, and produces a contextualized execution plan. The operator reviews and approves the plan before any step runs.

This agent does **not** execute any steps autonomously. All execution requires operator approval (Governance Rule 11).

---

## Trigger

**Manual or agent-to-agent** — post a runbook definition via API.

```
POST /agents/agent_07_runbook/run
Authorization: Bearer <workspace_token>
Content-Type: application/json

{
  "payload": {
    "runbook_name": "OOMKilled Recovery Runbook",
    "runbook_version": "1.2",
    "incident_context": "payment-service OOMKilled 4 times in 10 minutes, exit code 137, 512Mi limit",
    "trigger_source": "agent_02",
    "repository": "acme/ops",
    "steps": [
      {
        "id": "step-01",
        "name": "Check pod status",
        "type": "shell",
        "command": "kubectl get pods -n {{namespace}} -l app={{app_name}}",
        "on_failure": "continue",
        "timeout_seconds": 15
      },
      {
        "id": "step-02",
        "name": "Get pod logs",
        "type": "shell",
        "command": "kubectl logs -n {{namespace}} {{pod_name}} --tail=50 --previous",
        "on_failure": "continue",
        "timeout_seconds": 15
      },
      {
        "id": "step-03",
        "name": "Increase memory limit to 1Gi",
        "type": "kubectl",
        "kubectl_action": "apply",
        "namespace": "{{namespace}}",
        "manifest": "apiVersion: apps/v1\nkind: Deployment\n...",
        "on_failure": "stop",
        "timeout_seconds": 60,
        "risk_note": "Modifies production deployment memory limit"
      },
      {
        "id": "step-04",
        "name": "Notify team",
        "type": "notification",
        "channel": "slack",
        "message": "OOMKilled recovery applied to {{deployment_name}} in {{namespace}}",
        "on_failure": "continue"
      }
    ]
  },
  "cloud_provider": "aws"
}
```

**Required payload fields:**
| Field | Description |
|---|---|
| `runbook_name` | Human-readable name for this runbook |
| `steps` | List of step objects (see Step Schema below) |

**Optional payload fields:**
| Field | Description |
|---|---|
| `runbook_version` | Version string (default: `"1.0"`) |
| `incident_context` | Free-text description of the triggering incident for LLM contextualization |
| `trigger_source` | `"manual"` (default) or `"agent_01"` / `"agent_02"` etc. |
| `repository` | `"owner/repo"` — enables automatic execution report issue creation |

---

## Step Schema

Each step object supports the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique step identifier (used for `skip_to` references) |
| `name` | string | yes | Human-readable step name |
| `type` | string | yes | `"shell"` / `"http"` / `"kubectl"` / `"notification"` |
| `on_failure` | string | no | `"stop"` (default for mutations) / `"continue"` / `"skip_to:<id>"` |
| `timeout_seconds` | int | no | Max execution time (capped at 120s for shell) |
| `risk_note` | string | no | Operator-visible warning about this step |

**Type-specific fields:**

| Type | Extra Fields |
|---|---|
| `shell` | `command` (string with `{{variable}}` placeholders) |
| `http` | `method`, `url`, `headers` (dict), `body` (dict or string) |
| `kubectl` | `kubectl_action` (apply/delete/rollout/get/describe), `namespace`, `resource` or `manifest` |
| `notification` | `channel` (slack/github_comment), `message` (string with placeholders) |

**Template variables** (`{{...}}` in commands/messages) are substituted at execution time from the incident context. Undefined variables are left as-is.

---

## Workflow

```
ingest → diagnose (LLM) → hitl_gate [PAUSE] → execute → complete
```

### 1. Ingest
- Extracts runbook_name, version, trigger_source, repository
- Normalizes steps into canonical list (accepts list, dict with `steps` key, or JSON string)
- Capped at 50 steps per run
- Sanitizes step commands and incident context via `shield.sanitize()`
- Truncates: steps → 6,000 chars; incident context → 3,000 chars

### 2. Diagnose (LLM)
- Calls LLM via `.llm/router.py` with `task_type="runbook_automation"`
- LLM produces: `execution_plan` (filtered/ordered steps), `skipped_steps`, `plan_summary`, `options`
- Returns full step objects with original fields intact — LLM does not modify commands

### 3. HITL Gate (Governance Rule 11)
- Creates incident with runbook + step count context
- Sends `interrupt()` — **workflow pauses here**
- Operator reviews: step list, skip reasoning, risk notes
- Approves via `POST /incidents/{id}/approve`

### 4. Execute (Post-Approval Only)
- **opt_1 — Execute Plan**: Runs all steps sequentially via `execute_runbook_plan()`
  - Respects `on_failure`: stop | continue | skip_to:<id>
  - Each step result recorded (stdout, stderr, exit_code, status_code)
  - After completion, creates a GitHub execution report issue (if repository configured)
- **opt_2 — Dry-Run Issue**: Creates GitHub issue with the plan — no steps executed
- **hold**: No execution; incident set to `held`

### 5. Complete
- Marks incident as executed
- Writes final audit record

---

## Approval Options

| Option | When to Choose |
|---|---|
| **opt_1 — Execute** | Plan looks correct; ready to run automatically |
| **opt_2 — Dry-Run Issue** | Want team review before execution; runbook is new or untested |
| **hold** | Plan is wrong; will execute manually with the plan as a guide |

---

## Security & Compliance

- **Sanitization**: Step commands and incident context pass through `shield.sanitize()` before LLM (Rule 6).
- **Shell Safety**: Shell commands use `shlex.split()` — never `shell=True`. User input is never interpolated as shell arguments.
- **Step Cap**: Maximum 50 steps per run; additional steps are silently dropped with a log warning.
- **Timeout Cap**: Shell step timeout is capped at 120 seconds regardless of what the step specifies.
- **LLM Routing**: All LLM calls go through `.llm/router.py` (Rule 6).
- **Audit Trail**: Every node writes to `audit_log` table (Rule 9).
- **No Autonomous Execution**: No step runs without `interrupt()` + operator approval (Rule 11).

---

## Error Handling

| Error | Behavior |
|---|---|
| 0 runbook steps | LLM sets `execution_plan=[]`; opt_1 returns "skipped" |
| Shell command timeout | Step result: `status=failed`, `error="timed out"`, `on_failure` applied |
| HTTP step non-2xx | Step result: `status=failed`; `on_failure` applied |
| `GITHUB_TOKEN` missing | `create_runbook_issue` raises `EnvironmentError`; logged; execution result still returned |
| LLM parse failure | `error` set; HITL gate skipped; incident not created |
| Budget exceeded | `check_budget()` raises; workflow pauses; operator alerted |

---

## Runbook Library

Store runbooks as JSON files in your repository under `runbooks/`:

```
runbooks/
  oomkilled-recovery.json
  high-cpu-response.json
  disk-full-cleanup.json
  deployment-rollback.json
```

Submit via the API using `cat runbooks/oomkilled-recovery.json | jq '{runbook_name: .name, runbook_version: .version, steps: .steps}'`.
