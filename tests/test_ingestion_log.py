"""
tests/test_ingestion_log.py
Tests for core/ingestion_log.py -- Phase 6, scale-readiness build.

FastAPI's BackgroundTasks aren't durable: if the process restarts
between the 202 response and a background task finishing, the task is
lost with no trace (see db/migrations/030_alert_ingestion_log.sql). This
file proves the recovery mechanism actually works:
  - log_alert_received() persists a row before any processing happens
  - mark_alert_processed() marks it done on completion
  - a task that never completes (simulated process death) leaves the row
    recoverable -- find_unprocessed_older_than() finds it
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from core.ingestion_log import (
    find_unprocessed_older_than,
    log_alert_received,
    mark_alert_processed,
)


def _mock_conn():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    return conn


class TestLogAlertReceived:
    async def test_persists_row_and_returns_id(self):
        conn = _mock_conn()
        row_id = uuid4()
        conn.fetchrow.return_value = {"id": row_id}

        log_id = await log_alert_received(conn, str(uuid4()), {"AlarmName": "x"})

        assert log_id == str(row_id)
        conn.fetchrow.assert_awaited_once()
        sql = conn.fetchrow.await_args.args[0]
        assert "INSERT INTO alert_ingestion_log" in sql

    async def test_accepts_raw_bytes_payload(self):
        """Webhook routes pass raw request bytes for some formats --
        confirms bytes get parsed to JSON before storage, not stored as
        an opaque blob."""
        conn = _mock_conn()
        conn.fetchrow.return_value = {"id": uuid4()}

        await log_alert_received(conn, str(uuid4()), b'{"AlarmName": "prod-cpu-high"}')

        payload_arg = conn.fetchrow.await_args.args[2]
        assert "prod-cpu-high" in payload_arg

    async def test_malformed_bytes_payload_does_not_raise(self):
        conn = _mock_conn()
        conn.fetchrow.return_value = {"id": uuid4()}

        # Must not raise -- a malformed payload still needs to be logged
        # as "received" before validation rejects it downstream.
        log_id = await log_alert_received(conn, str(uuid4()), b"not valid json{{{")
        assert log_id is not None


class TestMarkAlertProcessed:
    async def test_updates_processed_at(self):
        conn = _mock_conn()
        log_id = str(uuid4())

        await mark_alert_processed(conn, log_id)

        conn.execute.assert_awaited_once()
        sql, *params = conn.execute.await_args.args
        assert "UPDATE alert_ingestion_log" in sql
        assert "SET processed_at" in sql


class TestFindUnprocessedOlderThan:
    async def test_returns_stale_unprocessed_rows(self):
        conn = _mock_conn()
        stale_row = {
            "id": uuid4(), "workspace_id": uuid4(),
            "raw_payload": {"AlarmName": "x"},
            "received_at": datetime.now(timezone.utc) - timedelta(minutes=10),
        }
        conn.fetch.return_value = [stale_row]

        result = await find_unprocessed_older_than(conn, older_than_minutes=5)

        assert len(result) == 1
        assert result[0]["id"] == stale_row["id"]
        conn.fetch.assert_awaited_once()
        sql = conn.fetch.await_args.args[0]
        assert "processed_at IS NULL" in sql


class TestSimulatedProcessRestartRecovery:
    """The actual requirement this phase exists to satisfy: a background
    task that never completes (simulated process death mid-execution)
    leaves a recoverable row -- not a silently vanished alert."""

    async def test_task_never_completing_leaves_a_recoverable_row(self):
        # A tiny in-memory fake DB that behaves like the real table for
        # exactly the two operations under test: insert (log_alert_received)
        # and the stale-row query (find_unprocessed_older_than). Proves the
        # end-to-end row lifecycle, not just each function in isolation.
        store: dict[str, dict] = {}

        class _FakeConn:
            async def fetchrow(self, sql, *args):
                if "INSERT INTO alert_ingestion_log" in sql:
                    new_id = uuid4()
                    # A real JSONB column round-trips a stored string back
                    # as a parsed dict (register_jsonb_codec, api/main.py) --
                    # mirrored here so this fake behaves like the real thing.
                    store[str(new_id)] = {
                        "id": new_id,
                        "workspace_id": args[0],
                        "raw_payload": json.loads(args[1]),
                        "received_at": datetime.now(timezone.utc) - timedelta(minutes=10),
                        "processed_at": None,
                    }
                    return {"id": new_id}
                raise AssertionError(f"unexpected fetchrow: {sql}")

            async def execute(self, sql, *args):
                if "UPDATE alert_ingestion_log" in sql:
                    row_id = str(args[0])
                    if row_id in store:
                        store[row_id]["processed_at"] = args[1]
                    return
                raise AssertionError(f"unexpected execute: {sql}")

            async def fetch(self, sql, *args):
                cutoff = args[0]
                return [
                    row for row in store.values()
                    if row["processed_at"] is None and row["received_at"] < cutoff
                ]

        conn = _FakeConn()
        workspace_id = str(uuid4())

        # Step 1: webhook route logs "alert received" before returning 202.
        log_id = await log_alert_received(conn, workspace_id, {"AlarmName": "prod-cpu-high"})

        # Step 2: the background task that WOULD process this alert never
        # runs to completion -- simulated process death. mark_alert_processed
        # is deliberately never called here, unlike a normal successful (or
        # even handled-failure) run's `finally` block.

        # Step 3: recovery query on the next process startup finds it.
        recoverable = await find_unprocessed_older_than(conn, older_than_minutes=5)

        assert len(recoverable) == 1
        assert str(recoverable[0]["id"]) == log_id
        assert recoverable[0]["raw_payload"] == {"AlarmName": "prod-cpu-high"}

    async def test_task_completing_normally_is_not_in_the_recovery_set(self):
        """Same scenario, but mark_alert_processed IS called (the normal
        path) -- the row must NOT show up as recoverable."""
        store: dict[str, dict] = {}

        class _FakeConn:
            async def fetchrow(self, sql, *args):
                new_id = uuid4()
                store[str(new_id)] = {
                    "id": new_id, "workspace_id": args[0], "raw_payload": json.loads(args[1]),
                    "received_at": datetime.now(timezone.utc) - timedelta(minutes=10),
                    "processed_at": None,
                }
                return {"id": new_id}

            async def execute(self, sql, *args):
                row_id = str(args[0])
                store[row_id]["processed_at"] = args[1]

            async def fetch(self, sql, *args):
                cutoff = args[0]
                return [
                    row for row in store.values()
                    if row["processed_at"] is None and row["received_at"] < cutoff
                ]

        conn = _FakeConn()
        log_id = await log_alert_received(conn, str(uuid4()), {"AlarmName": "x"})
        await mark_alert_processed(conn, log_id)  # normal completion path

        recoverable = await find_unprocessed_older_than(conn, older_than_minutes=5)

        assert recoverable == []
