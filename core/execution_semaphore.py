"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Phase 7, scale-readiness build. Bounds how many agent executions can run
concurrently on this process, so a burst (50 webhooks arriving at once,
per this session's own scale-readiness assessment) degrades gracefully
-- extra jobs queue behind the semaphore, visible via the log line below
-- instead of all piling into app.state.db_pool at once and silently
exhausting it.

Sized from the pool's own max_size (asyncpg.Pool.get_max_size()) rather
than a second, independently-drifting magic number -- when Phase 8
raises the pool's max_size, this semaphore's ceiling moves with it
automatically, since it's derived at acquire time.
"""

import asyncio
import functools
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from core.error_tracking import capture_message

log = logging.getLogger(__name__)

# Threshold above which a wait is logged as backpressure, not just normal
# scheduling jitter -- an agent run genuinely queued behind a full pool,
# not just a few milliseconds of event-loop scheduling noise.
_BACKPRESSURE_LOG_THRESHOLD_SECONDS = 1.0


def _get_or_create_semaphore(app) -> asyncio.Semaphore:
    """One semaphore per process, created lazily on first use and cached
    on app.state -- avoids a second startup-ordering dependency in
    lifespan() beyond "the db_pool already exists"."""
    existing = getattr(app.state, "agent_execution_semaphore", None)
    if existing is not None:
        return existing

    max_size = app.state.db_pool.get_max_size()
    semaphore = asyncio.Semaphore(max_size)
    app.state.agent_execution_semaphore = semaphore
    log.info("[ExecutionSemaphore] Created with capacity=%d (from db_pool.get_max_size())", max_size)
    return semaphore


@asynccontextmanager
async def bounded_agent_execution(app, agent_id: str, workspace_id: Optional[str] = None):
    """
    Wrap an agent's background-task execution in this. Acquires the
    shared semaphore (bounded by the DB pool's max_size), logs a
    backpressure warning if the wait was non-trivial, then yields.

    Usage (each _run_* function in api/routes/webhooks.py):
        async with bounded_agent_execution(app, "agent_01_cicd_triage", workspace_id):
            async with app.state.db_pool.acquire() as conn:
                ...
    """
    semaphore = _get_or_create_semaphore(app)

    wait_start = time.monotonic()
    async with semaphore:
        wait_seconds = time.monotonic() - wait_start
        if wait_seconds >= _BACKPRESSURE_LOG_THRESHOLD_SECONDS:
            log.warning(
                "[ExecutionSemaphore] Backpressure — agent=%s workspace=%s waited %.2fs for a slot",
                agent_id, workspace_id, wait_seconds,
            )
            # Not an error -- a real signal worth Sentry visibility:
            # sustained backpressure means the burst-handling ceiling is
            # being tested for real, not a theoretical concern.
            capture_message(
                f"Agent execution backpressure: {wait_seconds:.2f}s wait for {agent_id}",
                level="warning", workspace_id=workspace_id, agent_id=agent_id,
                extra={"wait_seconds": wait_seconds},
            )
        yield


def bounded_execution(agent_id: str):
    """
    Decorator form of bounded_agent_execution -- wraps an entire
    background-task function's execution without needing to reindent its
    body. Applied to every api/routes/webhooks.py _run_* function:

        @bounded_execution("agent_01_cicd_triage")
        async def _run_cicd_triage(app, workspace, payload, cloud_provider, ingestion_log_id=None):
            ...

    Preserves the exact original call signature externally (app,
    workspace positionally, everything else passed through) -- FastAPI's
    background_tasks.add_task(_run_cicd_triage, app, workspace, payload,
    "github", ingestion_log_id=log_id) keeps working unchanged.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(app, workspace, *args, **kwargs):
            workspace_id = str(workspace["id"]) if isinstance(workspace, dict) and "id" in workspace else None
            async with bounded_agent_execution(app, agent_id, workspace_id):
                return await func(app, workspace, *args, **kwargs)

        return wrapper

    return decorator
