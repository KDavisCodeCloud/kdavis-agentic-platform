"""
tests/test_retention.py
Phase 12, scale-readiness build.

core/retention.py's run_retention_cleanup() deletes incidents/
audit_events past the workspace's tier retention window (starter=90d,
growth=365d, enterprise=unlimited -- core/compliance.py's
WorkspaceComplianceGuard.TIER_LIMITS). No real Postgres is available in
this suite (asyncpg stubbed in conftest.py), so these tests pin the
exact SQL/lock/tier-skip shape against a mocked pool -- the real DELETE
behavior against a live database is the kind of thing this session
verifies live post-deploy (see GAPS.md #20's same caveat for RLS).
"""

from unittest.mock import AsyncMock, MagicMock

from core.retention import _RETAINED_TABLES, run_retention_cleanup


def _mock_pool(fetchval_return=True, execute_return="DELETE 0"):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=fetchval_return)
    conn.execute = AsyncMock(return_value=execute_return)

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


class TestRunRetentionCleanup:
    async def test_takes_transaction_scoped_advisory_lock(self):
        pool, conn = _mock_pool()

        await run_retention_cleanup(pool)

        conn.fetchval.assert_awaited_once()
        sql = conn.fetchval.await_args.args[0]
        assert "pg_try_advisory_xact_lock" in sql

    async def test_skips_cleanup_when_lock_not_acquired(self):
        pool, conn = _mock_pool(fetchval_return=False)

        result = await run_retention_cleanup(pool)

        assert result == {}
        conn.execute.assert_not_awaited()

    async def test_deletes_from_incidents_and_audit_events(self):
        pool, conn = _mock_pool()

        await run_retention_cleanup(pool)

        delete_calls = [c for c in conn.execute.await_args_list if "DELETE FROM" in c.args[0]]
        tables_hit = {tbl for call in delete_calls for tbl in _RETAINED_TABLES if tbl in call.args[0]}
        assert tables_hit == set(_RETAINED_TABLES)

    async def test_skips_enterprise_tier_entirely(self):
        pool, conn = _mock_pool()

        await run_retention_cleanup(pool)

        tier_params = [
            call.args[1] for call in conn.execute.await_args_list
            if "DELETE FROM" in call.args[0]
        ]
        assert "enterprise" not in tier_params

    async def test_uses_starter_and_growth_retention_days(self):
        pool, conn = _mock_pool()

        await run_retention_cleanup(pool)

        calls_by_tier = {
            call.args[1]: call.args[2]
            for call in conn.execute.await_args_list
            if "DELETE FROM" in call.args[0]
        }
        assert calls_by_tier["starter"] == "90"
        assert calls_by_tier["growth"] == "365"

    async def test_sums_deleted_rows_across_tiers_and_tables(self):
        pool, conn = _mock_pool(execute_return="DELETE 3")

        result = await run_retention_cleanup(pool)

        # 2 tiers (starter, growth) x 2 tables (incidents, audit_events),
        # 3 rows each = 6 per table.
        assert result["incidents"] == 6
        assert result["audit_events"] == 6

    async def test_zero_deletions_returns_zero_counts_not_error(self):
        pool, conn = _mock_pool(execute_return="DELETE 0")

        result = await run_retention_cleanup(pool)

        assert result == {"incidents": 0, "audit_events": 0}
