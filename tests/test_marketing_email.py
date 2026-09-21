"""
tests/test_marketing_email.py
core/marketing_email.py -- the compliance layer every marketing send goes
through: template-approved gate, suppression check, daily cap, RFC 8058
headers, compliance footer, and the cd_email_sends ledger write for every
outcome (sent/suppressed/failed).
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from core import marketing_email
from core.email import EmailError
from core.unsubscribe_token import UnsubscribeConfigError


def _template(**overrides) -> dict:
    base = {
        "key": "onboarding_step1_connect_stack",
        "sequence_key": "onboarding",
        "step_number": 1,
        "status": "approved",
        "subject": "Still time to connect your stack",
        "body_html": "<p>hello</p>",
        "body_text": "hello",
        "cta_url": "https://theclouddecoded.com/dashboard",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _secret_env():
    with patch.dict("os.environ", {"CD_UNSUBSCRIBE_SECRET": "test-secret", "API_BASE_URL": "https://api.x.com"}):
        yield


class TestTemplateMustBeApproved:
    async def test_pending_approval_template_raises(self):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="non-approved"):
            await marketing_email.send_marketing_email(
                conn, recipient="a@b.com", template=_template(status="pending_approval"),
            )
        conn.fetchrow.assert_not_called()

    async def test_retired_template_raises(self):
        conn = AsyncMock()
        with pytest.raises(ValueError):
            await marketing_email.send_marketing_email(
                conn, recipient="a@b.com", template=_template(status="retired"),
            )


class TestSuppression:
    async def test_suppressed_recipient_never_sends_and_records_suppressed(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"reason": "unsubscribe"})  # is_suppressed check

        with patch("core.marketing_email.send_email", new=AsyncMock()) as mock_send:
            outcome = await marketing_email.send_marketing_email(conn, recipient="a@b.com", template=_template())

        assert outcome == "suppressed"
        mock_send.assert_not_awaited()
        insert_call = conn.execute.await_args
        # args: sql, send_id, enrollment_id, template_key, recipient, stream,
        # resend_message_id, status, utm_source, utm_medium, utm_campaign
        assert "INSERT INTO cd_email_sends" in insert_call.args[0]
        assert insert_call.args[7] == "suppressed"
        assert insert_call.args[6] is None  # no resend_message_id -- never actually sent


class TestDailyCap:
    async def test_cap_reached_suppresses_without_sending(self):
        conn = AsyncMock()
        # is_suppressed -> None (not suppressed), daily_cap_reached -> row (capped)
        conn.fetchrow = AsyncMock(side_effect=[None, {"1": 1}])

        with patch("core.marketing_email.send_email", new=AsyncMock()) as mock_send:
            outcome = await marketing_email.send_marketing_email(conn, recipient="a@b.com", template=_template())

        assert outcome == "suppressed"
        mock_send.assert_not_awaited()


class TestHappyPath:
    async def test_sends_with_rfc8058_headers_and_records_sent(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, None])  # not suppressed, not capped

        with patch("core.marketing_email.send_email", new=AsyncMock(return_value="resend-msg-1")) as mock_send:
            outcome = await marketing_email.send_marketing_email(conn, recipient="a@b.com", template=_template())

        assert outcome == "sent"
        mock_send.assert_awaited_once()
        kwargs = mock_send.await_args.kwargs
        assert kwargs["stream"] == "marketing"
        assert "List-Unsubscribe" in kwargs["headers"]
        assert kwargs["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        assert "unsubscribe?token=" in kwargs["headers"]["List-Unsubscribe"]

        insert_call = conn.execute.await_args
        assert insert_call.args[7] == "sent"
        assert insert_call.args[6] == "resend-msg-1"  # resend_message_id positional

    async def test_footer_and_unsubscribe_link_appended_to_body(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, None])

        with patch("core.marketing_email.send_email", new=AsyncMock(return_value="id")) as mock_send:
            await marketing_email.send_marketing_email(conn, recipient="a@b.com", template=_template())

        html = mock_send.await_args.kwargs["html"]
        assert "Unsubscribe" in html
        assert "<p>hello</p>" in html

    async def test_send_failure_records_failed_and_returns_failed(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, None])

        with patch("core.marketing_email.send_email", new=AsyncMock(side_effect=EmailError("boom"))):
            outcome = await marketing_email.send_marketing_email(conn, recipient="a@b.com", template=_template())

        assert outcome == "failed"
        insert_call = conn.execute.await_args
        assert insert_call.args[7] == "failed"


class TestMissingUnsubscribeSecret:
    async def test_raises_unsubscribe_config_error_fail_closed(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, None])

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(UnsubscribeConfigError):
                await marketing_email.send_marketing_email(conn, recipient="a@b.com", template=_template())


class TestSuppressHelper:
    async def test_suppress_upserts_by_lower_email(self):
        conn = AsyncMock()
        await marketing_email.suppress(conn, "Jane@Example.com", "bounce")
        sql, email_arg, reason_arg = conn.execute.await_args.args
        assert "ON CONFLICT (lower(email))" in sql
        assert email_arg == "jane@example.com"
        assert reason_arg == "bounce"
