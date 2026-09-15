-- Migration 033 — Workspace membership foundation
-- Membership/SSO/RBAC/SCIM plan, Phase A.
--
-- One row per human at a workspace. Generalizes the pattern proven by
-- the Enterprise MCP-invite flow (api/routes/internal_workspaces.py's
-- mcp-invite, admin-provisioned Supabase Auth account +
-- invite_user_by_email) into a real, workspace-admin-self-serve product
-- feature: a workspace's own admin invites teammates, not just THD's
-- internal admin.
--
-- supabase_user_id starts NULL (set on the invite) and is filled in once
-- the invited person accepts (POST /workspace-members/accept, api/
-- middleware/auth.py's get_workspace_member() looks rows up by this
-- column, not by email, once status='active'). A chicken/egg gap this
-- creates: before acceptance, there is no supabase_user_id yet to key
-- on, so the accept endpoint itself must authenticate by matching the
-- caller's verified Supabase email against this table's email column --
-- the ONE place email-matching auth is used instead of the id, and only
-- for that single bootstrap step.

CREATE TABLE IF NOT EXISTS workspace_members (
    id                UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id      UUID         NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    supabase_user_id  UUID         UNIQUE,               -- NULL until invite accepted
    email             VARCHAR(255) NOT NULL,
    role              VARCHAR(50)  NOT NULL DEFAULT 'member',  -- admin | member (Phase C, RBAC, narrows this further)
    status            VARCHAR(50)  NOT NULL DEFAULT 'invited', -- invited | active | deactivated
    invited_at        TIMESTAMPTZ  DEFAULT NOW(),
    joined_at         TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (workspace_id, email)
);

CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace ON workspace_members (workspace_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_supabase_user ON workspace_members (supabase_user_id);

DROP TRIGGER IF EXISTS trg_workspace_members_updated_at ON workspace_members;
CREATE TRIGGER trg_workspace_members_updated_at
    BEFORE UPDATE ON workspace_members
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- RLS: same convention as migration 031 (core tables) -- ENABLE, no
-- FORCE (see that migration's own comment for why forcing it blind
-- against an unknown-posture connecting role would risk an outage;
-- db/migrate.py's log_security_posture() already confirmed this
-- deployment's DATABASE_URL role has BYPASSRLS=true, so this closes the
-- same real gap for every OTHER access path without touching this
-- app's own connection either way).
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON workspace_members;
CREATE POLICY "service_role_all" ON workspace_members
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON workspace_members;
CREATE POLICY "workspace_isolation" ON workspace_members
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);
