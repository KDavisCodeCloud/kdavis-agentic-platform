# Agent 02 — Kubernetes Alert Fatigue & Remediation
## Standard Operating Procedure

### Purpose
Agent 02 monitors Kubernetes clusters for CrashLoopBackOff, OOMKilled, ImagePullBackOff,
and other pod-level failures. It diagnoses the root cause, presents remediation options
to the operator, and executes the approved fix — patching deployment resources, applying
an HPA, or rolling back to the previous deployment revision.

### Trigger Sources
| Source | Webhook Endpoint | Format |
|--------|-----------------|--------|
| Prometheus AlertManager | `POST /api/v1/webhooks/aks-alert?token=<ws_token>` | AlertManager v4 |
| Azure Monitor (Action Group) | `POST /api/v1/webhooks/aks-alert?token=<ws_token>` | Common Alert Schema |

### Workflow
```
Webhook received
  └─ ingest_node      extract: namespace, pod, deployment, alert_type, exit_code
  └─ evidence_node    read-only live cluster snapshot (see below) — never blocks
  └─ diagnose_node    LLM diagnosis via .llm/router.py (task_type: k8s_triage)
  └─ hitl_gate        INTERRUPT — operator approves one of 2-3 options
  └─ execute_node     approved option dispatched to K8sTools
  └─ complete_node    incident marked executed, audit trail finalized
```

### Evidence Gathering (read-only, pre-diagnose)
Before the LLM ever sees the alert, `evidence_node` fetches a live snapshot
of the cluster so diagnosis is grounded in what's happening right now, not
just the alert payload. `alert_type` is classified into one of these
categories (`_classify_alert_category` in `workflow.py`); each category
runs a fixed set of GET-only checks (`K8sTools.gather_evidence`):

| Category | Checks | K8s API calls |
|----------|--------|----------------|
| crashloop | describe + previous logs + events | `GET pods/{name}`, `GET pods/{name}/log?previous=true`, `GET events` |
| imagepull | describe + events | `GET pods/{name}`, `GET events` |
| pending | describe + node conditions | `GET pods/{name}`, `GET nodes` |
| oomkill | describe + metrics ("top") | `GET pods/{name}`, `GET metrics.k8s.io/.../pods/{name}` |
| service (service/ingress/endpoint alerts) | endpoints + service + ingress describe | `GET endpoints/{name}`, `GET services/{name}`, `GET ingresses/{name}` |
| pvc | PVC describe + storageclass | `GET persistentvolumeclaims/{name}`, `GET storageclasses/{name}` |
| dns | CoreDNS logs (kube-system) | `GET kube-system/pods?labelSelector=k8s-app=kube-dns`, `GET pods/{coredns}/log` |
| generic (fallback, e.g. Evicted or an unrecognized alert_type) | describe + events | `GET pods/{name}`, `GET events` |

Every call here is a **read** — no write verb ever appears in this step, so
it needs no operator approval (Governance Rule 11 gates mutation only).
Non-fatal by design: no cluster credentials configured, or the cluster is
unreachable, degrades to a `[live evidence unavailable: ...]` note and
`diagnose_node` reasons from the alert payload alone, exactly as it did
before this step existed. A single failed check within a category (e.g.
metrics-server not installed) degrades the same way without dropping the
other checks in that category.

### Remediation Options (post-approval execution)
| Option ID | Tool Method | Description |
|-----------|-------------|-------------|
| opt_1 | `patch_deployment_memory()` | PATCH deployment to increase memory limit |
| opt_2 | `apply_hpa()` | POST HorizontalPodAutoscaler |
| opt_3 | `rollback_deployment()` | Annotate deployment to trigger rollout restart |
| hold | — | No action, operator handles manually |

### Required Workspace Configuration
| Env Variable | Purpose |
|-------------|---------|
| `K8S_API_URL` | Kubernetes API server URL (e.g. https://my-cluster.azmk8s.io) |
| `K8S_TOKEN` | Service account bearer token with limited RBAC permissions |
| `GITHUB_TOKEN` | GitHub PAT for GitOps PR creation (optional) |

### RBAC Minimum Permissions
The service account token must have these permissions only. The first
block is unchanged (post-approval execution, gated by HITL); the second
block is new — read-only, needed by the pre-diagnose evidence step above.
Omitting the read block doesn't break the agent, it just means every
evidence category degrades to "unavailable" and diagnosis falls back to
the alert payload alone.
```yaml
rules:
  # Post-approval execution (Governance Rule 11 — gated by operator approval)
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "patch"]
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "create", "update"]
  # Read-only pre-diagnose evidence gathering — no write verbs, ever
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events", "nodes", "endpoints", "services", "persistentvolumeclaims"]
    verbs: ["get", "list"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses"]
    verbs: ["get"]
  - apiGroups: ["metrics.k8s.io"]
    resources: ["pods"]
    verbs: ["get"]
    # optional — only present when metrics-server is installed; absence
    # degrades the oomkill category's metrics check, nothing else
```

### Governance
- Rule 11: No autonomous remediation — every fix requires operator approval
- Rule 9: All actions logged to knowledge/operator/llm-audit.md
- Rule 6: All LLM calls route through .llm/router.py
- Rule 10: On any error, incident is marked failed — never left in executing state
