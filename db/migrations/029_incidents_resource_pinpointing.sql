-- Migration 029: structured resource/metric fields on incidents, plus the
-- dedup keying columns needed for flapping-alert collapsing.
--
-- Built as Phase 1 of the "resource pinpointing + dedup" scale-readiness
-- build (2026-09-15). Agent 11's diagnosis today only reaches a free-text
-- `parsed_error` -- there's no queryable field for "which resource was
-- this about" or "what metric/value/threshold fired," and no column to
-- key deduplication against a flapping alert. All nullable: this changes
-- nothing about existing rows or any other agent (01-10), which never
-- populate these fields and don't need to.
--
-- occurrence_count/last_seen_at exist so Phase 3 (dedup) can bump an
-- existing open incident instead of creating a new row on every repeat
-- delivery of the same alert.

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS resource_id            TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS resource_name          TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS resource_group         TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS metric_name            TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS metric_current_value   NUMERIC;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS metric_threshold       NUMERIC;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS alert_name             TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS occurrence_count       INT DEFAULT 1;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS last_seen_at           TIMESTAMPTZ;

-- Dedup lookup shape (Phase 3): find an open incident for this
-- workspace+resource+alert combination. Not unique -- a resolved/executed
-- incident for the same resource+alert is a legitimate new occurrence,
-- not a duplicate -- so this indexes the lookup, it doesn't constrain it.
CREATE INDEX IF NOT EXISTS idx_incidents_dedup_lookup
    ON incidents (workspace_id, resource_id, alert_name, execution_status);
