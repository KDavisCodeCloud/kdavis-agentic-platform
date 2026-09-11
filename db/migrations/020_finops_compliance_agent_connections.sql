-- Migration 020: FinOps/Compliance agent connection columns on workspaces
--
-- Backs the new /api/v1/finops-agent/* and /api/v1/compliance-agent/*
-- proxy routes, which let a workspace connect its AWS account to the
-- separately-deployed kdavis-finops-agent / kdavis-compliance-agent
-- Railway services. Named with an explicit "_agent_" marker to stay
-- visually distinct from this repo's own unrelated agents/agent_06_finops/
-- and core/compliance.py (WorkspaceComplianceGuard) -- neither has
-- anything to do with these two products.
--
-- 1:1 per workspace, so flat columns rather than a new table -- same
-- precedent as encrypted_llm_key (see 001_initial schema and
-- api/routes/workspaces.py's save_llm_key).
--
-- *_agent_setup_json stores the aws_trust_policy/aws_permissions_policy
-- JSON verbatim from the remote service's POST /tenants response (not
-- secret -- it's meant to be pasted into AWS by the customer) so it can
-- be redisplayed on a page reload before the role is verified, with zero
-- duplicated policy-generation logic in this repo.
--
-- *_agent_tenant_id IS NULL      -> never connected
-- *_agent_connected_at IS NULL   -> tenant created, role not verified yet
-- *_agent_connected_at IS NOT NULL -> active

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS finops_agent_tenant_id UUID;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS encrypted_finops_agent_tenant_token TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS finops_agent_setup_json JSONB;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS finops_agent_connected_at TIMESTAMPTZ;

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS compliance_agent_tenant_id UUID;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS encrypted_compliance_agent_tenant_token TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS compliance_agent_setup_json JSONB;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS compliance_agent_connected_at TIMESTAMPTZ;
