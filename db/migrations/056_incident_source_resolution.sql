-- Migration 056: source-reported resolution for Alertmanager/Grafana-
-- origin incidents (GAPS.md scale-readiness build, Agent 11 Alertmanager/
-- Grafana ingest).
--
-- Prometheus Alertmanager and Grafana unified alerting both resend a
-- previously-firing alert with status: "resolved" once its underlying
-- condition clears. That must never trigger a fresh diagnosis or a new
-- incident -- see agents/agent_11_resource_health/workflow.py's
-- _resolution_check_node. If an open incident already exists for the
-- same dedup key (workspace_id + resource_id + alert_name), this
-- timestamp records that the *source* reported resolution.
--
-- Advisory only, and deliberately distinct from two existing columns
-- with similar-sounding but different meanings:
--   - resolution_note (migration 038): operator-driven manual resolution
--     ("I'll handle this myself" on the HITL card). Its own comment
--     documents it as "NULL for every other resolution path" -- this is
--     exactly that other path, not a reuse of that column.
--   - resolved_at: set only by core/hitl.py's mark_executed(), i.e. the
--     platform actually executed an approved fix.
-- execution_status is deliberately left untouched by this column --
-- the source clearing an alert doesn't auto-close the incident, an
-- operator still decides.

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS source_resolved_at TIMESTAMPTZ;

COMMENT ON COLUMN incidents.source_resolved_at IS
    'Set when the alert source (Prometheus Alertmanager / Grafana) reported this incident''s underlying condition as resolved. Advisory only -- does not change execution_status or resolved_at. NULL until a resolved-status alert matches this incident''s dedup key (workspace_id + resource_id + alert_name).';
