"""
tests/test_workspace_scope.py
Phase 11, scale-readiness build.

core/workspace_scope.py's workspace_scoped_connection() is the Python
side of db/migrations/031_rls_core_tables.sql's RLS policies -- it sets
the app.current_workspace_id session variable those policies key off of.
No real Postgres is available in this test suite (asyncpg is stubbed in
conftest.py, "always mocked at DB layer"), so these tests pin the exact
SQL/transaction shape against a mocked pool/connection -- they cannot
prove the RLS policy itself blocks a cross-workspace read (that was
verified live against production this session, see GAPS.md #20), only
that the Python helper does what migration 031's policies require.
"""

from unittest.mock import AsyncMock, MagicMock

from core.workspace_scope import workspace_scoped_connection


def _mock_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)

    txn_ctx = AsyncMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool, conn


class TestWorkspaceScopedConnection:
    async def test_sets_workspace_session_variable(self):
        pool, conn = _mock_pool()

        async with workspace_scoped_connection(pool, "ws-123") as scoped_conn:
            assert scoped_conn is conn

        conn.execute.assert_awaited_once_with(
            "SELECT set_config('app.current_workspace_id', $1, true)", "ws-123",
        )

    async def test_opens_a_transaction(self):
        pool, conn = _mock_pool()

        async with workspace_scoped_connection(pool, "ws-123"):
            pass

        conn.transaction.assert_called_once()

    async def test_workspace_id_coerced_to_str(self):
        """A UUID object (as workspace['id'] often is) must not reach
        set_config() as a non-string type -- asyncpg would send it as its
        own uuid type, not the text $1 the SQL expects here."""
        pool, conn = _mock_pool()

        class FakeUUID:
            def __str__(self):
                return "fake-uuid-str"

        async with workspace_scoped_connection(pool, FakeUUID()):
            pass

        args = conn.execute.await_args.args
        assert args[1] == "fake-uuid-str"
        assert isinstance(args[1], str)

    async def test_yields_the_acquired_connection(self):
        pool, conn = _mock_pool()

        async with workspace_scoped_connection(pool, "ws-123") as scoped_conn:
            await scoped_conn.execute("SELECT 1")

        assert conn.execute.await_count == 2  # set_config + the caller's own query
