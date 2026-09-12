"""
tests/test_stripe_billing.py
Tests for api/routes/stripe_billing.py -- previously had zero coverage
despite being a real, money-handling integration (gap #2 from the
cross-repo audit).

Mocks the stripe SDK entirely (stripe.checkout.Session.create,
stripe.Webhook.construct_event, stripe.billing_portal.Session.create) --
no live network, no real Stripe calls. Same SimpleNamespace/AsyncMock
convention as the rest of this test suite.

Coverage:
  - create_checkout_session: happy path (new + existing customer),
    invalid tier, missing price config, missing API key, StripeError.
  - stripe_webhook: invalid/missing signature, malformed payload, no
    webhook secret configured, each of the three handled event types,
    an unhandled event type falling through cleanly.
  - create_customer_portal: happy path, no billing account yet, StripeError.
  - billing_status: reads straight from the workspace dict, with defaults.
  - _update_workspace_billing: partial updates only touch the given
    fields, a no-op call never touches the DB, an invalid tier is
    silently dropped rather than written.
  - The three webhook handlers directly: missing client_reference_id,
    unrecognized tier defaulting to starter, unrecognized price_id
    preserving the existing tier, and the "no workspace for this
    customer" early-return path shared by both subscription handlers.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import stripe.error
from fastapi import HTTPException

from api.routes import stripe_billing as billing


def _pool_with_conn(conn) -> MagicMock:
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return pool


def _make_request(conn) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=_pool_with_conn(conn))))


_ENV = {
    "STRIPE_SECRET_KEY": "sk_test_fake",
    "STRIPE_WEBHOOK_SECRET": "whsec_fake",
    "STRIPE_PRICE_ID_STARTER": "price_starter",
    "STRIPE_PRICE_ID_GROWTH": "price_growth",
    "STRIPE_PRICE_ID_ENTERPRISE": "price_enterprise",
    "FRONTEND_URL": "https://theclouddecoded.com",
}


@pytest.fixture(autouse=True)
def _env():
    with patch.dict("os.environ", _ENV):
        yield


class TestCreateCheckoutSession:
    async def test_new_customer_uses_customer_creation(self):
        workspace_id = uuid4()
        fake_workspace = {"id": workspace_id}
        request = _make_request(AsyncMock())

        fake_session = SimpleNamespace(url="https://checkout.stripe.com/session123")
        with patch("stripe.checkout.Session.create", return_value=fake_session) as mock_create:
            result = await billing.create_checkout_session(
                billing.CheckoutRequest(tier="growth"), request, workspace=fake_workspace
            )

        assert result.checkout_url == "https://checkout.stripe.com/session123"
        assert result.tier == "growth"
        kwargs = mock_create.call_args.kwargs
        assert kwargs["customer_creation"] == "always"
        assert "customer" not in kwargs
        assert kwargs["line_items"] == [{"price": "price_growth", "quantity": 1}]
        assert kwargs["client_reference_id"] == str(workspace_id)

    async def test_existing_customer_reuses_it(self):
        fake_workspace = {"id": uuid4(), "stripe_customer_id": "cus_existing"}
        request = _make_request(AsyncMock())
        fake_session = SimpleNamespace(url="https://checkout.stripe.com/session456")

        with patch("stripe.checkout.Session.create", return_value=fake_session) as mock_create:
            await billing.create_checkout_session(
                billing.CheckoutRequest(tier="starter"), request, workspace=fake_workspace
            )

        kwargs = mock_create.call_args.kwargs
        assert kwargs["customer"] == "cus_existing"
        assert "customer_creation" not in kwargs

    async def test_invalid_tier_rejected(self):
        request = _make_request(AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await billing.create_checkout_session(
                billing.CheckoutRequest(tier="ultra"), request, workspace={"id": uuid4()}
            )
        assert exc.value.status_code == 400

    async def test_missing_price_config_returns_503(self):
        request = _make_request(AsyncMock())
        with patch.dict("os.environ", {"STRIPE_PRICE_ID_GROWTH": ""}):
            with pytest.raises(HTTPException) as exc:
                await billing.create_checkout_session(
                    billing.CheckoutRequest(tier="growth"), request, workspace={"id": uuid4()}
                )
        assert exc.value.status_code == 503

    async def test_missing_api_key_returns_503(self):
        request = _make_request(AsyncMock())
        with patch.dict("os.environ", {"STRIPE_SECRET_KEY": ""}):
            with pytest.raises(HTTPException) as exc:
                await billing.create_checkout_session(
                    billing.CheckoutRequest(tier="growth"), request, workspace={"id": uuid4()}
                )
        assert exc.value.status_code == 503

    async def test_stripe_error_returns_502(self):
        request = _make_request(AsyncMock())
        with patch(
            "stripe.checkout.Session.create",
            side_effect=stripe.error.StripeError("card issue", code="card_declined"),
        ):
            with pytest.raises(HTTPException) as exc:
                await billing.create_checkout_session(
                    billing.CheckoutRequest(tier="growth"), request, workspace={"id": uuid4()}
                )
        assert exc.value.status_code == 502


class TestStripeWebhook:
    async def _request_with_body(self, conn, body: bytes = b'{"type": "noop"}'):
        request = _make_request(conn)
        request.body = AsyncMock(return_value=body)
        request.headers = {"stripe-signature": "sig_fake"}
        return request

    async def test_invalid_signature_returns_400(self):
        request = await self._request_with_body(AsyncMock())
        with patch(
            "stripe.Webhook.construct_event",
            side_effect=stripe.error.SignatureVerificationError("bad sig", "sig_fake"),
        ):
            with pytest.raises(HTTPException) as exc:
                await billing.stripe_webhook(request)
        assert exc.value.status_code == 400

    async def test_malformed_payload_returns_400(self):
        request = await self._request_with_body(AsyncMock())
        with patch("stripe.Webhook.construct_event", side_effect=ValueError("bad json")):
            with pytest.raises(HTTPException) as exc:
                await billing.stripe_webhook(request)
        assert exc.value.status_code == 400

    async def test_no_webhook_secret_returns_503(self):
        request = await self._request_with_body(AsyncMock())
        with patch.dict("os.environ", {"STRIPE_WEBHOOK_SECRET": ""}):
            with pytest.raises(HTTPException) as exc:
                await billing.stripe_webhook(request)
        assert exc.value.status_code == 503

    async def test_checkout_completed_dispatches_to_handler(self):
        request = await self._request_with_body(AsyncMock())
        fake_event = {"type": "checkout.session.completed", "id": "evt_1", "data": {"object": {"foo": "bar"}}}
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            with patch.object(billing, "_handle_checkout_completed", new=AsyncMock()) as mock_handler:
                result = await billing.stripe_webhook(request)
        assert result == {"received": True}
        mock_handler.assert_awaited_once_with(request.app.state.db_pool, {"foo": "bar"})

    async def test_subscription_updated_dispatches_to_handler(self):
        request = await self._request_with_body(AsyncMock())
        fake_event = {"type": "customer.subscription.updated", "id": "evt_2", "data": {"object": {"sub": 1}}}
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            with patch.object(billing, "_handle_subscription_updated", new=AsyncMock()) as mock_handler:
                await billing.stripe_webhook(request)
        mock_handler.assert_awaited_once_with(request.app.state.db_pool, {"sub": 1})

    async def test_subscription_deleted_dispatches_to_handler(self):
        request = await self._request_with_body(AsyncMock())
        fake_event = {"type": "customer.subscription.deleted", "id": "evt_3", "data": {"object": {"sub": 2}}}
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            with patch.object(billing, "_handle_subscription_deleted", new=AsyncMock()) as mock_handler:
                await billing.stripe_webhook(request)
        mock_handler.assert_awaited_once_with(request.app.state.db_pool, {"sub": 2})

    async def test_unhandled_event_type_is_a_clean_noop(self):
        request = await self._request_with_body(AsyncMock())
        fake_event = {"type": "invoice.paid", "id": "evt_4", "data": {"object": {}}}
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            result = await billing.stripe_webhook(request)
        assert result == {"received": True}


class TestCreateCustomerPortal:
    async def test_no_billing_account_returns_404(self):
        request = _make_request(AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await billing.create_customer_portal(request, workspace={"id": uuid4()})
        assert exc.value.status_code == 404

    async def test_happy_path_returns_portal_url(self):
        request = _make_request(AsyncMock())
        fake_workspace = {"id": uuid4(), "stripe_customer_id": "cus_123"}
        fake_session = SimpleNamespace(url="https://billing.stripe.com/portal789")

        with patch("stripe.billing_portal.Session.create", return_value=fake_session) as mock_create:
            result = await billing.create_customer_portal(request, workspace=fake_workspace)

        assert result.portal_url == "https://billing.stripe.com/portal789"
        assert mock_create.call_args.kwargs["customer"] == "cus_123"

    async def test_stripe_error_returns_502(self):
        request = _make_request(AsyncMock())
        fake_workspace = {"id": uuid4(), "stripe_customer_id": "cus_123"}
        with patch("stripe.billing_portal.Session.create", side_effect=stripe.error.StripeError("boom")):
            with pytest.raises(HTTPException) as exc:
                await billing.create_customer_portal(request, workspace=fake_workspace)
        assert exc.value.status_code == 502


class TestBillingStatus:
    async def test_reads_workspace_fields(self):
        result = await billing.billing_status(
            workspace={"product_tier": "enterprise", "stripe_subscription_status": "active", "stripe_customer_id": "cus_1"}
        )
        assert result.tier == "enterprise"
        assert result.subscription_status == "active"
        assert result.has_billing_account is True

    async def test_defaults_when_never_billed(self):
        result = await billing.billing_status(workspace={})
        assert result.tier == "starter"
        assert result.subscription_status == "trialing"
        assert result.has_billing_account is False


class TestUpdateWorkspaceBilling:
    async def test_partial_update_only_touches_given_fields(self):
        conn = AsyncMock()
        pool = _pool_with_conn(conn)
        workspace_id = str(uuid4())

        await billing._update_workspace_billing(pool, workspace_id, subscription_status="canceled")

        sql, status_value, bound_id = conn.execute.await_args.args
        assert "stripe_subscription_status" in sql
        assert "product_tier" not in sql
        assert "stripe_customer_id" not in sql
        assert status_value == "canceled"

    async def test_noop_call_never_touches_db(self):
        conn = AsyncMock()
        pool = MagicMock()
        pool.acquire = MagicMock()

        await billing._update_workspace_billing(pool, str(uuid4()))

        pool.acquire.assert_not_called()
        conn.execute.assert_not_called()

    async def test_invalid_tier_is_silently_dropped(self):
        conn = AsyncMock()
        pool = _pool_with_conn(conn)

        await billing._update_workspace_billing(pool, str(uuid4()), tier="not_a_real_tier", subscription_status="active")

        sql, status_value, bound_id = conn.execute.await_args.args
        assert "product_tier" not in sql


class TestWebhookHandlers:
    async def test_checkout_completed_missing_workspace_id_logs_and_skips(self):
        with patch.object(billing, "_update_workspace_billing", new=AsyncMock()) as mock_update:
            await billing._handle_checkout_completed(MagicMock(), {"customer": "cus_1", "metadata": {"tier": "growth"}})
        mock_update.assert_not_called()

    async def test_checkout_completed_unrecognized_tier_defaults_to_starter(self):
        with patch.object(billing, "_update_workspace_billing", new=AsyncMock()) as mock_update:
            await billing._handle_checkout_completed(
                MagicMock(),
                {"client_reference_id": "ws-1", "customer": "cus_1", "metadata": {"tier": "not_a_tier"}},
            )
        mock_update.assert_awaited_once()
        kwargs = mock_update.await_args.kwargs
        assert kwargs["tier"] == "starter"

    async def test_subscription_updated_no_workspace_found_is_a_noop(self):
        with patch.object(billing, "_workspace_id_for_customer", new=AsyncMock(return_value=None)):
            with patch.object(billing, "_update_workspace_billing", new=AsyncMock()) as mock_update:
                await billing._handle_subscription_updated(MagicMock(), {"customer": "cus_ghost", "status": "active"})
        mock_update.assert_not_called()

    async def test_subscription_updated_unrecognized_price_preserves_tier(self):
        subscription = {
            "customer": "cus_1",
            "status": "active",
            "items": {"data": [{"price": {"id": "price_unknown"}}]},
        }
        with patch.object(billing, "_workspace_id_for_customer", new=AsyncMock(return_value="ws-1")):
            with patch.object(billing, "_update_workspace_billing", new=AsyncMock()) as mock_update:
                await billing._handle_subscription_updated(MagicMock(), subscription)
        kwargs = mock_update.await_args.kwargs
        assert kwargs["tier"] is None
        assert kwargs["subscription_status"] == "active"

    async def test_subscription_updated_recognized_price_maps_to_tier(self):
        subscription = {
            "customer": "cus_1",
            "status": "active",
            "items": {"data": [{"price": {"id": "price_enterprise"}}]},
        }
        with patch.object(billing, "_workspace_id_for_customer", new=AsyncMock(return_value="ws-1")):
            with patch.object(billing, "_update_workspace_billing", new=AsyncMock()) as mock_update:
                await billing._handle_subscription_updated(MagicMock(), subscription)
        assert mock_update.await_args.kwargs["tier"] == "enterprise"

    async def test_subscription_deleted_no_workspace_found_is_a_noop(self):
        with patch.object(billing, "_workspace_id_for_customer", new=AsyncMock(return_value=None)):
            with patch.object(billing, "_update_workspace_billing", new=AsyncMock()) as mock_update:
                await billing._handle_subscription_deleted(MagicMock(), {"customer": "cus_ghost"})
        mock_update.assert_not_called()

    async def test_subscription_deleted_marks_canceled(self):
        with patch.object(billing, "_workspace_id_for_customer", new=AsyncMock(return_value="ws-1")):
            with patch.object(billing, "_update_workspace_billing", new=AsyncMock()) as mock_update:
                await billing._handle_subscription_deleted(MagicMock(), {"customer": "cus_1"})
        mock_update.assert_awaited_once()
        assert mock_update.await_args.kwargs["subscription_status"] == "canceled"
