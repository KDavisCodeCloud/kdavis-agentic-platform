-- Migration 035 — Per-workspace SSO configuration storage
-- Membership/SSO/RBAC/SCIM plan, Phase D.
--
-- Storage layer for "use Supabase Auth's native SSO support (SAML 2.0 +
-- OAuth providers)" -- mirrors the existing per-workspace external-
-- system credential pattern (022_workspace_target_credentials.sql's
-- github/aws/azure columns, kept as its own table here rather than more
-- workspaces columns since SSO config is multi-valued in a way those
-- single-value-per-provider credentials aren't -- an IdP's SAML metadata
-- XML blob is a different shape than a role ARN).
--
-- One row per workspace (UNIQUE workspace_id -- one active IdP per
-- customer, matching how Supabase's own SSO routes by email domain, one
-- domain to one provider). idp_metadata_xml_encrypted follows
-- encrypted_llm_key's existing convention (security/encryption.py) since
-- SAML IdP metadata can carry sensitive endpoint/certificate details.
--
-- supabase_sso_provider_id is NULL until someone with Supabase Management
-- API access actually registers this config as a real SSO provider
-- (POST /v1/projects/{ref}/config/auth/sso/providers) -- that call is
-- deliberately NOT made by application code in this phase; see GAPS.md
-- for why (no Management API token available to verify the integration
-- against, a materially different credential than SUPABASE_SERVICE_ROLE_KEY).
-- status stays 'pending' until that id is set.

CREATE TABLE IF NOT EXISTS workspace_sso_config (
    id                          UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id                UUID         NOT NULL UNIQUE REFERENCES workspaces(id) ON DELETE CASCADE,
    provider_type               VARCHAR(20)  NOT NULL DEFAULT 'saml',  -- saml | oidc
    email_domain                VARCHAR(255) NOT NULL,                 -- e.g. 'acme.com' -- Supabase routes SSO by this
    idp_metadata_url            TEXT,                                  -- SAML metadata URL or OIDC discovery URL
    idp_metadata_xml_encrypted  TEXT,                                  -- raw SAML metadata XML, Fernet-encrypted (security/encryption.py)
    supabase_sso_provider_id    TEXT,                                  -- set once actually registered with Supabase -- see above
    status                      VARCHAR(20)  NOT NULL DEFAULT 'pending', -- pending | active | disabled
    created_at                  TIMESTAMPTZ  DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workspace_sso_config_workspace ON workspace_sso_config (workspace_id);
CREATE INDEX IF NOT EXISTS idx_workspace_sso_config_domain ON workspace_sso_config (email_domain);

DROP TRIGGER IF EXISTS trg_workspace_sso_config_updated_at ON workspace_sso_config;
CREATE TRIGGER trg_workspace_sso_config_updated_at
    BEFORE UPDATE ON workspace_sso_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- RLS: same convention as migrations 031/033 -- ENABLE, no FORCE (see
-- 031's own comment for why forcing it blind is risky; this deployment's
-- DATABASE_URL role is already confirmed BYPASSRLS=true via
-- db/migrate.py's log_security_posture(), so this closes the gap for
-- every OTHER access path without affecting this app's own connection).
ALTER TABLE workspace_sso_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON workspace_sso_config;
CREATE POLICY "service_role_all" ON workspace_sso_config
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON workspace_sso_config;
CREATE POLICY "workspace_isolation" ON workspace_sso_config
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);
