-- Migration 068 — Row-level security on alert_ingestion_log.
--
-- Kelvin's decision after the 2026-11-18 claims audit ("alert_ingestion_log
-- retention + RLS"). This table holds the raw, unsanitized webhook payload
-- of every alert a workspace sends (migration 030) and was the one
-- workspace-scoped table carrying customer payloads with no RLS. Same
-- pattern as migration 031: a service-role policy first, then workspace
-- isolation keyed on app.current_workspace_id. Rows with a NULL
-- workspace_id never match the isolation policy, so they're reachable only
-- by the service role.
--
-- Retention lives in core/retention.py (30 days; each workspace's first row
-- is kept with its payload removed so the setup checklist still knows the
-- alert source was verified).

ALTER TABLE alert_ingestion_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all" ON alert_ingestion_log;
CREATE POLICY "service_role_all" ON alert_ingestion_log
  FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "workspace_isolation" ON alert_ingestion_log;
CREATE POLICY "workspace_isolation" ON alert_ingestion_log
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);
