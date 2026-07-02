-- Migration 004: MCP API keys
-- Run after 003_outreach.sql
--
-- Stores hashed API keys for MCP server authentication.
-- Raw keys are NEVER stored — only SHA-256 hashes.
-- Enterprise tier workspaces are blocked at the application layer (OAuth 2.1 required).

CREATE TABLE IF NOT EXISTS mcp_api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,

    key_hash        TEXT NOT NULL UNIQUE,   -- SHA-256(raw_key), hex-encoded
    key_prefix      TEXT NOT NULL,          -- First 12 chars of raw key (for display only)
    name            TEXT NOT NULL,          -- Human-readable label ("Claude Code - prod")

    scopes          TEXT[] NOT NULL,        -- ['mcp:read'] or ['mcp:read', 'mcp:write']

    -- Hard expiry — max 90 days from creation, no "never expires"
    expires_at      TIMESTAMPTZ NOT NULL,

    last_used_at    TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,            -- NULL = active, non-NULL = revoked

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookup path: hash → key record + workspace tier in one query
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_hash
    ON mcp_api_keys (key_hash)
    WHERE revoked_at IS NULL;

-- Workspace key management view
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_workspace
    ON mcp_api_keys (workspace_id, created_at DESC);

-- MCP connection audit log — tool call telemetry (no argument values stored)
CREATE TABLE IF NOT EXISTS mcp_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,

    tool_name       TEXT NOT NULL,
    auth_method     TEXT NOT NULL CHECK (auth_method IN ('oauth', 'api_key')),
    caller_subject  TEXT NOT NULL,          -- OAuth: JWT sub / API key: key UUID
    user_id         TEXT,                   -- OAuth only

    -- Argument shapes only — never argument values
    arg_keys        TEXT[],                 -- e.g. ['incident_id', 'approver_note']
    arg_key_count   INT NOT NULL DEFAULT 0,

    status          TEXT NOT NULL CHECK (status IN ('ok', 'error', 'rejected', 'killed')),
    error_code      TEXT,
    latency_ms      INT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_audit_workspace
    ON mcp_audit_log (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_mcp_audit_tool
    ON mcp_audit_log (tool_name, created_at DESC);
