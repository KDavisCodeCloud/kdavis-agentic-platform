"""
tests/test_click_tracking.py
core/click_tracking.py -- link rewriting + signed click tokens.
"""

from unittest.mock import patch

import pytest

from core import click_tracking as ct


@pytest.fixture(autouse=True)
def _secret_env():
    with patch.dict("os.environ", {"CD_UNSUBSCRIBE_SECRET": "test-secret-value"}):
        yield


class TestClickToken:
    def test_round_trips_send_id_and_url(self):
        token = ct.make_click_token("send-123", "https://theclouddecoded.com/pricing")
        assert ct.verify_click_token(token) == ("send-123", "https://theclouddecoded.com/pricing")

    def test_tampered_token_rejected(self):
        token = ct.make_click_token("send-123", "https://theclouddecoded.com/pricing")
        payload, sig = token.split(".", 1)
        assert ct.verify_click_token(f"{payload}.{sig[:-1]}0") is None

    def test_malformed_token_rejected(self):
        assert ct.verify_click_token("garbage") is None

    def test_url_containing_pipe_still_round_trips(self):
        # partition() on the first '|' only -- a destination URL with its
        # own '|' must not truncate.
        url = "https://theclouddecoded.com/x?a=1|2"
        token = ct.make_click_token("send-1", url)
        assert ct.verify_click_token(token) == ("send-1", url)


class TestRewriteLinksHtml:
    def test_rewrites_absolute_http_links(self):
        html = '<a href="https://theclouddecoded.com/pricing">Pricing</a>'
        rewritten = ct.rewrite_links_html(html, "send-1", "https://api.theclouddecoded.com")
        assert "https://api.theclouddecoded.com/api/v1/e/c/" in rewritten
        assert "theclouddecoded.com/pricing" not in rewritten

    def test_leaves_non_http_hrefs_untouched(self):
        html = '<a href="mailto:hello@theclouddecoded.com">Email</a>'
        rewritten = ct.rewrite_links_html(html, "send-1", "https://api.theclouddecoded.com")
        assert rewritten == html


class TestRewriteCtaText:
    def test_rewrites_the_cta_url_only(self):
        text = "Visit https://theclouddecoded.com/pricing today"
        rewritten = ct.rewrite_cta_text(text, "send-1", "https://theclouddecoded.com/pricing", "https://api.x.com")
        assert "https://api.x.com/api/v1/e/c/" in rewritten

    def test_no_cta_url_returns_text_unchanged(self):
        text = "No links here"
        assert ct.rewrite_cta_text(text, "send-1", None, "https://api.x.com") == text


class TestAppendUtm:
    def test_appends_with_question_mark_when_no_query(self):
        result = ct.append_utm("https://x.com/page", "email", "newsletter", "issue_1")
        assert result.startswith("https://x.com/page?")
        assert "utm_source=email" in result

    def test_appends_with_ampersand_when_query_exists(self):
        result = ct.append_utm("https://x.com/page?a=1", "email", "newsletter", "issue_1")
        assert "?a=1&" in result
