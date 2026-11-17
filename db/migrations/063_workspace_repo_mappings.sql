-- Migration 063: which repo and IaC file a cloud resource is defined in (G13).
--
-- Break-It Lab A1/Z1: Agent 11 read owner/repo from the alert payload, and
-- SNS / Azure Monitor alerts never carry them, so every fix returned
-- `skipped`. A workspace now says where its IaC lives:
--   - match_prefix NULL: the workspace default (at most one).
--   - match_prefix set: resources whose ID starts with it (case-insensitive;
--     Azure resource IDs are). The longest matching prefix wins.
-- An alert payload that does carry owner/repo still wins over both.
--
-- Prefix rules only, no tag rules: alert payloads carry no resource tags,
-- so a tag rule could never match without an extra cloud lookup.

CREATE TABLE IF NOT EXISTS workspace_repo_mappings (
    id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id  UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    match_prefix  TEXT,
    repository    TEXT        NOT NULL,          -- "owner/repo"
    base_branch   TEXT        NOT NULL DEFAULT 'main',
    iac_path      TEXT        NOT NULL,          -- repo-relative .tf file
    created_by    UUID        REFERENCES workspace_members(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_repo_mappings_default
    ON workspace_repo_mappings (workspace_id) WHERE match_prefix IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_repo_mappings_prefix
    ON workspace_repo_mappings (workspace_id, lower(match_prefix)) WHERE match_prefix IS NOT NULL;

-- RLS, matching migration 031 / 049's policy shape.
ALTER TABLE workspace_repo_mappings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON workspace_repo_mappings;
CREATE POLICY "service_role_all" ON workspace_repo_mappings
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON workspace_repo_mappings;
CREATE POLICY "workspace_isolation" ON workspace_repo_mappings
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);
