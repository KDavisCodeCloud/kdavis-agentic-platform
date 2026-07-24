-- Migration 014: linkedin_content_queue columns MKT-LI1 has always written
-- but 007_marketing_queues.sql never actually defined.
--
-- Found 2026-07-23 while wiring the monthly batch/Gemini pipeline: 007 was
-- never applied to the live database at all (confirmed via
-- information_schema.tables before this session — linkedin_content_queue
-- did not exist), so this gap had never been exercised against a real
-- schema. agents/marketing/mkt_li1_linkedin_brand.py's run_li1_brand_agent
-- has queued pillar/topic/hitl_tier/estimated_length/notes on every post
-- since it was written — none of those columns existed in 007's CREATE
-- TABLE. Confirmed by a direct INSERT against the live table
-- (UndefinedColumnError: column "pillar" does not exist) before writing
-- this migration. Applying 007 for the first time this session is what
-- surfaced it.

ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS pillar integer;
ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS pillar_name text;
ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS topic text;
ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS hitl_tier integer;
ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS estimated_length text;
ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS notes text;
