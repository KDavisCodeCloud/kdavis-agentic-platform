"""
tests/test_checkpointer_lock.py
Tests for core/checkpointer_lock.py -- Phase 5, scale-readiness build.

Confirms LockedAsyncPostgresSaver actually SERIALIZES concurrent access to
the wrapped inner checkpointer -- not just that a lock object exists on
the class, but that no two calls are ever genuinely "in flight" on the
shared connection at the same time. Uses a fake inner checkpointer that
tracks concurrent-call depth and sleeps mid-call (yielding control back
to the event loop) so a real race would actually surface if the lock
didn't work, rather than asserting on timing that could pass by luck.
"""

import asyncio
from unittest.mock import MagicMock

from core.checkpointer_lock import LockedAsyncPostgresSaver


class _FakeInnerCheckpointer:
    """Simulates AsyncPostgresSaver's async interface with an artificial
    await point on every call, tracking how many calls were concurrently
    in-flight -- the actual thing under test."""

    def __init__(self):
        self.serde = MagicMock()
        self._in_flight = 0
        self.max_concurrent_seen = 0
        self.calls: list[str] = []

    async def _simulate(self, name, result):
        self._in_flight += 1
        self.max_concurrent_seen = max(self.max_concurrent_seen, self._in_flight)
        self.calls.append(name)
        await asyncio.sleep(0.01)  # yields control -- a real race surfaces here if unlocked
        self._in_flight -= 1
        return result

    async def aget(self, config):
        return await self._simulate("aget", "aget-result")

    async def aget_tuple(self, config):
        return await self._simulate("aget_tuple", "aget_tuple-result")

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await self._simulate("aput", "aput-result")

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await self._simulate("aput_writes", None)

    async def adelete_thread(self, thread_id):
        await self._simulate("adelete_thread", None)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        self._in_flight += 1
        self.max_concurrent_seen = max(self.max_concurrent_seen, self._in_flight)
        self.calls.append("alist")
        await asyncio.sleep(0.01)
        self._in_flight -= 1
        for item in ():
            yield item


class TestLockedAsyncPostgresSaverConcurrency:
    async def test_three_concurrent_aput_calls_never_overlap(self):
        inner = _FakeInnerCheckpointer()
        locked = LockedAsyncPostgresSaver(inner)

        await asyncio.gather(*[
            locked.aput({"configurable": {"thread_id": f"t{i}"}}, {}, {}, {})
            for i in range(3)
        ])

        assert inner.max_concurrent_seen == 1  # never more than one in flight
        assert len(inner.calls) == 3

    async def test_five_concurrent_aput_calls_never_overlap(self):
        """Explicitly covers "3+" with headroom -- 5 simulated concurrent
        agent runs' checkpoint writes."""
        inner = _FakeInnerCheckpointer()
        locked = LockedAsyncPostgresSaver(inner)

        await asyncio.gather(*[
            locked.aput({"configurable": {"thread_id": f"t{i}"}}, {}, {}, {})
            for i in range(5)
        ])

        assert inner.max_concurrent_seen == 1
        assert len(inner.calls) == 5

    async def test_mixed_concurrent_operations_never_overlap(self):
        """Different method types (not just N copies of one call) mixed
        together -- proves the lock is shared across the whole
        interface, not scoped per-method."""
        inner = _FakeInnerCheckpointer()
        locked = LockedAsyncPostgresSaver(inner)

        config = {"configurable": {"thread_id": "t1"}}
        await asyncio.gather(
            locked.aput(config, {}, {}, {}),
            locked.aget(config),
            locked.aget_tuple(config),
            locked.aput_writes(config, [], "task1"),
            locked.adelete_thread("t1"),
        )

        assert inner.max_concurrent_seen == 1
        assert len(inner.calls) == 5

    async def test_alist_holds_lock_for_full_iteration(self):
        """A partially-consumed generator interleaving with another
        coroutine's aput on the same connection is exactly the failure
        mode this wrapper exists to prevent -- confirms the lock is held
        for alist's entire iteration, not just the call that starts it."""
        inner = _FakeInnerCheckpointer()
        locked = LockedAsyncPostgresSaver(inner)

        async def consume_alist():
            async for _ in locked.alist(None):
                pass

        await asyncio.gather(
            consume_alist(),
            locked.aget({"configurable": {"thread_id": "t1"}}),
            locked.aput({"configurable": {"thread_id": "t2"}}, {}, {}, {}),
        )

        assert inner.max_concurrent_seen == 1

    async def test_delegates_return_values_correctly(self):
        """Confirms the wrapper isn't just serializing -- it still
        returns exactly what the inner checkpointer returned, no
        corruption/loss across the lock boundary."""
        inner = _FakeInnerCheckpointer()
        locked = LockedAsyncPostgresSaver(inner)

        assert await locked.aget({"configurable": {"thread_id": "t1"}}) == "aget-result"
        assert await locked.aput({}, {}, {}, {}) == "aput-result"

    async def test_serde_passed_through_from_inner(self):
        inner = _FakeInnerCheckpointer()
        locked = LockedAsyncPostgresSaver(inner)
        assert locked.serde is inner.serde
