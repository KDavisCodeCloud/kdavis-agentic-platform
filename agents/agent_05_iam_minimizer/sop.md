# SOP — Agent 05: IAM Policy Minimization

**Version:** 1.0 | **Owner:** Security Engineering | **Tier:** Growth, Enterprise

---

## Purpose

Agent 05 enforces least-privilege IAM by comparing a principal's **granted permissions** against its **observed API usage** and generating a minimized replacement policy. It eliminates the most common IAM misconfiguration in cloud environments: permissions granted during initial setup that were never revoked.

This agent does **not** apply any policy changes autonomously. All mutations require operator approval (Governance Rule 11).

---

## Trigger

**Manual only** — post to `/agents/agent_05_iam_minimizer/run`.

```
POST /agents/agent_05_iam_minimizer/run
Authorization: Bearer <workspace_token>
Content-Type: application/json

{
  "payload": {
    "principal_id": "arn:aws:iam::123456789012:role/AppRole",
    "principal_name": "AppRole",
    "resource_scope": "arn:aws:iam::123456789012:policy/AppPolicy",
    "current_policy": {
      "Version": "2012-10-17",
      "Statement": [...]
    },
    "access_log": [
      {"eventTime": "2026-06-01T10:00:00Z", "eventName": "s3:GetObject"},
      {"eventTime": "2026-06-01T10:01:00Z", "eventName": "logs:PutLogEvents"}
    ],
    "repository": "acme/infra"
  },
  "cloud_provider": "aws"
}
```

**Supported `cloud_provider` values:** `aws`, `azure`, `gcp`

**Required payload fields:**
| Field | Description |
|---|---|
| `principal_id` | ARN (AWS), object ID (Azure), or `serviceAccount:email` (GCP) |
| `current_policy` | Current IAM policy document (dict or JSON string) |

**Optional payload fields:**
| Field | Description |
|---|---|
| `principal_name` | Human-readable name (auto-derived from principal_id if omitted) |
| `principal_type` | `"role"` / `"user"` / `"service_account"` / `"group"` (auto-detected if omitted) |
| `resource_scope` | Policy ARN (AWS), subscription ID (Azure), or project ID (GCP) |
| `access_log` | List of API call dicts from CloudTrail / Activity Log / GCP Audit Log |
| `repository` | `"owner/repo"` — required only if opting for the PR-based review path |

---

## Workflow

```
ingest → diagnose (LLM) → hitl_gate [PAUSE] → execute → complete
```

### 1. Ingest
- Extracts principal_id, principal_type (auto-detected from ARN/member prefix), resource_scope
- Flattens `current_policy` into a permission summary via `_summarize_permissions()`
- Normalizes `access_log` into a text block (list of dicts or raw string)
- Sanitizes both via `shield.sanitize()` — strips secrets, retains resource ARNs
- Truncates: policy → 8,000 chars; access log → 6,000 chars

### 2. Diagnose (LLM)
- Calls LLM via `.llm/router.py` with `task_type="iam_minimization"`
- LLM compares granted vs. observed permissions
- Returns: `parsed_error`, `risk_score`, `permissions_removed`, `permissions_kept`, `minimized_policy`, `options`
- Validates required option fields: `id`, `title`, `description`, `impact`, `docs_url`

### 3. HITL Gate (Governance Rule 11)
- Creates incident with risk context (principal, risk_score, permissions_removed count)
- Sends `interrupt()` — **workflow pauses here**
- Operator reviews at `GET /incidents/{id}` (dashboard shows diff and risk score)
- Operator approves via `POST /incidents/{id}/approve`

### 4. Execute (Post-Approval Only)
- **opt_1 — Apply Directly**: Calls cloud-provider API to apply the minimized policy
  - AWS: `CreatePolicyVersion` (sets as default)
  - Azure: `PUT roleAssignments` (creates new minimized assignment)
  - GCP: `setIamPolicy` (replaces the full policy)
- **opt_2 — Create PR**: Commits minimized policy JSON to GitHub and opens PR
- **hold**: No action; incident status set to `held`

### 5. Complete
- Marks incident as executed
- Writes final audit record

---

## Approval Options

| Option | When to Choose |
|---|---|
| **opt_1 — Apply Directly** | High-confidence minimization; well-tested workload; CRITICAL risk warrants immediate action |
| **opt_2 — Create PR** | Policy change needs team review first; complex workload behavior; standard change management required |
| **hold** | Uncertain usage window; access log is incomplete; manually validate before applying |

---

## Risk Score

| Score | Meaning | Default Recommendation |
|---|---|---|
| **CRITICAL** | Unused admin/wildcard permissions on production | opt_1 after review |
| **HIGH** | Unused data-exfiltration or cross-account permissions | opt_1 or opt_2 |
| **MEDIUM** | Unused write permissions on non-critical resources | opt_2 |
| **LOW** | Minor scope reduction | opt_2 or hold |

---

## Security & Compliance

- **Credential Sanitization**: Policy docs and access logs pass through `shield.sanitize()` before LLM (Rule 6).
- **LLM Routing**: All calls go through `.llm/router.py` — never direct SDK calls (Rule 6).
- **Audit Trail**: Every node writes to `audit_log` table (Rule 9).
- **Budget Guard**: `check_budget(estimated_tokens=6000)` called pre-LLM (Rule 10).
- **No Autonomous Mutations**: `execute` node only reachable after `interrupt()` + operator approval (Rule 11).
- **Access Log Age**: Analysis is based on the last 30 days of logs. Permissions not seen in 30 days may still be needed. Always verify with the application team before applying CRITICAL changes.

---

## Getting the Access Log

### AWS (CloudTrail)
```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=Username,AttributeValue=<role-name> \
  --start-time 2026-05-27 \
  --output json \
  | jq '[.Events[] | {eventTime: .EventTime, eventName: .EventName}]'
```

### Azure (Activity Log)
```bash
az monitor activity-log list \
  --caller <object-id> \
  --start-time 2026-05-27 \
  --query "[].{time: eventTimestamp, action: operationName.value}" \
  --output json
```

### GCP (Audit Logs)
```bash
gcloud logging read \
  'protoPayload.authenticationInfo.principalEmail="sa@project.iam.gserviceaccount.com" AND timestamp>="2026-05-27T00:00:00Z"' \
  --format json \
  | jq '[.[] | {time: .timestamp, action: .protoPayload.methodName}]'
```

Pass the resulting JSON array as `access_log` in the payload.

---

## Error Handling

| Error | Behavior |
|---|---|
| Missing `current_policy` | Ingest uses empty dict; LLM flags as "policy unavailable" |
| Empty `access_log` | LLM retains full policy and sets risk_score "MEDIUM (unknown usage)" |
| LLM parse failure | `error` set; HITL gate skipped; incident not created |
| `AWS_ACCESS_KEY_ID` missing | `apply_aws_policy` raises `EnvironmentError`; logged |
| Cloud API 4xx/5xx | Raises `RuntimeError`; execution status set to `failed` |
| Budget exceeded | `check_budget()` raises; workflow pauses; operator alerted |

---

## Escalation

If the minimized policy appears incorrect:
1. Select **hold** at the HITL gate
2. Use the `permissions_kept` list as a starting point for manual policy construction
3. Re-run with a longer access log window (90 days recommended for seasonal workloads)

---

## Managed Identity Detection (Phase 3, 2026-09-14)

Standalone read-only checks in `IAMMinimizeTools`, separate from the
principal-minimization workflow above -- these don't go through the
ingest/diagnose/HITL/execute pipeline (there's no "correction" step;
they're detection only, the finding itself is the product). Call
directly, e.g. from a scheduled sweep or on-demand via the dashboard.

**Azure — orphaned identities:** `detect_orphaned_managed_identities(subscription_id)`
lists every user-assigned managed identity in the subscription
(`list_azure_managed_identities`, `Microsoft.ManagedIdentity/
userAssignedIdentities`) and cross-references each against its role
assignments (`get_azure_role_assignments`, already existed). An identity
with zero assignments is flagged orphaned -- created, once possibly
wired up, now doing nothing. System-assigned identities are out of
scope: they're tied 1:1 to their host resource's lifecycle and can't
outlive it the way a standalone user-assigned identity can.

**Azure — overpermissive identities:** `detect_overpermissive_managed_identities(subscription_id, expected_role_definition_ids)`
takes a caller-supplied IaC definition (`{principal_id: [role_definition_id, ...]}`,
built from the workspace's Terraform/Bicep `azurerm_role_assignment` /
`Microsoft.Authorization/roleAssignments` resources) and flags any
identity holding a role assignment NOT in its expected set. Identities
with no entry in `expected_role_definition_ids` are skipped, not
flagged -- this check only applies where the caller actually has an IaC
definition to compare against.

**AWS equivalent:** `list_aws_instance_profile_roles()` and
`list_lambda_execution_roles()` enumerate the AWS analogue of a managed
identity (an EC2 instance profile's role; a Lambda function's execution
role). `detect_overpermissive_aws_roles(role_arns, expected_actions)`
fetches each role's attached-managed-policy actions plus inline-policy
actions (`_summarize_permissions`, the same flattening the minimization
workflow already uses) and flags any action not in
`expected_actions[role_name]`. Same skip-if-no-IaC-entry behavior as the
Azure check.

All four return `{"error": ...}` on a missing/broken credential or API
failure rather than raising -- unlike this file's older single-call
fetchers (`get_azure_role_assignments` etc., which raise
`EnvironmentError`/`RuntimeError`), these are multi-call aggregations
where a partial result being useless is common, so the caller checks
`"error" in result` the same way Agent 08's live-state fetchers already
work. No new agent, no HITL gate -- these are read-only findings meant
to feed a future sweep/alert, same scope boundary as Agent 08's Phase
1/2 storage and networking fetchers.
