-- Migration 062: GitHub App installations no workspace has claimed (item 3).
--
-- Break-It Lab run 2: Kelvin installed the App on the lab repo and the
-- install callback never fired (the App had no Setup URL), so the
-- `installation` webhook arrived for an installation_id no workspace held
-- and was dropped with only a log line.
--
-- The webhook payload carries no proof of which workspace started the
-- install, so it never links one (Kelvin, 2026-11-17: "never auto-link";
-- guessing could link customer A's repos to customer B). Linking happens
-- only through the signed Setup URL callback. This table records what
-- arrived unclaimed so support can see it, and is cleared when the
-- installation is claimed or uninstalled.
--
-- Platform-level (an installation belongs to no workspace yet), scoped by
-- product_id like cd_funnel_events (migration 060).

CREATE TABLE IF NOT EXISTS github_app_unclaimed_installations (
    installation_id  VARCHAR(64)  PRIMARY KEY,
    product_id       VARCHAR(64)  NOT NULL DEFAULT 'cloud_decoded',
    account_login    VARCHAR(255),
    account_type     VARCHAR(32),
    sender_login     VARCHAR(255),
    repository_count INTEGER,
    received_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE github_app_unclaimed_installations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "github_app_unclaimed_installations_service_role" ON github_app_unclaimed_installations;
CREATE POLICY "github_app_unclaimed_installations_service_role" ON github_app_unclaimed_installations
  FOR ALL TO service_role USING (true) WITH CHECK (true);
