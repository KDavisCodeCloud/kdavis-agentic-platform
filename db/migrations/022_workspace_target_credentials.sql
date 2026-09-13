-- Migration 022: per-workspace target-system credentials for agents 01/05/06/08
--
-- Agents 01 (CI/CD), 05 (IAM), 06 (FinOps), and 08 (Drift) previously read a
-- single shared GitHub/AWS/Azure token from the server's process env vars --
-- fine for one internal user, not correct for any real second customer.
-- These columns let each workspace store its own credentials, decrypted
-- per-call the same way encrypted_llm_key already is (security/encryption.py).
--
-- GitHub: a classic PAT, plus a per-workspace webhook HMAC secret -- closes
-- api/routes/webhooks.py's "per-workspace secrets are Phase 4" gap, which
-- until now relied on one global GITHUB_WEBHOOK_SECRET for every workspace.
--
-- AWS: cross-account role assumption with an external ID -- NEVER raw
-- access keys, matching kdavis-finops-agent's already-proven finops_tenants
-- pattern (see that repo's db/migrations for the same shape).
--
-- Azure: Service Principal (tenant/client/secret/subscription) -- same
-- shape as kdavis-finops-agent's migration 002, but this platform's agents
-- actually write (unlike the satellite products' read-only Reader role),
-- so the Service Principal a customer creates for this needs Contributor,
-- not just Reader -- that's a setup-instructions detail, not a schema one.

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS github_pat_encrypted TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS github_pat_verified_at TIMESTAMPTZ;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS encrypted_github_webhook_secret TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS github_webhook_secret_created_at TIMESTAMPTZ;

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS aws_role_arn TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS aws_external_id TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS aws_role_verified_at TIMESTAMPTZ;

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS azure_tenant_id TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS azure_client_id TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS azure_client_secret_encrypted TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS azure_subscription_id TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS azure_verified_at TIMESTAMPTZ;
