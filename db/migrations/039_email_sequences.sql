-- Migration 039 — Email sequence drafts + steps (HITL review tables)
--
-- Closes a real gap found in the 2026-09-16 marketing-loop audit:
-- agents/internal/email_sequence_agent.py has been fully built since the
-- Phase 2 lead-capture session, but its output was only ever written into
-- internal_agent_runs.result as an opaque JSON blob -- no table existed
-- for the dashboard to list, review, or approve individual sequences/
-- emails against, so every drafted sequence was structurally unreviewable.
-- (A schema for this was drafted once before in infra/supabase/migrations/
-- 001_initial_schema.sql, but that file was never part of this repo's real
-- migration pipeline -- db/migrate.py only ever applies db/migrations/*.sql
-- -- so it was never actually live. This migration is the real one.)
--
-- Same conventions as 007_marketing_queues.sql: product_id text (not every
-- product has a UUID row anywhere yet), service_role-only RLS policy,
-- CHECK-constrained status vocab, IF NOT EXISTS / DROP POLICY IF EXISTS
-- throughout for safe re-runs.

CREATE TABLE IF NOT EXISTS email_sequences (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id        text NOT NULL,
  agent_id          text NOT NULL DEFAULT 'email_sequence_agent',
  sequence_name     text NOT NULL
                      CHECK (sequence_name IN ('trial_nurture', 'email_only_nurture', 'post_churn_winback')),
  niche             text,
  max_words         int,
  research_run_id   uuid,
  status            text NOT NULL DEFAULT 'pending_hitl'
                      CHECK (status IN ('pending_hitl', 'approved', 'rejected', 'deployed')),
  hitl_notes        text,
  approved_by       text,
  approved_at       timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE email_sequences ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "email_sequences_service_role" ON email_sequences;
CREATE POLICY "email_sequences_service_role" ON email_sequences FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_email_sequences_product_status
  ON email_sequences (product_id, status, created_at DESC);


CREATE TABLE IF NOT EXISTS email_sequence_steps (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sequence_id       uuid NOT NULL REFERENCES email_sequences(id) ON DELETE CASCADE,
  day               int NOT NULL,
  theme             text NOT NULL,
  subject           text NOT NULL,
  body              text NOT NULL,
  cta               text NOT NULL,
  word_count        int,
  meets_word_limit  boolean,
  buzzword_flags    jsonb,
  status            text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'approved', 'modified', 'held', 'rejected')),
  hitl_notes        text,
  created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE email_sequence_steps ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "email_sequence_steps_service_role" ON email_sequence_steps;
CREATE POLICY "email_sequence_steps_service_role" ON email_sequence_steps FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_email_sequence_steps_sequence_day
  ON email_sequence_steps (sequence_id, day);
