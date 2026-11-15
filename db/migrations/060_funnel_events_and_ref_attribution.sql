-- Migration 060: first-party funnel events + outreach reference attribution.
--
-- Gap-table #12/#13 from the 2026-11-14 live demo audit. No third-party
-- analytics, no cookies (core/funnel_events.py, api/routes/funnel_events.py).
--
-- cd_funnel_events: one row per funnel step. Client-sent events
-- (demo_opened, incident_viewed, signup_clicked) carry a random per-tab
-- visitor_id; server-recorded events (fix_approved, fix_resolved_manually,
-- signup_completed, checkout_started, subscribed) are written by the API
-- itself and can never be sent by a browser. ref is an opaque outreach
-- reference code from a ?ref= link -- disclosed on /privacy. Pruned after
-- 395 days by core/retention.py.
--
-- demo_sessions.ref/utm_* and workspaces.signup_ref/signup_utm_* carry the
-- same attribution forward so server-recorded events (approve, signup,
-- checkout, subscription) know which outreach link they came from.

CREATE TABLE IF NOT EXISTS cd_funnel_events (
    id               UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id       VARCHAR(64)  NOT NULL DEFAULT 'cloud_decoded',
    event_name       VARCHAR(40)  NOT NULL,
    visitor_id       VARCHAR(64),
    ref              VARCHAR(64),
    utm_source       VARCHAR(100),
    utm_medium       VARCHAR(100),
    utm_campaign     VARCHAR(100),
    path             VARCHAR(255),
    demo_session_id  UUID         REFERENCES demo_sessions(id) ON DELETE SET NULL,
    workspace_id     UUID         REFERENCES workspaces(id) ON DELETE SET NULL,
    properties       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE cd_funnel_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cd_funnel_events_service_role" ON cd_funnel_events;
CREATE POLICY "cd_funnel_events_service_role" ON cd_funnel_events
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_cd_funnel_events_ref
  ON cd_funnel_events (ref, created_at) WHERE ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cd_funnel_events_name_time
  ON cd_funnel_events (product_id, event_name, created_at);
CREATE INDEX IF NOT EXISTS idx_cd_funnel_events_created
  ON cd_funnel_events (created_at);

ALTER TABLE demo_sessions ADD COLUMN IF NOT EXISTS ref          VARCHAR(64);
ALTER TABLE demo_sessions ADD COLUMN IF NOT EXISTS utm_source   VARCHAR(100);
ALTER TABLE demo_sessions ADD COLUMN IF NOT EXISTS utm_medium   VARCHAR(100);
ALTER TABLE demo_sessions ADD COLUMN IF NOT EXISTS utm_campaign VARCHAR(100);

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS signup_ref          VARCHAR(64);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS signup_utm_source   VARCHAR(100);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS signup_utm_medium   VARCHAR(100);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS signup_utm_campaign VARCHAR(100);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS signup_visitor_id   VARCHAR(64);
