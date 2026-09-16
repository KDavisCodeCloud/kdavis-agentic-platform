-- Migration 042: Incident schema foundation (24-gap-closure build, Phase 1).
--
-- severity: critical | high | medium | low, derived at ingest per-agent
-- from whatever real signal that agent already has (see
-- core/severity.py's normalize_severity() -- agents 02/05/08/10/11 each
-- have a genuine existing severity-shaped signal, verified by reading
-- their diagnose/ingest nodes directly, not assumed; agents 01/03/04/06/
-- 07/09 have none and get the same 'medium' default this backfill uses).
-- Backfilled to 'medium' for every pre-existing row -- the same
-- conservative default, not a guess at what those incidents actually
-- were.
--
-- assigned_to: nullable FK to workspace_members. ON DELETE SET NULL (not
-- CASCADE) -- removing a member must return their incidents to
-- unassigned, never delete the incident itself (this is also Phase 4's
-- own stated behavior for member deactivation; the FK action is what
-- makes that true at the database level regardless of which code path
-- triggers the deletion).
--
-- incident_comments: workspace_id is denormalized from the parent
-- incident (not in Kelvin's literal column list, which was incident_id/
-- member_id/body/created_at) so this table can carry the same RLS
-- workspace-isolation policy every other core table has (migration 031)
-- without a per-row subquery join through incidents -- CLAUDE.md's own
-- "tenant/product scoping on every table" rule applies here the same as
-- everywhere else in this schema.
--
-- before_state: JSONB, nullable. Only agent_02 (K8s) performs a genuine
-- direct-cloud-API mutation today (patch_deployment_memory/apply_hpa/
-- rollback_deployment against a live cluster) -- every other agent's
-- "execute" step opens a PR, which is already reversible via git revert
-- and was never in scope for this. Confirmed by reading all 11 agents'
-- _execute_node methods before writing this, not assumed.

ALTER TABLE incidents
  ADD COLUMN IF NOT EXISTS severity VARCHAR(10) NOT NULL DEFAULT 'medium',
  ADD COLUMN IF NOT EXISTS assigned_to UUID REFERENCES workspace_members(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS before_state JSONB;

ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_severity_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_severity_check
  CHECK (severity IN ('critical', 'high', 'medium', 'low'));

UPDATE incidents SET severity = 'medium' WHERE severity IS NULL;

CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents (severity);
CREATE INDEX IF NOT EXISTS idx_incidents_assigned_to ON incidents (assigned_to) WHERE assigned_to IS NOT NULL;

-- HITL queue sort order (api/routes/incidents.py's list_incidents) needs
-- severity + created_at together -- this composite index serves
-- "ORDER BY severity_rank, created_at DESC" without a second lookup.
CREATE INDEX IF NOT EXISTS idx_incidents_workspace_severity_created
  ON incidents (workspace_id, severity, created_at DESC);

CREATE TABLE IF NOT EXISTS incident_comments (
    id            UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id  UUID         NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    incident_id   UUID         NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    member_id     UUID         REFERENCES workspace_members(id) ON DELETE SET NULL,
    body          TEXT         NOT NULL,
    created_at    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incident_comments_incident ON incident_comments (incident_id, created_at);
CREATE INDEX IF NOT EXISTS idx_incident_comments_workspace ON incident_comments (workspace_id);

-- RLS: same convention as migration 031/033 (ENABLE, no FORCE -- see
-- migration 031's own comment on why forcing it blind against an
-- unknown-posture connecting role risks an outage; db/migrate.py's
-- log_security_posture() already confirmed this deployment's
-- DATABASE_URL role has BYPASSRLS=true, so this protects every OTHER
-- access path, same as every other RLS-enabled table in this schema).
ALTER TABLE incident_comments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON incident_comments;
CREATE POLICY "service_role_all" ON incident_comments
  FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "workspace_isolation" ON incident_comments;
CREATE POLICY "workspace_isolation" ON incident_comments
  FOR ALL TO PUBLIC
  USING (workspace_id = (current_setting('app.current_workspace_id', true))::uuid)
  WITH CHECK (workspace_id = (current_setting('app.current_workspace_id', true))::uuid);
