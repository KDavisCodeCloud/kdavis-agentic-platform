-- Real persistence for accounting_agent.process_receipt() /
-- tax_agent.track_deductions() — the highest-leverage piece of the finance
-- system CLAUDE.md specs, since expenses feeds both directly plus
-- finance_assistant_agent's software_spend/receipts_for_month/
-- cpa_handoff_readiness. Column set matches
-- finance/accounting/receipt_processor.py's ProcessedReceipt.to_expense_record()
-- exactly (already produces this exact shape, not an invented schema) plus
-- id/created_at.
--
-- Scope note: this is deliberately ONE table, not the full CLAUDE.md finance
-- spec (revenue_events/invoices/tax_estimates/deductions/salary_records/
-- investment_allocations all remain unbuilt) - expenses is the piece real
-- code already produces and multiple already-written methods actually
-- consume. The rest is a separate, larger follow-up.
CREATE TABLE IF NOT EXISTS expenses (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id         TEXT,
  amount             NUMERIC,
  vendor             TEXT NOT NULL,
  description        TEXT,
  expense_date       DATE,
  irs_category       TEXT NOT NULL,
  receipt_url        TEXT,
  receipt_ocr_text   TEXT,
  tax_year           INTEGER,
  deductible         BOOLEAN NOT NULL DEFAULT true,
  approved_by_cpa    BOOLEAN NOT NULL DEFAULT false,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_expenses_tax_year ON expenses(tax_year);
CREATE INDEX IF NOT EXISTS idx_expenses_irs_category ON expenses(tax_year, irs_category);

ALTER TABLE expenses ENABLE ROW LEVEL SECURITY;

-- Same convention as internal_agent_runs (008): this backend always talks
-- to Postgres via the shared db_pool with elevated credentials, never a
-- per-user Supabase client, so service_role is the only real caller.
-- TO service_role is not optional - a bare USING (true) defaults to PUBLIC.
CREATE POLICY "expenses_service_role" ON expenses
  FOR ALL TO service_role USING (true) WITH CHECK (true);
