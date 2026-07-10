-- Migration 007: Wave 2 marketing agent queue tables
-- Run after 006_mse_opportunities.sql
--
-- linkedin_content_queue (MKT-LI1), content_queue (MKT-V1), and
-- newsletter_queue (MKT-N1) — flagged as missing in
-- agents/marketing/_shared.py's module docstring when those agents were
-- built; this migration closes that gap. Every row lands with a
-- pending/draft status — HITL approval happens in the dashboard, nothing
-- here auto-publishes.
--
-- CREATE POLICY has no IF NOT EXISTS in Postgres, so each policy below is
-- preceded by DROP POLICY IF EXISTS to keep the file safely re-runnable,
-- same idempotency goal as the IF NOT EXISTS on the CREATE TABLE/INDEX
-- statements.
--
-- Policies use "FOR ALL TO service_role" (006's convention), not a bare
-- USING (true): omitting TO defaults a Postgres policy to PUBLIC, which
-- would grant every role — including anon — full access and defeat the
-- point of enabling RLS at all.

CREATE TABLE IF NOT EXISTS linkedin_content_queue (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id           text,
  agent_id             text NOT NULL DEFAULT 'mkt-li1',
  post_copy            text NOT NULL,
  hook_variants        jsonb,
  suggested_post_time  text,
  format               text CHECK (format IN ('text_post', 'document_carousel')),
  content_type         text CHECK (content_type IN ('educational', 'journey', 'repurposed', 'product')),
  image_brief          jsonb,
  carousel_slides      jsonb,
  carousel_pdf_brief   jsonb,
  status               text NOT NULL DEFAULT 'pending_review'
                         CHECK (status IN ('pending_review', 'approved', 'rejected', 'published')),
  hitl_notes           text,
  hitl_reviewer        text,
  hitl_reviewed_at     timestamptz,
  tenant_id            uuid,
  created_at           timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE linkedin_content_queue ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "linkedin_content_queue_service_role" ON linkedin_content_queue;
CREATE POLICY "linkedin_content_queue_service_role" ON linkedin_content_queue FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_linkedin_content_queue_status_created
  ON linkedin_content_queue (status, created_at DESC);


CREATE TABLE IF NOT EXISTS content_queue (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id     text,
  agent_id       text NOT NULL DEFAULT 'mkt-v1',
  platform       text NOT NULL,
  content_json   jsonb NOT NULL,
  status         text NOT NULL DEFAULT 'pending_review'
                   CHECK (status IN ('pending_review', 'approved', 'rejected', 'published')),
  mkt10_passed   boolean NOT NULL DEFAULT false,
  mkt10_notes    text,
  hitl_notes     text,
  tenant_id      uuid,
  created_at     timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE content_queue ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "content_queue_service_role" ON content_queue;
CREATE POLICY "content_queue_service_role" ON content_queue FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_content_queue_status_created
  ON content_queue (status, created_at DESC);


CREATE TABLE IF NOT EXISTS newsletter_queue (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id        text,
  agent_id          text NOT NULL DEFAULT 'mkt-n1',
  variant           text CHECK (variant IN ('cloud_decoded', 'decodedsix')),
  subject_lines     jsonb,
  hook_paragraph    text,
  story_summaries   jsonb,
  builders_note     text,
  cta               text,
  list_segment      text,
  status            text NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft', 'approved', 'sent', 'archived')),
  hitl_notes        text,
  tenant_id         uuid,
  created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE newsletter_queue ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "newsletter_queue_service_role" ON newsletter_queue;
CREATE POLICY "newsletter_queue_service_role" ON newsletter_queue FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_newsletter_queue_status_created
  ON newsletter_queue (status, created_at DESC);
