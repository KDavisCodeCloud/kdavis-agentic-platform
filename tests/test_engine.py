"""
tests/test_engine.py
Tests for core/engine.py — the generic LangGraph engine every agent builds on.

What this file validates:
  - Happy path: high confidence + valid output + no blocklisted tool calls
    runs straight through to completion, no HITL pause
  - Low confidence routes to the HITL gate, pauses the graph, and creates
    an incident via core/hitl.py's HITLGate
  - A blocklisted tool call forces HITL even at high confidence
  - Sanitize actually redacts PII in raw_input before execute_fn sees it
  - resume() continues a paused run through to completion
  - emit_audit / emit_sop failures are non-fatal — the run still returns
"""

import sys

from unittest.mock import MagicMock

import pytest

# tests/conftest.py unconditionally overwrites langgraph.graph.StateGraph /
# START / END and langgraph.types.interrupt / Command with MagicMocks — it
# was written for a "langgraph not installed" CI environment where those
# stubs are the only option. When the real package *is* installed (required
# to exercise core/engine.py's actual graph behavior, in particular real
# interrupt()/Command(resume=...) pause-resume semantics, rather than a mock),
# that clobbering must be undone before core.engine binds its
# `from langgraph... import ...` names.
#
# importlib.reload() is NOT enough here: LangGraph's Pregel loop does
# `isinstance(self.input, Command)` internally, and reload() re-executes
# langgraph/types.py's source into the *same* module object without
# necessarily giving identical class objects everywhere that module has
# already been imported from — so a reloaded Command can end up failing that
# isinstance check against the Command used elsewhere in the dependency
# graph, breaking resume() specifically (run() alone doesn't hit this path).
# Purging every langgraph*/langchain_core* entry from sys.modules and letting
# Python re-import the whole chain fresh avoids the split-identity problem.
if isinstance(sys.modules.get("langgraph.graph").StateGraph, MagicMock):
    for _name in list(sys.modules):
        if _name == "langgraph" or _name.startswith("langgraph.") \
                or _name == "langchain_core" or _name.startswith("langchain_core."):
            del sys.modules[_name]

from core.engine import DEFAULT_CONFIDENCE_THRESHOLD, Engine

WORKSPACE_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def _fake_sop_client_factory(recorder=None):
    """Fake Supabase-shaped client: .table(name).insert(row).execute()."""
    client = MagicMock()
    table = MagicMock()
    insert = MagicMock()
    execute = MagicMock(return_value=MagicMock(data=[{"id": "sop-1"}]))
    if recorder is not None:
        def _insert(row):
            recorder.append(row)
            return insert
        table.insert.side_effect = _insert
    else:
        table.insert.return_value = insert
    insert.execute = execute
    client.table.return_value = table
    return lambda: client


async def _confident_execute_fn(sanitized_input: dict) -> dict:
    return {
        "output": {"result": "ok"},
        "confidence": 0.95,
        "tool_calls": ["read_data"],
        "tokens_used": 42,
    }


async def _low_confidence_execute_fn(sanitized_input: dict) -> dict:
    return {
        "output": {"result": "uncertain"},
        "confidence": 0.4,
        "tool_calls": [],
        "tokens_used": 10,
    }


async def _blocklisted_execute_fn(sanitized_input: dict) -> dict:
    return {
        "output": {"result": "would delete something"},
        "confidence": 0.99,
        "tool_calls": ["delete_workspace"],
        "tokens_used": 5,
    }


@pytest.fixture
def audit_log():
    return MagicMock()


class TestHappyPath:
    async def test_high_confidence_completes_without_hitl(self, mock_db, audit_log):
        engine = Engine(
            agent_name="test_agent",
            execute_fn=_confident_execute_fn,
            db_conn=mock_db,
            audit_log=audit_log,
            sop_client_factory=_fake_sop_client_factory(),
        )

        result = await engine.run({"query": "hello"}, workspace_id=WORKSPACE_ID)

        assert result["hitl_required"] is False
        assert result["assertion_passed"] is True
        assert result["output"] == {"result": "ok"}
        assert result.get("incident_id") is None
        assert result["sop_written"] is True

    async def test_emit_audit_called_on_completion(self, mock_db, audit_log):
        engine = Engine(
            agent_name="test_agent",
            execute_fn=_confident_execute_fn,
            db_conn=mock_db,
            audit_log=audit_log,
            sop_client_factory=_fake_sop_client_factory(),
        )

        await engine.run({"query": "hello"}, workspace_id=WORKSPACE_ID, product_id="mse", tenant_id="tenant-1")

        audit_log.append.assert_called_once()
        _, kwargs = audit_log.append.call_args
        assert kwargs["outcome"] == "ok"
        assert kwargs["product_id"] == "mse"
        assert kwargs["tenant_id"] == "tenant-1"


class TestHitlGate:
    async def test_low_confidence_pauses_and_creates_incident(self, mock_db, audit_log):
        engine = Engine(
            agent_name="test_agent",
            execute_fn=_low_confidence_execute_fn,
            db_conn=mock_db,
            audit_log=audit_log,
            sop_client_factory=_fake_sop_client_factory(),
            confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
        )

        result = await engine.run({"query": "hello"}, workspace_id=WORKSPACE_ID)

        assert result["hitl_required"] is True
        assert result["incident_id"] is not None
        assert "confidence" in result["hitl_reason"]
        mock_db.fetchrow.assert_awaited()

    async def test_blocklisted_tool_call_forces_hitl_despite_high_confidence(self, mock_db, audit_log):
        engine = Engine(
            agent_name="test_agent",
            execute_fn=_blocklisted_execute_fn,
            db_conn=mock_db,
            audit_log=audit_log,
            sop_client_factory=_fake_sop_client_factory(),
        )

        result = await engine.run({"query": "hello"}, workspace_id=WORKSPACE_ID)

        assert result["hitl_required"] is True
        assert "delete_workspace" in result["hitl_reason"]

    async def test_resume_completes_after_hitl_approval(self, mock_db, audit_log):
        engine = Engine(
            agent_name="test_agent",
            execute_fn=_low_confidence_execute_fn,
            db_conn=mock_db,
            audit_log=audit_log,
            sop_client_factory=_fake_sop_client_factory(),
        )

        paused = await engine.run({"query": "hello"}, workspace_id=WORKSPACE_ID)
        assert paused["hitl_required"] is True

        resumed = await engine.resume(
            paused["thread_id"],
            selected_option={"id": "approve", "title": "Approve output"},
        )

        assert resumed["selected_option"]["id"] == "approve"
        assert resumed["sop_written"] is True


class TestSanitize:
    async def test_pii_redacted_before_execute_fn_sees_it(self, mock_db, audit_log):
        seen_inputs = []

        async def _capturing_execute_fn(sanitized_input: dict) -> dict:
            seen_inputs.append(sanitized_input)
            return {"output": {"ok": True}, "confidence": 0.95, "tool_calls": [], "tokens_used": 1}

        engine = Engine(
            agent_name="test_agent",
            execute_fn=_capturing_execute_fn,
            db_conn=mock_db,
            audit_log=audit_log,
            sop_client_factory=_fake_sop_client_factory(),
        )

        result = await engine.run(
            {"note": "contact john.doe@example.com for details"},
            workspace_id=WORKSPACE_ID,
        )

        assert "john.doe@example.com" not in seen_inputs[0]["note"]
        assert "[REDACTED_EMAIL]" in seen_inputs[0]["note"]
        assert len(result["redaction_log"]) == 1


class TestNonFatalSideEffects:
    async def test_emit_sop_failure_does_not_fail_run(self, mock_db, audit_log):
        def _broken_sop_client():
            raise RuntimeError("supabase unreachable")

        engine = Engine(
            agent_name="test_agent",
            execute_fn=_confident_execute_fn,
            db_conn=mock_db,
            audit_log=audit_log,
            sop_client_factory=_broken_sop_client,
        )

        result = await engine.run({"query": "hello"}, workspace_id=WORKSPACE_ID)

        assert result["sop_written"] is False
        assert result["output"] == {"result": "ok"}

    async def test_emit_audit_failure_does_not_fail_run(self, mock_db):
        broken_audit_log = MagicMock()
        broken_audit_log.append.side_effect = RuntimeError("audit sink down")

        engine = Engine(
            agent_name="test_agent",
            execute_fn=_confident_execute_fn,
            db_conn=mock_db,
            audit_log=broken_audit_log,
            sop_client_factory=_fake_sop_client_factory(),
        )

        result = await engine.run({"query": "hello"}, workspace_id=WORKSPACE_ID)

        assert result["output"] == {"result": "ok"}


class TestInvalidInput:
    async def test_empty_input_short_circuits_to_hitl(self, mock_db, audit_log):
        engine = Engine(
            agent_name="test_agent",
            execute_fn=_confident_execute_fn,
            db_conn=mock_db,
            audit_log=audit_log,
            sop_client_factory=_fake_sop_client_factory(),
        )

        result = await engine.run({}, workspace_id=WORKSPACE_ID)

        assert result["input_valid"] is False
        assert result["confidence"] == 0.0
        assert result["hitl_required"] is True
