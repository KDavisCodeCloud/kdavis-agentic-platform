"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Per-workspace rate limiter.
Uses slowapi (a FastAPI-compatible wrapper around limits).

Limits:
- Manual agent-trigger routes (api/routes/agents.py):
    Starter 30/min, Growth 120/min, Enterprise 600/min
- Webhook routes (api/routes/webhooks.py) -- higher ceilings, since these
  fire from external systems (CI pipelines, cloud alert managers), not a
  human clicking a button:
    Starter 60/min, Growth 300/min, Enterprise 1200/min
"""

import logging
from fastapi import Request

from slowapi import Limiter
from slowapi.util import get_remote_address

log = logging.getLogger(__name__)


def _workspace_key(request: Request) -> str:
    """Use workspace token prefix as the rate limit key, fall back to IP.

    Also embeds the workspace's tier (set by WorkspaceTierMiddleware) so
    _tier_limit/_webhook_tier_limit can recover it. slowapi==0.1.9's
    LimitGroup.__iter__ only ever invokes a callable limit-value provider
    as fn(key) or fn() — it never hands the callable the Request — so a
    tier lookup that needs request.state has no other way to reach it
    than riding along in the key this function already produces (which
    *does* receive the Request).

    Checks the X-Workspace-Token header first (manual-trigger routes),
    then the ?token= query param (webhook routes use this instead) --
    same precedence WorkspaceTierMiddleware already uses to resolve the
    tier itself, so the key and the tier it embeds always agree.
    """
    tier = getattr(request.state, "workspace_tier", "starter")
    token = request.headers.get("X-Workspace-Token") or request.query_params.get("token")
    if token:
        return f"ws:{tier}:{token[:16]}"
    return get_remote_address(request)


limiter = Limiter(key_func=_workspace_key)


def _tier_limit(key: str) -> str:
    """
    Callable for @limiter.limit() — returns the rate limit string for the
    workspace's tier, parsed back out of `key`.

    Takes `key`, not `request`: slowapi==0.1.9's LimitGroup.__iter__ calls a
    callable limit-value provider with the computed rate-limit key when its
    signature has a `key` parameter (as this one now does), or with no
    arguments otherwise — it has no code path that passes the Request
    itself. Confirmed live 2026-09-10: the old `fn(request)` signature threw
    `TypeError: _tier_limit() missing 1 required positional argument:
    'request'` on every call, because slowapi always called it with zero
    args (no `key` param existed to trigger the key-passing branch). See
    GAPS.md gap #5 in kdavis-cloud-audit for the discovery, and
    _workspace_key above for where the tier gets embedded in the key.
    """
    parts = key.split(":", 2)
    tier = parts[1] if len(parts) == 3 and parts[0] == "ws" else "starter"
    return get_rate_limit_for_tier(tier)


def get_rate_limit_for_tier(tier: str) -> str:
    """Return the slowapi limit string for the given product tier
    (manual agent-trigger routes)."""
    return {
        "starter":    "30/minute",
        "growth":     "120/minute",
        "enterprise": "600/minute",
    }.get(tier, "30/minute")


def _webhook_tier_limit(key: str) -> str:
    """Same key-parsing shape as _tier_limit, higher ceilings for webhook
    routes -- see get_webhook_rate_limit_for_tier."""
    parts = key.split(":", 2)
    tier = parts[1] if len(parts) == 3 and parts[0] == "ws" else "starter"
    return get_webhook_rate_limit_for_tier(tier)


def get_webhook_rate_limit_for_tier(tier: str) -> str:
    """Return the slowapi limit string for the given product tier
    (webhook routes -- higher than the manual-trigger limits since these
    fire from external systems, not a human)."""
    return {
        "starter":    "60/minute",
        "growth":     "300/minute",
        "enterprise": "1200/minute",
    }.get(tier, "60/minute")
