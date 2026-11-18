-- Migration 070 — Drop workspaces.auto_execution_enabled.
--
-- Follow-up to the 2026-11-18 claims-audit build (PR #9), which removed every
-- reader and writer of this column: the execution-policy endpoints, the
-- Policies toggle, core/execution_policy.py and the auth SELECT. It shipped in
-- its own deploy so no running worker still selects the column while this
-- migration runs. Every fix needs an explicit approval; there is no setting.

ALTER TABLE workspaces DROP COLUMN IF EXISTS auto_execution_enabled;
