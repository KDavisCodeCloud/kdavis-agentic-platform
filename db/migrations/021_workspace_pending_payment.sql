-- Migration 021: default new workspaces to pending_payment
--
-- Closes a real paywall gap found 2026-09-11: stripe_subscription_status
-- defaulted to 'trialing', which api/middleware/auth.py's get_workspace
-- never blocked on -- a new workspace could use the full product forever
-- without ever completing Stripe checkout. 'trialing' is only supposed
-- to be reached via a real Stripe-granted trial after checkout.
--
-- Only changes the default for NEW inserts -- existing rows (including
-- any already-issued owner/test workspaces) are untouched.

ALTER TABLE workspaces ALTER COLUMN stripe_subscription_status SET DEFAULT 'pending_payment';
