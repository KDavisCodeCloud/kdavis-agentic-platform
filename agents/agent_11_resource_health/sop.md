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

**Verified setup path (live-tested 2026-09-15 — see Verification status
below for the full trace):**

1. **Register the resource providers first**, on the subscription —
   `Microsoft.Insights` and `Microsoft.AlertsManagement`. An
   unregistered provider is the most common reason a freshly-created
   Action Group's webhook silently never fires:
   ```
   az provider register --namespace Microsoft.Insights
   az provider register --namespace Microsoft.AlertsManagement
   az provider show --namespace Microsoft.Insights --query registrationState
   az provider show --namespace Microsoft.AlertsManagement --query registrationState
   ```
   Wait for both to report `Registered` before continuing.

2. **Create the Action Group**, then add an action of type **Webhook —
   not "Secure Webhook"**. Secure Webhook requires an Azure AD auth
   handshake (AAD app registration, token validation) this backend does
   not implement; a plain Webhook action is what `resource_health_alert_webhook`
   (`api/routes/webhooks.py`) expects — token-in-query-string auth only.

3. **Turn the "Common Alert Schema" toggle ON** for the webhook action.
   This is not optional: `is_azure_monitor` detection
   (`api/routes/webhooks.py`) only recognizes the Common Alert Schema's
   `{"data": {"essentials": {...}}}` shape. The legacy (non-common)
   schema is a structurally different payload and falls through to
   `{"status": "ignored", "reason": "unrecognized alert payload format"}`
   — silently dropped, not an error, so this is easy to miss if the
   toggle is left off.

4. **Webhook URI** — must include the `/api/v1` prefix
   (`api/main.py` mounts `webhooks.router` under `/api/v1` on top of the
   router's own `/webhooks` prefix; every path in this doc has
   historically been documented without it, which is itself a bug this
   session fixed live — see commit `e30e3a7`). The current production
   URL (no custom domain mapped to this Railway service yet):
   ```
   URL: https://kdavis-agentic-platform-production.up.railway.app/api/v1/webhooks/resource-health-alert?token=<ws_token>
   ```

5. **Test it** — in the Azure Portal, open the Action Group → **Test
   action group** → sample type **Metric alert** (both the "static
   threshold" and "dynamic threshold" Metric alert samples exercise the
   same Common Alert Schema shape and both were used for the live
   verification below). A successful test reaches
   `resource_health_alert_webhook`, which returns `200` — if you instead
   see Azure report `403 Forbidden`, the most common cause is a stray
   space or line-break character accidentally pasted into the `token`
   query-string value (copy from a plain-text field, not a
   line-wrapping chat/terminal view, and verify the pasted URL has no
   embedded whitespace before saving).

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
  --notification-endpoint "https://kdavis-agentic-platform-production.up.railway.app/api/v1/webhooks/resource-health-alert?token=<ws_token>"
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

### Prometheus Alertmanager / Grafana unified alerting

Same endpoint as Azure/AWS above — register it as an Alertmanager
`webhook_config` receiver, or a Grafana unified alerting webhook contact
point:

```yaml
# Prometheus Alertmanager (alertmanager.yml)
receivers:
  - name: cloud-decoded-resource-health
    webhook_configs:
      - url: https://kdavis-agentic-platform-production.up.railway.app/api/v1/webhooks/resource-health-alert?token=<ws_token>
```

```
# Grafana — Alerting → Contact points → New contact point
Integration: Webhook
URL: https://kdavis-agentic-platform-production.up.railway.app/api/v1/webhooks/resource-health-alert?token=<ws_token>
```

Both notifiers send an identical top-level shape (a `"alerts"` array,
each element carrying `labels`/`annotations`/`status`) — Grafana's is
told apart only by a top-level `orgId` field the route (and
`_ingest_node`, mirroring it) checks for. A single delivery can batch
several alerts together, including a mix of newly-firing and newly-
resolved ones; each element gets its own independent triage (see
Resolution handling below) rather than being collapsed into one.

Field mapping (GAPS.md scale-readiness build — previously these payloads
were accepted and routed by the webhook route but `_ingest_node` had no
parsing branch for either, so they silently fell through to the raw-JSON
catch-all: no dedup, no severity, no resource pinpointing, nothing):

| Incident field | Source |
|---|---|
| `alert_name` | `labels.alertname` |
| `resource_id` / `resource_name` | `labels.pod` + `labels.namespace` when present (K8s-origin alert, e.g. kube-state-metrics), else `labels.instance` |
| `resource_group` | `labels.namespace`, else `labels.job` |
| `severity` | `labels.severity`, mapped **conservatively** — `critical`/`warning` → `high`, `info` → `low`, anything else → `medium`. A raw Prometheus `critical` label is deliberately NOT passed through as incident severity `critical` (that's reserved for signals the platform itself computes) — see `_map_alertmanager_severity` in `workflow.py`. |
| Diagnosis context | `annotations.summary` + `annotations.description` |
| `metric_current_value` (Grafana only) | First value in the alert's `values{}` map |

### Resolution handling (Alertmanager/Grafana only)

Both notifiers resend a previously-firing alert with `status: "resolved"`
once its condition clears. A resolved-status alert **never** reaches
diagnosis and **never** creates a new incident:
- If an open incident already exists for the same dedup key
  (`workspace_id` + `resource_id` + `alert_name`), the resolution is
  noted on that record (`incidents.source_resolved_at`, migration 056) —
  advisory only, does **not** change `execution_status`. The incident
  still needs an operator's decision regardless of what the source says
  (a flapping alert, a false resolve, or just wanting to review before
  closing).
- If there's no matching open incident, nothing happens at all — no row,
  no audit noise beyond a single `resolution_check: resolved_no_match`
  entry.

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
ingest → resolution_check → dedup_check → diagnose (LLM) → hitl_gate [PAUSE] → execute → complete
              │                   │
              └→ resolution_complete → END    └→ dedup_complete → END
```

A single Alertmanager/Grafana delivery carrying several alerts in one
`"alerts"` array is fanned out by `run()` into one independent graph run
per alert element **before** any of this — own `thread_id`, own
resolution/dedup check, own possible incident. Every other source is
always exactly one alert per delivery already.

### 1. Ingest
- Detects alert source (`azure_monitor` / `aws_cloudwatch` /
  `prometheus_alertmanager` / `grafana`) from payload shape
- Heuristically classifies domain from the resource type / CloudWatch namespace (context for the LLM, not a gate — the LLM confirms or corrects it)
- Sanitizes the alert excerpt via `shield.sanitize()` before LLM consumption

### 2. Resolution check (Alertmanager/Grafana only)
- A `"firing"`-status alert (or any non-Alertmanager/Grafana source, always implicitly firing) passes straight through unchanged
- A `"resolved"`-status alert never reaches diagnose or dedup_check — see Resolution handling above

### 3. Dedup check
- A flapping alert for the same `workspace_id` + `resource_id` + `alert_name` that already has an open incident short-circuits to `dedup_complete` (bumps `occurrence_count`) instead of spending another LLM call

### 4. Diagnose (LLM)
- Calls LLM via `.llm/router.py` with `task_type="resource_health_triage"`
- Returns `parsed_error`, 2-3 `options` (or exactly 1 + hold for human-judgment alerts), `estimated_duration_seconds`

### 5. HITL Gate (Governance Rule 11)
- Creates incident, sends `interrupt()` — **workflow pauses here**
- Operator approves via `POST /incidents/{id}/approve`

### 6. Execute (Post-Approval Only)
- **opt_1 — Remediation PR**: opens a PR with the proposed IaC fix (GitHub or Azure DevOps, whichever this workspace connected)
- **opt_2 — Investigation Issue**: opens a GitHub issue (Azure DevOps work items not supported yet — same limitation as Agent 08's `create_drift_issue`)
- **hold**: no execution

### 7. Complete
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
| Resolved-status Alertmanager/Grafana alert, no matching open incident | Nothing created; single `resolution_check: resolved_no_match` audit entry |
| Resolved-status Alertmanager/Grafana alert, matching open incident | `incidents.source_resolved_at` set on the existing row; `execution_status` and diagnosis untouched |

---

## Verification status

**Prometheus Alertmanager / Grafana ingest (GAPS.md scale-readiness
build): unit-tested only, not yet live-verified end-to-end against a
real Alertmanager or Grafana instance** — `tests/test_agent11.py`
exercises `_ingest_node`'s field mapping (both notifier shapes, K8s-
origin vs generic-instance resource identification, severity mapping,
Grafana's `values{}`), `_resolution_check_node`'s note/no-op paths, and
`run()`'s multi-alert fan-out, against realistic synthetic payloads —
but no real webhook registration against a live Alertmanager/Grafana
deployment has been exercised the way the Azure/AWS paths below were.
Treat this the same way the rest of this document treats "unit-tested"
vs. "live-verified": don't assume production behavior matches until it
has actually been driven end-to-end once, the same discipline the five
bugs below were only ever found by.

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

**Azure Action Group path: live-verified end-to-end against production on
2026-09-15**, using the setup steps documented above (a real Action
Group in Kelvin's own subscription, webhook action, Common Alert Schema
on). Two real Azure Monitor test alerts were fired via the Portal's Test
action group → Metric alert sample type — one **static threshold**, one
**dynamic threshold** — both reached `resource_health_alert_webhook`,
both were correctly detected as `format=azure_monitor`, and both ran
Agent 11's full graph: ingest → diagnose (LLM) → a real incident row
created (`pending_approval`, plain-English `parsed_error`, two real
remediation options) → `interrupt()` fired correctly, pausing for
operator approval exactly as designed.

Getting from "alert lands as a pending incident" to a genuinely
complete approve → execute → resolved loop surfaced **four** real,
previously-undiscovered production bugs this same session — the
ingest half had clearly been exercised before (SNS path above), but
approve → resume never had been, for any agent, until this. Each was
found by actually driving the full loop against production and reading
the failure, not by inspection:

1. **Checkpoint write crash on interrupt**
   `TypeError: AsyncPostgresSaver.aput_writes() takes 4 positional
   arguments but 5 were given` (`core/checkpointer_lock.py`) — a
   version-skew bug between `langgraph-checkpoint` 2.1.2's abstract
   interface (added a `task_path` parameter) and the pinned
   `langgraph-checkpoint-postgres==2.0.4` concrete implementation
   (predates it). Affected every agent's HITL-gate checkpoint, not just
   Agent 11's. Fixed, commit `8a0ae1a`.

2. **Agent 11 missing from the approve-resume dispatch table**
   `api/routes/incidents.py`'s `_WORKFLOW_CLASSES` had no entry for
   `agent_11_resource_health` at all — every real approval of a real
   Agent 11 incident selecting anything but `hold` hit a 500 "No
   workflow class registered." Broken since Agent 11 shipped, for every
   customer. Fixed, commit `c84a1c1`.

3. **Sync `get_state()` against an async-only checkpointer** — 7 of 11
   agents (02, 03, 04, 07, 09, 10, 11) called the synchronous
   `self._graph.get_state(config)` right after `ainvoke()` returns from
   an interrupted run, to pull the interrupt payload back out.
   `core/checkpointer_lock.py`'s `LockedAsyncPostgresSaver` only
   implements the async interface; the sync path raises
   `NotImplementedError`, crashing `run()` itself immediately after
   every interrupt, for all 7 agents. Fixed with `await
   self._graph.aget_state(config)`, commit `8110344` — see
   `tests/test_agent_workflow_conventions.py` for the static regression
   guard.

4. **Incident id never matched the real LangGraph checkpoint thread_id**
   — the actual root cause of the `InvalidUpdateError` that survived
   fix #3. The same 7 agents generated a fresh `thread_id` for the
   checkpoint config but never seeded `initial_state["incident_id"]`
   with it (hardcoded `None`), and Agent 11's own `_ingest_node`
   independently reset it back to `None` a second time even where it
   had been seeded — so `create_incident()` got no `incident_id` kwarg,
   Postgres auto-generated an unrelated random UUID for the DB row, and
   `POST /incidents/{id}/approve` naturally resumed against *that* id
   instead of the real thread_id the graph was actually checkpointed
   under. LangGraph found no checkpoint, treated `Command(resume=...)`
   as a fresh `__start__` invocation, and raised — a `Command` object is
   not valid raw state input there. Fixed to match the pattern
   agent_01/05/06/08 already had correct, commit `3900fd8`. Immediately
   surfaced a **fifth**, narrower bug in Agent 11 specifically: its
   dedup-collapse routing (`_route_after_dedup`) keyed off
   `incident_id`'s truthiness, which is exactly what fix #4 made
   always-true from the start of every run — so every alert, new ones
   included, got silently routed to `dedup_complete` and no incident was
   ever created. Fixed with an explicit `is_dedup_match` state field,
   commit `68c25c2`.

Each of the five fixes was deployed and re-tested against a fresh
synthetic Azure Monitor alert before moving to the next — a fix that
looked complete in isolation twice turned out to still be blocked by
the next bug in the chain, so **the only claim trusted here is the one
backed by the final clean run**, not any intermediate "should work now."

**Full loop verified end-to-end against production, 2026-09-15**: a
real synthetic Azure Monitor test alert → webhook accepted → real
incident created (`pending_approval`) → `POST /incidents/{id}/approve`
→ agent resumes from the persisted checkpoint under the correct
thread_id → `execute` node runs (returned `skipped` — no repo
configured on the test workspace, the documented, expected, side-
effect-free outcome per the Error Handling table above, not a failure)
→ `complete` node runs → incident reaches `execution_status = 'executed'`
with `resolved_at` populated → a full 7-row `audit_events` trail for the
incident confirms GAPS.md #28's audit writer fired correctly at every
step (`created` → `hitl_gate` → `execute:opt_1` → `hitl_gate` → `complete`
→ `executed`). Four earlier test incidents, created and stranded by
bugs 1-5 above before each respective fix deployed, were deleted rather
than left as unapprovable orphans in the Cloud Decoded — Internal QA
workspace.
