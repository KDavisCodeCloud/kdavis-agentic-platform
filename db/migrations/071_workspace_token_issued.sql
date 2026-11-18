-- Migration 071 — Track whether a workspace token has ever been handed out.
--
-- Owner account at signup (Kelvin, 2026-11-18): the workspace token is never
-- a login. A new workspace is created with a token hash nobody holds, and the
-- owner generates a real token in Settings (shown once) when they need one
-- for webhooks or MCP. workspace_token_issued_at is NULL until then.
-- Every existing workspace was handed its token at creation, so they're
-- backfilled to their created_at; that keeps their 72h rotation grace window.

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS workspace_token_issued_at TIMESTAMPTZ;

UPDATE workspaces
   SET workspace_token_issued_at = COALESCE(created_at, NOW())
 WHERE workspace_token_issued_at IS NULL;

COMMENT ON COLUMN workspaces.workspace_token_issued_at IS
    'When a raw workspace token was last handed to a human (signup before 2026-11-18, or a rotate/generate). NULL = never issued: the stored hash is of a token nobody holds.';
