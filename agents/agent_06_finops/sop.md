# SOP — Agent 06: FinOps Cost Optimization

**Version:** 1.0 | **Owner:** FinOps / Platform Engineering | **Tier:** Growth, Enterprise

---

## Purpose

Agent 06 analyzes cloud billing data and idle resource inventory to identify cost waste and produce a prioritized list of savings recommendations. It estimates monthly and annual savings for each opportunity and classifies them by effort and risk.

This agent does **not** stop, delete, or modify any resources autonomously. All resource mutations require operator approval (Governance Rule 11).

---

## Trigger

**Manual only** — submit billing data via POST.

```
POST /agents/agent_06_finops/run
Authorization: Bearer <workspace_token>
Content-Type: application/json

{
  "payload": {
    "billing_period": "2026-06",
    "account_id": "123456789012",
    "cost_data": { <Cost Explorer / Azure Cost Management / GCP Billing response> },
    "resource_inventory": {
      "instance_ids": ["i-0abc123"],
      "volume_ids": ["vol-0xyz"],
      "allocation_ids": ["eipalloc-0abc"]
    },
    "repository": "acme/infra",
    "currency": "USD"
  },
  "cloud_provider": "aws"
}
```

**Required payload fields:**
| Field | Description |
|---|---|
| `billing_period` | Billing period string (e.g. `"2026-06"` or `"2026-05-01/2026-05-31"`) |
| `account_id` | AWS account ID, Azure subscription ID, or GCP project ID |
| `cost_data` | Raw JSON from the cloud billing API (see below for fetch commands) |

**Optional payload fields:**
| Field | Description |
|---|---|
| `resource_inventory` | Dict of idle resource IDs — enables `opt_2` (quick wins) |
| `repository` | `"owner/repo"` — required for `opt_1` (GitHub issue) |
| `currency` | `"USD"` (default), `"EUR"`, `"GBP"` |

---

## Workflow

```
ingest → diagnose (LLM) → hitl_gate [PAUSE] → execute → complete
```

### 1. Ingest
- Extracts billing_period, account_id, repository, currency
- Normalizes cost_data JSON into a per-service text table (cloud-specific parsing)
- Computes total_spend from the cost data
- Normalizes resource_inventory to a text block
- Sanitizes both via `shield.sanitize()` before LLM
- Truncates: cost_data → 8,000 chars; resource_inventory → 4,000 chars

### 2. Diagnose (LLM)
- Calls LLM via `.llm/router.py` with `task_type="finops_optimization"`
- Returns: `parsed_error`, `cost_report`, `recommendations`, `quick_win_resources`, `estimated_monthly_savings`, `options`
- Recommendations ranked by savings descending; each has `effort` and `risk` classification

### 3. HITL Gate (Governance Rule 11)
- Creates incident with spend context (period, total spend, estimated savings)
- Sends `interrupt()` — **workflow pauses here**
- Operator reviews at `GET /incidents/{id}`
- Operator approves via `POST /incidents/{id}/approve`

### 4. Execute (Post-Approval Only)
- **opt_1 — GitHub Issue**: Creates a cost report issue with `finops`, `cost-optimization` labels
- **opt_2 — Quick Wins**: Stops/deletes idle resources from `quick_win_resources`:
  - AWS: StopInstances, DeleteVolume, ReleaseAddress
  - Azure: Deallocate VMs, Delete unattached managed disks
  - GCP: Stop GCE instances
- **opt_3 — Slack Alert**: Posts cost summary to configured webhook
- **hold**: No action; incident status set to `held`

### 5. Complete
- Marks incident as executed
- Writes final audit record

---

## Approval Options

| Option | When to Choose |
|---|---|
| **opt_1 — GitHub Issue** | Want team visibility and tracking; not ready to apply changes yet |
| **opt_2 — Quick Wins** | Confident the listed idle resources are unused; stop them immediately |
| **opt_3 — Slack Alert** | Need to notify the team; will follow up manually |
| **hold** | Need more investigation before acting |

> **IMPORTANT for opt_2:** Quick-win resources are pre-screened by the LLM as LOW effort + LOW risk. Before approving, verify the resource_inventory came from your monitoring tools (CloudWatch, Azure Monitor, etc.), not guessed by the LLM. The LLM will only populate `quick_win_resources` from data explicitly provided in the payload.

---

## Getting the Billing Data

### AWS (Cost Explorer)
```bash
aws ce get-cost-and-usage \
  --time-period Start=2026-06-01,End=2026-06-30 \
  --granularity MONTHLY \
  --group-by Type=DIMENSION,Key=SERVICE \
  --metrics UnblendedCost UsageQuantity \
  --output json
```

### AWS (Idle Resources)
```bash
# Unattached EBS volumes
aws ec2 describe-volumes \
  --filters Name=status,Values=available \
  --query 'Volumes[*].VolumeId' --output json

# Unused Elastic IPs
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].AllocationId' --output json

# Low-CPU EC2 (requires CloudWatch)
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 --metric-name CPUUtilization \
  --period 2592000 --statistics Average \
  --dimensions Name=InstanceId,Value=i-0abc123 \
  --start-time 2026-06-01 --end-time 2026-06-30
```

### Azure (Cost Management)
```bash
az costmanagement query \
  --type ActualCost \
  --timeframe Custom \
  --time-period from=2026-06-01T00:00:00Z to=2026-06-30T23:59:59Z \
  --dataset-grouping name=ServiceName type=Dimension \
  --dataset-aggregation totalCost='{"name":"Cost","function":"Sum"}' \
  --scope /subscriptions/<sub-id> \
  --output json
```

### GCP (requires BigQuery billing export)
Export to BigQuery and query:
```sql
SELECT service.description AS service, SUM(cost) AS total_cost
FROM `project.dataset.gcp_billing_export_*`
WHERE DATE(_PARTITIONTIME) BETWEEN '2026-06-01' AND '2026-06-30'
GROUP BY service ORDER BY total_cost DESC
```

---

## Security & Compliance

- **Data Sanitization**: Cost data and resource inventories pass through `shield.sanitize()` before LLM (Rule 6).
- **LLM Routing**: All calls go through `.llm/router.py` (Rule 6).
- **Audit Trail**: Every node writes to `audit_log` table (Rule 9).
- **Budget Guard**: `check_budget(estimated_tokens=6000)` called pre-LLM (Rule 10).
- **No Autonomous Mutations**: No resource is stopped or deleted without `interrupt()` + operator approval (Rule 11).

---

## Error Handling

| Error | Behavior |
|---|---|
| Missing `cost_data` | Ingest uses empty dict; LLM flags "insufficient cost data" |
| Empty `resource_inventory` | `quick_win_resources` is empty; opt_2 returns "skipped" |
| LLM parse failure | `error` set; HITL gate skipped; incident not created |
| `GITHUB_TOKEN` missing | `create_cost_report_issue` raises `EnvironmentError` |
| `SLACK_WEBHOOK_URL` missing | `post_slack_alert` raises `EnvironmentError` |
| Cloud API error | Raises `RuntimeError`; logged; execution status set to `failed` |

---

## Escalation

If the recommendations appear incorrect:
1. Select **hold** at the HITL gate
2. Review the `cost_report` in the incident detail
3. Re-run with a longer billing window (90 days) for more accurate averages
4. Open a support ticket if LLM recommendations are consistently wrong for your workload
