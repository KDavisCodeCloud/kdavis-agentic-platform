"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 KDavis Agentic Systems LLC. All rights reserved.
"""

"""
Token usage middleware — tracks API call counts per workspace for rate limiting
and usage analytics. Distinct from core/token_budget.py which tracks LLM spend.
"""

import logging
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)


class TokenMeterMiddleware(BaseHTTPMiddleware):
    """
    Records API request counts and latency per workspace.
    Writes to app.state for in-memory aggregation; a background task
    can flush to the DB periodically.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

        workspace_token = request.headers.get("X-Workspace-Token")
        if workspace_token:
            # Lightweight in-memory counter — no DB hit on every request
            counts = getattr(request.app.state, "request_counts", {})
            token_prefix = workspace_token[:8]
            counts[token_prefix] = counts.get(token_prefix, 0) + 1
            request.app.state.request_counts = counts

        if elapsed_ms > 5000:
            log.warning(
                "[TokenMeter] Slow request: %s %s — %.1fms",
                request.method, request.url.path, elapsed_ms
            )

        return response
