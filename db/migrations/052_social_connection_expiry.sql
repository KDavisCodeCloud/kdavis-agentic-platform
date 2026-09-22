-- Migration 052 — LinkedIn (internal_social_connections) token expiry
-- tracking + alerting.
--
-- Root cause of the 2026-09-22 "approved LinkedIn posts not posting"
-- incident: the OAuth callback in api/routes/internal_marketing.py
-- (linkedin_callback) has never captured LinkedIn's `expires_in` from the
-- token exchange response. LinkedIn's standard w_member_social access
-- token (no offline_access/refresh_token support under this app's
-- product config -- that requires a separate Marketing Developer
-- Platform partner approval, not just a scope) has a fixed ~60-day
-- lifetime with no refresh path. The token connected 2026-07-21 expired
-- around 2026-09-19; every scheduled post since has failed closed with a
-- 401 from LinkedIn's Images API, silently, with nothing surfacing it
-- until Kelvin noticed posts weren't going out three days later.
--
-- These two columns let core/social_token_expiry.py (new, mirrors the
-- existing core/credential_expiry.py warn-then-escalate pattern for
-- workspace-facing Azure credentials, adapted for this single-row
-- platform-internal table) warn OWNER_ALERT_EMAIL before expiry next
-- time instead of failing silently for days.

ALTER TABLE internal_social_connections
  ADD COLUMN IF NOT EXISTS expires_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS expiry_warned_at  TIMESTAMPTZ;

-- Backfill the current LinkedIn row's expires_at from what we already
-- know is true (confirmed live via a real 401 from LinkedIn's API this
-- incident): updated_at + LinkedIn's documented 60-day access token
-- lifetime. This is a one-time reconstruction for the row that predates
-- this migration -- linkedin_callback stores the real expires_at from
-- LinkedIn's own response on every future (re)connect, so this backfill
-- logic is never needed again after the next reconnect.
UPDATE internal_social_connections
SET expires_at = updated_at + INTERVAL '60 days'
WHERE platform = 'linkedin' AND expires_at IS NULL;
