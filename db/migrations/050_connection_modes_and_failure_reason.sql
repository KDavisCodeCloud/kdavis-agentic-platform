-- Migration 050 — Per-connection execution mode + graceful permission-
-- failure surfacing.
--
-- aws_connection_mode / azure_connection_mode: 'read_only' or 'execute',
-- set per cloud connection in ConnectionsPanel (frontend/src/components/
-- ConnectionsPanel.tsx). Scoped to AWS and Azure specifically (not
-- GitHub/Azure DevOps/Kubernetes) because those are the two providers
-- agents 05 (IAM Minimizer), 06 (FinOps), and 08 (Drift Detection) call
-- directly via boto3/ARM to mutate a customer's live cloud resources --
-- confirmed by the pre-build execution-path audit. GitHub/Azure DevOps
-- writes (PR/issue creation) and Kubernetes writes (agents 01/02/04/08/
-- 09/10/11) stay governed by HITL approval alone, same as today -- this
-- migration does not touch those.
--
-- Default 'execute' (NOT 'read_only'): every workspace that already
-- connected an AWS role or Azure Service Principal did so against
-- core/workspace_credentials.py's build_permissions_policy(), which is
-- already a write-scoped policy -- defaulting existing connections to
-- read-only here would silently revoke functionality a paying customer
-- already explicitly granted, with no action on their part. A workspace
-- opts into Read-Only going forward, same verify-then-store discipline
-- as every other credential setting in this file.

ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS aws_connection_mode   TEXT NOT NULL DEFAULT 'execute',
  ADD COLUMN IF NOT EXISTS azure_connection_mode TEXT NOT NULL DEFAULT 'execute';

ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_aws_connection_mode_check;
ALTER TABLE workspaces ADD CONSTRAINT workspaces_aws_connection_mode_check
    CHECK (aws_connection_mode IN ('read_only', 'execute'));

ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_azure_connection_mode_check;
ALTER TABLE workspaces ADD CONSTRAINT workspaces_azure_connection_mode_check
    CHECK (azure_connection_mode IN ('read_only', 'execute'));

COMMENT ON COLUMN workspaces.aws_connection_mode IS
    'read_only | execute. read_only: agents 05/06/08 still ingest and diagnose against this AWS account, but no write API call is ever attempted -- HITL cards render execution options disabled and steer to manual resolution instead.';
COMMENT ON COLUMN workspaces.azure_connection_mode IS
    'read_only | execute. Same semantics as aws_connection_mode, for the Azure Service Principal connection.';

-- Graceful 403 handling: today, any exception raised inside an agent's
-- _execute_node (a permission error included) propagates out of
-- api/routes/incidents.py's fire-and-forget `asyncio.create_task(_resume())`
-- with NOTHING catching it -- the incident is left stuck at
-- execution_status='executing' forever, and the operator's HITL card
-- spins on the fake execution-log animation indefinitely. This is a real,
-- separate, currently-live gap the audit found while tracing the
-- execution path for this exact build -- not something introduced by
-- read-only mode. failure_reason gives mark_failed() somewhere to put a
-- human-readable explanation (permission-denied ones name the specific
-- missing action) instead of the incident just hanging.
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS failure_reason TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS failure_kind   TEXT;

ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_failure_kind_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_failure_kind_check
    CHECK (failure_kind IS NULL OR failure_kind IN ('permission_denied', 'execution_error'));

COMMENT ON COLUMN incidents.failure_reason IS
    'Human-readable reason set by core/hitl.py mark_failed() when an approved execution raises. For failure_kind=permission_denied, names the specific missing Azure/AWS action and points to the permissions guide.';
COMMENT ON COLUMN incidents.failure_kind IS
    'permission_denied (Azure 403/AuthorizationFailed or AWS AccessDenied-class error, caught by core/cloud_errors.py) | execution_error (anything else) | NULL for incidents that never reached execution.';
