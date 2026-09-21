-- Migration 051 — Cloud Decoded email lifecycle system.
--
-- Replaces two things that predate this migration and are being retired
-- (flagged DEPRECATED in code, not dropped -- see DECISIONS.md):
--   - agents/internal/email_sequence_agent.py + email_sequences /
--     email_sequence_steps (migration 039) -- that system was built for
--     the platform-generic Brevo lead-nurture plan and was never actually
--     wired to a live HTTP route or a real send path (process_signup()/
--     handle_signup() in leads/capture/ have zero callers outside tests).
--   - core/onboarding_sequence.py's 3-email day0/day2/day5 cron -- folded
--     into this engine's 'onboarding' sequence as its first steps.
--
-- Same conventions as migration 039/043: IF NOT EXISTS / DROP POLICY IF
-- EXISTS throughout for safe re-runs, RLS + service_role-only policy on
-- every table (defense in depth for other access paths -- Supabase
-- Studio, anon/authenticated keys -- even though this app's own
-- DATABASE_URL role may bypass RLS entirely; see db/migrate.py's
-- log_security_posture), CHECK-constrained status vocab.
--
-- Tables use `key` (text) as their natural primary key where the API
-- contract (docs/internal/email-approval-api.md) already names that
-- field template_key/sequence_key -- avoids a separate surrogate id
-- everywhere a foreign key needs to reference "which template"/"which
-- sequence".

CREATE TABLE IF NOT EXISTS cd_email_sequences (
  key           text PRIMARY KEY,
  name          text NOT NULL,
  description   text,
  trigger_type  text NOT NULL,
  exit_rules    jsonb NOT NULL DEFAULT '{}'::jsonb,
  active        boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE cd_email_sequences ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cd_email_sequences_service_role" ON cd_email_sequences;
CREATE POLICY "cd_email_sequences_service_role" ON cd_email_sequences FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS cd_email_templates (
  key             text PRIMARY KEY,
  sequence_key    text NOT NULL REFERENCES cd_email_sequences(key),
  step_number     int NOT NULL,
  -- Days after enrollment (step_number=1) or after the PREVIOUS step's
  -- send (step_number>1) that this step should fire. 0 = immediate.
  delay_days      int NOT NULL DEFAULT 0,
  subject         text NOT NULL,
  preheader       text,
  body_html       text NOT NULL,
  body_text       text NOT NULL,
  status          text NOT NULL DEFAULT 'pending_approval'
                    CHECK (status IN ('pending_approval', 'approved', 'retired')),
  -- origin/source_script: kept for API-contract stability with the MSE
  -- feed (docs/internal/email-approval-api.md), even though every row
  -- this build inserts is 'generated' -- no source scripts existed to
  -- adapt from (Phase 0 recon, confirmed with Kelvin).
  origin          text NOT NULL DEFAULT 'generated'
                    CHECK (origin IN ('generated', 'adapted_from_script')),
  source_script   text,
  cta_url         text,
  utm_campaign    text,
  -- skip_if: name of a core/setup_checklist.py SetupChecklist key
  -- ('cloud_connected'|'repo_connected'|'alert_source_verified'|
  -- 'notification_channel_set'|'end_to_end_test_passed'), or a bespoke
  -- flag like 'has_members' -- the scheduler checks it before sending an
  -- onboarding step and advances without sending if already true. NULL
  -- means "always send".
  skip_if         text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  approved_at     timestamptz,
  approved_by     text
);

-- Only one APPROVED template may occupy a given step of a sequence at a
-- time -- retired/pending drafts of the same step are allowed to coexist
-- (history, in-review edits), but the scheduler must never have two
-- candidate approved templates for the same (sequence_key, step_number).
CREATE UNIQUE INDEX IF NOT EXISTS idx_cd_email_templates_active_step
  ON cd_email_templates (sequence_key, step_number)
  WHERE status = 'approved';

CREATE INDEX IF NOT EXISTS idx_cd_email_templates_sequence_status
  ON cd_email_templates (sequence_key, status, step_number);

ALTER TABLE cd_email_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cd_email_templates_service_role" ON cd_email_templates;
CREATE POLICY "cd_email_templates_service_role" ON cd_email_templates FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS cd_email_subscribers (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email           text NOT NULL,
  source          text NOT NULL
                    CHECK (source IN ('newsletter_signup', 'lead_magnet', 'checkout', 'manual')),
  workspace_id    uuid REFERENCES workspaces(id) ON DELETE SET NULL,
  subscribed_at   timestamptz NOT NULL DEFAULT now(),
  unsubscribed_at timestamptz,
  sunset_status   text NOT NULL DEFAULT 'active'
                    CHECK (sunset_status IN ('active', 'sunset'))
);

-- Case-insensitive uniqueness without requiring the citext extension --
-- matches this repo's existing plain-text-column convention elsewhere.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cd_email_subscribers_email
  ON cd_email_subscribers (lower(email));

ALTER TABLE cd_email_subscribers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cd_email_subscribers_service_role" ON cd_email_subscribers;
CREATE POLICY "cd_email_subscribers_service_role" ON cd_email_subscribers FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS cd_email_enrollments (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id uuid NOT NULL REFERENCES cd_email_subscribers(id) ON DELETE CASCADE,
  sequence_key  text NOT NULL REFERENCES cd_email_sequences(key),
  current_step  int NOT NULL DEFAULT 0,
  status        text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'completed', 'exited')),
  enrolled_at   timestamptz NOT NULL DEFAULT now(),
  next_send_at  timestamptz,
  exit_reason   text,
  UNIQUE (subscriber_id, sequence_key)
);

CREATE INDEX IF NOT EXISTS idx_cd_email_enrollments_due
  ON cd_email_enrollments (status, next_send_at)
  WHERE status = 'active';

ALTER TABLE cd_email_enrollments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cd_email_enrollments_service_role" ON cd_email_enrollments;
CREATE POLICY "cd_email_enrollments_service_role" ON cd_email_enrollments FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS cd_email_sends (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id   uuid REFERENCES cd_email_enrollments(id) ON DELETE SET NULL,
  template_key    text NOT NULL REFERENCES cd_email_templates(key),
  recipient       text NOT NULL,
  stream          text NOT NULL CHECK (stream IN ('transactional', 'marketing')),
  resend_message_id text,
  sent_at         timestamptz NOT NULL DEFAULT now(),
  status          text NOT NULL CHECK (status IN ('sent', 'failed', 'suppressed')),
  utm_source      text,
  utm_medium      text,
  utm_campaign    text
);

-- Daily-cap check (1 marketing email/recipient/day) and expansion-email
-- dedupe (1 per threshold per 60 days) both scan by recipient + time.
CREATE INDEX IF NOT EXISTS idx_cd_email_sends_recipient_sent
  ON cd_email_sends (recipient, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_cd_email_sends_recipient_template
  ON cd_email_sends (recipient, template_key, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_cd_email_sends_template_metrics
  ON cd_email_sends (template_key, status);

ALTER TABLE cd_email_sends ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cd_email_sends_service_role" ON cd_email_sends;
CREATE POLICY "cd_email_sends_service_role" ON cd_email_sends FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS cd_email_clicks (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  send_id    uuid NOT NULL REFERENCES cd_email_sends(id) ON DELETE CASCADE,
  url        text NOT NULL,
  clicked_at timestamptz NOT NULL DEFAULT now(),
  ip_hash    text
);

CREATE INDEX IF NOT EXISTS idx_cd_email_clicks_send ON cd_email_clicks (send_id);

ALTER TABLE cd_email_clicks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cd_email_clicks_service_role" ON cd_email_clicks;
CREATE POLICY "cd_email_clicks_service_role" ON cd_email_clicks FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS cd_email_suppressions (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email      text NOT NULL,
  reason     text NOT NULL
               CHECK (reason IN ('unsubscribe', 'bounce', 'complaint', 'sunset', 'manual')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cd_email_suppressions_email
  ON cd_email_suppressions (lower(email));

ALTER TABLE cd_email_suppressions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cd_email_suppressions_service_role" ON cd_email_suppressions;
CREATE POLICY "cd_email_suppressions_service_role" ON cd_email_suppressions FOR ALL TO service_role USING (true) WITH CHECK (true);


-- Phase 7 attribution: stamp which template first/last touched a
-- workspace before checkout, if the checkout email matches a subscriber
-- with clicks in the prior 90 days.
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS first_touch_template text;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS last_touch_template text;
