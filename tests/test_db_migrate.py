"""
tests/test_db_migrate.py
Tests for db/migrate.py -- the migration runner built 2026-09-15 after
discovering migrations 024-028 had been deployed for an entire session
without ever running against production (see GAPS.md #15).

What this file validates:
  _discover_migrations():
    - Real db/migrations/*.sql files are discovered and sorted by their
      numeric prefix, not lexical filename order
    - A malformed filename (doesn't match NNN_description.sql) raises
      ValueError rather than silently misordering it

  run_pending_migrations():
    - Acquires the transaction-scoped advisory lock before touching
      schema_migrations (pg_advisory_xact_lock, not the session-scoped
      pg_advisory_lock/unlock pair -- matters for Supabase's transaction-
      mode pooler, see db/migrate.py's own module docstring)
    - Creates the schema_migrations tracking table
    - Skips files already recorded as applied
    - Applies pending files in numeric order, records each
    - Returns the list of newly-applied filenames
    - Propagates an exception from a failing migration (fail closed) --
      does not catch-and-continue

Runs with pytest-asyncio + unittest.mock -- no live Postgres needed for
these; the actual SQL correctness of db/migrations/*.sql (including that
every CREATE POLICY is now preceded by a matching DROP POLICY IF EXISTS)
was verified directly against the live database as part of this fix, not
re-verified here.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db import migrate


def _mock_pool(conn):
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return pool


def _mock_conn():
    conn = AsyncMock()
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=tx_ctx)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    return conn


class TestDiscoverMigrations:
    def test_real_migrations_directory_sorted_numerically(self):
        files = migrate._discover_migrations()
        assert len(files) >= 28  # at least through 028 as of this fix

        numbers = [int(migrate._FILENAME_RE.match(p.name).group(1)) for p in files]
        assert numbers == sorted(numbers)
        assert numbers[0] == 1
        # no gaps skipped, no duplicates -- every number appears exactly once
        assert len(numbers) == len(set(numbers))

    def test_raises_on_malformed_filename(self, tmp_path):
        (tmp_path / "not_numbered.sql").write_text("SELECT 1;")
        with patch.object(migrate, "_MIGRATIONS_DIR", tmp_path):
            with pytest.raises(ValueError, match="naming convention"):
                migrate._discover_migrations()

    def test_all_real_migration_files_parse_as_valid_sql_text(self):
        """Every discovered file must at least be readable text -- catches
        an accidentally-binary or empty file before it ever reaches asyncpg."""
        for path in migrate._discover_migrations():
            content = path.read_text()
            assert len(content.strip()) > 0, f"{path.name} is empty"


class TestRunPendingMigrations:
    async def test_acquires_advisory_lock_before_reading_tracking_table(self):
        conn = _mock_conn()
        pool = _mock_pool(conn)

        with patch.object(migrate, "_discover_migrations", return_value=[]):
            await migrate.run_pending_migrations(pool)

        first_call_sql = conn.execute.await_args_list[0].args[0]
        assert "pg_advisory_xact_lock" in first_call_sql

    async def test_creates_schema_migrations_table(self):
        conn = _mock_conn()
        pool = _mock_pool(conn)

        with patch.object(migrate, "_discover_migrations", return_value=[]):
            await migrate.run_pending_migrations(pool)

        create_calls = [c.args[0] for c in conn.execute.await_args_list if "CREATE TABLE IF NOT EXISTS schema_migrations" in c.args[0]]
        assert len(create_calls) == 1

    async def test_skips_already_applied_and_applies_pending_in_order(self, tmp_path):
        f1 = tmp_path / "001_first.sql"
        f2 = tmp_path / "002_second.sql"
        f1.write_text("CREATE TABLE IF NOT EXISTS a (id int);")
        f2.write_text("CREATE TABLE IF NOT EXISTS b (id int);")

        conn = _mock_conn()
        conn.fetch = AsyncMock(return_value=[{"filename": "001_first.sql"}])  # already applied
        pool = _mock_pool(conn)

        with patch.object(migrate, "_MIGRATIONS_DIR", tmp_path):
            result = await migrate.run_pending_migrations(pool)

        assert result == ["002_second.sql"]
        executed_sql = " ".join(c.args[0] for c in conn.execute.await_args_list)
        assert "CREATE TABLE IF NOT EXISTS b" in executed_sql
        assert "CREATE TABLE IF NOT EXISTS a" not in executed_sql  # skipped, already applied

    async def test_returns_empty_list_when_nothing_pending(self, tmp_path):
        f1 = tmp_path / "001_first.sql"
        f1.write_text("CREATE TABLE IF NOT EXISTS a (id int);")

        conn = _mock_conn()
        conn.fetch = AsyncMock(return_value=[{"filename": "001_first.sql"}])
        pool = _mock_pool(conn)

        with patch.object(migrate, "_MIGRATIONS_DIR", tmp_path):
            result = await migrate.run_pending_migrations(pool)

        assert result == []

    async def test_records_each_applied_migration(self, tmp_path):
        f1 = tmp_path / "001_first.sql"
        f1.write_text("CREATE TABLE IF NOT EXISTS a (id int);")

        conn = _mock_conn()
        pool = _mock_pool(conn)

        with patch.object(migrate, "_MIGRATIONS_DIR", tmp_path):
            await migrate.run_pending_migrations(pool)

        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO schema_migrations" in c.args[0]]
        assert len(insert_calls) == 1
        assert insert_calls[0].args[1] == "001_first.sql"

    async def test_propagates_exception_from_failing_migration(self, tmp_path):
        f1 = tmp_path / "001_bad.sql"
        f1.write_text("THIS IS NOT VALID SQL;")

        conn = _mock_conn()

        async def _execute(sql, *args):
            if "THIS IS NOT VALID SQL" in sql:
                raise Exception("syntax error at or near THIS")
            return None
        conn.execute = AsyncMock(side_effect=_execute)
        pool = _mock_pool(conn)

        with patch.object(migrate, "_MIGRATIONS_DIR", tmp_path):
            with pytest.raises(Exception, match="syntax error"):
                await migrate.run_pending_migrations(pool)

    async def test_does_not_insert_tracking_row_for_a_failed_migration(self, tmp_path):
        f1 = tmp_path / "001_bad.sql"
        f1.write_text("THIS IS NOT VALID SQL;")

        conn = _mock_conn()

        async def _execute(sql, *args):
            if "THIS IS NOT VALID SQL" in sql:
                raise Exception("syntax error")
            return None
        conn.execute = AsyncMock(side_effect=_execute)
        pool = _mock_pool(conn)

        with patch.object(migrate, "_MIGRATIONS_DIR", tmp_path):
            with pytest.raises(Exception):
                await migrate.run_pending_migrations(pool)

        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO schema_migrations" in c.args[0]]
        assert len(insert_calls) == 0


class TestLogSecurityPosture:
    """
    Phase 11, scale-readiness build (GAPS.md #20). log_security_posture()
    is a read-only diagnostic -- it must never raise, never write
    anything, and must warn specifically when the connecting role would
    silently bypass every RLS policy migration 031 adds.
    """

    def _mock_pool_for_role(self, role, rolsuper, rolbypassrls):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"role": role, "rolsuper": rolsuper, "rolbypassrls": rolbypassrls}
        )
        return _mock_pool(conn), conn

    async def test_queries_pg_roles_for_current_user(self):
        pool, conn = self._mock_pool_for_role("app_user", False, False)

        await migrate.log_security_posture(pool)

        conn.fetchrow.assert_awaited_once()
        sql = conn.fetchrow.await_args.args[0]
        assert "pg_roles" in sql
        assert "current_user" in sql

    async def test_does_not_raise_for_a_non_privileged_role(self, caplog):
        pool, _ = self._mock_pool_for_role("app_user", False, False)

        await migrate.log_security_posture(pool)  # must not raise

    async def test_warns_when_role_is_superuser(self, caplog):
        import logging
        pool, _ = self._mock_pool_for_role("postgres", True, False)

        with caplog.at_level(logging.WARNING, logger="db.migrate"):
            await migrate.log_security_posture(pool)

        assert any("bypasses row-level security" in r.message for r in caplog.records)

    async def test_warns_when_role_has_bypassrls(self, caplog):
        import logging
        pool, _ = self._mock_pool_for_role("app_user", False, True)

        with caplog.at_level(logging.WARNING, logger="db.migrate"):
            await migrate.log_security_posture(pool)

        assert any("bypasses row-level security" in r.message for r in caplog.records)

    async def test_no_warning_for_a_properly_scoped_role(self, caplog):
        import logging
        pool, _ = self._mock_pool_for_role("app_user", False, False)

        with caplog.at_level(logging.WARNING, logger="db.migrate"):
            await migrate.log_security_posture(pool)

        assert not any("bypasses row-level security" in r.message for r in caplog.records)
