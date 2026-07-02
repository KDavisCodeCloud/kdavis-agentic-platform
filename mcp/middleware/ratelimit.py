"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Per-tool, per-workspace sliding window rate limiter.

Limits (from config.py):
  Read tools:  100 req/min per workspace
  Write tools: 10  req/min per workspace

Implementation: in-memory sliding window with asyncio.Lock.
  - Correct for single-process deployment (uvicorn --workers 1)
  - In multi-worker deployments, effective limit = N × configured limit
    because each worker maintains its own window.
    Upgrade path: replace _windows dict with Redis ZRANGEBYSCORE / ZADD.

The lock is per-bucket (not global) to minimize contention across
different workspace+tool combinations.
"""

import asyncio
import time
from collections import defaultdict, deque
from typing import Optional

from config import TOOL_RATE_LIMITS

# bucket key → deque of request timestamps (monotonic)
_windows: dict[str, deque] = defaultdict(deque)
_lock = asyncio.Lock()   # global lock — acceptable at this scale, replace with per-bucket for high throughput


class RateLimitError(Exception):
    def __init__(self, tool_name: str, limit: int) -> None:
        super().__init__(
            f"Rate limit exceeded for '{tool_name}': {limit} requests/min per workspace. "
            f"Try again in a moment."
        )
        self.tool_name = tool_name
        self.limit = limit


async def enforce_rate_limit(tool_name: str, workspace_id: str) -> None:
    """
    Slide the window and count. Raises RateLimitError if over limit.
    Increments the counter on every call that passes.
    """
    limit: int = TOOL_RATE_LIMITS.get(tool_name, 100)
    window: float = 60.0
    now = time.monotonic()
    key = f"{workspace_id}:{tool_name}"

    async with _lock:
        q = _windows[key]

        # Evict entries outside the rolling window
        while q and q[0] < now - window:
            q.popleft()

        if len(q) >= limit:
            raise RateLimitError(tool_name, limit)

        q.append(now)


def current_count(tool_name: str, workspace_id: str) -> int:
    """Return the current window count (for health/debug endpoints)."""
    now = time.monotonic()
    key = f"{workspace_id}:{tool_name}"
    q = _windows.get(key, deque())
    return sum(1 for t in q if t >= now - 60.0)
