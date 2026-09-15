-- Migration 001 — Initial schema
-- KDavis Agentic Systems LLC — Cloud Decoded
--
-- Was previously `\i db/schema.sql` -- a psql meta-command, not valid SQL.
-- Worked fine for manual `psql -f` runs but broke the generic migration
-- runner (db/migrate.py, added 2026-09-15 after migrations 024-028 were
-- deployed for an entire session without ever actually running against
-- production — see GAPS.md #15): asyncpg sends this file's text as a
-- plain SQL query, and Postgres has no concept of `\i`. Inlined here so
-- this file is self-contained and executable by any client, not just
-- psql. db/schema.sql itself is kept as a standalone reference for fresh
-- local dev setup (`psql $DATABASE_URL -f db/schema.sql`) and is now
-- idempotent too — this is the same content, not a fork of it.
--
-- Every statement below is idempotent (IF NOT EXISTS / DROP...IF EXISTS
-- guards) per this project's migration-authoring convention — safe to
-- run against a database where all of this already exists.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ──────────────────────────────────────────────
-- WORKSPACES — one row per paying customer
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workspaces (
    id                         UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_name               VARCHAR(255) NOT NULL,
    workspace_token            VARCHAR(255) UNIQUE NOT NULL,      -- API auth token (hashed)
    stripe_customer_id         VARCHAR(255) UNIQUE,
    stripe_subscription_status VARCHAR(50)  DEFAULT 'trialing',   -- active|trialing|past_due|canceled|suspended
    product_tier               VARCHAR(50)  DEFAULT 'starter',    -- starter|growth|enterprise
    encrypted_llm_key          TEXT,                              -- BYOK — AES-256/Fernet encrypted
    monthly_token_budget_usd   NUMERIC(10,2) DEFAULT 50.00,
    current_month_spend_usd    NUMERIC(10,2) DEFAULT 0.00,
    max_repos                  INT           DEFAULT 3,
    cloud_providers            TEXT[]        DEFAULT '{}',        -- ['aws','azure']
    created_at                 TIMESTAMPTZ   DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workspaces_token   ON workspaces (workspace_token);
CREATE INDEX IF NOT EXISTS idx_workspaces_stripe  ON workspaces (stripe_customer_id);

-- ──────────────────────────────────────────────
-- INCIDENTS — one row per agent diagnosis/approval cycle
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS incidents (
    id                          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id                UUID        REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id                    VARCHAR(50) NOT NULL,              -- 'agent_01_cicd_triage' etc.
    cloud_provider              VARCHAR(50),                       -- 'aws'|'azure'|'gcp'
    raw_log_hash                VARCHAR(64),                       -- SHA-256 of original (not stored)
    parsed_error                TEXT        NOT NULL,              -- scrubbed human-readable diagnosis
    remediation_options         JSONB       NOT NULL,              -- [{id,title,description,impact,docs_url}]
    selected_option_id          VARCHAR(50),                       -- set on approval
    custom_solution_input       TEXT,                              -- if operator types custom fix
    execution_status            VARCHAR(50) DEFAULT 'pending_approval',
    -- pending_approval | executing | executed | held | failed | budget_exceeded
    estimated_duration_seconds  INT,
    tokens_used                 INT         DEFAULT 0,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    resolved_at                 TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_incidents_workspace ON incidents (workspace_id);
CREATE INDEX IF NOT EXISTS idx_incidents_status    ON incidents (execution_status);
CREATE INDEX IF NOT EXISTS idx_incidents_agent     ON incidents (agent_id);

-- ──────────────────────────────────────────────
-- INTERNAL AGENT TASKS — cross-agent message bus
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS internal_agent_tasks (
    id                       UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_agent             VARCHAR(100) NOT NULL,
    target_agent             VARCHAR(100),
    task_type                VARCHAR(100) NOT NULL,
    payload                  JSONB        NOT NULL,
    operator_approval_required BOOLEAN    DEFAULT TRUE,
    operator_approved        BOOLEAN      DEFAULT FALSE,
    execution_state          VARCHAR(50)  DEFAULT 'queued',
    -- queued | approved | executing | completed | rejected
    created_at               TIMESTAMPTZ  DEFAULT NOW(),
    updated_at               TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_internal_tasks_state  ON internal_agent_tasks (execution_state);
CREATE INDEX IF NOT EXISTS idx_internal_tasks_source ON internal_agent_tasks (source_agent);

-- ──────────────────────────────────────────────
-- AUDIT LOG — immutable append-only event trail
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_events (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID        REFERENCES workspaces(id) ON DELETE SET NULL,
    agent_id     VARCHAR(100),
    incident_id  UUID        REFERENCES incidents(id) ON DELETE SET NULL,
    action       VARCHAR(100) NOT NULL,
    status       VARCHAR(50),
    tokens_used  INT          DEFAULT 0,
    metadata     JSONB,
    created_at   TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_events (workspace_id);
CREATE INDEX IF NOT EXISTS idx_audit_created   ON audit_events (created_at);

-- ──────────────────────────────────────────────
-- TOKEN USAGE — monthly spend tracking
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_usage (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID        REFERENCES workspaces(id) ON DELETE CASCADE,
    incident_id  UUID        REFERENCES incidents(id) ON DELETE SET NULL,
    agent_id     VARCHAR(50),
    tokens_used  INT         NOT NULL,
    cost_usd     NUMERIC(10,6) NOT NULL DEFAULT 0.0,
    billing_month CHAR(7)    NOT NULL,  -- 'YYYY-MM'
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_usage_workspace_month ON token_usage (workspace_id, billing_month);

-- ──────────────────────────────────────────────
-- FUNCTION: auto-update updated_at timestamps
-- ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_workspaces_updated_at ON workspaces;
CREATE TRIGGER trg_workspaces_updated_at
    BEFORE UPDATE ON workspaces
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_internal_tasks_updated_at ON internal_agent_tasks;
CREATE TRIGGER trg_internal_tasks_updated_at
    BEFORE UPDATE ON internal_agent_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
