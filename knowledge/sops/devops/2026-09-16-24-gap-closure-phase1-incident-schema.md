# SOP: 24-Gap-Closure Build, Phase 1 — Incident Schema Foundation
Date: 2026-09-16
Status: Live — migration applied, deployed, verified, committed, pushed

---

## Scope

Phase 1 of Kelvin's 24-gap-closure build for Cloud Decoded. Phase-gated:
this phase only, full suite must pass, deploy, checkpoint before Phase 2.

- `severity` column on `incidents` (critical/high/medium/low), derived at
  ingest per-agent from whatever real signal that agent already has
- `assigned_to` (nullable FK to `workspace_members`)
- `incident_comments` table
- `before_state` JSONB on `incidents`, captured at execution time for
  direct cloud API actions
- Severity wired into: Jira priority mapping, HITL queue sort order

## What was read before building (per Kelvin's own instruction)

- Every one of the 11 agents' `_hitl_gate_node` and `_execute_node`
  methods, to find out which already carry a real severity-shaped or
  rollback-shaped signal rather than assuming none do.
- `core/ticketing.py` for the literal "Jira priority... replaces uniform
  P3" claim — confirmed exact, not approximate: `_jira_priority()`
  existed with a docstring plainly stating the gap and returning `"P3"`
  unconditionally.
- `api/routes/incidents.py`'s `list_incidents` for the current sort order
  (`ORDER BY created_at DESC`, no severity concept at all).

## What was actually found (the "partially built" check)

- **Agent 05** (IAM minimizer) already computes `risk_score`:
  `CRITICAL|HIGH|MEDIUM|LOW` — a real signal, never persisted.
- **Agent 08** (drift detection) already computes `drift_severity`, same
  four values — also never persisted.
- **Agent 10** (dependency patch) already computes `critical_count`/
  `high_count` from real OSV vulnerability scan results — no single
  label, so severity is derived from the counts instead.
- **Agent 02** (K8s) and **Agent 11** (resource health) both parse Azure
  Monitor's `essentials.severity` (`"Sev0".."Sev4"`) — Agent 11 already
  captured it into state; **Agent 02 was dropping it entirely** after
  logging it. Agent 11 also handles AWS CloudWatch alarms, whose only
  comparable field (`NewStateValue`) is alarm *state*, not severity —
  mapped as a best-effort proxy (`ALARM`→high, `OK`/`INSUFFICIENT_DATA`→low)
  rather than inventing a severity CloudWatch never sends.
- **Agents 01/03/04/06/07/09** have no severity-shaped signal at ingest
  at all (confirmed by grep, not assumed) — they get the same `medium`
  default the backfill uses, not a fabricated signal.
- **Only Agent 02 performs a genuine direct-cloud-API mutation** —
  `patch_deployment_memory`/`apply_hpa`/`rollback_deployment` against a
  live K8s cluster. Every other agent's execute step opens a PR, already
  reversible via git revert. None of `patch_deployment_memory`/`apply_hpa`
  fetched the pre-mutation state before this build; `rollback_deployment`
  already fetched `current_revision` internally but never surfaced it.

## What was built

- `db/migrations/042_incident_severity_assignment_comments.sql` — the
  schema above, plus a composite index for the new sort order.
  `incident_comments` denormalizes `workspace_id` from the parent
  incident (not in Kelvin's literal column list) so it can carry the same
  RLS workspace-isolation policy every other core table has.
- `core/severity.py` (new) — `normalize_severity()` (Azure Sev0-4 / AWS
  alarm state / already-canonical CRITICAL-HIGH-MEDIUM-LOW → canonical
  lowercase), `severity_from_counts()` (for Agent 10), `SEVERITY_SORT_RANK`.
- `core/hitl.py` — `create_incident()` gains `severity: str = "medium"`;
  `mark_executed()` gains `before_state: Optional[dict] = None` (written
  via `COALESCE($5, before_state)` so a `None` never clobbers an existing
  value); both resolution paths' ticketing `incident_summary` now include
  `severity`.
- Each of agents 02/05/08/10/11's `_hitl_gate_node` now passes a real
  derived `severity` to `create_incident`. Agent 02's `_ingest_node` now
  captures `raw_severity` instead of dropping it; its `tools.py` gained
  `_capture_container_resources()`/`_capture_hpa()` (best-effort, never
  raise — a failed capture must never block an operator-approved
  remediation) and `rollback_deployment` now surfaces its
  already-fetched revision as `before_state`.
- `core/ticketing.py`'s `_jira_priority()` now maps
  critical→P1/high→P2/medium→P3/low→P4, falling back to P3 only when
  severity is genuinely missing (same conservative default as before).
- `api/routes/incidents.py`'s `list_incidents` now sorts by severity
  (critical first) then `created_at DESC`; both it and `get_incident`
  now return `severity` in `IncidentResponse` (`db/models.py`).

## Deliberately not built (Phase 2's scope)

No assignment UI, no comment thread UI, no bulk-select — Kelvin's own
phase boundary. Backend-only: schema, derivation, and the two named
wiring points (ticketing priority, sort order).

## Tests and verification

- 1920 passed, same 4 pre-existing unrelated failures
  (`test_diagnose_node_returns_three_options` + 3 secret-redaction
  tests — documented as pre-existing baseline repeatedly throughout this
  session's history, confirmed unrelated by re-reading their failures).
- New/updated: `tests/test_severity.py` (new), `tests/test_hitl_severity_and_before_state.py`
  (new — no prior dedicated test file exercised `create_incident`/
  `mark_executed` directly), severity assertions added to
  `tests/test_agent02.py`/`05`/`08`/`10`/`11`, before_state assertions
  added to `tests/test_agent02.py`'s K8sTools tests, sort-order and
  response-field tests added to `tests/test_incidents_workspace_scope.py`,
  Jira priority-mapping tests added to `tests/test_ticketing.py`.
- **Regression caught and fixed during this pass, not after**: adding
  `severity` to `get_incident`'s `SELECT`/response broke
  `tests/test_incidents_workspace_scope.py`'s existing
  `test_sets_workspace_session_variable_before_query` (its mocked row
  dict had no `severity` key → `KeyError`) — the exact kind of gap
  running the full suite before considering this phase done is meant to
  catch. Fixed by adding the key to that test's fixture, not by silently
  weakening the new code to `.get()`.
- Migration applied via `db/migrate.py`'s existing runner (no manual
  step needed — this repo's runner has been live since 2026-09-15,
  confirmed still fully caught up before this migration: 39/39 tracked
  going in, 40/40 after). Deploy confirmed live via Railway.

---

## If this breaks again

- **A new agent's severity always shows `medium`:** check whether that
  agent's `_hitl_gate_node` actually derives and passes `severity=` to
  `create_incident` — the default exists specifically so a caller that
  hasn't been updated yet degrades safely, not silently to something
  wrong.
- **Jira priority looks wrong for an old, pre-migration incident:**
  expected — `_jira_priority` falls back to P3 when `severity` is
  missing, and incidents created before this migration have the column
  default (`medium` → P3) rather than a retroactively-derived real value.
- **HITL queue sort order and `core/severity.py`'s `SEVERITY_SORT_RANK`
  disagree:** there is no cross-language shared source of truth between
  the SQL `CASE` expression in `list_incidents` and the Python dict —
  `tests/test_incidents_workspace_scope.py`'s
  `test_orders_by_severity_rank_then_created_at_desc` pins the exact
  mapping to catch drift, but a manual edit to one side without the
  other will still pass Python-level type checks.
