-- Migration 001 — Initial platform schema
-- KDavis Agentic Platform — Phase 1, Session 4
-- Run: psql $DATABASE_URL -f infra/supabase/migrations/001_initial_schema.sql
--
-- Covers CLAUDE.md Phase 1 Step 12 (core platform tables) and the Finance,
-- Accounting, and Wealth Management System tables added later in the doc.
-- Every table is created with IF NOT EXISTS and RLS is enabled immediately
-- after creation, per the global Database Rules non-negotiables.
--
-- ── RLS MODEL (read before applying) ─────────────────────────────────────────
-- CLAUDE.md's literal instruction is "SELECT: auth.uid() matches tenant_id
-- AND product_id matches" applied to every table. Two structural gaps make
-- that impossible to implement verbatim and required judgment calls:
--
--   1. `tenants` as documented (id, product_id, stripe_customer_id, created_at)
--      has no column linking a row to a Supabase auth user. This migration
--      adds `tenants.user_id UUID REFERENCES auth.users(id)` — the minimum
--      addition needed to make "auth.uid() matches tenant_id" resolvable at
--      all. [ASSUMPTION — flagged for owner review]
--
--   2. Most core tables (hitl_queue, audit_log, sops, tech_debt, leads,
--      visitor_sessions, email_sequences, and the finance tables) carry
--      product_id but no tenant_id column — they are platform/ops tables,
--      not per-customer data. For these, "authenticated" access is scoped to
--      product_id via membership in `tenants` (auth.uid() has some tenant
--      row under that product). This is almost certainly broader than
--      intended for internal-only tables (audit_log, sops, tech_debt,
--      prompts) — those are written by agents/CI, not by paying customers.
--      Until a real staff/role model exists, treat any authenticated
--      Supabase user on this project as internal staff, not a SaaS
--      customer. [ASSUMPTION — flagged for owner review]
--
--   `prompts` has no product_id/tenant_id at all in the documented schema
--   (it's a cross-product versioning table) — scoped to authenticated
--   SELECT, service_role write only.
--
--   `tax_estimates`, `deductions`, `salary_records`, `investment_allocations`
--   are entity-level personal finance tables with no product_id or tenant_id
--   column in the documented schema. These get service_role access ONLY —
--   no authenticated policy at all, so RLS default-denies every other role.
--   Access should be mediated through backend finance endpoints, never
--   direct table access. [ASSUMPTION — flagged for owner review]
--
--   `dispute_evidence` is named in the Session 4 table list but never
--   defined anywhere in CLAUDE.md. Columns below are inferred from Stripe's
--   own dispute object model and payments/dispute_handler.py's stated
--   purpose (Phase 2, Session 10 PM). [INFERRED SCHEMA — flagged for owner
--   review before relying on it from application code]
-- ──────────────────────────────────────────────────────────────────────────

create extension if not exists pgcrypto;

-- ============================================================================
-- CORE PLATFORM TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    subdomain       TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'planning'
                      CHECK (status IN ('planning', 'building', 'live', 'paused', 'archived')),
    pricing_tier    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE products ENABLE ROW LEVEL SECURITY;

CREATE POLICY "products_service_role_all" ON products
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "products_authenticated_select" ON products
    FOR SELECT TO authenticated USING (true);


CREATE TABLE IF NOT EXISTS tenants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    -- [ASSUMPTION] not in CLAUDE.md's documented column list — added so RLS
    -- ("auth.uid() matches tenant_id") has something to resolve against.
    user_id             UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    stripe_customer_id  TEXT UNIQUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenants_product ON tenants (product_id);
CREATE INDEX IF NOT EXISTS idx_tenants_user ON tenants (user_id);

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenants_service_role_all" ON tenants
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "tenants_authenticated_select" ON tenants
    FOR SELECT TO authenticated USING (user_id = auth.uid());


CREATE TABLE IF NOT EXISTS agent_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_name          TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'running', 'paused', 'completed', 'failed')),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    token_count         INTEGER NOT NULL DEFAULT 0,
    cost_usd            NUMERIC(10,4) NOT NULL DEFAULT 0,
    confidence_score    NUMERIC(4,3) CHECK (confidence_score BETWEEN 0 AND 1)
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_product ON agent_runs (product_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_tenant ON agent_runs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_started ON agent_runs (started_at DESC);

ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "agent_runs_service_role_all" ON agent_runs
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "agent_runs_authenticated_select" ON agent_runs
    FOR SELECT TO authenticated
    USING (tenant_id IN (SELECT id FROM tenants WHERE user_id = auth.uid()));
CREATE POLICY "agent_runs_authenticated_insert" ON agent_runs
    FOR INSERT TO authenticated
    WITH CHECK (
        product_id IS NOT NULL AND tenant_id IS NOT NULL
        AND tenant_id IN (SELECT id FROM tenants WHERE user_id = auth.uid())
    );
CREATE POLICY "agent_runs_authenticated_update" ON agent_runs
    FOR UPDATE TO authenticated
    USING (tenant_id IN (SELECT id FROM tenants WHERE user_id = auth.uid()))
    WITH CHECK (tenant_id IN (SELECT id FROM tenants WHERE user_id = auth.uid()));


CREATE TABLE IF NOT EXISTS hitl_queue (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    agent_run_id        UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    status              TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'held', 'approved', 'rejected', 'expired')),
    options_json        JSONB NOT NULL DEFAULT '[]'::jsonb,
    selected_option     TEXT,
    hold_until          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_hitl_queue_product ON hitl_queue (product_id);
CREATE INDEX IF NOT EXISTS idx_hitl_queue_status ON hitl_queue (status);
CREATE INDEX IF NOT EXISTS idx_hitl_queue_agent_run ON hitl_queue (agent_run_id);

ALTER TABLE hitl_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "hitl_queue_service_role_all" ON hitl_queue
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "hitl_queue_authenticated_select" ON hitl_queue
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));
-- Authenticated write is limited to resolving cards (approve/reject/hold) —
-- this is the one dashboard interaction that must work without service_role.
CREATE POLICY "hitl_queue_authenticated_update" ON hitl_queue
    FOR UPDATE TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()))
    WITH CHECK (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


CREATE TABLE IF NOT EXISTS audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,
    resource        TEXT NOT NULL,
    outcome         TEXT NOT NULL CHECK (outcome IN ('win', 'lose')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_product ON audit_log (product_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (created_at DESC);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "audit_log_service_role_all" ON audit_log
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "audit_log_authenticated_select" ON audit_log
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));

-- security/audit_log.py requires "Immutable: no update or delete methods".
-- service_role typically carries BYPASSRLS in Supabase, so RLS policies
-- alone cannot guarantee immutability against it — enforce with a trigger
-- that rejects UPDATE/DELETE unconditionally, for every role.
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is immutable: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log;
CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();


CREATE TABLE IF NOT EXISTS sops (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    agent_name      TEXT NOT NULL,
    task_summary    TEXT NOT NULL,
    content_md      TEXT NOT NULL,
    obsidian_path   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sops_product ON sops (product_id);

ALTER TABLE sops ENABLE ROW LEVEL SECURITY;

CREATE POLICY "sops_service_role_all" ON sops
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "sops_authenticated_select" ON sops
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


-- [ASSUMPTION] No product_id/tenant_id in CLAUDE.md's documented column
-- list — prompts are versioned per agent across the whole platform, not
-- per product. Reads are open to authenticated (internal staff); writes
-- go through the prompt-version-check.yml CI gate via service_role only.
CREATE TABLE IF NOT EXISTS prompts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      TEXT NOT NULL,
    version         TEXT NOT NULL,
    content         TEXT NOT NULL,
    changelog       TEXT,
    active          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_name, version)
);

ALTER TABLE prompts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "prompts_service_role_all" ON prompts
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "prompts_authenticated_select" ON prompts
    FOR SELECT TO authenticated USING (true);


CREATE TABLE IF NOT EXISTS tech_debt (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    file            TEXT NOT NULL,
    line            INTEGER,
    issue_type      TEXT NOT NULL,
    description     TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN ('blocking', 'non_blocking')),
    pr_number       INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tech_debt_product ON tech_debt (product_id);
CREATE INDEX IF NOT EXISTS idx_tech_debt_unresolved ON tech_debt (product_id) WHERE resolved_at IS NULL;

ALTER TABLE tech_debt ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tech_debt_service_role_all" ON tech_debt
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "tech_debt_authenticated_select" ON tech_debt
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


CREATE TABLE IF NOT EXISTS leads (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    email               TEXT NOT NULL,
    name                TEXT,
    company             TEXT,
    role                TEXT,
    source              TEXT,
    utm_source          TEXT,
    utm_medium          TEXT,
    utm_campaign        TEXT,
    ip_country          TEXT,
    page_path           TEXT,
    signup_type         TEXT NOT NULL CHECK (signup_type IN ('email_only', 'trial')),
    systeme_contact_id  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_product ON leads (product_id);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads (email);

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "leads_service_role_all" ON leads
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "leads_authenticated_select" ON leads
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


CREATE TABLE IF NOT EXISTS visitor_sessions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id              UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    session_id              TEXT NOT NULL,
    ip_country              TEXT,
    referrer                TEXT,
    utm_source              TEXT,
    utm_medium              TEXT,
    utm_campaign            TEXT,
    pages_viewed            INTEGER NOT NULL DEFAULT 0,
    time_on_site_seconds    INTEGER NOT NULL DEFAULT 0,
    converted_to_lead       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_visitor_sessions_product ON visitor_sessions (product_id);

ALTER TABLE visitor_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "visitor_sessions_service_role_all" ON visitor_sessions
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "visitor_sessions_authenticated_select" ON visitor_sessions
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


CREATE TABLE IF NOT EXISTS email_sequences (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id              UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    name                    TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft', 'pending_approval', 'approved', 'deployed')),
    systeme_sequence_id     TEXT,
    approved_by             TEXT,
    approved_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_sequences_product ON email_sequences (product_id);

ALTER TABLE email_sequences ENABLE ROW LEVEL SECURITY;

CREATE POLICY "email_sequences_service_role_all" ON email_sequences
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "email_sequences_authenticated_select" ON email_sequences
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


CREATE TABLE IF NOT EXISTS email_sequence_steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sequence_id     UUID NOT NULL REFERENCES email_sequences(id) ON DELETE CASCADE,
    step_number     INTEGER NOT NULL,
    subject         TEXT NOT NULL,
    body_md         TEXT NOT NULL,
    delay_days      INTEGER NOT NULL DEFAULT 0,
    approved        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sequence_id, step_number)
);

CREATE INDEX IF NOT EXISTS idx_email_sequence_steps_sequence ON email_sequence_steps (sequence_id);

ALTER TABLE email_sequence_steps ENABLE ROW LEVEL SECURITY;

CREATE POLICY "email_sequence_steps_service_role_all" ON email_sequence_steps
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "email_sequence_steps_authenticated_select" ON email_sequence_steps
    FOR SELECT TO authenticated
    USING (
        sequence_id IN (
            SELECT id FROM email_sequences
            WHERE product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid())
        )
    );


-- ============================================================================
-- FINANCE, ACCOUNTING, AND WEALTH MANAGEMENT TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS expenses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    amount              NUMERIC(12,2) NOT NULL,
    vendor              TEXT NOT NULL,
    description         TEXT,
    date                DATE NOT NULL,
    irs_category        TEXT NOT NULL,
    receipt_url         TEXT,
    receipt_ocr_text    TEXT,
    tax_year            INTEGER NOT NULL,
    deductible          BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by_cpa     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_expenses_product ON expenses (product_id);
CREATE INDEX IF NOT EXISTS idx_expenses_tax_year ON expenses (tax_year);

ALTER TABLE expenses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "expenses_service_role_all" ON expenses
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "expenses_authenticated_select" ON expenses
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


CREATE TABLE IF NOT EXISTS revenue_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    source              TEXT NOT NULL,
    amount              NUMERIC(12,2) NOT NULL,
    stripe_event_id     TEXT UNIQUE,
    customer_email      TEXT,
    description         TEXT,
    date                DATE NOT NULL,
    tax_year            INTEGER NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_revenue_events_product ON revenue_events (product_id);
CREATE INDEX IF NOT EXISTS idx_revenue_events_tax_year ON revenue_events (tax_year);

ALTER TABLE revenue_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "revenue_events_service_role_all" ON revenue_events
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "revenue_events_authenticated_select" ON revenue_events
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


CREATE TABLE IF NOT EXISTS invoices (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    type                TEXT NOT NULL CHECK (type IN ('sent', 'received')),
    vendor_or_client    TEXT NOT NULL,
    amount              NUMERIC(12,2) NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft', 'sent', 'paid', 'overdue', 'void')),
    due_date            DATE,
    paid_date           DATE,
    document_url        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invoices_product ON invoices (product_id);

ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;

CREATE POLICY "invoices_service_role_all" ON invoices
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "invoices_authenticated_select" ON invoices
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


-- [ASSUMPTION] Entity-level personal finance tables below have no
-- product_id/tenant_id in CLAUDE.md's documented column list. service_role
-- is the only policy defined — RLS default-denies every other role,
-- including authenticated. Access must go through backend finance
-- endpoints, never direct table queries.

CREATE TABLE IF NOT EXISTS tax_estimates (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tax_year                INTEGER NOT NULL,
    quarter                 INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    estimated_income        NUMERIC(14,2) NOT NULL,
    estimated_tax           NUMERIC(14,2) NOT NULL,
    safe_harbor_amount      NUMERIC(14,2),
    status                  TEXT NOT NULL DEFAULT 'estimated'
                              CHECK (status IN ('estimated', 'paid', 'overdue')),
    cpa_reviewed            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tax_year, quarter)
);

ALTER TABLE tax_estimates ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tax_estimates_service_role_all" ON tax_estimates
    FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS deductions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tax_year                INTEGER NOT NULL,
    category                TEXT NOT NULL,
    description             TEXT NOT NULL,
    amount                  NUMERIC(12,2) NOT NULL,
    supporting_doc_url      TEXT,
    confidence              NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
    cpa_reviewed            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deductions_tax_year ON deductions (tax_year);

ALTER TABLE deductions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "deductions_service_role_all" ON deductions
    FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS salary_records (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tax_year                    INTEGER NOT NULL,
    recommended_amount          NUMERIC(12,2),
    actual_amount                NUMERIC(12,2),
    entity_revenue               NUMERIC(14,2),
    basis_for_recommendation     TEXT,
    cpa_reviewed                 BOOLEAN NOT NULL DEFAULT FALSE,
    effective_date               DATE,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE salary_records ENABLE ROW LEVEL SECURITY;

CREATE POLICY "salary_records_service_role_all" ON salary_records
    FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS investment_allocations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_type        TEXT NOT NULL,
    institution         TEXT NOT NULL,
    amount              NUMERIC(14,2) NOT NULL,
    date                DATE NOT NULL,
    purpose             TEXT,
    advisor_reviewed    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE investment_allocations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "investment_allocations_service_role_all" ON investment_allocations
    FOR ALL TO service_role USING (true) WITH CHECK (true);


CREATE TABLE IF NOT EXISTS revenue_opportunities (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id              UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    opportunity_type        TEXT NOT NULL,
    description             TEXT NOT NULL,
    estimated_impact_mrr    NUMERIC(12,2),
    confidence              NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
    status                  TEXT NOT NULL DEFAULT 'open'
                              CHECK (status IN ('open', 'actioned', 'dismissed')),
    data_snapshot_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actioned_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_revenue_opportunities_product ON revenue_opportunities (product_id);

ALTER TABLE revenue_opportunities ENABLE ROW LEVEL SECURITY;

CREATE POLICY "revenue_opportunities_service_role_all" ON revenue_opportunities
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "revenue_opportunities_authenticated_select" ON revenue_opportunities
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));


-- [INFERRED SCHEMA] Named in the Session 4 table list but never defined in
-- CLAUDE.md. Columns model Stripe's dispute object directly since this
-- table exists to back payments/dispute_handler.py (Phase 2, Session 10 PM)
-- and the charge.dispute.created webhook wired in infra/stripe/setup.py.
-- Confirm shape against the real dispute_handler.py implementation before
-- treating this as final.
CREATE TABLE IF NOT EXISTS dispute_evidence (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    stripe_dispute_id   TEXT NOT NULL UNIQUE,
    charge_id           TEXT NOT NULL,
    amount              NUMERIC(12,2) NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'usd',
    reason              TEXT,
    status              TEXT NOT NULL DEFAULT 'needs_response'
                          CHECK (status IN (
                              'warning_needs_response', 'warning_under_review', 'warning_closed',
                              'needs_response', 'under_review', 'charge_refunded', 'won', 'lost'
                          )),
    evidence_due_by     TIMESTAMPTZ,
    evidence_submitted  BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dispute_evidence_product ON dispute_evidence (product_id);

ALTER TABLE dispute_evidence ENABLE ROW LEVEL SECURITY;

CREATE POLICY "dispute_evidence_service_role_all" ON dispute_evidence
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "dispute_evidence_authenticated_select" ON dispute_evidence
    FOR SELECT TO authenticated
    USING (product_id IN (SELECT product_id FROM tenants WHERE user_id = auth.uid()));
