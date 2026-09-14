-- Migration 028: click-through Terms of Service acceptance, timestamped.
--
-- Operational-readiness gap found 2026-09-14: the signup checkbox text
-- ("I agree to the Terms of Service and Privacy Policy") was plain text,
-- not even a link -- no /terms or /privacy page existed, and the checkbox
-- state was never sent to the backend at all. This column plus
-- api/routes/workspaces.py's validation closes that: a workspace cannot be
-- created without a true tos_accepted, and the acceptance is timestamped.

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS tos_accepted_at TIMESTAMPTZ;
