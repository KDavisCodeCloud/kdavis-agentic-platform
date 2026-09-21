"""
tests/test_email_public_routes.py
api/routes/email_public.py -- subscribe, unsubscribe (GET confirmation
page never mutates state, POST performs the RFC 8058 one-click action),
click redirect, and the Resend bounce/complaint webhook.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.middleware.rate_limiter import limiter
from api.routes import email_public


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """Same convention as tests/test_workspace_members.py's fixture of
    this name -- slowapi's @limiter.limit decorator on subscribe()
    requires a real starlette Request, which these MagicMock fakes
    deliberately are not."""
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _mock_request(conn):
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)

    request = MagicMock()
    request.app.state.db_pool = pool
    request.client.host = "1.2.3.4"
    return request


class TestSubscribe:
    async def test_invalid_email_rejected(self):
        request = _mock_request(AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await email_public.subscribe(email_public.SubscribeRequest(email="not-an-email"), request)
        assert exc.value.status_code == 400

    async def test_invalid_source_rejected(self):
        request = _mock_request(AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await email_public.subscribe(
                email_public.SubscribeRequest(email="a@b.com", source="checkout"), request,
            )
        assert exc.value.status_code == 400

    async def test_bounce_held_address_gets_generic_success_without_enrolling(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"reason": "bounce"})
        request = _mock_request(conn)

        with (
            patch("api.routes.email_public.get_or_create_subscriber", new=AsyncMock()) as mock_gc,
            patch("api.routes.email_public.enroll", new=AsyncMock()) as mock_enroll,
        ):
            result = await email_public.subscribe(
                email_public.SubscribeRequest(email="a@b.com", source="newsletter_signup"), request,
            )

        assert result.success is True
        mock_gc.assert_not_awaited()
        mock_enroll.assert_not_awaited()

    async def test_valid_signup_enrolls_in_newsletter(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # no existing suppression
        request = _mock_request(conn)

        with (
            patch("api.routes.email_public.get_or_create_subscriber", new=AsyncMock(return_value="sub-1")) as mock_gc,
            patch("api.routes.email_public.enroll", new=AsyncMock()) as mock_enroll,
        ):
            await email_public.subscribe(
                email_public.SubscribeRequest(email="a@b.com", source="newsletter_signup"), request,
            )

        mock_gc.assert_awaited_once()
        mock_enroll.assert_awaited_once_with(conn, "sub-1", "newsletter")

    async def test_lead_magnet_enrolls_in_trust_drip(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _mock_request(conn)

        with (
            patch("api.routes.email_public.get_or_create_subscriber", new=AsyncMock(return_value="sub-1")),
            patch("api.routes.email_public.enroll", new=AsyncMock()) as mock_enroll,
        ):
            await email_public.subscribe(
                email_public.SubscribeRequest(email="a@b.com", source="lead_magnet"), request,
            )
        mock_enroll.assert_awaited_once_with(conn, "sub-1", "trust_drip")


class TestUnsubscribeConfirmPage:
    async def test_never_mutates_state(self):
        request = _mock_request(AsyncMock())
        with (
            patch("api.routes.email_public.verify_token", return_value="a@b.com"),
            patch("api.routes.email_public.suppress", new=AsyncMock()) as mock_suppress,
        ):
            resp = await email_public.unsubscribe_confirm_page("sometoken", request)
        assert "Unsubscribe a@b.com?" in resp.body.decode()
        mock_suppress.assert_not_awaited()

    async def test_invalid_token_shows_generic_expired_page(self):
        request = _mock_request(AsyncMock())
        with patch("api.routes.email_public.verify_token", return_value=None):
            resp = await email_public.unsubscribe_confirm_page("bad", request)
        assert "expired" in resp.body.decode().lower()


class TestUnsubscribeAction:
    async def test_valid_token_suppresses_and_exits_all(self):
        conn = AsyncMock()
        request = _mock_request(conn)
        with (
            patch("api.routes.email_public.verify_token", return_value="a@b.com"),
            patch("api.routes.email_public.suppress", new=AsyncMock()) as mock_suppress,
            patch("api.routes.email_public.exit_all_by_email", new=AsyncMock()) as mock_exit_all,
        ):
            result = await email_public.unsubscribe_action("tok", request)

        assert result == {"success": True}
        mock_suppress.assert_awaited_once_with(conn, "a@b.com", "unsubscribe")
        mock_exit_all.assert_awaited_once_with(conn, "a@b.com", "unsubscribed")

    async def test_invalid_token_returns_success_false_not_an_error(self):
        request = _mock_request(AsyncMock())
        with patch("api.routes.email_public.verify_token", return_value=None):
            result = await email_public.unsubscribe_action("bad", request)
        assert result["success"] is False


class TestClickRedirect:
    async def test_invalid_token_404s(self):
        request = _mock_request(AsyncMock())
        with patch("api.routes.email_public.verify_click_token", return_value=None):
            with pytest.raises(HTTPException) as exc:
                await email_public.click_redirect("bad", request)
        assert exc.value.status_code == 404

    async def test_valid_token_records_click_and_redirects_with_utm(self):
        send_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"utm_source": "email", "utm_medium": "newsletter", "utm_campaign": "issue_1"})
        request = _mock_request(conn)

        with patch("api.routes.email_public.verify_click_token", return_value=(str(send_id), "https://x.com/pricing")):
            resp = await email_public.click_redirect("tok", request)

        assert resp.status_code == 302
        assert "utm_source=email" in resp.headers["location"]
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO cd_email_clicks" in c.args[0]]
        assert len(insert_calls) == 1

    async def test_missing_send_row_still_redirects_without_recording_click(self):
        send_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # send row doesn't exist
        request = _mock_request(conn)

        with patch("api.routes.email_public.verify_click_token", return_value=(str(send_id), "https://x.com/pricing")):
            resp = await email_public.click_redirect("tok", request)

        assert resp.status_code == 302
        conn.execute.assert_not_called()


class TestResendWebhook:
    async def test_bad_signature_returns_400(self):
        request = MagicMock()
        request.body = AsyncMock(return_value=b"{}")
        request.headers = {}
        with patch("api.routes.email_public.verify_resend_webhook", side_effect=email_public.WebhookVerificationError("bad")):
            with pytest.raises(HTTPException) as exc:
                await email_public.resend_webhook(request)
        assert exc.value.status_code == 400

    async def test_bounce_event_suppresses_and_exits(self):
        conn = AsyncMock()
        request = _mock_request(conn)
        request.body = AsyncMock(return_value=b"{}")
        request.headers = {}
        request.json = AsyncMock(return_value={"type": "email.bounced", "data": {"to": ["a@b.com"]}})

        with (
            patch("api.routes.email_public.verify_resend_webhook", return_value=None),
            patch("api.routes.email_public.suppress", new=AsyncMock()) as mock_suppress,
            patch("api.routes.email_public.exit_all_by_email", new=AsyncMock()) as mock_exit_all,
        ):
            result = await email_public.resend_webhook(request)

        assert result == {"received": True}
        mock_suppress.assert_awaited_once_with(conn, "a@b.com", "bounce")
        mock_exit_all.assert_awaited_once_with(conn, "a@b.com", "bounce")

    async def test_unrelated_event_type_is_a_noop(self):
        conn = AsyncMock()
        request = _mock_request(conn)
        request.body = AsyncMock(return_value=b"{}")
        request.headers = {}
        request.json = AsyncMock(return_value={"type": "email.delivered", "data": {"to": ["a@b.com"]}})

        with (
            patch("api.routes.email_public.verify_resend_webhook", return_value=None),
            patch("api.routes.email_public.suppress", new=AsyncMock()) as mock_suppress,
        ):
            result = await email_public.resend_webhook(request)

        assert result == {"received": True}
        mock_suppress.assert_not_awaited()
