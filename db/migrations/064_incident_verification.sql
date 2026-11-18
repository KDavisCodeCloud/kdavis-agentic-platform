-- Migration 064: post-fix verification (G4, item 4).
--
-- Break-It Lab: A3 was marked executed while the policy was still `*:*`;
-- A1/Z1 while CPU stayed pegged; A2/Z2 never got a signal at all. After an
-- action runs (or its fix PR merges), core/verification.py re-reads the
-- live resource and closes the incident as 'verified' or
-- 'verification_failed' (execution_status keeps its no-CHECK VARCHAR
-- convention, see migration 038).
--
--   verification_spec      what to re-read and what "fixed" looks like,
--                          recorded by the agent when it acts (JSONB, no LLM)
--   verification_next_at   when the background pass should check next
--                          (NULL = not scheduled)
--   verification_deadline  after this, "still not fixed" becomes
--                          verification_failed
--   verification_attempts  checks made so far
--   verification_result    the last check: {outcome, detail, checked_at}
--   verified_at            when it was confirmed fixed
--
-- No new table, so no new RLS policy; incidents keeps its workspace-scoped
-- RLS from migration 031.

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS verification_spec     JSONB;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS verification_next_at  TIMESTAMPTZ;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS verification_deadline TIMESTAMPTZ;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS verification_attempts INT NOT NULL DEFAULT 0;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS verification_result   JSONB;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS verified_at           TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_incidents_verification_due
    ON incidents (verification_next_at)
    WHERE verification_next_at IS NOT NULL;
