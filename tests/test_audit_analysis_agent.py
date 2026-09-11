"""
tests/test_audit_analysis_agent.py
Tests for agents/audit_analysis/workflow.py — Phase 2C's analyze -> rank ->
persist flow. Deliberately plain sequential async code, not a LangGraph
StateGraph (see the module docstring for why) — no _build_graph patching
needed like the agent_01 tests, just call_llm (via the shared mock_router
fixture) and the mock_db fixture from conftest.py.

What this file validates:
  - happy path: LLM output persisted as remediation items, ranked by
    severity then dollar impact, submission marked 'ready'
  - invalid severity/category from the LLM is rejected, not silently stored
  - a malformed (non-JSON) LLM response marks the submission 'failed' with
    a descriptive analysis_error instead of raising out of run()
  - an empty items list from the LLM is treated as a failure, not a no-op
"""

import json
from unittest.mock import patch

from agents.audit_analysis.workflow import AuditAnalysisAgent


def _make_agent(mock_db, mock_router, workspace_id):
    with patch("agents.base_agent._load_router", return_value=mock_router):
        return AuditAnalysisAgent(mock_db, workspace_id)


def _findings():
    return [
        {
            "finding_id": "f1",
            "provider": "aws",
            "category": "SECURITY",
            "severity": "HIGH",
            "service": "IAM",
            "resource_type": "user",
            "resource_id": "USER-REDACTED",
            "title": "No MFA",
            "description": "d",
            "remediation": "r",
            "estimated_monthly_waste_usd": 0.0,
            "detected_at": "2026-09-11T00:00:00Z",
        }
    ]


class TestAnalysisHappyPath:
    async def test_items_persisted_and_ranked(self, mock_db, mock_router, workspace_id):
        mock_router.complete.return_value = json.dumps(
            [
                {
                    "title": "Enable MFA everywhere",
                    "description": "Several users have no MFA.",
                    "remediation": "Enforce MFA org-wide.",
                    "severity": "HIGH",
                    "category": "SECURITY",
                    "estimated_monthly_waste_usd": 0,
                },
                {
                    "title": "Downsize idle EC2",
                    "description": "Stopped instance still billing storage.",
                    "remediation": "Terminate it.",
                    "severity": "MEDIUM",
                    "category": "WASTE",
                    "estimated_monthly_waste_usd": 12.5,
                },
            ]
        )
        agent = _make_agent(mock_db, mock_router, workspace_id)

        result = await agent.run(payload={"submission_id": "sub-1", "findings": _findings()})

        assert result == "sub-1"
        insert_calls = [c for c in mock_db.execute.await_args_list if "INSERT INTO cloud_audit_remediation_items" in c.args[0]]
        assert len(insert_calls) == 2
        # HIGH-severity item ranked first (priority_rank = 1, last bound param)
        assert insert_calls[0].args[-1] == 1
        assert insert_calls[1].args[-1] == 2

        update_calls = [c for c in mock_db.execute.await_args_list if "UPDATE cloud_audit_submissions" in c.args[0]]
        assert any("'ready'" in c.args[0] or "ready" in c.args for c in update_calls)


class TestAnalysisFailures:
    async def test_invalid_severity_marks_submission_failed(self, mock_db, mock_router, workspace_id):
        mock_router.complete.return_value = json.dumps(
            [{"title": "x", "description": "d", "remediation": "r", "severity": "CRITICAL", "category": "WASTE"}]
        )
        agent = _make_agent(mock_db, mock_router, workspace_id)

        result = await agent.run(payload={"submission_id": "sub-2", "findings": _findings()})

        assert result == "sub-2"
        failed_calls = [c for c in mock_db.execute.await_args_list if "status = 'failed'" in c.args[0]]
        assert len(failed_calls) == 1
        assert failed_calls[0].args[1]  # analysis_error is non-empty
        insert_calls = [c for c in mock_db.execute.await_args_list if "INSERT INTO cloud_audit_remediation_items" in c.args[0]]
        assert insert_calls == []

    async def test_malformed_json_marks_submission_failed(self, mock_db, mock_router, workspace_id):
        mock_router.complete.return_value = "not json at all"
        agent = _make_agent(mock_db, mock_router, workspace_id)

        result = await agent.run(payload={"submission_id": "sub-3", "findings": _findings()})

        assert result == "sub-3"
        failed_calls = [c for c in mock_db.execute.await_args_list if "status = 'failed'" in c.args[0]]
        assert len(failed_calls) == 1

    async def test_empty_items_list_treated_as_failure(self, mock_db, mock_router, workspace_id):
        mock_router.complete.return_value = json.dumps([])
        agent = _make_agent(mock_db, mock_router, workspace_id)

        result = await agent.run(payload={"submission_id": "sub-4", "findings": _findings()})

        assert result == "sub-4"
        failed_calls = [c for c in mock_db.execute.await_args_list if "status = 'failed'" in c.args[0]]
        assert len(failed_calls) == 1
