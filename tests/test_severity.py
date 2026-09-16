"""
tests/test_severity.py
Tests for core/severity.py -- severity normalization built for migration
042 (GAPS.md 24-gap closure Phase 1). See that module's own docstring for
which agents have a real severity-shaped signal vs. none.
"""

import pytest

from core.severity import SEVERITY_SORT_RANK, normalize_severity, severity_from_counts


class TestNormalizeSeverity:
    @pytest.mark.parametrize("raw,expected", [
        ("critical", "critical"),
        ("HIGH", "high"),
        ("Medium", "medium"),
        ("low", "low"),
    ])
    def test_already_canonical_values_pass_through_case_insensitively(self, raw, expected):
        assert normalize_severity(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("Sev0", "critical"),
        ("sev0", "critical"),
        ("Sev1", "high"),
        ("Sev2", "medium"),
        ("Sev3", "low"),
        ("Sev4", "low"),
    ])
    def test_azure_monitor_severity_mapped(self, raw, expected):
        assert normalize_severity(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("ALARM", "high"),
        ("alarm", "high"),
        ("OK", "low"),
        ("INSUFFICIENT_DATA", "low"),
    ])
    def test_aws_cloudwatch_alarm_state_mapped(self, raw, expected):
        assert normalize_severity(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "unknown", "totally-unrecognized"])
    def test_missing_or_unrecognized_defaults_to_medium(self, raw):
        assert normalize_severity(raw) == "medium"


class TestSeverityFromCounts:
    def test_any_critical_makes_it_critical(self):
        assert severity_from_counts(critical_count=1, high_count=5) == "critical"

    def test_high_with_no_critical_makes_it_high(self):
        assert severity_from_counts(critical_count=0, high_count=1) == "high"

    def test_zero_critical_and_high_defaults_to_medium(self):
        assert severity_from_counts(critical_count=0, high_count=0) == "medium"


class TestSeveritySortRank:
    def test_rank_orders_critical_first(self):
        ranked = sorted(["low", "critical", "medium", "high"], key=lambda s: SEVERITY_SORT_RANK[s])
        assert ranked == ["critical", "high", "medium", "low"]
