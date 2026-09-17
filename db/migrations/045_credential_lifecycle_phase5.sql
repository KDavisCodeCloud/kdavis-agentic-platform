-- Migration 045 — Credential lifecycle (24-gap-closure build, Phase 5)
--
-- Azure Service Principal client secrets and Azure DevOps PATs both have
-- a fixed expiry chosen by the customer when they created the credential
-- in Azure -- we only capture it at connection time, never generate it.
-- AWS roles are deliberately N/A here: an IAM role's AssumeRole trust
-- relationship has no expiring secret the way an SP client secret or a
-- PAT does, so there is nothing to capture or warn about for AWS.
--
-- *_expiry_warned_at: dedups the daily "expiring within 14 days" email
-- per credential so a workspace isn't emailed once a day for two weeks
-- straight. Cleared back to NULL whenever the credential is reconnected/
-- rotated with a new expiry, so the next expiry cycle warns again.
--
-- previous_workspace_token_hash / previous_workspace_token_expires_at:
-- the webhook token rotation grace window. rotate_workspace_token_self_
-- serve moves the OLD hash here (with a 72h expiry) instead of discarding
-- it outright, so an alert source that hasn't been updated yet keeps
-- authenticating for the grace window rather than silently breaking.

ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS azure_client_secret_expires_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS azure_client_secret_expiry_warned_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS azure_devops_pat_expires_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS azure_devops_pat_expiry_warned_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS previous_workspace_token_hash TEXT,
  ADD COLUMN IF NOT EXISTS previous_workspace_token_expires_at TIMESTAMPTZ;
