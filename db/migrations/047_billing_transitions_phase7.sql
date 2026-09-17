-- Migration 047 — Billing transitions (24-gap-closure build, Phase 7)
--
-- downgrade_blocked_reason: set when a Stripe-side downgrade (customer.
-- subscription.updated to a lower-priced tier) would drop the workspace
-- below its current active+invited member count for the new tier's seat
-- cap. The tier change is NOT applied in our system in that case (the
-- workspace keeps being served at its current, higher tier) until seats
-- are reduced -- surfaced here so GET /billing/status can show a clear
-- reason instead of a silent no-op. NULL means no downgrade is blocked.

ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS downgrade_blocked_reason TEXT;
