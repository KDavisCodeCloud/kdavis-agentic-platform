"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
OAuth 2.1 JWT validation for MCP server auth.

Token source: Supabase Auth (HS256, project JWT secret).
Audience:     mcp.theclouddecoded.com (RFC 8707 resource indicator).

Supabase JWT template required (Dashboard → Auth → JWT Template):
  {
    "workspace_id":   "{{ user.user_metadata.workspace_id }}",
    "workspace_tier": "{{ user.user_metadata.workspace_tier }}",
    "mcp_scopes":     ["mcp:read"],   // or ["mcp:read","mcp:write"]
    "aud":            "mcp.theclouddecoded.com"
  }

Per-request: every MCP call carries the JWT in Authorization: Bearer <token>.
Tokens are validated offline — no Supabase API call per request.
"""

import logging
from typing import Any

import jwt  # PyJWT

from config import SUPABASE_JWT_SECRET, MCP_AUDIENCE
from auth.models import CallerIdentity, AuthError

log = logging.getLogger(__name__)


async def validate_oauth_token(raw_token: str) -> CallerIdentity:
    """
    Validate a Supabase JWT and return a CallerIdentity.

    Checks (all enforced by PyJWT):
      - Signature (HS256, SUPABASE_JWT_SECRET)
      - Expiry (exp claim)
      - Audience (aud == MCP_AUDIENCE, RFC 8707)

    Additional checks:
      - sub claim present
      - workspace_id in app_metadata or top-level claim
      - mcp_scopes claim present (defaults to ["mcp:read"] if missing)
    """
    if not SUPABASE_JWT_SECRET:
        raise AuthError("Server misconfiguration: SUPABASE_JWT_SECRET not set", 500)

    try:
        claims: dict[str, Any] = jwt.decode(
            raw_token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=MCP_AUDIENCE,
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired")
    except jwt.InvalidAudienceError:
        raise AuthError(
            f"Token audience must be '{MCP_AUDIENCE}'. "
            f"Check your Supabase JWT template includes \"aud\": \"{MCP_AUDIENCE}\"."
        )
    except jwt.DecodeError as exc:
        raise AuthError(f"Token decode failed: {exc}")
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"Invalid token: {exc}")

    sub = claims.get("sub")
    if not sub:
        raise AuthError("Token missing 'sub' claim")

    # Extract workspace context from app_metadata (Supabase convention)
    # or top-level claims (custom JWT template may place them there)
    app_meta: dict = claims.get("app_metadata") or {}
    workspace_id   = app_meta.get("workspace_id")   or claims.get("workspace_id")
    workspace_tier = app_meta.get("workspace_tier") or claims.get("workspace_tier") or "starter"
    mcp_scopes     = app_meta.get("mcp_scopes")     or claims.get("mcp_scopes") or ["mcp:read"]

    if not workspace_id:
        raise AuthError(
            "Token missing 'workspace_id'. "
            "Ensure the Supabase JWT template includes workspace_id in app_metadata."
        )

    # Validate scopes are known values
    known_scopes = {"mcp:read", "mcp:write"}
    clean_scopes = frozenset(s for s in mcp_scopes if s in known_scopes)
    if not clean_scopes:
        clean_scopes = frozenset({"mcp:read"})  # safe default

    return CallerIdentity(
        workspace_id=str(workspace_id),
        workspace_tier=str(workspace_tier),
        auth_method="oauth",
        scopes=clean_scopes,
        subject=str(sub),
        user_id=str(sub),
    )
