"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
SSRF-protected HTTP client for all calls to the FastAPI backend.

SECURITY CONTRACT:
- Egress is restricted to MCP_UPSTREAM_URL exclusively.
- The host is validated at import time against ALLOWED_UPSTREAM_HOST.
- No arbitrary outbound HTTP calls are allowed from this service.
- The MCP server authenticates to the backend using MCP_SERVICE_KEY.
- Customer OAuth tokens and API keys are NEVER forwarded to the backend.
  The backend trusts the MCP server as a known internal caller and accepts
  the workspace_id it provides.
"""

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from config import MCP_UPSTREAM_URL, MCP_SERVICE_KEY, ALLOWED_UPSTREAM_HOST

log = logging.getLogger(__name__)

# ── SSRF guard — fail fast on misconfiguration ────────────────────────────────

_parsed = urlparse(MCP_UPSTREAM_URL)
_actual_host = _parsed.hostname or ""

if _actual_host != ALLOWED_UPSTREAM_HOST:
    raise EnvironmentError(
        f"SSRF guard: MCP_UPSTREAM_URL host '{_actual_host}' does not match "
        f"derived ALLOWED_UPSTREAM_HOST '{ALLOWED_UPSTREAM_HOST}'. "
        f"Check MCP_UPSTREAM_URL is set correctly."
    )

# ── HTTP client factory ───────────────────────────────────────────────────────

def _client(workspace_id: str) -> httpx.AsyncClient:
    """
    Returns a configured async client for one upstream call.
    Sets service auth header and workspace context.
    Customer credentials are never included here.
    """
    return httpx.AsyncClient(
        base_url=MCP_UPSTREAM_URL,
        headers={
            "X-MCP-Service-Key": MCP_SERVICE_KEY,
            "X-Workspace-Id": workspace_id,
            "User-Agent": "cloud-decoded-mcp/1.0",
        },
        timeout=httpx.Timeout(30.0, connect=5.0),
        # Enforce single-host egress at the transport level
        follow_redirects=False,
    )


# ── Public helpers ────────────────────────────────────────────────────────────

async def get(path: str, workspace_id: str, params: dict | None = None) -> Any:
    """GET /api/v1{path} on the FastAPI backend."""
    async with _client(workspace_id) as client:
        resp = await client.get(f"/api/v1{path}", params=params)
        resp.raise_for_status()
        return resp.json()


async def post(path: str, workspace_id: str, body: dict | None = None) -> Any:
    """POST /api/v1{path} on the FastAPI backend."""
    async with _client(workspace_id) as client:
        resp = await client.post(f"/api/v1{path}", json=body or {})
        resp.raise_for_status()
        return resp.json()
