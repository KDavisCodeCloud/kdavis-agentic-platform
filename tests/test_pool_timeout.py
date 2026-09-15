"""
tests/test_pool_timeout.py
Tests for core/pool_timeout.py -- Phase 7, scale-readiness build.

asyncpg's Pool.acquire() has no pool-wide default timeout (only a
per-call one, and every call site in this codebase omits it) -- pool
exhaustion previously blocked indefinitely. TimeoutBoundPool wraps the
real pool so acquire() defaults to a real timeout unless the caller
explicitly overrides it, and everything else delegates straight through.
"""

from unittest.mock import AsyncMock, MagicMock

from core.pool_timeout import DEFAULT_ACQUIRE_TIMEOUT_SECONDS, TimeoutBoundPool


class TestTimeoutBoundPool:
    def test_acquire_uses_default_timeout_when_caller_omits_it(self):
        real_pool = MagicMock()
        wrapped = TimeoutBoundPool(real_pool)

        wrapped.acquire()

        real_pool.acquire.assert_called_once_with(timeout=DEFAULT_ACQUIRE_TIMEOUT_SECONDS)

    def test_acquire_respects_caller_supplied_timeout(self):
        real_pool = MagicMock()
        wrapped = TimeoutBoundPool(real_pool)

        wrapped.acquire(timeout=30)

        real_pool.acquire.assert_called_once_with(timeout=30)

    def test_custom_default_timeout_at_construction(self):
        real_pool = MagicMock()
        wrapped = TimeoutBoundPool(real_pool, default_timeout=2.5)

        wrapped.acquire()

        real_pool.acquire.assert_called_once_with(timeout=2.5)

    def test_other_methods_delegate_through(self):
        real_pool = MagicMock()
        real_pool.get_max_size.return_value = 20
        wrapped = TimeoutBoundPool(real_pool)

        assert wrapped.get_max_size() == 20
        real_pool.get_max_size.assert_called_once()

    async def test_close_delegates_through(self):
        real_pool = MagicMock()
        real_pool.close = AsyncMock()
        wrapped = TimeoutBoundPool(real_pool)

        await wrapped.close()

        real_pool.close.assert_awaited_once()
