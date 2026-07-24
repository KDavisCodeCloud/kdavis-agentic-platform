-- Migration 013: Monthly batch scheduling for linkedin_content_queue
-- Run after 012_internal_canva_connection.sql
--
-- MKT-LI1 moves from a weekly (4/week) pooled cadence to a monthly batch of
-- ~12 posts (2026-07-23, Kelvin's decision — the technical/authority
-- content reads as a fixed monthly batch, not the pooled weekly system).
-- Kelvin reviews and approves the whole batch once; each post then fires
-- automatically on its own scheduled_for time across the month via a cron
-- dispatcher (scripts/dispatch_scheduled_posts.py) — not a bulk immediate
-- publish. batch_month groups a batch for the dashboard's review view;
-- scheduled_for is what the dispatcher actually reads.
--
-- image_description carries the Gemini image-gen prompt MKT-LI1 drafts
-- per post (assets_library/gemini_image_gen.py consumes it) — separate
-- from image_brief (jsonb), which holds the SELECTED/generated image's
-- metadata once one exists.
--
-- published_at is separate from status='published' so the dashboard can
-- show when a post actually went out, not just that it did.

ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS batch_month text;
ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS scheduled_for timestamptz;
ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS image_description text;
ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS published_at timestamptz;

-- Dispatcher's own query: approved rows whose scheduled_for has arrived
-- and haven't been published yet. Partial index keeps it cheap since the
-- table is otherwise dominated by pending/published rows the dispatcher
-- never needs to scan.
CREATE INDEX IF NOT EXISTS idx_linkedin_content_queue_dispatch
  ON linkedin_content_queue (scheduled_for)
  WHERE status = 'approved' AND published_at IS NULL;

-- Dashboard's batch review view: all rows for a given month, newest first.
CREATE INDEX IF NOT EXISTS idx_linkedin_content_queue_batch_month
  ON linkedin_content_queue (batch_month, created_at DESC);
