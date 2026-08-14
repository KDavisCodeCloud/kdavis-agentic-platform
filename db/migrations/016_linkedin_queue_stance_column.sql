-- Migration 016: linkedin_content_queue.stance -- MKT-LI1's Opinion Matrix
-- rewrite (2026-08-14, agents/marketing/mkt_li1_linkedin_brand.py v2.2)
-- added "stance" to every drafted post's payload (which of the 11 Opinion
-- Matrix stances the post routes through, also threaded forward between
-- drafts within a batch so the same stance never repeats twice in a row)
-- but no migration ever added the matching column, same gap 014 already
-- found and fixed once for pillar/topic/hitl_tier/estimated_length/notes.
-- Confirmed by a real live INSERT failing (PGRST204 "Could not find the
-- 'stance' column") the first time a real batch ran after the rewrite.

ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS stance text;
