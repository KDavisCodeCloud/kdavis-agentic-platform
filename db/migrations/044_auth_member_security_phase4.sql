-- Migration 044 — Auth & member security (24-gap-closure build, Phase 4)
--
-- workspace_token_last_used_at / workspace_token_expires_at: the shared
-- workspace token (migration 040 already tracks last4/rotated_at, but
-- never when it was actually last used, and has no expiry concept at
-- all). expires_at is nullable -- NULL means "never expires", the same
-- default behavior every existing token already has, so this is
-- additive-only for every workspace that never opts in.
--
-- require_mfa: workspace-wide Enterprise setting (Phase 4 spec) --
-- admin can require every member session to be at Supabase's aal2
-- before workspace_members auth accepts it. Supabase Auth owns the
-- actual TOTP factor storage/verification (auth.mfa_factors) -- nothing
-- to model here beyond the on/off switch.
--
-- workspace_members.deactivated_at: status already supported
-- 'deactivated' as a value since migration 033's own comment, but no
-- endpoint ever set it and no timestamp existed to record when.

ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS workspace_token_last_used_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS workspace_token_expires_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS require_mfa BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE workspace_members
  ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;
