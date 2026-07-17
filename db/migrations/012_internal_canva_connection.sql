-- Internal (owner) Canva Connect API connection — same isolation principle
-- as internal_social_connections (db/migrations/011): this is Kelvin's own
-- design-asset generation pipeline (MKT-CN1's Canva path), not a
-- customer-facing feature. Kept in its own table rather than reusing
-- internal_social_connections because Canva isn't a "social" platform
-- (no posting), it's a design-autofill tool, and its OAuth flow needs two
-- fields LinkedIn's doesn't: a refresh token (Canva access tokens are
-- short-lived) and brand_template_ids so the publisher module knows which
-- Canva Brand Templates are available to autofill against.

CREATE TABLE IF NOT EXISTS internal_canva_connection (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Same singleton-via-UNIQUE-column pattern as internal_social_connections'
  -- platform column, even though this table only ever holds one platform —
  -- keeps ON CONFLICT (platform) trivial and matches the established
  -- convention rather than inventing a constant-expression unique index.
  platform                TEXT NOT NULL UNIQUE CHECK (platform = 'canva'),
  platform_user_id        TEXT NOT NULL,
  platform_display_name   TEXT,
  encrypted_access_token  TEXT NOT NULL,
  encrypted_refresh_token TEXT,
  token_expires_at        TIMESTAMPTZ,
  brand_template_ids      JSONB NOT NULL DEFAULT '{}'::jsonb,
  connected_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE internal_canva_connection ENABLE ROW LEVEL SECURITY;

CREATE POLICY "internal_canva_connection_service_role" ON internal_canva_connection
  FOR ALL TO service_role USING (true) WITH CHECK (true);
