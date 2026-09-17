-- Migration 043: 24-gap-closure build, Phase 3 (notification layer).
--
-- min_severity/quiet_hours_*: per-channel, not per-workspace -- Kelvin's
-- own example ("PagerDuty critical-only, Slack all") requires this to
-- vary per channel_type, not be one workspace-wide setting.
-- min_severity is nullable TEXT (no CHECK against core/severity.py's
-- VALID_SEVERITIES here -- application code validates on write, same
-- convention as execution_status elsewhere in this schema, migration
-- 001's own comment); NULL means "every severity" (the existing,
-- unchanged behavior for a channel that never sets a floor).
-- quiet_hours_timezone is a plain TEXT IANA zone name (e.g.
-- "America/Los_Angeles") -- validated at the application layer
-- (zoneinfo.ZoneInfo raising on a bad name), not a DB-level check.
--
-- "email" needs no new column -- channel_type is already free-text
-- (migration 037's own comment: Tier 2/3 channels "just need a new
-- channel_type value... not a new migration") and its one piece of
-- config (a destination address) fits the existing config_encrypted
-- JSON blob exactly like slack's webhook_url / pagerduty's routing_key.
ALTER TABLE workspace_notification_channels
  ADD COLUMN IF NOT EXISTS min_severity TEXT,
  ADD COLUMN IF NOT EXISTS quiet_hours_start TIME,
  ADD COLUMN IF NOT EXISTS quiet_hours_end TIME,
  ADD COLUMN IF NOT EXISTS quiet_hours_timezone TEXT;

-- Durable outbound retry queue. core/notifications.py's notify_incident_channels
-- and core/ticketing.py's notify_resolution both used to just log-and-drop
-- a failed send (see each module's own docstring, "never raises... every
-- failure is caught and logged as a warning"). A row here is the
-- alternative to that silent drop -- a periodic in-process loop
-- (api/main.py, same pattern as _retention_loop/_onboarding_sequence_loop)
-- retries with exponential backoff up to max_attempts, then marks
-- 'exhausted' so it surfaces in the dashboard instead of only ever
-- existing as a log line nobody is watching.
-- send_kind distinguishes WHICH sender to retry with for a channel_type
-- that means two different things depending on when it fires:
-- 'pagerduty' is send_pagerduty_notification (create) from
-- core/notifications.py OR send_pagerduty_resolve_event (resolve) from
-- core/ticketing.py -- channel_type alone can't tell those apart. slack/
-- email are always 'create'; jira/linear/github_issues/servicenow are
-- always 'resolve' (ticketing only ever fires on resolution). resolved_by
-- is only meaningful for 'resolve' (every create_*_ticket function takes
-- it), NULL otherwise.
CREATE TABLE IF NOT EXISTS notification_retry_queue (
    id               UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id     UUID         NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    channel_type     TEXT         NOT NULL,
    send_kind        TEXT         NOT NULL DEFAULT 'create' CHECK (send_kind IN ('create', 'resolve')),
    resolved_by      TEXT,
    payload_json     JSONB        NOT NULL,  -- the incident_summary dict, exactly as first attempted
    attempt_count    INT          NOT NULL DEFAULT 0,
    max_attempts     INT          NOT NULL DEFAULT 5,
    next_attempt_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    status           TEXT         NOT NULL DEFAULT 'pending'
                                   CHECK (status IN ('pending', 'exhausted', 'succeeded')),
    last_error       TEXT,
    created_at       TIMESTAMPTZ  DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notification_retry_queue_due
    ON notification_retry_queue (status, next_attempt_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_notification_retry_queue_workspace
    ON notification_retry_queue (workspace_id, status);

DROP TRIGGER IF EXISTS trg_notification_retry_queue_updated_at ON notification_retry_queue;
CREATE TRIGGER trg_notification_retry_queue_updated_at
    BEFORE UPDATE ON notification_retry_queue
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE notification_retry_queue ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON notification_retry_queue;
CREATE POLICY "service_role_all" ON notification_retry_queue
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON notification_retry_queue;
CREATE POLICY "workspace_isolation" ON notification_retry_queue
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);

-- Incidents suppressed by a channel's quiet hours -- never retried (this
-- isn't a failure), instead batched into one digest notification sent
-- the next time that channel is checked and found to be OUTSIDE its
-- quiet-hours window. digested=false rows are "still waiting for the
-- window to end"; the digest sender flips them true rather than deleting,
-- so there's a real record of what was suppressed and when.
CREATE TABLE IF NOT EXISTS notification_suppressed (
    id            UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id  UUID         NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    channel_type  TEXT         NOT NULL,
    incident_id   UUID,
    payload_json  JSONB        NOT NULL,
    suppressed_at TIMESTAMPTZ  DEFAULT NOW(),
    digested      BOOLEAN      NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_notification_suppressed_pending
    ON notification_suppressed (workspace_id, channel_type) WHERE digested = false;

ALTER TABLE notification_suppressed ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON notification_suppressed;
CREATE POLICY "service_role_all" ON notification_suppressed
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON notification_suppressed;
CREATE POLICY "workspace_isolation" ON notification_suppressed
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);
