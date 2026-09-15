-- Migration 030: alert_ingestion_log -- durability for webhook-triggered
-- agent runs.
--
-- Phase 6, scale-readiness build (2026-09-15). FastAPI's BackgroundTasks
-- (used by every webhook route today) only exist in this one process's
-- memory -- if the process restarts (deploy, crash, OOM) between
-- returning 202 and a background task finishing, that task is lost with
-- no trace, and neither GitHub, Azure DevOps, nor Azure Monitor/AWS SNS
-- will ever retry, since a 2xx was already returned before the work even
-- started. This table makes "alert received" durable BEFORE the 202
-- goes out, so a lost in-process task leaves a recoverable, queryable
-- row (processed_at IS NULL) instead of vanishing.
--
-- No real SQS queue is provisioned in this environment (the platform's
-- own AWS IAM user is narrowly scoped -- confirmed this session when
-- live-verifying Agent 11's SNS path required Kelvin to attach a scoped
-- policy for even one test topic), so this is the DB-backed fallback
-- explicitly authorized for that case: simpler, no new infrastructure
-- dependency. job_queue/worker.py's SQS scaffold stays available for a
-- future pass if/when a real queue is provisioned.

CREATE TABLE IF NOT EXISTS alert_ingestion_log (
    id             UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id   UUID         REFERENCES workspaces(id) ON DELETE CASCADE,
    raw_payload    JSONB        NOT NULL,
    received_at    TIMESTAMPTZ  DEFAULT NOW(),
    processed_at   TIMESTAMPTZ,
    worker_id      TEXT
);

-- Recovery-set query shape: unprocessed rows older than N minutes.
CREATE INDEX IF NOT EXISTS idx_alert_ingestion_log_unprocessed
    ON alert_ingestion_log (received_at)
    WHERE processed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_alert_ingestion_log_workspace
    ON alert_ingestion_log (workspace_id);
