"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Phase 7, scale-readiness build. asyncpg's Pool.acquire() takes a per-call
`timeout` (default None -- wait indefinitely) but create_pool() has no
pool-wide default. Every call site in this codebase does
`async with app.state.db_pool.acquire() as conn:` with no timeout
argument, so pool exhaustion previously blocked indefinitely instead of
surfacing as a clear error. Retrofitting a `timeout=` kwarg onto every
call site individually would be a large, error-prone mechanical change;
this wraps the pool once instead, applying a default timeout to any
acquire() call that doesn't explicitly override it.
"""

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

DEFAULT_ACQUIRE_TIMEOUT_SECONDS = 5.0


class TimeoutBoundPool:
    """Thin wrapper around an asyncpg.Pool: acquire() defaults to
    `timeout=default_timeout` when the caller doesn't specify one.
    Everything else delegates straight through to the real pool."""

    def __init__(self, pool: Any, default_timeout: float = DEFAULT_ACQUIRE_TIMEOUT_SECONDS):
        self._pool = pool
        self._default_timeout = default_timeout

    def acquire(self, *, timeout: Optional[float] = None):
        return self._pool.acquire(timeout=timeout if timeout is not None else self._default_timeout)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pool, name)
