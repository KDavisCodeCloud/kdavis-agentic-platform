"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Internal (owner/team) auth — completely separate from api/middleware/auth.py's
customer workspace-token model. This path validates a real Supabase session
JWT issued by the platform's own Supabase project (SUPABASE_URL /
SUPABASE_SERVICE_ROLE_KEY — the same project ceo-dashboard's magic-link login
authenticates against) and requires user_metadata.role == "admin", matching
the exact role check ceo-dashboard/middleware.ts already enforces client-side
(lib/types.ts: Role = "admin" | "marketing" | "rnd").

This dependency must never be reachable via X-Workspace-Token, must never
read from or write to the `workspaces`/`incidents` tables, and must never be
used to grant access to customer workspace data. Full isolation from
api/middleware/auth.py's model is the entire point — do not merge these two
auth paths or have one call into the other.
"""

import logging
import os

from fastapi import HTTPException, Request, status

log = logging.getLogger(__name__)

_ADMIN_ROLE = "admin"


async def get_internal_user(request: Request) -> dict:
    """
    FastAPI dependency: validates the Supabase session JWT in the
    Authorization header and returns {"id", "email", "role"} for an admin
    user. Raises 401 if missing/invalid, 403 if the user isn't an admin.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <supabase session token> required",
        )
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <supabase session token> required",
        )

    # Lazy import — matches this repo's convention (core/engine.py,
    # security/audit_log.py, agents/mse/*) of never importing third-party
    # clients at module top level, so this file imports cleanly with no deps.
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not service_key:
        log.error("[InternalAuth] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal auth is not configured on this server",
        )

    client = create_client(url, service_key)
    try:
        user_resp = client.auth.get_user(token)
    except Exception:
        log.warning("[InternalAuth] Token verification failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    user = getattr(user_resp, "user", None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    role = (user.user_metadata or {}).get("role", "rnd")
    if role != _ADMIN_ROLE:
        log.warning("[InternalAuth] user=%s role=%s denied — admin required", user.id, role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    return {"id": str(user.id), "email": user.email, "role": role}
