# SOP — Agent 08: Drift Detection & Auto-Correction

**Version:** 1.0 | **Owner:** Platform / SRE | **Tier:** Growth, Enterprise

---

## Purpose

Agent 08 detects configuration drift between the declared desired state (IaC or Git) and the actual live infrastructure state. It identifies every differing field, classifies severity (CRITICAL → LOW), generates corrected content, and presents the operator with remediation options before any change is applied.

This agent does **not** apply any correction autonomously. All remediation requires operator approval (Governance Rule 11).

---

## Trigger

**Manual or CI-scheduled** — post state snapshots via the API after fetching them with your preferred tooling.

```
POST /agents/agent_08_drift_detection/run
Authorization: Bearer <workspace_token>
Content-Type: application/json

{
  "payload": {
    "drift_source": "terraform",
    "resource_type": "aws_security_group",
    "resource_id": "sg-0a1b2c3d4e5f67890",
    "scope": "us-east-1",
    "repository": "acme/infra",
    "file_path": "terraform/security_groups.tf",
    "desired_state": {
      "resource_type": "aws_security_group",
      "name": "web-sg",
      "ingress": [
        { "from_port": 443, "to_port": 443, "protocol": "tcp", "cidr_blocks": ["10.0.0.0/8"] }
      ],
      "egress": [
        { "from_port": 0, "to_port": 0, "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"] }
      ]
    },
    "actual_state": {
      "GroupId": "sg-0a1b2c3d4e5f67890",
      "GroupName": "web-sg",
      "IpPermissions": [
        { "FromPort": 443, "ToPort": 443, "IpProtocol": "tcp",
          "IpRanges": [{ "CidrIp": "0.0.0.0/0" }] }
      ]
    }
  },
  "cloud_provider": "aws"
}
```

**Required payload fields:**
| Field | Description |
|---|---|
| `desired_state` | Desired resource state (from IaC/Git). Also accepted: `terraform_state`, `k8s_manifest`, `cfn_template` |
| `actual_state` | Live resource state (from cloud API). Also accepted: `live_state`, `k8s_live_resource`, `cfn_stack` |

**Optional payload fields:**
| Field | Description |
|---|---|
| `drift_source` | `"terraform"` / `"kubernetes"` / `"cloudformation"` / `"generic"` (auto-detected if absent) |
| `resource_type` | Resource type string (e.g., `aws_security_group`, `Deployment`, `AWS::EC2::SecurityGroup`) |
| `resource_id` | Resource identifier (name, ARN, or `namespace/name`) |
| `scope` | Region, namespace, or account for context |
| `repository` | `"owner/repo"` — enables PR and issue creation |
| `file_path` | Path to IaC/manifest file in repo — used for PR commits |

---

## How to Pre-fetch State

### Terraform

```bash
# Fetch desired state (from HCL or state file)
terraform show -json terraform.tfstate | jq '.values.root_module.resources[] | select(.address == "aws_security_group.web")'

# Fetch actual state (AWS CLI)
aws ec2 describe-security-groups --group-ids sg-0a1b2c3d4e5f67890 --region us-east-1
```

### Kubernetes

```bash
# Desired state (from Git/Helm)
cat kubernetes/deployment.yaml | yq -o json

# Actual live state
kubectl get deployment payment-service -n production -o json
```

### CloudFormation

```bash
# Desired state (template)
cat infra/cloudformation/template.yaml

# Actual state
aws cloudformation describe-stack-resources --stack-name my-stack
```

---

## Workflow

```
ingest → diagnose (LLM) → hitl_gate [PAUSE] → execute → complete
```

### 1. Ingest
- Detects drift source from payload keys or explicit `drift_source` field
- Normalizes desired and actual state to text representation (JSON/YAML → string)
- Sanitizes both state blobs via `shield.sanitize()` before LLM consumption
- Truncates each state blob to 6,000 chars for LLM context efficiency

### 2. Diagnose (LLM)
- Calls LLM via `.llm/router.py` with `task_type="drift_detection"`
- LLM identifies all drift items with severity, generates corrected content
- Returns: `drift_items`, `drift_severity`, `drift_summary`, `corrected_content`, `options`
- Overall severity = highest individual item severity

### 3. HITL Gate (Governance Rule 11)
- Creates incident with drift details and severity
- Sends `interrupt()` — **workflow pauses here**
- Operator reviews: drift items, severity, top 5 items in raw log
- Approves via `POST /incidents/{id}/approve`

### 4. Execute (Post-Approval Only)
- **opt_1 — Remediation PR**: Opens GitHub PR with corrected IaC/manifest content (5-step flow)
- **opt_2 — Apply Directly**: `kubectl apply` for Kubernetes; PR for Terraform/CloudFormation
- **opt_3 — Create Issue**: GitHub issue documenting drift, no correction applied
- **hold**: No execution; incident set to `held`

### 5. Complete
- Marks incident as executed
- Writes final audit record

---

## Approval Options

| Option | When to Choose |
|---|---|
| **opt_1 — Remediation PR** | Always the safest choice. Gives team visibility before merging |
| **opt_2 — Apply Directly** | K8s only: production is actively degraded and fix is low-risk. For IaC sources, creates a PR |
| **opt_3 — Drift Issue** | Drift is acceptable/known and should be tracked without correction |
| **hold** | Plan is wrong; needs manual correction with this report as a guide |

---

## Security & Compliance

- **Sanitization**: State blobs pass through `shield.sanitize()` before LLM (Rule 6).
- **No Direct IaC Apply**: Agent never runs `terraform apply` or `aws cloudformation deploy`. For Terraform/CloudFormation, correction always goes through a PR.
- **kubectl Safety**: Manifests applied via stdin to `kubectl apply -f -`; never `shell=True`.
- **LLM Routing**: All LLM calls go through `.llm/router.py` (Rule 6).
- **Audit Trail**: Every node writes to `audit_log` table (Rule 9).
- **No Autonomous Execution**: No correction runs without `interrupt()` + operator approval (Rule 11).

---

## Error Handling

| Error | Behavior |
|---|---|
| Desired state empty | LLM sets `drift_severity=UNKNOWN`; operator can still create a tracking issue |
| Actual state empty | LLM reports cannot compare; `opt_3` (issue) recommended |
| kubectl not on PATH | `apply_k8s_manifest()` returns `status=failed`; logged; use PR path instead |
| `GITHUB_TOKEN` missing | `create_drift_pr`/`create_drift_issue` raise `EnvironmentError`; logged |
| LLM parse failure | `error` set in state; HITL gate skipped; incident not created |
| No drift (0 items) | `drift_severity=NONE`; opt_3 (issue) or hold are most appropriate |

---

## CI Integration (Scheduled Drift Detection)

Run drift checks on a schedule using a CI job that:

1. Fetches desired state from Git
2. Fetches actual state from cloud API
3. Posts both to `POST /agents/agent_08_drift_detection/run`
4. Polls `GET /incidents?agent=agent_08_drift_detection&status=pending_approval`
5. Sends notification to Slack/PagerDuty with drift summary and approval link

Example GitHub Actions workflow:

```yaml
name: Drift Detection
on:
  schedule:
    - cron: '0 */6 * * *'   # every 6 hours

jobs:
  drift-check:
    runs-on: ubuntu-latest
    steps:
      - name: Fetch desired state
        run: terraform show -json > desired.json
      - name: Fetch actual state
        run: aws ec2 describe-security-groups --group-ids $SG_ID > actual.json
      - name: Post to Cloud Decoded
        run: |
          curl -X POST $CLOUD_DECODED_API/agents/agent_08_drift_detection/run \
            -H "Authorization: Bearer $WORKSPACE_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{
              \"payload\": {
                \"drift_source\": \"terraform\",
                \"resource_id\": \"$SG_ID\",
                \"repository\": \"$GITHUB_REPOSITORY\",
                \"file_path\": \"terraform/security_groups.tf\",
                \"desired_state\": $(cat desired.json),
                \"actual_state\": $(cat actual.json)
              },
              \"cloud_provider\": \"aws\"
            }"
```
