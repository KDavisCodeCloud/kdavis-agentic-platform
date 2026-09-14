-- Migration 027: real data-deletion path for cancelled/offboarded workspaces.
--
-- Operational-readiness gap found 2026-09-14: Stripe cancellation preserves
-- all data intentionally (stripe_billing.py's own comment), but nothing
-- anywhere in the codebase could actually delete a workspace's stored
-- credentials or PII on request -- a real GDPR/CCPA gap, not just a
-- nice-to-have. data_purged_at marks when POST
-- /internal/workspaces/{id}/purge-data ran; the workspace row and its
-- audit_log/incident history are kept (billing and audit-trail integrity),
-- but every credential and PII column is nulled out.

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS data_purged_at TIMESTAMPTZ;
