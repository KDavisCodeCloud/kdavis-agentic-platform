-- Migration 055 — generic alert-dedup table.
--
-- Built for core/linkedin_queue_health.py's stale-approved-post monitor
-- (2026-09-22: Kelvin's core ask after the LinkedIn incident was "make
-- this loop robust, don't let it break silently again" -- the actual gap
-- wasn't any single bug, it was that posts sat stuck for 3 days with zero
-- signal). Generic and reusable by design rather than a one-off column on
-- linkedin_content_queue: any future "check X, alert at most once a day if
-- something's wrong" need (there will be more) can reuse this instead of
-- adding another bespoke *_warned_at column, matching the "extract to a
-- shared utility on the second real use" convention already followed
-- elsewhere in this codebase.

CREATE TABLE IF NOT EXISTS system_health_alerts (
  key             TEXT PRIMARY KEY,
  last_alerted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE system_health_alerts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "system_health_alerts_service_role" ON system_health_alerts;
CREATE POLICY "system_health_alerts_service_role" ON system_health_alerts
  FOR ALL TO service_role USING (true) WITH CHECK (true);
