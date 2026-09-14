"""
tests/test_email.py
Tests for core/email.py -- transactional email via Resend, added 2026-09-14
to close the "zero email infrastructure exists anywhere" operational-
readiness gap.

What this validates:
  - send_email: without RESEND_API_KEY set, skips the network call
    entirely rather than raising -- the caller's own operation (a
    checkout webhook, a tier change) must never break on a missing key.
  - send_email: a non-2xx/3xx response from Resend raises EmailError with
    useful detail, so callers can log it, but a network-level failure
    (httpx.RequestError) also raises EmailError, not a raw httpx exception
    callers would have to know to catch separately.
  - send_email: the happy path posts to Resend's API with the right
    Authorization header and body shape.

Runs with pytest-asyncio + unittest.mock, no live network.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core import email


@pytest.fixture(autouse=True)
def _clear_resend_key():
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("RESEND_API_KEY", None)
        yield


class TestSendEmail:
    async def test_skips_send_when_api_key_missing(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            await email.send_email(to="a@b.com", subject="hi", html="<p>hi</p>")
        mock_client_cls.assert_not_called()

    async def test_happy_path_posts_to_resend_with_auth_header(self):
        mock_resp = MagicMock(status_code=200)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {"RESEND_API_KEY": "re_test_key"}),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            await email.send_email(to="a@b.com", subject="hi", html="<p>hi</p>")

        _, kwargs = mock_client.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer re_test_key"
        assert kwargs["json"]["to"] == ["a@b.com"]
        assert kwargs["json"]["subject"] == "hi"

    async def test_non_2xx_response_raises_email_error(self):
        mock_resp = MagicMock(status_code=422, text="invalid recipient")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {"RESEND_API_KEY": "re_test_key"}),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            with pytest.raises(email.EmailError, match="422"):
                await email.send_email(to="a@b.com", subject="hi", html="<p>hi</p>")

    async def test_network_error_raises_email_error_not_httpx_error(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("dns failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {"RESEND_API_KEY": "re_test_key"}),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            with pytest.raises(email.EmailError):
                await email.send_email(to="a@b.com", subject="hi", html="<p>hi</p>")

    async def test_custom_from_addr_overrides_default(self):
        mock_resp = MagicMock(status_code=200)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {"RESEND_API_KEY": "re_test_key"}),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            await email.send_email(to="a@b.com", subject="hi", html="<p>hi</p>", from_addr="custom@x.com")

        assert mock_client.post.call_args.kwargs["json"]["from"] == "custom@x.com"


class TestHtmlBuilders:
    def test_welcome_email_html_includes_company_name(self):
        html = email.welcome_email_html("Acme")
        assert "Acme" in html

    def test_enterprise_alert_html_includes_workspace_id(self):
        html = email.enterprise_alert_html("Acme", "ws-123", "ops@acme.com")
        assert "ws-123" in html
        assert "ops@acme.com" in html

    def test_enterprise_alert_html_handles_missing_contact(self):
        html = email.enterprise_alert_html("Acme", "ws-123", None)
        assert "none captured" in html.lower()
