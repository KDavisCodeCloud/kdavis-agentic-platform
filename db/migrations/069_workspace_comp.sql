-- Migration 069 — Complimentary (comped) workspaces.
--
-- Kelvin, 2026-11-18: the owner's dogfood workspace is created through the
-- real /signup flow and then comped to Growth "via an admin flag that skips
-- Stripe; record the comp in the admin audit log". A comp sets the tier and
-- an active subscription status without a Stripe customer; these columns
-- record who comped it, when and why. core/workspace_comp.py is the only
-- writer; every comp also writes a `workspace_comped` audit_events row.

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS comped_at   TIMESTAMPTZ;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS comped_by   TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS comp_reason TEXT;

COMMENT ON COLUMN workspaces.comped_at IS
    'Set when a platform admin comped this workspace (no Stripe billing). NULL = billed normally.';
