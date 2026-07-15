-- Internal (owner) social account connections — completely separate from
-- workspace_social_connections (the customer-facing Cloud Decoded product
-- feature in api/routes/content.py). This backs Kelvin's own MKT-LI1
-- LinkedIn posting pipeline (linkedin_content_queue), not a paying
-- customer's connected account. Single row per platform, no workspace_id -
-- there is exactly one owner.

CREATE TABLE IF NOT EXISTS internal_social_connections (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform                TEXT NOT NULL UNIQUE CHECK (platform IN ('linkedin')),
  platform_user_id        TEXT NOT NULL,
  platform_display_name   TEXT,
  encrypted_access_token  TEXT NOT NULL,
  author_urn              TEXT,
  connected_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE internal_social_connections ENABLE ROW LEVEL SECURITY;

-- Service-role only - this backend always talks to Postgres via the shared
-- db_pool with elevated credentials, matching internal_agent_runs' own
-- convention (db/migrations/008). TO service_role is not optional: a bare
-- USING (true) with no TO clause defaults to PUBLIC.
CREATE POLICY "internal_social_connections_service_role" ON internal_social_connections
  FOR ALL TO service_role USING (true) WITH CHECK (true);
