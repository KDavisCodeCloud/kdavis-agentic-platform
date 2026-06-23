"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 KDavis Agentic Systems LLC. All rights reserved.
"""

"""
Per-workspace rate limiter.
Uses slowapi (a FastAPI-compatible wrapper around limits).

Limits:
- Starter:    30 req/min on agent endpoints
- Growth:     120 req/min
- Enterprise: 600 req/min
"""

import logging
from fastapi import Request

from slowapi import Limiter
from slowapi.util import get_remote_address

log = logging.getLogger(__name__)


def _workspace_key(request: Request) -> str:
    """Use workspace token prefix as the rate limit key, fall back to IP."""
    token = request.headers.get("X-Workspace-Token")
    if token:
        return f"ws:{token[:16]}"
    return get_remote_address(request)


limiter = Limiter(key_func=_workspace_key)


def get_rate_limit_for_tier(tier: str) -> str:
    """Return the slowapi limit string for the given product tier."""
    return {
        "starter":    "30/minute",
        "growth":     "120/minute",
        "enterprise": "600/minute",
    }.get(tier, "30/minute")
