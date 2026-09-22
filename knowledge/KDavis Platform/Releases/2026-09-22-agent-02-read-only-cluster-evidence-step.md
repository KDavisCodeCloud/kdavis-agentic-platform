# Release: Agent 02 — Read-Only Cluster Evidence Before Diagnosis
Date: 2026-09-22

## What Kelvin asked for
Two-part request. First, verify: when a K8s alert arrives, does Agent 02
fetch any live cluster state (pod logs, describe, events) before the LLM
diagnoses it, or does diagnosis run on the alert payload alone? Same
question for Agent 11 handling a Prometheus alert about a K8s workload.
Second, if the answer was "payload alone" — build a read-only evidence
step between ingest and diagnose, matching the alert type to the right
kubectl-equivalent checks, entirely read verbs, non-fatal on failure.

## Verification result
Confirmed payload-alone for both agents. Agent 02's `_diagnose_node`
built its LLM prompt entirely from fields `_ingest_node` had already
extracted from the webhook payload (namespace, pod, exit code, restart
count) — no K8s API call happened anywhere before that LLM call.
`tools.py` had zero read verbs at all; every method in it was a
post-approval write (`patch_deployment_memory`, `apply_hpa`,
`rollback_deployment`).

Agent 11 showed the same pattern, plus a separate pre-existing gap worth
flagging even though it's outside what was asked to be built this
session: its `_ingest_node` has no branch for Prometheus's `"alerts"`
payload shape at all — only Azure Monitor and CloudWatch — even though
`POST /resource-health-alert` explicitly detects and routes Prometheus/
Grafana alerts to Agent 11. A Prometheus alert about a K8s workload
routed there today falls into the "unrecognized format" catch-all and
gets JSON-dumped raw instead of being parsed into structured fields.
Not touched this session — logged here, not built, since it wasn't part
of the scoped ask and deserves its own pass.

## What was built (Agent 02 only)
A new `evidence` node in the LangGraph state machine, between `ingest`
and `diagnose`:

```
ingest → evidence → diagnose → hitl_gate (interrupt) → execute → complete
```

`_classify_alert_category()` (`workflow.py`) maps the alert's `alert_type`
string into one of 7 categories — crashloop, imagepull, pending, oomkill,
service, pvc, dns — with a `generic` fallback (describe + events) for
anything else, including `Evicted` and any alert_type the classifier
doesn't recognize. Order matters here: a real-world alertname like
`PersistentVolumeClaimPending` needs to route to `pvc` (describe + 
storageclass) rather than the generic `pending` category (pod describe +
node conditions, which says nothing about storage) — the pvc/volume
check runs before the pending check specifically for this reason,
caught by a test that initially asserted the wrong category.

`K8sTools.gather_evidence()` (`tools.py`) dispatches to the matching
GET-only checks per category, using the workspace's existing per-tenant
K8s credentials (the same bearer-token pattern Agent 02 already had for
its write tools — no new credential plumbing needed):

| Category | Checks |
|----------|--------|
| crashloop | pod describe, previous container logs, namespace events |
| imagepull | pod describe, namespace events |
| pending | pod describe, node conditions (cluster-wide — pod isn't scheduled yet, so no node name to target) |
| oomkill | pod describe, pod metrics ("top", via metrics.k8s.io) |
| service | endpoints, service describe, ingress describe (best-effort: deployment_name as the target, since ingest doesn't extract a dedicated service/ingress name today) |
| pvc | PVC describe, then storageclass describe if the PVC fetch named one |
| dns | CoreDNS logs from kube-system, found via the k8s-app=kube-dns label rather than assuming a pod name |
| generic | pod describe, namespace events |

Every one of those is a `GET` — no write verb anywhere in this step, so
Governance Rule 11 (no autonomous remediation) doesn't even apply here;
there's nothing to gate. Evidence text is truncated to 6000 chars (same
char-budget convention as `_MAX_*_CHARS` constants elsewhere in this
codebase) and injected into the diagnose prompt as a new "Live Cluster
Evidence" section. The diagnose prompt itself (`prompts/diagnose.md`) was
updated to tell the LLM to trust that live snapshot over the alert
payload when the two disagree, and to say so plainly in `parsed_error`
when evidence is unavailable rather than guessing.

Non-fatal by design, matching every other `*Tools` capture-style helper
in this codebase (`_capture_container_resources`, `_capture_hpa`): no
cluster credentials configured, an unreachable cluster, or a single
failed check within a category (metrics-server not installed is routine,
not exceptional) degrades to an `[unavailable: ...]` note rather than
raising. Diagnosis still runs on the alert payload alone in that case —
identical behavior to before this step existed, just now explicit about
why.

`sop.md` (the agent's own repo-tracked reference doc, not this Obsidian
entry) was updated to match: the workflow diagram now shows the evidence
step, and a new RBAC minimum-permissions block documents the read-only
verbs a workspace's K8s ServiceAccount needs for evidence gathering to
actually work (pods/log, events, nodes, endpoints, services,
persistentvolumeclaims, ingresses, storageclasses, and an optional
metrics.k8s.io grant). Omitting that block doesn't break anything — it
just means every evidence category degrades to unavailable for that
workspace.

## Tests
89 tests in `tests/test_agent02.py` (up from the pre-existing suite),
covering: `_classify_alert_category`'s mapping including the ordering
fix above, `K8sTools.gather_evidence` per category (including the
metrics-server-absent and no-CoreDNS-pods degradation paths, and a
`_never_issues_a_write_verb` test that fails loudly if a PATCH/POST/PUT/
DELETE call is ever reachable from this method), `_evidence_node`'s
available/unavailable/upstream-error-skip paths, and — the part that
actually proves the step matters, not just exists — parametrized fixtures
per alert type asserting the gathered evidence text lands in the real
LLM message sent to `call_llm`. Full suite: 89/89 passing. Full repo
suite: only the 4 failures already present on a clean `master` before
this session touched anything (confirmed via `git stash`), all in
unrelated files (`test_agent01_local.py`, `test_security.py`).
