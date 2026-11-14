-- Migration 059: per-visitor demo state.
--
-- Before this, every demo visitor shared ONE set of 8 seeded incidents in the
-- demo workspace (migration 057). One visitor approving all 8 left every other
-- visitor with an empty "Needs Action" list for up to 30 minutes, and comments
-- posted by one visitor were visible to all of them.
--
-- Now each demo_sessions row owns its own copy of the baseline incidents.
-- core/demo_sandbox.py's create_demo_session seeds them, and
-- api/routes/incidents.py filters every demo-reachable lookup on
-- demo_session_id. ON DELETE CASCADE means pruning an expired session (the
-- 30-minute run_demo_reset pass) also removes its incidents, and through
-- incident_comments' own ON DELETE CASCADE, its comments. audit_events and
-- token_usage reference incidents ON DELETE SET NULL, so those rows survive.
--
-- Real (non-demo) incidents always have demo_session_id NULL; none of the
-- real-workspace query paths change.
--
-- No new table, so no new RLS policy. incidents keeps its existing
-- workspace-scoped RLS from migration 031.

ALTER TABLE incidents
  ADD COLUMN IF NOT EXISTS demo_session_id UUID REFERENCES demo_sessions(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_incidents_demo_session
  ON incidents (demo_session_id) WHERE demo_session_id IS NOT NULL;

-- Retire the old shared baseline. Sessions minted before this migration have
-- no incidents of their own; the demo page re-mints a session when the API
-- rejects its token, so deleting them hands every open tab a fresh, seeded
-- session instead of an empty console.
DELETE FROM incidents
 WHERE is_test = true
   AND demo_session_id IS NULL
   AND workspace_id IN (SELECT id FROM workspaces WHERE is_demo_workspace);

DELETE FROM demo_sessions;
