"""
tests/test_core_audit.py
Tests for core/audit.py — GAPS.md #28: the real audit_events DB writer.

Not to be confused with tests/test_audit.py (api/routes/audit.py's cloud
audit *findings* submission feature) or tests/test_audit_log.py
(security/audit_log.py's AuditLog, a completely separate table --
`audit_log`, Supabase REST client, product_id/tenant_id-keyed -- used by
the internal platform's own MSE/marketing agents, not Cloud Decoded
customer workspaces). core/audit.py writes to `audit_events`
(asyncpg, workspace_id/incident_id/agent_id-keyed), the table
core/hitl.py and every agents/agent_0N_*/workflow.py's markdown-only
audit writers never actually wrote to before this.

What this file validates:
  - write_audit_event: happy path INSERT shape, no-DATABASE_URL and
    connection-failure and INSERT-failure all swallowed (never raises),
    the connection is always closed even on failure (finally).
  - The "unknown" workspace_id fallback: core/hitl.py's own
    bump_occurrence/mark_executed/mark_failed call sites pass the
    literal string "unknown" as workspace_id (a pre-existing gap in
    hitl.py itself) -- write_audit_event must resolve the real
    workspace_id from the incidents table via incident_id rather than
    silently dropping the write, since mark_executed is the completion
    event for every successful remediation across every agent.
  - schedule_audit_event: a no-running-loop synchronous caller (the
    normal case for both core/hitl.py and agents/base_agent.py, which
    are plain `def` methods) never raises and never even constructs the
    write_audit_event() coroutine (no 'coroutine was never awaited'
    warning); a real running loop does get a real task scheduled.
"""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from core.audit import _looks_like_uuid, schedule_audit_event, write_audit_event


def _mock_conn(fetchrow_return=None, execute_side_effect=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    if execute_side_effect is not None:
        conn.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    return conn


class TestLooksLikeUuid:
    def test_real_uuid_string_is_valid(self):
        assert _looks_like_uuid(str(uuid4())) is True

    def test_unknown_sentinel_is_invalid(self):
        assert _looks_like_uuid("unknown") is False

    def test_none_is_invalid(self):
        assert _looks_like_uuid(None) is False

    def test_empty_string_is_invalid(self):
        assert _looks_like_uuid("") is False


class TestWriteAuditEventHappyPath:
    async def test_inserts_with_correct_shape(self):
        workspace_id = str(uuid4())
        incident_id = str(uuid4())
        conn = _mock_conn()

        with (
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://u:p@host/db"}),
            patch("core.audit.asyncpg.connect", AsyncMock(return_value=conn)),
        ):
            await write_audit_event(
                workspace_id=workspace_id,
                action="hitl_approved",
                status="executing",
                incident_id=incident_id,
                agent_id="agent_01_cicd_triage",
                tokens_used=42,
                metadata={"selected_option_id": "opt_1"},
            )

        conn.execute.assert_awaited_once()
        args = conn.execute.await_args.args
        assert "INSERT INTO audit_events" in args[0]
        assert str(args[1]) == workspace_id
        assert args[2] == "agent_01_cicd_triage"
        assert str(args[3]) == incident_id
        assert args[4] == "hitl_approved"
        assert args[5] == "executing"
        assert args[6] == 42
        assert json.loads(args[7]) == {"selected_option_id": "opt_1"}
        conn.close.assert_awaited_once()

    async def test_no_metadata_passes_null(self):
        conn = _mock_conn()
        with (
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://u:p@host/db"}),
            patch("core.audit.asyncpg.connect", AsyncMock(return_value=conn)),
        ):
            await write_audit_event(workspace_id=str(uuid4()), action="incident_created")

        args = conn.execute.await_args.args
        assert args[7] is None


class TestWriteAuditEventUnknownWorkspaceFallback:
    """core/hitl.py's bump_occurrence/mark_executed/mark_failed pass the
    literal "unknown" for workspace_id -- write_audit_event must resolve
    the real workspace via incidents.workspace_id rather than drop the
    write silently."""

    async def test_resolves_workspace_id_from_incidents_table(self):
        incident_id = str(uuid4())
        real_workspace_id = uuid4()
        conn = _mock_conn(fetchrow_return={"workspace_id": real_workspace_id})

        with (
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://u:p@host/db"}),
            patch("core.audit.asyncpg.connect", AsyncMock(return_value=conn)),
        ):
            await write_audit_event(
                workspace_id="unknown",
                action="executed",
                incident_id=incident_id,
            )

        conn.fetchrow.assert_awaited_once()
        conn.execute.assert_awaited_once()
        args = conn.execute.await_args.args
        assert args[1] == real_workspace_id

    async def test_unresolvable_workspace_skips_write_without_raising(self):
        # "unknown" workspace_id, no incident_id at all -- nothing to
        # resolve against. Must not raise, must not insert.
        conn = _mock_conn(fetchrow_return=None)

        with (
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://u:p@host/db"}),
            patch("core.audit.asyncpg.connect", AsyncMock(return_value=conn)),
        ):
            await write_audit_event(workspace_id="unknown", action="deduplicated")

        conn.execute.assert_not_awaited()
        conn.close.assert_awaited_once()

    async def test_incident_not_found_skips_write_without_raising(self):
        conn = _mock_conn(fetchrow_return=None)  # incident lookup finds nothing

        with (
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://u:p@host/db"}),
            patch("core.audit.asyncpg.connect", AsyncMock(return_value=conn)),
        ):
            await write_audit_event(workspace_id="unknown", action="failed:timeout", incident_id=str(uuid4()))

        conn.execute.assert_not_awaited()


class TestWriteAuditEventNeverRaises:
    async def test_missing_database_url_returns_quietly(self):
        with patch.dict("os.environ", {}, clear=True):
            await write_audit_event(workspace_id=str(uuid4()), action="ingest")
        # No exception raised -- that's the assertion.

    async def test_connection_failure_is_swallowed(self):
        with (
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://u:p@host/db"}),
            patch("core.audit.asyncpg.connect", AsyncMock(side_effect=OSError("connection refused"))),
        ):
            await write_audit_event(workspace_id=str(uuid4()), action="ingest")

    async def test_insert_failure_is_swallowed_and_connection_still_closed(self):
        conn = _mock_conn(execute_side_effect=RuntimeError("db exploded"))
        with (
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://u:p@host/db"}),
            patch("core.audit.asyncpg.connect", AsyncMock(return_value=conn)),
        ):
            await write_audit_event(workspace_id=str(uuid4()), action="ingest")

        conn.close.assert_awaited_once()


class TestScheduleAuditEvent:
    def test_no_running_loop_does_not_raise_or_warn(self, recwarn):
        # Plain sync call -- exactly how core/hitl.py and
        # agents/base_agent.py's synchronous methods call this.
        schedule_audit_event(workspace_id=str(uuid4()), action="ingest")
        assert not any("never awaited" in str(w.message) for w in recwarn.list)

    async def test_running_loop_schedules_a_real_task(self):
        with patch("core.audit.write_audit_event", AsyncMock(return_value=None)) as mock_write:
            schedule_audit_event(workspace_id=str(uuid4()), action="ingest", agent_id="agent_01_cicd_triage")
            # Let the scheduled task actually run before asserting.
            import asyncio
            await asyncio.sleep(0)

        mock_write.assert_called_once()
        _, kwargs = mock_write.call_args
        assert kwargs["action"] == "ingest"
        assert kwargs["agent_id"] == "agent_01_cicd_triage"
