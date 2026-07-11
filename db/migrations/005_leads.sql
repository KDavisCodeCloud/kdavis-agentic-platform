-- Migration 005 — Leads funnel core table
-- Run after 004_mcp_api_keys.sql

CREATE TABLE IF NOT EXISTS leads (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id    text NOT NULL,
  tenant_id     uuid,
  email         text NOT NULL,
  name          text,
  source        text NOT NULL DEFAULT 'organic',
  stage         text NOT NULL DEFAULT 'signup' CHECK (stage IN ('signup','trial','converted','churned')),
  metadata      jsonb DEFAULT '{}',
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON leads
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "workspace_read" ON leads
  FOR SELECT TO authenticated
  USING (tenant_id = (current_setting('app.workspace_id')::uuid));
