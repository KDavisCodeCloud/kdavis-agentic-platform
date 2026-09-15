-- Migration 037 — Workspace notification channels (Slack, PagerDuty)
-- Tier 1 webhook build (2026-09-14): outbound notifications on incident
-- creation.
--
-- One row per workspace per channel_type. channel_type is deliberately a
-- free-text column, not a fixed two-value enum/CHECK constraint -- Tier 2
-- (OpsGenie outbound) and Tier 3 (Microsoft Teams outbound) both fan out
-- from the exact same "notify every enabled channel on incident creation"
-- choke point in core/hitl.py, and both just need a new channel_type value
-- plus a new sender in core/notifications.py when they're built -- not a
-- new migration or a widened CHECK constraint.
--
-- config_encrypted holds a JSON blob (Fernet-encrypted as one string, same
-- security/encryption.py helper already used by workspace_credentials.py)
-- rather than one plain column per provider's secret shape -- Slack needs
-- only a webhook_url, PagerDuty only a routing_key, but Tier 2/3 providers
-- (OpsGenie API key + optional region, Teams webhook URL, ServiceNow
-- instance + credentials) won't all fit one column shape either. One
-- encrypted JSON blob per channel avoids a schema change per provider.
--
-- RLS: same convention as migrations 031/033 -- ENABLE, no FORCE (see
-- migration 031's comment for why; db/migrate.py's log_security_posture()
-- confirmed this deployment's DATABASE_URL role has BYPASSRLS=true, so
-- this closes the same real gap for every OTHER access path without
-- touching this app's own connection either way).

CREATE TABLE IF NOT EXISTS workspace_notification_channels (
    id               UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id     UUID         NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    channel_type     VARCHAR(50)  NOT NULL,  -- 'slack' | 'pagerduty' today -- see comment above
    config_encrypted TEXT         NOT NULL,
    enabled          BOOLEAN      NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ  DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (workspace_id, channel_type)
);

CREATE INDEX IF NOT EXISTS idx_workspace_notification_channels_workspace
    ON workspace_notification_channels (workspace_id);

DROP TRIGGER IF EXISTS trg_workspace_notification_channels_updated_at ON workspace_notification_channels;
CREATE TRIGGER trg_workspace_notification_channels_updated_at
    BEFORE UPDATE ON workspace_notification_channels
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE workspace_notification_channels ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON workspace_notification_channels;
CREATE POLICY "service_role_all" ON workspace_notification_channels
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON workspace_notification_channels;
CREATE POLICY "workspace_isolation" ON workspace_notification_channels
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);
