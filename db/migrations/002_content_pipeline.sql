-- Migration 002: Content pipeline tables
-- Run after 001_initial_schema.sql

-- Content drafts — one row per piece of content moving through the pipeline
CREATE TABLE IF NOT EXISTS content_drafts (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id            UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    platform                VARCHAR(20) NOT NULL CHECK (platform IN ('linkedin', 'x', 'video')),
    raw_idea                TEXT NOT NULL,
    goal                    VARCHAR(50) NOT NULL,
    target_audience         TEXT NOT NULL DEFAULT 'Engineering Managers and DevOps leads',
    additional_constraints  TEXT NOT NULL DEFAULT '',

    -- Pipeline outputs (JSONB — populated progressively)
    brief                   JSONB,
    draft_output            JSONB,
    review_output           JSONB,
    publish_package         JSONB,

    -- State machine
    status                  VARCHAR(20) NOT NULL DEFAULT 'generating'
                            CHECK (status IN (
                                'generating', 'pending_review', 'approved',
                                'publishing', 'published', 'rejected', 'failed'
                            )),

    -- Human decision
    selected_draft          VARCHAR(10),   -- 'draft_a' or 'draft_b'
    operator_edit           TEXT,          -- override text if human edited
    rejection_feedback      TEXT,

    -- Quality scores (from review-agent)
    brand_voice_score       SMALLINT,
    brief_alignment_score   SMALLINT,

    -- Published result
    linkedin_post_id        TEXT,
    x_post_id               TEXT,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_drafts_workspace
    ON content_drafts (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_content_drafts_status
    ON content_drafts (workspace_id, status);


-- Social OAuth connections — one row per workspace+platform pair
CREATE TABLE IF NOT EXISTS workspace_social_connections (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id            UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    platform                VARCHAR(20) NOT NULL CHECK (platform IN ('linkedin', 'x')),
    platform_user_id        TEXT NOT NULL,
    platform_display_name   TEXT,
    encrypted_access_token  TEXT NOT NULL,   -- Fernet-encrypted OAuth access token
    encrypted_token_secret  TEXT,            -- X OAuth 1.0a token secret (if applicable)
    author_urn              TEXT,            -- LinkedIn author URN: urn:li:person:{id}
    connected_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_social_connections_workspace
    ON workspace_social_connections (workspace_id);
