-- Migration 046 — Activation & onboarding (24-gap-closure build, Phase 6)
--
-- incidents.is_test: marks a synthetic incident created by the
-- connection-test button or demo/sandbox seed data. Approving a test
-- incident (api/routes/incidents.py's approve_incident) simulates
-- instant success instead of resuming any real agent workflow --
-- required since is_test incidents use a sentinel agent_id
-- ("system_connection_test"/"system_demo_seed") that has no entry in
-- _WORKFLOW_CLASSES.
--
-- workspaces.setup_test_passed_at: the 5th setup-completeness checklist
-- item. Set only when the connection-test incident is cleaned up (proof
-- the customer actually saw it land in their dashboard and closed the
-- loop), never merely on creation.

ALTER TABLE incidents
  ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_incidents_is_test ON incidents (is_test) WHERE is_test = true;

ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS setup_test_passed_at TIMESTAMPTZ;
