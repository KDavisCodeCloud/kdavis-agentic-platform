-- Migration 006: MSE opportunities + product specs
-- Run after 005_leads.sql
-- (originally drafted as 005 before a concurrent session claimed that
-- number for the leads funnel migration — renumbered to avoid collision)
--
-- Feeds the CEO dashboard MSE research review queue. mse_opportunities has
-- no unique constraint beyond `id` (fresh gen_random_uuid() per scan run,
-- even for a repeat niche/name) — agents/mse/demand_validator.py inserts
-- rather than upserts for that reason; see its module docstring.

CREATE TABLE IF NOT EXISTS mse_opportunities (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id        text NOT NULL DEFAULT 'mse',
  name              text NOT NULL,
  problem           text,
  target_user       text,
  estimated_arr     text,
  competition_level text,
  demand_score      int,
  build_complexity  int,
  weeks_to_revenue  int,
  go                boolean NOT NULL DEFAULT false,
  reason            text,
  created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE mse_opportunities ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all" ON mse_opportunities FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE TABLE IF NOT EXISTS mse_product_specs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id      text NOT NULL DEFAULT 'mse',
  opportunity_id  uuid REFERENCES mse_opportunities(id) ON DELETE CASCADE,
  product_name    text NOT NULL,
  problem         text,
  icp             text,
  features        jsonb DEFAULT '[]',
  price_monthly   int,
  stack_notes     text,
  milestones      jsonb DEFAULT '[]',
  created_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE mse_product_specs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all" ON mse_product_specs FOR ALL TO service_role USING (true) WITH CHECK (true);
