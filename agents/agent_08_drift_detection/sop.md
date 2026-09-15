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
| `drift_source` | `"terraform"` / `"kubernetes"` / `"cloudformation"` / `"arm_bicep"` / `"generic"` (auto-detected if absent) |
| `resource_type` | Resource type string (e.g., `aws_security_group`, `Deployment`, `AWS::EC2::SecurityGroup`) |
| `resource_id` | Resource identifier (name, ARN, or `namespace/name`) |
| `scope` | Region, namespace, or account for context |
| `repository` | `"owner/repo"` — enables PR and issue creation |
| `file_path` | Path to IaC/manifest file in repo — used for PR commits |

---

## Domain Coverage

Agent 08's ingest/diagnose pipeline is fully generic — any two JSON/YAML
blobs work through the same desired-vs-actual diff. These are
representative `resource_type` examples across the five infrastructure
domains in scope (IAM/RBAC/Policy, Networking, Storage, Compute,
Database-as-a-Service).

| Domain | AWS `resource_type` example | Azure `resource_type` example |
|---|---|---|
| IAM/RBAC/Policy | `aws_iam_role` (attached policy vs. IaC-defined; also: orphaned access keys with no IaC reference) | `azure_role_assignment` (RBAC assignments that exist live but shouldn't, or are missing) |
| Networking | `aws_security_group` (see the worked example above; also route table drift, VPC peering state — Security Group and route table both have dedicated live-state fetchers now, see below) | `azure_network_security_group` (NSG rule drift — flag as CRITICAL by default, this is the highest-severity drift category; also has a dedicated live-state fetcher, see below) |
| Storage | `aws_s3_bucket` (versioning/encryption/lifecycle/object-lock drift — dedicated live-state fetcher, see below) | `azure_storage_account` (access policy changed outside IaC, replication rules — dedicated live-state fetcher, see below) |
| Compute | `aws_instance` (instance type, auto-scaling min/max/desired, AMI version, tag compliance drift) | `azure_app_service` (see App Service content/config drift below — the one domain with a dedicated live-state fetcher instead of relying on the caller to supply `actual_state`) |
| Database-as-a-Service | `aws_db_instance` / `aws_dynamodb_table` (engine/instance-class drift, parameter group drift, backup-retention drift, DynamoDB billing-mode or GSI/LSI drift) | `azure_sql_database` / `azure_cosmosdb_account` (service-tier/DTU-vCore drift, firewall-rule drift, Cosmos DB throughput/RU drift) |

**GCP:** payload shape and `resource_type` conventions (e.g.
`google_compute_instance`, `google_storage_bucket`) are accepted the same
way any `generic` drift source is — the ingest/diagnose path doesn't care
which cloud a JSON blob describes. What's *not* built yet is a dedicated
GCP live-state fetcher (the way `fetch_cloudformation_stack` and
`fetch_app_service_state` exist for AWS/Azure) — a GCP `actual_state` has
to be fetched by the caller's own tooling and posted in, same as the CI
pattern below. This matches Agent 05's existing GCP treatment in this
platform: the payload shape and field mapping are documented, but no
per-workspace GCP credential connector exists to build collection against
yet.

### App Service content/config drift (Azure, dedicated fetcher)

Unlike every other domain above, this one doesn't require the caller to
fetch `actual_state` themselves — `DriftTools.fetch_app_service_state()`
calls it live via Azure's ARM (app settings) and Kudu VFS (deployed file
listing) APIs, using this workspace's stored Azure Service Principal
credential. Post only `desired_state` (what the deploy *should* have
produced — file manifest + app settings, sourced from the connected
repo's build output or IaC) and a `live_fetch` block instead of a real
`actual_state`:

```json
{
  "payload": {
    "drift_source": "generic",
    "resource_type": "azure_app_service",
    "resource_id": "acme-prod-app",
    "live_fetch": {
      "app_name": "acme-prod-app",
      "resource_group": "acme-prod-rg",
      "subscription_id": "00000000-0000-0000-0000-000000000000"
    },
    "desired_state": {
      "app_settings": { "API_KEY_REF": "@Microsoft.KeyVault(...)" },
      "files": ["index.js", "package.json", "web.config"]
    }
  },
  "cloud_provider": "azure"
}
```

This is what turns "an App Service doesn't have an uploaded file" or
"app settings are wrong / contain invalid JSON" into a normal drift item —
a missing file shows up as a `desired_state.files` entry absent from the
live listing, with the path it should be at; a bad app-settings value that
fails JSON validation (when JSON is expected) is flagged CRITICAL, never
silently accepted. See `prompts/diagnose.md` rules 8-9.

### Storage drift, dedicated fetchers (Phase 1, 2026-09-14)

`DriftTools.fetch_s3_bucket_state(bucket_name)` (AWS) and
`DriftTools.fetch_azure_blob_storage_state(storage_account_name,
resource_group, subscription_id)` (Azure) live-fetch the same way
`fetch_app_service_state` does — post `live_fetch` instead of
`actual_state`:

```json
{"live_fetch": {"bucket_name": "acme-prod-uploads"}}
```
```json
{"live_fetch": {"storage_account_name": "acmeprodstorage", "resource_group": "acme-prod-rg", "subscription_id": "..."}}
```

Both return a `findings` list computed directly from the live config
(versioning/encryption/Public Access Block/policy/replication for S3;
encryption/public network access/soft delete/replication SKU for Blob) —
these findings feed straight into the diagnose step's drift summary even
before any `desired_state` comparison, so a genuinely misconfigured
bucket/storage account is flagged even when the caller has no IaC
definition to diff against.

### Networking drift, dedicated fetchers (Phase 2, 2026-09-14)

Security Groups and NSGs are the highest-value, most commonly
misconfigured networking resource, so they're covered first (route
tables next):

```json
{"live_fetch": {"security_group_id": "sg-0a1b2c3d"}}
```
```json
{"live_fetch": {"nsg_name": "acme-prod-nsg", "resource_group": "acme-prod-rg", "subscription_id": "..."}}
```
```json
{"live_fetch": {"route_table_id": "rtb-0a1b2c3d"}}
```
```json
{"live_fetch": {"route_table_name": "acme-prod-rt", "resource_group": "acme-prod-rg", "subscription_id": "..."}}
```

`fetch_security_group_state` flags any inbound rule opening a sensitive
management/DB port (SSH 22, RDP 3389, MySQL 3306, PostgreSQL 5432, Redis
6379, Elasticsearch 9200, MongoDB 27017, Kibana 5601) — or all
ports/protocols — to `0.0.0.0/0`/`::/0`. `fetch_nsg_state` does the
equivalent for Azure NSGs, but with **effective-rule evaluation**: rules
are sorted by priority ascending and only the first rule matching a given
port+source is checked, matching how Azure itself evaluates NSG rules —
a lower-priority Deny correctly suppresses a finding that a naive
per-rule scan would have raised. Route table fetchers return raw routes
only (no findings computed yet — the "default route bypasses expected
gateway" check is comparison-driven, left to the LLM diagnose step
against a supplied `desired_state`, not hardcoded here).

**Agent 11 (health monitoring) integration:** rather than adding a new
polling path, AWS Security Group change alerts (via a CloudWatch Events/
EventBridge rule → SNS topic) and Azure NSG change alerts (via an Azure
Monitor Activity Log alert → Action Group) are ingested through the
*already-generic* `/webhooks/resource-health-alert` endpoint — it already
detects and handles both AWS SNS and Azure Monitor Common Alert Schema
payloads (see `api/routes/webhooks.py`). No endpoint changes were needed
for this; what was missing (and is now built) was Agent 08's ability to
independently verify what a Security Group/NSG's rules actually are once
an alert names one, which these fetchers now provide. See Agent 11's own
`sop.md` for the exact CloudWatch/Azure Monitor alert configuration.

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
