"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

WorkspaceTierMiddleware

Sets request.state.workspace_tier before the route handler runs.
This allows the rate limiter's _tier_limit()/_webhook_tier_limit()
callables to read the tier from request.state and enforce per-tier
request limits without a second DB lookup inside the endpoint.

Only acts on /api/v1/agents/* and /api/v1/webhooks/* requests —
everything else gets the "starter" default and passes through without a
DB query.
"""

import hashlib
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)

_RATE_LIMITED_PREFIXES = ("/api/v1/agents", "/api/v1/webhooks")


class WorkspaceTierMiddleware(BaseHTTPMiddleware):
    """
    Lightweight middleware that reads product_tier from the DB and attaches
    it to request.state.workspace_tier for the rate limiter.

    Does NOT consume the request body — safe to use alongside the
    /billing/webhook endpoint which needs raw bytes.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.workspace_tier = "starter"  # safe default

        if not request.url.path.startswith(_RATE_LIMITED_PREFIXES):
            return await call_next(request)

        # Manual-trigger routes (api/routes/agents.py) send the workspace
        # token as the X-Workspace-Token header; webhook routes
        # (api/routes/webhooks.py) send it as a ?token= query param
        # instead -- POST /webhooks/github?token=<workspace_token>. Both
        # need to resolve a real tier, or every webhook customer silently
        # rate-limits at the Starter floor regardless of what they pay for.
        token = request.headers.get("X-Workspace-Token") or request.query_params.get("token")
        if not token:
            return await call_next(request)

        db_pool = getattr(request.app.state, "db_pool", None)
        if not db_pool:
            return await call_next(request)

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT product_tier FROM workspaces WHERE workspace_token = $1",
                    token_hash,
                )
            if row and row["product_tier"]:
                request.state.workspace_tier = row["product_tier"]
        except Exception as exc:
            log.debug("[TierMiddleware] DB lookup failed: %s", exc)

        return await call_next(request)
