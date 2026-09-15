-- Migration 036 — SCIM bearer token per workspace
-- Membership/SSO/RBAC/SCIM plan, Phase E.
--
-- SCIM 2.0 endpoints (api/routes/scim.py) are authenticated by a
-- dedicated bearer token, not the shared X-Workspace-Token or a
-- Supabase member session -- an IdP's SCIM connector (Okta, Azure AD)
-- is a machine, not a human or the workspace's own integration
-- credential, and needs its own revocable secret. Stored as a hash only
-- (SHA-256, same convention as workspaces.workspace_token via
-- api.middleware.auth._hash_token) -- the raw token is returned exactly
-- once, at generation time, same "shown once" contract as
-- POST /internal/workspaces/{id}/rotate-token.
--
-- Lives on workspace_sso_config rather than its own table since a SCIM
-- connector only makes sense once SSO is configured (an IdP without an
-- SSO connection to this workspace has no reason to also provision
-- users into it) -- one workspace, one IdP, one SCIM token, same
-- one-row-per-workspace shape that table already has.

ALTER TABLE workspace_sso_config ADD COLUMN IF NOT EXISTS scim_bearer_token_hash TEXT;
ALTER TABLE workspace_sso_config ADD COLUMN IF NOT EXISTS scim_token_created_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_workspace_sso_config_scim_token ON workspace_sso_config (scim_bearer_token_hash);
