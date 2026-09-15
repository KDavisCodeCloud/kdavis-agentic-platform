"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Error monitoring for Cloud Decoded's own backend -- catches problems in this
platform's infrastructure, not customer infrastructure (that's what the
agents are for). GAPS.md #16.

init_sentry() is a no-op if SENTRY_DSN isn't set: local dev, tests, and any
environment that hasn't configured Sentry work identically with or without
it, never raising or blocking startup on a missing/invalid DSN.

capture_exception() is safe to call even when Sentry was never initialized
-- sentry_sdk's global functions no-op without a configured client, so
every call site here works in local dev without an `if sentry configured`
guard at each call.
"""

import logging
import os
from typing import Optional

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

log = logging.getLogger(__name__)


def init_sentry() -> None:
    """Call once at startup, before the FastAPI app is instantiated --
    the FastAPI/Starlette integrations instrument at import/init time."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        log.info("[ErrorTracking] SENTRY_DSN not set -- error monitoring disabled")
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("ENVIRONMENT", "production"),
        integrations=[StarletteIntegration(), FastApiIntegration()],
        # Errors only -- no performance/trace sampling. This is about
        # catching unhandled exceptions and job failures, not APM.
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    log.info("[ErrorTracking] Sentry initialized")


def capture_exception(
    exc: BaseException,
    *,
    workspace_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Report an exception to Sentry, tagged so it's traceable per tenant.
    No-ops safely if Sentry was never initialized (see module docstring)."""
    with sentry_sdk.new_scope() as scope:
        if workspace_id:
            scope.set_tag("workspace_id", str(workspace_id))
        if agent_id:
            scope.set_tag("agent_id", agent_id)
        if extra:
            for key, value in extra.items():
                scope.set_extra(key, value)
        sentry_sdk.capture_exception(exc)
