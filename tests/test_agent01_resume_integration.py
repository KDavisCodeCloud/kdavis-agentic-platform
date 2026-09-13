"""
tests/test_agent01_resume_integration.py
Real end-to-end regression test for a bug found live in this session:
run()'s LangGraph checkpoint thread_id and the incidents.id row it returns
were two independent random UUIDs. resume(incident_id, ...) always looked
up a checkpoint keyed by an id the graph was never actually invoked with,
so LangGraph silently treated every resume as a fresh __start__ invocation
instead -- raising langgraph.errors.InvalidUpdateError. This had never been
caught because every other test in this suite patches _build_graph out
entirely (see tests/test_agent01_local.py's _make_workflow), so none of
them ever exercised a real compiled graph's interrupt/resume cycle.

Unlike those tests, this one compiles the REAL graph (no _build_graph
patch) against a real in-memory LangGraph checkpointer (MemorySaver --
same interface AsyncPostgresSaver implements, no live DB needed) and
drives run() then resume() through the actual interrupt/Command(resume=...)
mechanics, mocking only the DB conn (for HITLGate/TokenBudgetGuard) and
the LLM router.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from agents.agent_01_cicd_triage.workflow import CICDTriageWorkflow
from tests.mocks.aws_fixtures import MOCK_GITHUB_WEBHOOK_FAILURE

MOCK_LLM_DIAGNOSIS = json.dumps({
    "parsed_error": "The pipeline failed for a real-looking reason.",
    "options": [
        {"id": "opt_1", "title": "Rerun failed jobs", "description": "d", "impact": "low", "docs_url": None},
        {"id": "opt_2", "title": "Full rerun", "description": "d", "impact": "low", "docs_url": None},
        {"id": "custom", "title": "Custom / stay broken", "description": "Hold", "impact": "none", "docs_url": None},
    ],
    "estimated_duration_seconds": 60,
})


def _mock_db():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": uuid4()})
    conn.execute = AsyncMock(return_value=None)
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=tx_ctx)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)
    return conn


def _mock_router():
    # self._router.complete(...) returns a plain string (base_agent.py's
    # call_llm does len(response) on it directly) -- not a response object.
    router = MagicMock()
    router.complete = MagicMock(return_value=MOCK_LLM_DIAGNOSIS)
    return router


class TestRealRunThenResumeRoundtrip:
    async def test_run_uses_the_same_id_for_thread_and_incident(self):
        """The core regression assertion: run()'s returned incident_id must
        be the exact id the DB row was created under (not a different
        random UUID than the LangGraph thread_id)."""
        checkpointer = MemorySaver()
        db = _mock_db()

        with patch("agents.base_agent._load_router", return_value=_mock_router()):
            workflow = CICDTriageWorkflow(db, str(uuid4()), checkpointer)
            with patch.object(workflow.budget, "assert_budget_available", new=AsyncMock()):
                incident_id = await workflow.run(MOCK_GITHUB_WEBHOOK_FAILURE, cloud_provider="github")

        # create_incident's INSERT was called with the pre-generated id as
        # the first bound param (see core/hitl.py's incident_id-provided branch).
        insert_call = next(
            c for c in db.fetchrow.await_args_list
            if "INSERT INTO incidents" in c.args[0]
        )
        bound_id = insert_call.args[1]
        assert str(bound_id) == incident_id

    async def test_resume_on_a_fresh_workflow_instance_does_not_raise(self):
        """The actual bug: resuming from a NEW CICDTriageWorkflow object
        (exactly what api/routes/incidents.py's approve_incident does --
        a fresh instance per request) must find the real checkpoint and
        complete without langgraph.errors.InvalidUpdateError."""
        checkpointer = MemorySaver()
        db = _mock_db()

        with patch("agents.base_agent._load_router", return_value=_mock_router()):
            workflow = CICDTriageWorkflow(db, str(uuid4()), checkpointer)
            with patch.object(workflow.budget, "assert_budget_available", new=AsyncMock()):
                incident_id = await workflow.run(MOCK_GITHUB_WEBHOOK_FAILURE, cloud_provider="github")

            # Fresh instance, same checkpointer -- mirrors incidents.py's
            # approve_incident building a new workflow object per request.
            resumed_workflow = CICDTriageWorkflow(db, str(uuid4()), checkpointer)
            with patch.object(resumed_workflow._tools, "execute_option", new=AsyncMock(return_value={"status": "held"})):
                result = await resumed_workflow.resume(incident_id, {"id": "hold"})

        assert result is not None
