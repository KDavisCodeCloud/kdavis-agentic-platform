-- Migration 048 — Execution policy (Settings → Policies, admin-only)
--
-- Audit trace performed before this migration (see the Step 0 report
-- delivered alongside this build) confirmed: no code path in any of the
-- 11 agents' workflow.py files, or anywhere else in this repo, executes a
-- repo write or cloud API call without the incident first passing through
-- api/routes/incidents.py's POST /{incident_id}/approve -- every agent's
-- LangGraph graph is a strictly linear
-- ingest -> diagnose -> hitl_gate(interrupt()) -> execute -> complete
-- shape, and every _execute_node only runs on a `selected_option` that
-- LangGraph's Command(resume=...) supplies, which only that one endpoint
-- ever calls. No tiered-autonomy, confidence-based-skip, or
-- "previously-approved pattern" logic exists anywhere (grepped for
-- auto_approve/auto_execute/tiered/previously_approved/low_risk/
-- skip_hitl/bypass across agents/, core/, api/ -- zero matches besides
-- unrelated RLS-bypass comments in core/workspace_scope.py).
--
-- auto_execution_enabled is therefore not gating an existing bypass --
-- there isn't one. It's built anyway, per Kelvin's instruction, so the
-- "approval always required" guarantee is a structural, queryable,
-- auditable workspace setting rather than only a code-review-time fact.
-- Default FALSE on every workspace. core/execution_policy.py's
-- assert_auto_execution_allowed() is the guard any FUTURE code path that
-- wants to execute a remediation WITHOUT an explicit human
-- POST /incidents/{id}/approve call is required to pass -- it raises
-- unless this flag is TRUE, and nothing sets it TRUE by default. See
-- that module's docstring for the full reasoning and why it currently
-- has no call site (there is nothing to gate yet).

ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS auto_execution_enabled BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN workspaces.auto_execution_enabled IS
    'Structural kill-switch, default FALSE. Governs whether ANY future code path may execute a remediation without an explicit human POST /incidents/{id}/approve call. As of migration 048, no such path exists -- every execution today already requires that endpoint regardless of this flag. core/execution_policy.py.assert_auto_execution_allowed() is the enforcement point any future auto-execution feature must call.';

-- Admin-only PATCH /workspace/policies/execution (api/routes/policies.py)
-- writes an audit_events row via core/audit.py's write_audit_event() on
-- every change to this column -- no new table needed, audit_events
-- already carries workspace_id/action/metadata (see migration 001).
