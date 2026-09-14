-- Migration 024: per-workspace Azure DevOps credentials (item 5, connectivity
-- build sequence -- see core/repo_tools.py's AzureDevOpsRepoTools and
-- agents/agent_01_cicd_triage/tools.py's CICDTools.azure_token, which has
-- accepted this credential's shape since the item 4 GitHub App migration but
-- had "no per-workspace storage yet" until this migration.
--
-- Deliberately NOT an App/OAuth model like migration 023's GitHub App:
-- Azure DevOps's equivalent (an Azure AD "multi-tenant app" published through
-- the Visual Studio Marketplace, with its own separate publisher-verification
-- process) is a materially bigger lift than GitHub's manifest-flow App
-- registration, and isn't justified for a still-open, not-yet-sold
-- connectivity path. A per-workspace Personal Access Token -- scoped to
-- Code (Read & Write) on one Azure DevOps organization -- is the standard,
-- documented integration pattern for Azure DevOps automation tooling and
-- mirrors the shape GitHub itself used before the App existed (the original
-- github_pat_encrypted column this same migration's sibling, 022, added).
--
-- org is stored alongside the PAT (not just derivable from the repo the
-- agent is pointed at) because Azure DevOps addresses resources as
-- org/project/repo -- three parts, not GitHub's two -- and the PAT itself is
-- already scoped to one org at creation time in Azure DevOps's own UI.

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS azure_devops_org TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS azure_devops_pat_encrypted TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS azure_devops_pat_verified_at TIMESTAMPTZ;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS encrypted_azure_devops_webhook_secret TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS azure_devops_webhook_secret_created_at TIMESTAMPTZ;
