-- Migration 067 — New AWS/Azure connections start in Read-Only mode.
--
-- Kelvin's decision after the 2026-11-18 claims audit ("Build: read-only
-- default"). Migration 050 defaulted aws_connection_mode /
-- azure_connection_mode to 'execute' so existing connections kept the
-- write access their customers had already granted. That stays true: this
-- migration changes the column default and flips only workspaces that
-- have NOT connected that provider yet (there is no granted access to
-- revoke). A workspace that already connected AWS or Azure keeps its
-- current mode. Switching to Execute stays a one-click, audited change in
-- Settings → Connections.

ALTER TABLE workspaces ALTER COLUMN aws_connection_mode   SET DEFAULT 'read_only';
ALTER TABLE workspaces ALTER COLUMN azure_connection_mode SET DEFAULT 'read_only';

UPDATE workspaces
   SET aws_connection_mode = 'read_only'
 WHERE aws_connection_mode = 'execute'
   AND aws_role_arn IS NULL;

UPDATE workspaces
   SET azure_connection_mode = 'read_only'
 WHERE azure_connection_mode = 'execute'
   AND azure_client_id IS NULL;

COMMENT ON COLUMN workspaces.aws_connection_mode IS
    'read_only (default since migration 067) | execute. read_only: agents still ingest and diagnose against this AWS account, but no write API call is ever attempted.';
COMMENT ON COLUMN workspaces.azure_connection_mode IS
    'read_only (default since migration 067) | execute. Same semantics as aws_connection_mode, for the Azure Service Principal connection.';
