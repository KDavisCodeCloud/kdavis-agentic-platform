-- Internal (owner/team) agent execution log — completely separate from the
-- customer-facing `incidents` table. Backs POST/GET /internal/agents/* in
-- api/routes/internal_agents.py, gated by api/middleware/internal_auth.py
-- (Supabase session JWT + user_metadata.role == "admin"), never by
-- X-Workspace-Token. Not tenant-scoped data — tenant_id is the fixed
-- 'internal' placeholder, matching the existing convention in
-- security/audit_log.py for agents with no real tenant concept.

CREATE TABLE IF NOT EXISTS internal_agent_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL DEFAULT 'internal',
  agent_id TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  requested_by_email TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'executing' CHECK (status IN ('executing', 'executed', 'failed')),
  result JSONB,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_internal_agent_runs_agent_id ON internal_agent_runs(agent_id);
CREATE INDEX IF NOT EXISTS idx_internal_agent_runs_created_at ON internal_agent_runs(created_at DESC);

ALTER TABLE internal_agent_runs ENABLE ROW LEVEL SECURITY;

-- Service-role only — this backend always talks to Postgres via the shared
-- db_pool with elevated credentials, never a per-user Supabase client, so
-- there is no anon/authenticated policy to write here. TO service_role is
-- not optional: a bare USING (true) with no TO clause defaults to PUBLIC.
CREATE POLICY "internal_agent_runs_service_role" ON internal_agent_runs
  FOR ALL TO service_role USING (true) WITH CHECK (true);
