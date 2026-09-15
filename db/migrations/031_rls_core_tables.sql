-- Migration 031 — Row-level security on core tables
-- Phase 11, scale-readiness build.
--
-- workspaces, incidents, audit_events, and token_usage had ZERO row-level
-- security despite docs/customer/security-questionnaire-response.md
-- telling customers "row-level security enforced at the database layer,
-- not just application logic." That claim was false until this migration.
--
-- Policy shape matches the existing convention already used in
-- 005_leads.sql / 019_cloud_audit_findings.sql: a service_role bypass
-- (Supabase's own internal role, and this app's own DATABASE_URL
-- connection if that role happens to carry service_role privileges) +
-- a workspace-scoped policy keyed on the app.current_workspace_id
-- session variable, which core/workspace_scope.py's
-- workspace_scoped_connection() sets via set_config() before running a
-- scoped query. If that variable is never set, current_setting(...,
-- true) returns NULL, the UUID comparison is never true, and the table
-- is read as empty for that connection -- correctly fails closed.
--
-- Deliberately NOT using FORCE ROW LEVEL SECURITY here. FORCE would
-- also apply these policies to the table OWNER -- and depending on
-- which Postgres role DATABASE_URL actually connects as (checked at
-- every startup by db/migrate.py's log_security_posture(), not
-- assumed), that could be this application's own primary connection.
-- The app does not yet set app.current_workspace_id on every query path
-- (see core/workspace_scope.py's docstring and GAPS.md #20) -- forcing
-- RLS onto an unprepared owner role here would make every unwrapped
-- query return zero rows platform-wide, a self-inflicted outage. Without
-- FORCE, a superuser or the owning role continues working exactly as
-- before (unaffected either way), while ENABLE alone already closes the
-- real gap this migration exists for: any OTHER role that ever queries
-- these tables (Supabase Studio's SQL editor under a human's own
-- session, the anon/authenticated Supabase client keys, a future
-- analytics or support tool) is now blocked from cross-workspace access
-- by the database itself, not by whether that tool's author remembered
-- a WHERE clause.

ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON workspaces;
CREATE POLICY "service_role_all" ON workspaces
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON workspaces;
CREATE POLICY "workspace_isolation" ON workspaces
  FOR ALL TO PUBLIC
  USING (id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (id = (current_setting('app.current_workspace_id', true))::uuid);

ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON incidents;
CREATE POLICY "service_role_all" ON incidents
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON incidents;
CREATE POLICY "workspace_isolation" ON incidents
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON audit_events;
CREATE POLICY "service_role_all" ON audit_events
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON audit_events;
CREATE POLICY "workspace_isolation" ON audit_events
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);

ALTER TABLE token_usage ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON token_usage;
CREATE POLICY "service_role_all" ON token_usage
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON token_usage;
CREATE POLICY "workspace_isolation" ON token_usage
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);
