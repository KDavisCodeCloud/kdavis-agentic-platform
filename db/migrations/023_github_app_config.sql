-- Migration 023: GitHub App migration (item 4 of the connectivity build
-- sequence, decided 2026-09-13) -- retires PATs in favor of a real GitHub
-- App. One App for the whole platform; each customer workspace gets its own
-- installation.
--
-- github_app_config: singleton row (id always 'singleton') holding the
-- App's own identity -- created once via the manifest-conversion flow
-- (core/github_app.py, api/routes/github_app_admin.py). Not per-workspace;
-- there is exactly one Cloud Decoded GitHub App.
--
-- workspaces.github_app_installation_id: which installation of that one App
-- belongs to this workspace. NULL until the customer clicks through the
-- App's install flow. When set, core/workspace_credentials.py mints a fresh
-- ~1hr installation token per call instead of decrypting a stored PAT --
-- github_pat_encrypted stays as a legacy fallback for any workspace that
-- connected before the App existed (Kelvin's own included), but
-- PATCH /workspace/credentials/github's PAT-verify flow is deprecated for
-- new connections as of this migration.

CREATE TABLE IF NOT EXISTS github_app_config (
    id TEXT PRIMARY KEY DEFAULT 'singleton',
    app_id TEXT NOT NULL,
    app_slug TEXT NOT NULL,
    client_id TEXT NOT NULL,
    client_secret_encrypted TEXT NOT NULL,
    webhook_secret_encrypted TEXT NOT NULL,
    private_key_encrypted TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT github_app_config_singleton CHECK (id = 'singleton')
);

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS github_app_installation_id TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS github_app_installed_at TIMESTAMPTZ;
