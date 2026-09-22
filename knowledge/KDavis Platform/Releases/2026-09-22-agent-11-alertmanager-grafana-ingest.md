# Release: Agent 11 — Prometheus Alertmanager & Grafana Ingest
Date: 2026-09-22
Migrations: 056

## What Kelvin asked for
Fix Agent 11's ingest for Prometheus Alertmanager and Grafana payloads.
The webhook route already accepted and routed both shapes to Agent 11
(`api/routes/webhooks.py`'s `resource_health_alert_webhook` detects an
`"alerts"` array and, via Grafana's `orgId` field, tells the two apart)
but `_ingest_node` had no parsing branch for either — they fell straight
through to the raw-JSON catch-all, so `alert_name`/`resource_id`/
`severity` never populated. That silently bypassed dedup, severity
normalization, resource exemptions, and resource pinpointing for every
alert from either source — the same earlier session's read-only Agent 02
evidence-step work had flagged this as a known gap without fixing it,
since it was out of that session's scope.

## What was built

### Field extraction — two branches, one shared helper
`_ingest_node` gained two new branches (Grafana checked first, since a
Grafana payload also carries `"alerts"` — `orgId` is the only reliable
discriminator), both calling a new shared `_parse_alertmanager_alert()`
helper so the actual per-alert field logic isn't duplicated:

- `alert_name` ← `labels.alertname`
- `resource_id`/`resource_name` ← `labels.pod` + `labels.namespace` when
  present (a K8s-origin alert — kube-state-metrics and similar exporters
  commonly set these), else `labels.instance`. Namespace/pod pinpoints
  the actual unhealthy resource far more precisely than `instance`,
  which for a K8s exporter is just the scrape target's host:port.
- `resource_group` ← `labels.namespace`, else `labels.job`
- `severity` ← `labels.severity`, mapped through a new, deliberately
  conservative table: `critical`/`warning` → `high`, `info` → `low`,
  anything unmapped → `medium`. This is intentionally NOT the same as
  `core.severity.normalize_severity()`'s generic pass-through (which
  would leave a raw `"critical"` label as `"critical"` unchanged) — a
  Prometheus severity label is set by whoever wrote the alerting rule
  with zero platform-side validation, so it's capped at `high`.
  `"critical"` stays reserved for signals the platform itself computes.
- Diagnosis context ← `annotations.summary` + `annotations.description`
- Grafana only: `metric_current_value` ← the first value in the alert's
  `values{}` map (Grafana-specific; Alertmanager proper has no
  equivalent field)

### Firing vs. resolved
Both notifiers resend a previously-firing alert with `status: "resolved"`
once its condition clears. Added a new `resolution_check` graph node
(between `ingest` and `dedup_check`) so a resolved alert never reaches
diagnosis and never creates an incident:
- Matches an open incident on the existing dedup key (`workspace_id` +
  `resource_id` + `alert_name`) → notes the resolution on that record.
  New column `incidents.source_resolved_at` (migration 056) and
  `core/hitl.py`'s new `note_source_resolution()` — deliberately
  advisory only, does **not** touch `execution_status`. The incident may
  still need an operator's attention regardless of what the source says
  (a flapping alert, a false resolve, or just a preference to review
  before closing), so this never auto-closes anything the way
  `mark_executed()` does. Kept as its own column rather than reusing
  `resolution_note` (migration 038) — that column's own comment
  documents it as "NULL for every other resolution path," and this is
  exactly that other path (source-reported, not operator-reported).
- No match → nothing happens at all. No row, no LLM call, one audit
  entry (`resolution_check: resolved_no_match`).

### One incident per alert element
A single Alertmanager/Grafana delivery can batch several alerts in one
`"alerts"` array (Alertmanager does this by default, often mixing
newly-firing and newly-resolved alerts in the same delivery).
`run()` now detects a multi-element array and fans out into one
independent graph invocation per element — own `thread_id`, own
resolution/dedup check, own possible incident — via a new private
`_run_single()` that holds the original single-run logic. Returns a
list of incident_ids for a genuinely multi-alert delivery (`None` entries
are resolved alerts that matched nothing); every other case — Azure
Monitor, AWS CloudWatch, and a single-alert Alertmanager/Grafana
delivery — is untouched and keeps the original single incident_id string
return, so the one real caller (`api/routes/webhooks.py`'s
`_run_resource_health_alert`) needed only a small `isinstance(list)`
branch in its log line, nothing structural.

## A test I had to extend, not just add to
`tests/test_agent_workflow_conventions.py` has a static regression guard
(`test_no_agent_workflow_resets_incident_id_to_none_after_seeding`) for a
real bug found live 2026-09-15: a node resetting `incident_id` back to
`None` on every run silently destroys `run()`'s thread_id seed, breaking
`POST /incidents/{id}/approve`'s resume path. `_resolution_check_node`'s
"resolved, no match" branch legitimately sets `incident_id: None` — but
it's not an instance of that bug: no incident is ever created on that
path, and the graph routes straight to `resolution_complete → END`
without ever reaching `hitl_gate`, so there's no resume/checkpoint
concern at all. Extended the guard with one precisely-scoped, documented
exception (exact file + expected match count, not a weakened regex) so
it still trips on a genuinely new None-reset anywhere, including a
second one in this same file.

## Tests
70 tests in `tests/test_agent11.py` (up from 40): field-extraction tests
for both Alertmanager and Grafana branches against real multi-alert
fixtures (a K8s-origin pod alert plus a generic instance alert in one
delivery), the severity mapping table, `_resolution_check_node`'s
match/no-match/firing-is-noop/upstream-error-skip paths, `run()`'s
fan-out (multi-alert splits correctly, orgId survives into each
sub-payload, a single-alert delivery of any source keeps the original
string return), and two integration-style tests chaining real
`_ingest_node` output into `_dedup_check_node`/`_resolution_check_node`
that directly prove a repeat firing dedups without a second LLM call and
a resolved status creates nothing — from actual fixture payloads, not
synthetic state. Full repo suite: 2227 passed, only the 4 failures
already present on a clean `master` before this session touched
anything (confirmed via `git stash`), all in unrelated files
(`test_agent01_local.py`, `test_security.py`).

## What's honestly not yet verified
Marked explicitly in `agents/agent_11_resource_health/sop.md`: this is
unit-tested only. No real webhook registration against a live
Alertmanager or Grafana instance has been exercised the way the Azure
Action Group and AWS SNS paths were on 2026-09-15 (that session's SOP
entry documents five real production bugs found only by actually driving
the full loop, not by inspection — same discipline applies here before
trusting this in production).
