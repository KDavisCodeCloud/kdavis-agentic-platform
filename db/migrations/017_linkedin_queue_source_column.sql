-- Migration 017: linkedin_content_queue.source
--
-- agents/marketing/mkt_li1_linkedin_brand.py's new generate_on_demand_posts
-- (the CEO dashboard fire button, 2026-08-17) tags every row it writes with
-- source='on_demand' so the dashboard/queue can tell an on-demand fire
-- apart from the monthly batch (run_li1_brand_agent never sets this field,
-- so existing/future monthly-batch rows fall back to the column default).

ALTER TABLE linkedin_content_queue ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'monthly_batch';
