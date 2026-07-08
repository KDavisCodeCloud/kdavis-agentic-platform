"""
tests/test_research_agent.py
Tests for agents/internal/research_agent.py — ResearchAgent

What this file validates:
  - Scraping is skipped (no HTTP calls) unless live scraping is enabled
  - Reddit scraping parses the public search.json response when enabled
  - run() end-to-end: mocked LLM synthesis produces schema-valid research
    JSON plus a correctly-shaped hitl_card
  - validate_research_schema() flags missing top-level/icp/design_brief_vars fields
  - Malformed LLM JSON and empty niche both raise ValueError
  - PII in scraped text is sanitized before reaching the LLM call
"""

import json
from unittest.mock import MagicMock

import pytest

import agents.internal.research_agent as research_agent_module
from agents.internal.research_agent import ResearchAgent, validate_research_schema


VALID_RESEARCH_JSON = {
    "niche": "freight invoice reconciliation",
    "icp": {
        "job_title": "AP Manager",
        "company_size": "50-200 employees",
        "tools_daily": ["Excel", "QuickBooks"],
        "visual_environment": "spreadsheet-heavy back office",
        "emotional_register": "OPERATIONAL",
        "trust_blockers": ["accuracy", "data security"],
        "proof_format": "METRICS",
    },
    "pain_language": ["I spend 10 hours a week matching invoices to BOLs"],
    "top_llm_queries": ["how to automate freight invoice reconciliation"],
    "competitor_gaps": ["no SMB-focused tool under $500/mo"],
    "estimated_build_days": 14,
    "estimated_mrr_range": {"low": 2000, "high": 6000},
    "viability_score": 78,
    "design_brief_vars": {
        "pain_headline_options": ["Stop matching invoices by hand"],
        "roi_number": "10 hrs/week saved",
        "proof_stat_1": "99.2% match accuracy",
        "proof_stat_2": "3x faster close",
        "proof_stat_3": "$4k/mo saved on overpayments",
        "faq_questions": ["Does this work with my TMS?"],
    },
}


@pytest.fixture
def mock_llm_complete():
    return MagicMock(return_value=json.dumps(VALID_RESEARCH_JSON))


@pytest.fixture
def agent(mock_llm_complete):
    return ResearchAgent(llm_complete=mock_llm_complete, http_client=MagicMock())


# ──────────────────────────────────────────────────────────────────────────────
# Scraping — disabled by default
# ──────────────────────────────────────────────────────────────────────────────

class TestScrapingDisabledByDefault:
    def test_reddit_skipped_without_live_scraping(self, agent, monkeypatch):
        monkeypatch.setattr(research_agent_module, "LIVE_SCRAPING_ENABLED", False)
        assert agent._scrape_reddit("freight invoice reconciliation") == []
        agent._http.get.assert_not_called()

    def test_g2_is_a_stub(self, agent):
        assert agent._scrape_g2("freight invoice reconciliation") == []

    def test_linkedin_is_a_stub(self, agent):
        assert agent._scrape_linkedin("freight invoice reconciliation") == []

    def test_quora_is_a_stub(self, agent):
        assert agent._scrape_quora("freight invoice reconciliation") == []


# ──────────────────────────────────────────────────────────────────────────────
# Reddit scraping — enabled
# ──────────────────────────────────────────────────────────────────────────────

class TestRedditScrapingEnabled:
    def test_reddit_parses_search_json(self, agent, monkeypatch):
        monkeypatch.setattr(research_agent_module, "LIVE_SCRAPING_ENABLED", True)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {"data": {"selftext": "I hate reconciling freight invoices by hand"}},
                    {"data": {"selftext": "", "title": "Any tools for BOL matching?"}},
                ]
            }
        }
        agent._http.get.return_value = mock_response

        result = agent._scrape_reddit("freight invoice reconciliation")

        agent._http.get.assert_called_once()
        mock_response.raise_for_status.assert_called_once()
        assert result == [
            "I hate reconciling freight invoices by hand",
            "Any tools for BOL matching?",
        ]

    def test_reddit_query_param_passed(self, agent, monkeypatch):
        monkeypatch.setattr(research_agent_module, "LIVE_SCRAPING_ENABLED", True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"children": []}}
        agent._http.get.return_value = mock_response

        agent._scrape_reddit("freight invoice reconciliation")

        _, kwargs = agent._http.get.call_args
        assert kwargs["params"]["q"] == "freight invoice reconciliation"


# ──────────────────────────────────────────────────────────────────────────────
# run() end-to-end
# ──────────────────────────────────────────────────────────────────────────────

class TestRunEndToEnd:
    def test_run_returns_valid_research_and_hitl_card(self, agent, mock_llm_complete):
        result = agent.run("freight invoice reconciliation")

        assert result["research"] == VALID_RESEARCH_JSON
        assert result["hitl_card"]["status"] == "pending_approval"
        assert result["hitl_card"]["options"] == ["approve_to_build", "kill", "hold"]
        assert result["hitl_card"]["payload"] == VALID_RESEARCH_JSON
        assert "78" in result["hitl_card"]["summary"]

    def test_run_passes_niche_and_hypothesis_to_llm(self, agent, mock_llm_complete):
        agent.run("freight invoice reconciliation", hypothesis="AP teams hate manual matching")

        _, kwargs = mock_llm_complete.call_args
        user_message = kwargs["messages"][0]["content"]
        assert "freight invoice reconciliation" in user_message
        assert "AP teams hate manual matching" in user_message

    def test_run_strips_markdown_fences_from_llm_response(self, agent, mock_llm_complete):
        mock_llm_complete.return_value = f"```json\n{json.dumps(VALID_RESEARCH_JSON)}\n```"
        result = agent.run("freight invoice reconciliation")
        assert result["research"] == VALID_RESEARCH_JSON

    def test_empty_niche_raises(self, agent):
        with pytest.raises(ValueError):
            agent.run("")

    def test_malformed_llm_json_raises(self, agent, mock_llm_complete):
        mock_llm_complete.return_value = "not json at all"
        with pytest.raises(ValueError):
            agent.run("freight invoice reconciliation")

    def test_llm_response_missing_schema_fields_raises(self, agent, mock_llm_complete):
        incomplete = dict(VALID_RESEARCH_JSON)
        del incomplete["viability_score"]
        mock_llm_complete.return_value = json.dumps(incomplete)
        with pytest.raises(ValueError):
            agent.run("freight invoice reconciliation")


# ──────────────────────────────────────────────────────────────────────────────
# PII sanitization before LLM call
# ──────────────────────────────────────────────────────────────────────────────

class TestSanitizationBeforeLLM:
    def test_scraped_pii_is_redacted_before_reaching_llm(self, mock_llm_complete, monkeypatch):
        monkeypatch.setattr(research_agent_module, "LIVE_SCRAPING_ENABLED", True)
        http = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"children": [{"data": {"selftext": "email me at leaker@example.com"}}]}
        }
        http.get.return_value = mock_response
        agent = ResearchAgent(llm_complete=mock_llm_complete, http_client=http)

        agent.run("freight invoice reconciliation")

        _, kwargs = mock_llm_complete.call_args
        user_message = kwargs["messages"][0]["content"]
        assert "leaker@example.com" not in user_message


# ──────────────────────────────────────────────────────────────────────────────
# validate_research_schema()
# ──────────────────────────────────────────────────────────────────────────────

class TestValidateResearchSchema:
    def test_valid_schema_passes(self):
        validate_research_schema(VALID_RESEARCH_JSON)  # should not raise

    def test_missing_top_level_field_raises(self):
        broken = dict(VALID_RESEARCH_JSON)
        del broken["competitor_gaps"]
        with pytest.raises(ValueError, match="competitor_gaps"):
            validate_research_schema(broken)

    def test_missing_icp_field_raises(self):
        broken = json.loads(json.dumps(VALID_RESEARCH_JSON))
        del broken["icp"]["proof_format"]
        with pytest.raises(ValueError, match="proof_format"):
            validate_research_schema(broken)

    def test_missing_design_brief_field_raises(self):
        broken = json.loads(json.dumps(VALID_RESEARCH_JSON))
        del broken["design_brief_vars"]["roi_number"]
        with pytest.raises(ValueError, match="roi_number"):
            validate_research_schema(broken)
