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
| Prometheus AlertManager | `POST /webhooks/aks-alert?token=<ws_token>` | AlertManager v4 |
| Azure Monitor (Action Group) | `POST /webhooks/aks-alert?token=<ws_token>` | Common Alert Schema |

### Workflow
```
Webhook received
  └─ ingest_node      extract: namespace, pod, deployment, alert_type, exit_code
  └─ diagnose_node    LLM diagnosis via .llm/router.py (task_type: k8s_triage)
  └─ hitl_gate        INTERRUPT — operator approves one of 2-3 options
  └─ execute_node     approved option dispatched to K8sTools
  └─ complete_node    incident marked executed, audit trail finalized
```

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
The service account token must have these permissions only:
```yaml
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "patch"]
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "create", "update"]
```

### Governance
- Rule 11: No autonomous remediation — every fix requires operator approval
- Rule 9: All actions logged to knowledge/operator/llm-audit.md
- Rule 6: All LLM calls route through .llm/router.py
- Rule 10: On any error, incident is marked failed — never left in executing state
