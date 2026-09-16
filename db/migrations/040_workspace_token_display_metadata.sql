-- Onboarding completeness build, item 4 (self-serve token management).
--
-- workspaces.workspace_token stores only a SHA-256 hash (see
-- db/schema.sql's own comment: "API auth token (hashed)") -- the raw
-- token is fundamentally unrecoverable once issued, same one-way
-- property as a password hash. There is no way to "reveal" an existing
-- token after the fact; the only real reveal moment is immediately
-- after issuance/rotation (api/routes/internal_workspaces.py's own
-- rotate-token docstring already says this explicitly: "only
-- rotate-token ever hands back a raw token, and only once").
--
-- These two columns exist purely to make the masked display usable
-- without inventing a fake "reveal" of something that can't be
-- recovered: a last-4 hint (like Stripe/GitHub key displays) plus when
-- the current token was last issued. Neither is sensitive on its own --
-- 4 characters of a long random token reveals nothing exploitable.
ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS workspace_token_last4 VARCHAR(4),
  ADD COLUMN IF NOT EXISTS workspace_token_rotated_at TIMESTAMPTZ;

-- Best-effort backfill for existing workspaces: we don't know their raw
-- token (never stored), so last4 stays NULL for them (shown in the UI as
-- "no hint available -- rotate to get one"). rotated_at backfills to
-- created_at as an honest lower bound (the token has been in place at
-- least since the workspace was created, even if never rotated).
UPDATE workspaces
SET workspace_token_rotated_at = created_at
WHERE workspace_token_rotated_at IS NULL;
