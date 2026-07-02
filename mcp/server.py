"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Cloud Decoded MCP Server — entry point.

This is a separate FastAPI application from the main backend.
It runs at mcp.theclouddecoded.com on port 8001 and acts as a
protocol adapter between MCP clients (Claude Code, Cursor, etc.)
and the Cloud Decoded FastAPI backend.

It contains NO business logic. All logic lives in the main backend.

Run locally:
    uvicorn server:app --reload --port 8001

Production:
    uvicorn server:app --host 0.0.0.0 --port 8001 --workers 4
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import MCP_PORT, MCP_ALLOWED_ORIGINS, SUPABASE_URL, MCP_AUDIENCE
from auth.middleware import MCPAuthMiddleware
import db
from mcp_instance import mcp

# Import tool modules — side effect: registers @mcp.tool() decorators
import tools.read   # noqa: F401
import tools.write  # noqa: F401

log = logging.getLogger(__name__)
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB pool for API key lookups and audit log writes
    await db.init_pool()

    log.info("[MCP] Server starting — port=%s", MCP_PORT)
    yield

    await db.close_pool()
    log.info("[MCP] Server shut down")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Cloud Decoded MCP Server",
    description="MCP protocol adapter for Cloud Decoded DevOps automation.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# CORS — restrict to known origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=MCP_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Auth middleware — pure ASGI, SSE-safe, runs before every request
# Must be added via add_middleware so it wraps the full app including mounts
app.add_middleware(MCPAuthMiddleware)  # type: ignore[arg-type]

# ── OAuth 2.1 discovery endpoints (RFC 8414) ──────────────────────────────────
# MCP clients call /.well-known/oauth-authorization-server to discover
# how to authenticate. These are exempt from auth (see middleware.py).

@app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def oauth_authorization_server_metadata() -> JSONResponse:
    """
    RFC 8414 — OAuth 2.0 Authorization Server Metadata.
    Points MCP clients at Supabase as the identity provider.

    The token_endpoint and authorization_endpoint here are Supabase's.
    The issuer is this MCP server (it validates the tokens).
    """
    supabase_base = SUPABASE_URL.rstrip("/")
    return JSONResponse({
        "issuer":                             "https://mcp.theclouddecoded.com",
        "authorization_endpoint":             f"{supabase_base}/auth/v1/authorize",
        "token_endpoint":                     f"{supabase_base}/auth/v1/token",
        "jwks_uri":                           f"{supabase_base}/auth/v1/.well-known/jwks.json",
        "registration_endpoint":              None,
        "scopes_supported":                   ["mcp:read", "mcp:write"],
        "response_types_supported":           ["code"],
        "response_modes_supported":           ["query"],
        "grant_types_supported":              ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none"],  # PKCE — no client secret
        "code_challenge_methods_supported":   ["S256"],
        "resource":                           MCP_AUDIENCE,
    })


@app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
async def oauth_protected_resource_metadata() -> JSONResponse:
    """
    RFC 9728 — OAuth 2.0 Protected Resource Metadata.
    Required by MCP 2025-03-26 spec for resource indicator support.
    """
    return JSONResponse({
        "resource":                    MCP_AUDIENCE,
        "authorization_servers":       ["https://mcp.theclouddecoded.com"],
        "scopes_supported":            ["mcp:read", "mcp:write"],
        "bearer_methods_supported":    ["header"],
    })


# ── Health probe ──────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "service": "cloud-decoded-mcp"}


# ── MCP SSE transport mount ───────────────────────────────────────────────────
# Clients connect to:   https://mcp.theclouddecoded.com/mcp/sse
# Messages posted to:   https://mcp.theclouddecoded.com/mcp/messages

app.mount("/mcp", mcp.sse_app())
