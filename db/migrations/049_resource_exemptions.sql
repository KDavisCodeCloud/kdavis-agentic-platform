-- Migration 049 — Resource exemptions (Settings → Policies)
--
-- Lets a workspace mark a specific cloud resource as exempt from
-- ingest/diagnosis -- e.g. a known-noisy dev resource that alerts
-- constantly for a reason the operator has already accepted. Checked
-- BEFORE any LLM diagnosis call, at the same ingest-time dedup point
-- agent_11 (Resource Health) and agent_08 (Drift Detection) already use
-- to collapse repeat alerts (core/hitl.py's find_open_incident/
-- bump_occurrence, migration 029) -- an exempted resource increments
-- suppressed_count and returns immediately, spending zero tokens.
--
-- resource_id matches incidents.resource_id (migration 029, TEXT --
-- provider-native identifier: an ARN, an Azure resource ID, etc.), not a
-- platform-internal UUID -- exemptions are looked up by the same key
-- ingest already has in hand before diagnosis runs.

CREATE TABLE IF NOT EXISTS resource_exemptions (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id    UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    resource_id     TEXT        NOT NULL,
    resource_name   TEXT,
    reason          TEXT        NOT NULL,
    suppressed_count INT        NOT NULL DEFAULT 0,
    created_by      UUID        REFERENCES workspace_members(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at      TIMESTAMPTZ,
    revoked_by      UUID        REFERENCES workspace_members(id),
    UNIQUE (workspace_id, resource_id)
);

CREATE INDEX IF NOT EXISTS idx_resource_exemptions_workspace
    ON resource_exemptions (workspace_id)
    WHERE revoked_at IS NULL;

-- RLS, matching migration 031's exact policy shape (service_role bypass +
-- app.current_workspace_id session-variable isolation, set by
-- core/workspace_scope.py's workspace_scoped_connection()). Not FORCE, for
-- the same owner-role reason migration 031 documents.
ALTER TABLE resource_exemptions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON resource_exemptions;
CREATE POLICY "service_role_all" ON resource_exemptions
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON resource_exemptions;
CREATE POLICY "workspace_isolation" ON resource_exemptions
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);

COMMENT ON TABLE resource_exemptions IS
    'Resources a workspace has explicitly opted out of ingest/diagnosis for. Checked before any LLM call fires -- see agent_08/agent_11 ingest/dedup nodes. reason is required (never a silent suppression). suppressed_count is incremented every time an incoming alert for resource_id is skipped, so an exemption stays visible rather than invisible.';
