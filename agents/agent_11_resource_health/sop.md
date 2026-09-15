# SOP — Agent 11: Cloud Resource Health Monitoring

**Version:** 1.0 | **Owner:** Platform / SRE | **Tier:** Growth, Enterprise

---

## Purpose

Agent 11 diagnoses live/runtime cloud-resource alerts — a resource going
down, a performance threshold breach, a security finding — and presents
the operator with remediation options before anything is created. This is
the runtime counterpart to Agent 01 (CI/CD deploy-time failures) and
Agent 08 (config drift): where those catch problems at deploy time or on
a scheduled check, Agent 11 catches problems as they happen, pushed in by
the cloud provider's own alerting.

This agent does **not** call any live cloud-mutation API. All it can do
post-approval is open a remediation PR (an IaC change) or a tracking/
investigation issue — never "restart this VM" or "scale this out"
directly. That's a deliberate scope boundary for this build, not an
oversight — see GAPS.md.

---

## Trigger

**Push-driven, not manual/scheduled like Agent 08** — you don't need to
know a customer's resource list in advance; register the webhook once
and every alert from a connected resource shows up automatically, the
same model as Agent 02's AKS alerting.

### Azure — Action Group webhook

Register as a webhook action on an Azure Monitor Action Group:

```
URL: https://your-api.cloud-decoded.com/api/v1/webhooks/resource-health-alert?token=<ws_token>
```

Any Azure Monitor alert rule (Defender for Cloud/Identity findings, Azure
Policy compliance alerts, NSG flow-log anomalies, VM/App Service/Storage
health alerts, etc.) that fires this Action Group is diagnosed the same
way — Agent 11 reads the Common Alert Schema's `essentials.targetResourceType`
to classify which domain it belongs to (a hint for the LLM, not a hard
gate).

### AWS — SNS topic subscription

Subscribe this same URL as an HTTPS endpoint on an SNS topic that
CloudWatch Alarms (or GuardDuty findings via EventBridge → SNS) publish
to:

```
aws sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:123456789012:cloud-decoded-alerts \
  --protocol https \
  --notification-endpoint "https://your-api.cloud-decoded.com/api/v1/webhooks/resource-health-alert?token=<ws_token>"
```

AWS sends a `SubscriptionConfirmation` message once, immediately after
this — Cloud Decoded auto-confirms it (`core/aws_sns.py`), nothing further
needed on your side. Every subsequent `Notification` message's signature
is verified against AWS's own signing certificate before the alarm inside
it is trusted; an unverified or tampered message is rejected with a `403`,
never processed.

**Not yet built:** a dedicated ingestion path for GuardDuty findings
delivered any way other than through an SNS topic (e.g., directly via
EventBridge → Lambda). Route GuardDuty through SNS for now.

### Security Group / NSG change alerts (Phase 2, 2026-09-14)

No new webhook code was needed for this — the endpoint above already
generically accepts both AWS SNS and Azure Monitor Common Alert Schema
payloads regardless of what changed. What's new is Agent 08's ability to
independently re-verify a Security Group/NSG's actual live rules once an
alert names one (`DriftTools.fetch_security_group_state` /
`fetch_nsg_state`, see Agent 08's `sop.md`). This is how to configure the
*change*-detection alert itself, distinct from the anomaly/health alerts
in the Domain Coverage table above:

**AWS — Security Group rule changes via CloudWatch:**
```
aws events put-rule \
  --name cloud-decoded-sg-changes \
  --event-pattern '{"source":["aws.ec2"],"detail-type":["AWS API Call via CloudTrail"],
    "detail":{"eventName":["AuthorizeSecurityGroupIngress","AuthorizeSecurityGroupEgress",
    "RevokeSecurityGroupIngress","RevokeSecurityGroupEgress"]}}'

aws events put-targets --rule cloud-decoded-sg-changes \
  --targets "Id"="1","Arn"="arn:aws:sns:us-east-1:123456789012:cloud-decoded-alerts"
```
Publishes to the same SNS topic already subscribed above — no separate
subscription needed, `resource-health-alert`'s existing SNS branch
handles it.

**Azure — NSG rule changes via Azure Monitor (Activity Log alert):**
```
az monitor activity-log alert create \
  --name cloud-decoded-nsg-changes \
  --resource-group acme-prod-rg \
  --condition category=Administrative \
    and resourceType=Microsoft.Network/networkSecurityGroups \
    and operationName=Microsoft.Network/networkSecurityGroups/securityRules/write \
  --action-group <the Action Group already wired to the webhook URL above>
```
Fires the same Action Group already registered, so no new webhook
registration is needed either — Agent 11 ingests it through the existing
Azure Monitor branch.

---

## Domain Coverage

Same five domains as Agent 01/08 (IAM/RBAC/Policy, Networking, Storage,
Compute, Database-as-a-Service). See `prompts/diagnose.md` for the full
category list per domain per cloud — this table is the quick reference:

| Domain | Example Azure alert | Example AWS alert |
|---|---|---|
| IAM/RBAC/Policy | Defender for Identity access-denied/privilege-escalation | GuardDuty credential-exposure finding |
| Networking | NSG flow-log anomaly, Network Watcher reachability failure | VPC Reachability Analyzer failure, Shield DDoS alert |
| Storage | Storage account unauthorized access, replication failure | S3 unusual data transfer, replication failure |
| Compute | VM/managed-disk performance alert, availability-set health | EC2 CPU/memory threshold, spot interruption notice |
| Database-as-a-Service | Azure SQL DTU/vCore threshold, Cosmos DB RU exhaustion (429) | RDS storage/replication-lag alert, DynamoDB throttling |

**GCP:** payload shape and category guidance documented in
`prompts/diagnose.md` — a GCP alert posted through this same webhook
(e.g. from Cloud Monitoring, once a customer wires it up themselves) is
diagnosed sensibly. No dedicated GCP alert-source parsing exists in
`_ingest_node` yet (only Azure Monitor Common Alert Schema and AWS
SNS/CloudWatch are recognized formats) — this matches Agent 08's GCP
treatment: shape documented, no per-workspace GCP credential connector or
dedicated collection built yet.

---

## The "human judgment" rule (safety boundary, not a style choice)

Credential exposure, privilege escalation, unusual authentication
patterns, and potential data exfiltration findings **never get a "fix"
option.** `prompts/diagnose.md` rule 5 requires the LLM to offer only an
investigation issue (`opt_2`) plus `hold` for these — no `opt_1`, no
proposed remediation. This agent cannot distinguish a real compromise
from a false positive, and an automated "fix" (e.g. rotating a key)
could destroy forensic evidence or cause an outage. If you ever see an
`opt_1` on one of these alert types, that's a prompt regression — treat
it as a bug, not a feature.

---

## Workflow

```
ingest → diagnose (LLM) → hitl_gate [PAUSE] → execute → complete
```

### 1. Ingest
- Detects alert source (`azure_monitor` / `aws_cloudwatch`) from payload shape
- Heuristically classifies domain from the resource type / CloudWatch namespace (context for the LLM, not a gate — the LLM confirms or corrects it)
- Sanitizes the alert excerpt via `shield.sanitize()` before LLM consumption

### 2. Diagnose (LLM)
- Calls LLM via `.llm/router.py` with `task_type="resource_health_triage"`
- Returns `parsed_error`, 2-3 `options` (or exactly 1 + hold for human-judgment alerts), `estimated_duration_seconds`

### 3. HITL Gate (Governance Rule 11)
- Creates incident, sends `interrupt()` — **workflow pauses here**
- Operator approves via `POST /incidents/{id}/approve`

### 4. Execute (Post-Approval Only)
- **opt_1 — Remediation PR**: opens a PR with the proposed IaC fix (GitHub or Azure DevOps, whichever this workspace connected)
- **opt_2 — Investigation Issue**: opens a GitHub issue (Azure DevOps work items not supported yet — same limitation as Agent 08's `create_drift_issue`)
- **hold**: no execution

### 5. Complete
- Marks incident executed, writes final audit record

---

## Security & Compliance

- **Sanitization**: alert excerpts pass through `shield.sanitize()` before LLM (Rule 6).
- **SNS signature verification**: every `Notification` message is verified against AWS's real signing certificate (RSA/SHA1, per AWS's documented algorithm) before being trusted — an unverified request never reaches the diagnosis pipeline.
- **No Live Cloud Mutation**: this agent never calls a cloud provider's write API. Every option is a PR proposal or an issue, both requiring approval.
- **No Autonomous Execution**: no action runs without `interrupt()` + operator approval (Rule 11).
- **Audit Trail**: every node writes to `audit_log` (Rule 9).

---

## Error Handling

| Error | Behavior |
|---|---|
| SNS signature invalid | `403`, request rejected before any processing |
| SNS `SubscribeURL` not on an AWS domain | Confirmation refused, logged |
| Unrecognized alert payload format | `{"status": "ignored", ...}`, no agent run |
| `GITHUB_TOKEN` missing, `opt_2` selected | `create_alert_issue` raises `EnvironmentError`, logged |
| No repository configured, `opt_1`/`opt_2` selected | Returns `status=skipped` |
| LLM parse failure | `error` set in state; HITL gate skipped; incident not created |

---

## Verification status

Unit-tested with synthetic Azure Common Alert Schema and SNS payloads,
including a real cryptographic signature round-trip
(`tests/test_aws_sns.py`) against a self-signed certificate generated at
test time.

**AWS SNS path: live-verified end-to-end against production on
2026-09-15.** A real SNS topic was created and this URL subscribed as an
HTTPS endpoint; AWS's own `SubscriptionConfirmation` was received and
auto-confirmed by `confirm_subscription()` (0s — no polling delay
needed). A real, AWS-signed CloudWatch-alarm-shaped `Notification` (RDS
CPU threshold breach) was then published to the topic; `verify_signature()`
accepted AWS's real signature, the background task ran, and an incident
landed in `incidents` at `pending_approval` with a correct plain-English
`parsed_error` within 6 seconds. Test topic, subscription, and workspace
were all torn down immediately after.

**Azure Action Group path: not yet live-verified** — no Azure Service
Principal credential is configured on this backend service to test
against a real Action Group. It reuses the exact Common Alert Schema
parsing `aks_alert_webhook` already proves works in production for AKS
alerts, so the risk here is low, but it hasn't been exercised end-to-end
the way the AWS path now has.
