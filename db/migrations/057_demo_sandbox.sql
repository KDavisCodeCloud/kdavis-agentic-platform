-- Migration 057: public demo sandbox (Phase 6).
--
-- workspaces.is_demo_workspace marks the ONE shared workspace that backs
-- GET /demo (api/routes/demo.py, core/demo_sandbox.py). A partial unique
-- index enforces "at most one" -- core/demo_sandbox.py's
-- get_or_create_demo_workspace() relies on this being a singleton, not a
-- convention it merely hopes holds.
--
-- Explicit aws_connection_mode/azure_connection_mode = 'read_only' at
-- creation (core/demo_sandbox.py) is a THIRD, redundant guarantee that
-- no real cloud action can ever fire from this workspace, on top of two
-- independent ones that already make it structurally impossible: (1) no
-- credential column is ever populated here, (2) every seeded incident
-- carries is_test = true (migration 046), which api/routes/incidents.py's
-- approve_incident short-circuits to a simulated result before ever
-- calling build_agent_credentials or an agent's resume().
--
-- demo_sessions is deliberately NOT workspace_members: a demo visitor
-- gets no real membership row, just a hashed, expiring bearer token
-- (api/middleware/auth.py's _get_workspace_by_demo_session) that
-- resolves to a workspace dict with member_role='approver' hardcoded in
-- Python, never persisted. One row per visitor session; many sessions
-- point at the one demo workspace concurrently.

ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS is_demo_workspace BOOLEAN NOT NULL DEFAULT false;

CREATE UNIQUE INDEX IF NOT EXISTS idx_workspaces_one_demo_workspace
  ON workspaces ((is_demo_workspace)) WHERE is_demo_workspace;

CREATE TABLE IF NOT EXISTS demo_sessions (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id        UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    session_token_hash  VARCHAR(64) UNIQUE NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_demo_sessions_token   ON demo_sessions (session_token_hash);
CREATE INDEX IF NOT EXISTS idx_demo_sessions_expires ON demo_sessions (expires_at);
