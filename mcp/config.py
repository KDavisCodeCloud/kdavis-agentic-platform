"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
MCP server configuration — environment variables and kill switches.

All kill switches default to True (enabled). Flip to False to disable
a tool server-side without redeploying. Applied before every tool call.
"""

import os
from typing import Final
from urllib.parse import urlparse

# ── Upstream backend ──────────────────────────────────────────────────────────

MCP_UPSTREAM_URL: Final[str] = os.environ.get("MCP_UPSTREAM_URL", "http://localhost:8000")
MCP_SERVICE_KEY:  Final[str] = os.environ.get("MCP_SERVICE_KEY", "")
MCP_PORT:         Final[int] = int(os.environ.get("MCP_PORT", "8001"))

# Derived from MCP_UPSTREAM_URL — used for SSRF allow-list enforcement
_parsed_upstream = urlparse(MCP_UPSTREAM_URL)
ALLOWED_UPSTREAM_HOST: Final[str] = _parsed_upstream.hostname or "localhost"
ALLOWED_UPSTREAM_PORT: Final[int] = _parsed_upstream.port or (
    443 if _parsed_upstream.scheme == "https" else 80
)

# ── Supabase (OAuth token validation + API key DB) ───────────────────────────

SUPABASE_URL:       Final[str] = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY:  Final[str] = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_JWT_SECRET: Final[str] = os.environ.get("SUPABASE_JWT_SECRET", "")

# DATABASE_URL — same Postgres DB as the main backend, used for API key lookups.
# Accepts postgresql+asyncpg:// (SQLAlchemy prefix stripped automatically).
_raw_db_url: str = os.environ.get("DATABASE_URL", "")
DATABASE_URL: Final[str] = _raw_db_url.replace("postgresql+asyncpg://", "postgresql://")

# OAuth audience claim — tokens issued for the MCP server must carry this value.
# Requires the Supabase JWT template to include: "aud": "mcp.theclouddecoded.com"
MCP_AUDIENCE: Final[str] = os.environ.get("MCP_AUDIENCE", "mcp.theclouddecoded.com")

# ── CORS ─────────────────────────────────────────────────────────────────────

MCP_ALLOWED_ORIGINS: Final[list[str]] = [
    o.strip()
    for o in os.environ.get("MCP_ALLOWED_ORIGINS", "https://theclouddecoded.com").split(",")
    if o.strip()
]

# ── Per-tool kill switches ────────────────────────────────────────────────────
# Flip any value to False to disable that tool without redeploying.
# Takes effect on the next request — no restart required.

TOOL_ENABLED: dict[str, bool] = {
    "list_incidents":       True,
    "get_incident":         True,
    "list_agents":          True,
    "get_workspace_status": True,
    "approve_incident":     True,
    "reject_incident":      True,
    "request_triage":       True,
}

# ── Per-tool rate limits (requests / minute per workspace) ───────────────────

TOOL_RATE_LIMITS: dict[str, int] = {
    "list_incidents":       100,
    "get_incident":         100,
    "list_agents":          100,
    "get_workspace_status": 100,
    "approve_incident":     10,
    "reject_incident":      10,
    "request_triage":       10,
}

# ── Scope requirements per tool ───────────────────────────────────────────────

TOOL_REQUIRED_SCOPE: dict[str, str] = {
    "list_incidents":       "mcp:read",
    "get_incident":         "mcp:read",
    "list_agents":          "mcp:read",
    "get_workspace_status": "mcp:read",
    "approve_incident":     "mcp:write",
    "reject_incident":      "mcp:write",
    "request_triage":       "mcp:write",
}

# ── Tier access — tiers that may use write tools ─────────────────────────────

WRITE_TOOL_TIERS: Final[frozenset[str]] = frozenset({"growth", "enterprise"})

# ── Enterprise-only: OAuth 2.1 required, no API key fallback ─────────────────

OAUTH_REQUIRED_TIERS: Final[frozenset[str]] = frozenset({"enterprise"})
