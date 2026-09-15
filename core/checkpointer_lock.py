"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Phase 5, scale-readiness build. Wraps LangGraph's AsyncPostgresSaver with a
single asyncio.Lock so concurrent coroutines never issue overlapping
operations on the one shared, non-pooled psycopg connection api/main.py's
lifespan() creates (see that module's own docstring for why a single
connection was chosen over from_conn_string() -- the prepare_threshold=None
fix for Supabase's transaction-mode pooler). A bare psycopg.AsyncConnection
is not safe for concurrent use from multiple coroutines; without this, two
agent runs whose checkpoint writes land in the same moment on this one
process risk protocol-level interleaving, not just serialized slowness --
this was flagged as the sharpest, lowest-threshold failure risk in this
session's scale-readiness assessment (single-digit concurrent agent runs
platform-wide, not per-customer).

Deliberately a lock, not a connection pool: pooling would mean giving
every new pooled connection api/main.py's exact prepare_threshold=None
override, adding a new dependency (psycopg_pool), and re-proving the
transaction-mode-pooler compatibility this session already fought to get
right once (see db/migrate.py and api/main.py's own comments on this same
class of bug). A single lock is a much smaller, lower-risk surface for the
same correctness guarantee -- serialization was already the practical
ceiling for checkpoint operations specifically (they're small, fast writes;
the real scale bottleneck sits elsewhere -- the asyncpg pool and job
durability, both addressed in other phases of this build), so trading
theoretical checkpoint-write parallelism for a much simpler, safer fix is
the right call here.
"""

import asyncio
from typing import Any, AsyncIterator, Optional, Sequence

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


class LockedAsyncPostgresSaver(BaseCheckpointSaver):
    """
    Drop-in replacement for AsyncPostgresSaver -- same public async
    interface (BaseCheckpointSaver's aget/aget_tuple/aput/aput_writes/
    adelete_thread/alist), each call serialized through one asyncio.Lock
    shared across every agent workflow on this process.

    Usage (api/main.py's lifespan()):
        inner = AsyncPostgresSaver(conn=lg_conn)
        await inner.setup()
        app.state.checkpointer = LockedAsyncPostgresSaver(inner)
    """

    def __init__(self, inner: AsyncPostgresSaver):
        super().__init__(serde=inner.serde)
        self._inner = inner
        self._lock = asyncio.Lock()

    async def aget(self, config: dict) -> Optional[Checkpoint]:
        async with self._lock:
            return await self._inner.aget(config)

    async def aget_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        async with self._lock:
            return await self._inner.aget_tuple(config)

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        async with self._lock:
            return await self._inner.aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        # task_path accepted (not forwarded): langgraph-checkpoint 2.1.2's
        # BaseCheckpointSaver.aput_writes abstract signature added task_path,
        # and langgraph's pregel executor always calls us with it -- but the
        # pinned langgraph-checkpoint-postgres==2.0.4's AsyncPostgresSaver
        # predates that addition and only takes (config, writes, task_id).
        # Forwarding it raised TypeError on every checkpoint write, breaking
        # HITL-gate resumption for every agent (caught live via Agent 11's
        # Azure Monitor webhook test, 2026-09-15 -- GraphInterrupt fired
        # correctly with a real incident_id, but the checkpoint that would
        # let an operator's later approval resume from that exact point
        # never got written). task_path is optional map/Send-task-fanout
        # metadata the postgres saver's schema doesn't have a column for in
        # this pinned version; this codebase's graphs don't use Send() fan-
        # out, so dropping it here is safe. Revisit when
        # langgraph-checkpoint-postgres is deliberately bumped past 2.0.x.
        async with self._lock:
            await self._inner.aput_writes(config, writes, task_id)

    async def adelete_thread(self, thread_id: str) -> None:
        async with self._lock:
            await self._inner.adelete_thread(thread_id)

    async def alist(
        self,
        config: Optional[dict],
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        # Held for the full iteration, not just the call that starts it --
        # a partially-consumed generator interleaving with another
        # coroutine's aput on the same connection is exactly the failure
        # mode this wrapper exists to prevent.
        async with self._lock:
            async for item in self._inner.alist(config, filter=filter, before=before, limit=limit):
                yield item
