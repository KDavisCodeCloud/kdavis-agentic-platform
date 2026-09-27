-- Migration 058: setup checklist stall alert (admin visibility build,
-- 2026-09-27).
--
-- workspaces.setup_stall_alert_sent_at: when core/setup_checklist_
-- stall_alert.py last emailed Kelvin about this workspace sitting below
-- 5/5 with no checklist activity for 72+ hours. Prevents re-alerting
-- every hourly check cycle for the same stall episode -- only re-alerts
-- once there has been NEW checklist activity (a later completed_at)
-- since the last alert, followed by another 72h of silence.

ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS setup_stall_alert_sent_at TIMESTAMPTZ;
