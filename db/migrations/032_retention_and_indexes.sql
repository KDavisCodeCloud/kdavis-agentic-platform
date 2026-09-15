-- Migration 032 — Composite/GIN indexes for retention + hot query paths
-- Phase 12, scale-readiness build.
--
-- core/retention.py's cleanup DELETE filters on (workspace_id via a JOIN
-- to workspaces.product_tier, created_at) -- and the dashboard's own
-- list/filter queries (api/routes/incidents.py's list_incidents,
-- status_filter) hit the same (workspace_id, execution_status,
-- created_at) shape. The existing single-column indexes from
-- 001_initial_schema.sql (idx_incidents_workspace, idx_incidents_status,
-- idx_audit_workspace, idx_audit_created) each help part of that filter
-- but Postgres can only use one of them per scan without a bitmap-and,
-- not the full three-column shape. audit_events.metadata is JSONB with
-- no index at all -- any query filtering on a metadata key does a full
-- table scan.

CREATE INDEX IF NOT EXISTS idx_incidents_workspace_status_created
  ON incidents (workspace_id, execution_status, created_at);

CREATE INDEX IF NOT EXISTS idx_audit_events_workspace_status_created
  ON audit_events (workspace_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_audit_events_metadata_gin
  ON audit_events USING GIN (metadata);
