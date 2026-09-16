"""
Coverage for agents/marketing/mkt_10_compliance_guard.py. No prior test
file existed for this agent -- added alongside the 2026-09-15 change that
removed "link in comments" from PLATFORM_PROHIBITED_PHRASES["linkedin"]
(it's now Kelvin's mandatory CTA closing line on every Pillar 4/Product
Launch post, enforced by mkt_li1_linkedin_brand.py's _apply_closing_line
-- this guard flagging/redacting it would silently break that directive).
"""
from unittest.mock import patch

from agents.marketing.mkt_10_compliance_guard import run_compliance_guard


def _run(content: str, platform: str = "linkedin"):
    with patch("agents.marketing.mkt_10_compliance_guard.write_audit_log"):
        return run_compliance_guard(content, platform=platform, product_id="marketing")


def test_link_in_the_comments_is_not_flagged_or_redacted():
    result = _run("Great post.\n\nLink in the comments.")
    assert result["passed"] is True
    assert result["flags"] == []
    assert result["revised_content"] is None


def test_link_in_comments_without_the_is_also_not_flagged():
    # Confirms this isn't just dodging the filter via the word "the" --
    # the phrase itself was removed from the banned list, not reworded around.
    result = _run("Great post.\n\nlink in comments below")
    assert result["passed"] is True
    assert result["flags"] == []


def test_other_platform_prohibited_phrases_still_flagged_on_linkedin():
    result = _run("Nice update! Tag a friend who needs to see this.")
    assert result["passed"] is False
    assert any("tag a friend" in f for f in result["flags"])


def test_financial_claim_phrase_still_flagged_and_redacted():
    result = _run("This is a guaranteed return on your investment.")
    assert result["passed"] is False
    assert result["revised_content"] is not None
    assert "guaranteed return" not in result["revised_content"].lower()


def test_clean_post_passes_with_no_revision():
    result = _run("A real technical post with no banned phrases in it at all.")
    assert result["passed"] is True
    assert result["revised_content"] is None
