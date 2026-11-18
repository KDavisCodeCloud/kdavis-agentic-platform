-- Migration 065: regression linking (G2) + ticket reopen retries (item 5).
--
-- Break-It Lab step 6: every problem re-injected after a fix came back as a
-- fresh, unlinked incident; agents 05/06/08 stored no resource identity.
--
--   regression_key        deterministic "what was wrong, where" set by the
--                         agent (core/regression.py), never LLM text
--   previous_incident_id  the most recent earlier incident with the same
--                         workspace + agent + regression_key
--   is_regression         that earlier incident was fixed (or claimed it was)
--
-- No new table, so no new RLS policy; incidents keeps its workspace-scoped
-- RLS from migration 031.

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS regression_key       TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS previous_incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS is_regression        BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_incidents_regression_key
    ON incidents (workspace_id, agent_id, regression_key, created_at DESC)
    WHERE regression_key IS NOT NULL;

-- verification_failed reopens the resolution ticket (core/ticketing.py);
-- a failed reopen is retried like a failed create/resolve.
ALTER TABLE notification_retry_queue DROP CONSTRAINT IF EXISTS notification_retry_queue_send_kind_check;
ALTER TABLE notification_retry_queue ADD CONSTRAINT notification_retry_queue_send_kind_check
    CHECK (send_kind IN ('create', 'resolve', 'reopen'));
