"""
tests/test_sop_agent.py
Tests for agents/internal/sop_agent.py — SOPAgent

What this file validates:
  - generate() renders every template section from an agent_run dict
  - missing optional fields fall back to "Not recorded."
  - agent_name / task_summary are required — missing either raises
  - hitl_decisions renders as a bullet list when it's a list, or verbatim
    when it's a string
  - run() calls obsidian.vault_sync.push_sop with the rendered content and
    returns its result
"""

from unittest.mock import patch

import pytest

from agents.internal.sop_agent import SOPAgent


FULL_AGENT_RUN = {
    "agent_name": "research_agent",
    "task_summary": "freight invoice reconciliation research",
    "completed_at": "2026-07-07 09:00:00 UTC",
    "version": "v1.2.0",
    "product_id": "freight_audit",
    "what_was_done": "Scraped Reddit and synthesized a viability report.",
    "why_it_was_done": "Kelvin requested niche validation before building.",
    "input_received": '{"niche": "freight invoice reconciliation"}',
    "output_produced": "research JSON with viability_score=78",
    "hitl_decisions": ["approve_to_build selected by Kelvin"],
    "outcome": "Approved — added to Week 4 build queue.",
    "if_this_fails_next_time": "Check ENABLE_LIVE_SCRAPING is set before assuming empty signal.",
}


@pytest.fixture
def agent() -> SOPAgent:
    return SOPAgent()


class TestGenerate:
    def test_all_sections_populated(self, agent):
        md = agent.generate(FULL_AGENT_RUN)

        assert "# SOP: research_agent — freight invoice reconciliation research" in md
        assert "Date: 2026-07-07 09:00:00 UTC" in md
        assert "Agent version: v1.2.0" in md
        assert "Product: freight_audit" in md
        assert "Scraped Reddit and synthesized a viability report." in md
        assert "Kelvin requested niche validation before building." in md
        assert "viability_score=78" in md
        assert "- approve_to_build selected by Kelvin" in md
        assert "Approved — added to Week 4 build queue." in md
        assert "Check ENABLE_LIVE_SCRAPING" in md

    def test_missing_optional_fields_default_to_not_recorded(self, agent):
        minimal = {"agent_name": "research_agent", "task_summary": "quick test"}
        md = agent.generate(minimal)

        assert "Not recorded." in md
        assert "Product: internal" in md
        assert "Agent version: v1.0.0" in md

    def test_missing_agent_name_raises(self, agent):
        with pytest.raises(ValueError):
            agent.generate({"task_summary": "quick test"})

    def test_missing_task_summary_raises(self, agent):
        with pytest.raises(ValueError):
            agent.generate({"agent_name": "research_agent"})

    def test_string_hitl_decisions_rendered_verbatim(self, agent):
        run = dict(FULL_AGENT_RUN)
        run["hitl_decisions"] = "held for manual review"
        md = agent.generate(run)
        assert "held for manual review" in md

    def test_empty_hitl_decisions_list_defaults_to_not_recorded(self, agent):
        run = dict(FULL_AGENT_RUN)
        run["hitl_decisions"] = []
        md = agent.generate(run)
        assert "## Decisions made (HITL approvals)\nNot recorded." in md


class TestRun:
    def test_run_pushes_generated_content_to_vault(self, agent):
        with patch("agents.internal.sop_agent.push_sop", return_value="/vault/path.md") as mock_push:
            result = agent.run(FULL_AGENT_RUN)

        assert result == "/vault/path.md"
        mock_push.assert_called_once()
        _, kwargs = mock_push.call_args
        assert kwargs["agent_name"] == "research_agent"
        assert kwargs["task_summary"] == "freight invoice reconciliation research"
        assert "# SOP: research_agent" in kwargs["content"]
