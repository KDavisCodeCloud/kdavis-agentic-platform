-- Migration 003: Outreach pipeline tables
-- Run after 002_content_pipeline.sql

CREATE TABLE IF NOT EXISTS outreach_leads (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,

    -- Lead info (entered by operator)
    lead_name           TEXT NOT NULL,
    company             TEXT NOT NULL,
    role                TEXT NOT NULL,
    team_size           TEXT NOT NULL,
    cloud_provider      TEXT NOT NULL,
    pain_points         TEXT NOT NULL,
    how_they_found_us   TEXT NOT NULL DEFAULT '',
    linkedin_url        TEXT NOT NULL DEFAULT '',
    additional_context  TEXT NOT NULL DEFAULT '',

    -- Pipeline outputs (JSONB — populated after agents run)
    qualify_output      JSONB,
    assessment_output   JSONB,
    proposal_output     JSONB,
    connection_note     TEXT,     -- drafted note ≤300 chars, for manual copy-paste only

    -- State machine
    status              TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN (
                            'new', 'qualifying', 'qualified', 'disqualified',
                            'ready_to_send', 'sent', 'accepted', 'declined', 'no_response'
                        )),

    -- Pacing tracking
    sent_at             TIMESTAMPTZ,     -- when operator marked as manually sent
    status_updated_at   TIMESTAMPTZ,     -- when accepted/declined/no_response was set

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_leads_workspace
    ON outreach_leads (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_outreach_leads_sent_at
    ON outreach_leads (workspace_id, sent_at)
    WHERE sent_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_outreach_leads_status
    ON outreach_leads (workspace_id, status);
