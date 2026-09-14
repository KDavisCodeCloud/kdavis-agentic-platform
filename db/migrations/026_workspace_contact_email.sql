-- Migration 026: capture a contact email at workspace creation.
--
-- Root-cause fix for the operational-readiness gap found 2026-09-14: the
-- `workspaces` table had no email column at all, so nothing in Cloud
-- Decoded's own code could ever send a welcome email, a post-checkout
-- confirmation, or an Enterprise-tier MCP-invite alert -- there was no
-- address to send to, and no way for the platform owner to identify a
-- customer without going to Stripe's dashboard directly.
--
-- Nullable: existing workspaces created before this migration have no
-- contact email on file and can't be backfilled from anywhere reliable.
-- New workspaces are required to supply one at creation time (enforced in
-- api/routes/workspaces.py, not at the DB layer, to keep the migration
-- itself non-blocking on deploy).

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS contact_email TEXT;
