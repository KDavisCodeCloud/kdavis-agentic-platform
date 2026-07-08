"""
tests/test_gap_detector_agent.py
Stub coverage for agents/internal/gap_detector_agent.py.

What this file validates:
  - detect_low_confidence_pattern() only flags an agent once it crosses
    min_occurrences, not on a single low-confidence run
  - detect_repeated_corrections() flags a (agent, from, to) correction
    pattern that repeats past the threshold
  - detect_claude_fallback_gap() groups fallback chat queries by topic
    and flags recurring ones
  - detect_roster_coverage_gap() flags reference agents with no active
    roster entry
  - GapRecommendation.options always ends with "hold"
  - append_to_gaps_md() creates the file with its header if missing and
    appends a dated section
"""

from datetime import date
from pathlib import Path

from agents.internal.gap_detector_agent import (
    AgentRosterEntry,
    AgentRunRecord,
    ChatQuery,
    GapDetectorAgent,
    HITLCorrection,
    detect_claude_fallback_gap,
    detect_low_confidence_pattern,
    detect_repeated_corrections,
    detect_roster_coverage_gap,
)


def test_low_confidence_pattern_requires_min_occurrences():
    runs = [AgentRunRecord("x_agent", "p1", "failed", 0.4, date(2026, 7, 1))]
    assert detect_low_confidence_pattern(runs, min_occurrences=3) == []

    runs = [AgentRunRecord("x_agent", "p1", "failed", 0.4, date(2026, 7, 1)) for _ in range(3)]
    recs = detect_low_confidence_pattern(runs, min_occurrences=3)
    assert len(recs) == 1
    assert "x_agent" in recs[0].gap_description


def test_repeated_corrections_flags_pattern():
    corrections = [HITLCorrection("y_agent", "a", "b", date(2026, 7, 1)) for _ in range(4)]
    recs = detect_repeated_corrections(corrections, min_occurrences=3)
    assert len(recs) == 1
    assert recs[0].suggested_agent_name == "y_agent_prompt_revision"


def test_claude_fallback_gap_groups_by_topic():
    queries = [ChatQuery("pricing question about tiers", True, date(2026, 7, 1)) for _ in range(5)]
    recs = detect_claude_fallback_gap(queries, min_occurrences=5)
    assert len(recs) == 1


def test_roster_coverage_gap_flags_missing_agents():
    roster = [AgentRosterEntry("research_agent", "active")]
    recs = detect_roster_coverage_gap(roster, reference=["research_agent", "content_agent"])
    assert len(recs) == 1
    assert recs[0].suggested_agent_name == "content_agent"


def test_recommendation_options_always_include_hold():
    roster = []
    recs = detect_roster_coverage_gap(roster, reference=["content_agent"])
    assert "hold" in recs[0].options


def test_weekly_scan_ranks_by_confidence_desc():
    agent = GapDetectorAgent()
    recs = agent.weekly_scan(runs=[], corrections=[], chat_queries=[], roster=[])
    confidences = [r.confidence for r in recs]
    assert confidences == sorted(confidences, reverse=True)


def test_append_to_gaps_md_creates_file_with_header(tmp_path):
    agent = GapDetectorAgent()
    path = tmp_path / "GAPS.md"
    roster = [AgentRosterEntry("research_agent", "active")]
    recs = detect_roster_coverage_gap(roster, reference=["content_agent"])

    written_path = agent.append_to_gaps_md(recs, path=path)

    content = Path(written_path).read_text()
    assert "gap_detector_agent writes here" in content
    assert "content_agent" in content
