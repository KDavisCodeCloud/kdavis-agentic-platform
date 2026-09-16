"""
tests/test_leads_capture.py
Tests for leads/capture/{signup_handler,trial_handler}.py and
leads/integrations/{slack,webhook_receiver}.py. Brevo client coverage
(leads/integrations/brevo_client.py, replaces systeme_io.py as of
2026-09-16) lives in tests/test_brevo_client.py, not here.

What this file validates:
  - signup_handler validates payloads and rejects bad input with
    descriptive errors (no silent failures)
  - process_signup writes the correct leads row shape and never raises
    when the downstream webhook/CRM sync fails (best-effort, warnings
    surfaced instead)
  - trial_handler reuses process_signup, creates a Stripe customer +
    trial subscription, and requires an explicit stripe_price_id
  - SlackClient builds correct requests and raises on API-level failures
  - webhook_receiver verifies the shared secret and dispatches by
    event type, updating the matching lead

All clients are injected mocks — no real Supabase/Stripe/Brevo/
Slack/network calls happen in this suite.
"""

from unittest.mock import MagicMock, patch

import pytest

from leads.capture.signup_handler import process_signup, validate_signup_payload
from leads.capture.trial_handler import process_trial_start
from leads.integrations.brevo_client import BrevoContactResult
from leads.integrations.slack import SlackClient, SlackAPIError
from leads.integrations import webhook_receiver


# ──────────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.content = b"x" if json_data is not None else b""
        self.text = str(json_data)

    def json(self):
        return self._json_data


def _supabase_client_stub(insert_return=None):
    """Mimics Supabase's real behavior: insert().execute() echoes back
    the inserted row (plus a generated id) unless a specific return is
    provided."""
    client = MagicMock()

    def _fake_insert(row):
        execute_result = MagicMock()
        execute_result.data = [insert_return] if insert_return else [{"id": 1, **row}]
        insert_mock = MagicMock()
        insert_mock.execute.return_value = execute_result
        return insert_mock

    client.table.return_value.insert.side_effect = _fake_insert
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()
    client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return client


# ──────────────────────────────────────────────────────────────────────────────
# validate_signup_payload
# ──────────────────────────────────────────────────────────────────────────────

class TestValidateSignupPayload:
    def test_valid_payload_parses(self):
        payload = validate_signup_payload({"email": "Jane@Example.com", "product_id": "cloud-decoded"})
        assert payload.email == "jane@example.com"  # normalized lowercase
        assert payload.product_id == "cloud-decoded"
        assert payload.signup_type == "email_only"

    def test_missing_email_raises(self):
        with pytest.raises(ValueError, match="email"):
            validate_signup_payload({"product_id": "cloud-decoded"})

    def test_malformed_email_raises(self):
        with pytest.raises(ValueError, match="email"):
            validate_signup_payload({"email": "not-an-email", "product_id": "cloud-decoded"})

    def test_missing_product_id_raises(self):
        with pytest.raises(ValueError, match="product_id"):
            validate_signup_payload({"email": "jane@example.com"})

    def test_invalid_signup_type_raises(self):
        with pytest.raises(ValueError, match="signup_type"):
            validate_signup_payload({"email": "jane@example.com", "product_id": "p", "signup_type": "bogus"})


# ──────────────────────────────────────────────────────────────────────────────
# process_signup
# ──────────────────────────────────────────────────────────────────────────────

class TestProcessSignup:
    def test_writes_lead_row_and_returns_no_warnings(self):
        supabase = _supabase_client_stub()
        result = process_signup({"email": "jane@example.com", "product_id": "cloud-decoded"}, supabase_client=supabase)

        insert_call = supabase.table.return_value.insert.call_args[0][0]
        assert insert_call["email"] == "jane@example.com"
        assert insert_call["product_id"] == "cloud-decoded"
        assert insert_call["signup_type"] == "email_only"
        assert result["warnings"] == []

    def test_brevo_failure_produces_warning_not_exception(self):
        supabase = _supabase_client_stub()
        # Any non-None brevo_client satisfies _sync_to_brevo's "configured"
        # guard; the actual Brevo SDK call is intercepted below via
        # create_or_update_contact itself, same pattern as
        # kdavis-microsaas-engine's own mkt_o3 tests.
        with patch(
            "leads.capture.signup_handler.create_or_update_contact",
            return_value=BrevoContactResult(success=False, error="boom"),
        ):
            result = process_signup(
                {"email": "jane@example.com", "product_id": "p"},
                supabase_client=supabase, brevo_client=MagicMock(),
            )

        assert any("Brevo" in w for w in result["warnings"])

    def test_brevo_not_configured_produces_no_warning_when_no_client_passed(self):
        # Default behavior, unchanged from the old Systeme.io wiring:
        # brevo_client=None (the default) means "don't sync" -- not an error.
        supabase = _supabase_client_stub()
        result = process_signup({"email": "jane@example.com", "product_id": "p"}, supabase_client=supabase)
        assert result["warnings"] == []

    def test_webhook_failure_produces_warning_not_exception(self):
        supabase = _supabase_client_stub()
        http_client = MagicMock()
        http_client.post.side_effect = RuntimeError("network down")

        result = process_signup(
            {"email": "jane@example.com", "product_id": "p"},
            supabase_client=supabase,
            visitor_capture_webhook_url="https://internal.example.com/hook",
            http_client=http_client,
        )

        assert any("webhook" in w for w in result["warnings"])

    def test_trial_lead_stage_differs_from_email_only_lead_stage(self):
        supabase = _supabase_client_stub()

        with patch(
            "leads.capture.signup_handler.create_or_update_contact",
            return_value=BrevoContactResult(success=True, contact_id=1),
        ) as mock_sync:
            process_signup(
                {"email": "a@example.com", "product_id": "p", "signup_type": "trial"},
                supabase_client=supabase, brevo_client=MagicMock(),
            )
            trial_stage = mock_sync.call_args.kwargs["attributes"]["LEAD_STAGE"]

            mock_sync.reset_mock()
            process_signup(
                {"email": "b@example.com", "product_id": "p", "signup_type": "email_only"},
                supabase_client=supabase, brevo_client=MagicMock(),
            )
            email_only_stage = mock_sync.call_args.kwargs["attributes"]["LEAD_STAGE"]

        assert trial_stage == "trial_active"
        assert email_only_stage == "interested"


# ──────────────────────────────────────────────────────────────────────────────
# process_trial_start
# ──────────────────────────────────────────────────────────────────────────────

class TestProcessTrialStart:
    def _stripe_stub(self):
        stripe = MagicMock()
        stripe.Customer.create.return_value = {"id": "cus_123"}
        stripe.Subscription.create.return_value = {"id": "sub_456"}
        return stripe

    def test_requires_stripe_price_id(self):
        with pytest.raises(ValueError, match="stripe_price_id"):
            process_trial_start({"email": "a@example.com", "product_id": "p"}, stripe_price_id="")

    def test_creates_customer_and_trial_subscription(self):
        supabase = _supabase_client_stub()
        stripe = self._stripe_stub()

        result = process_trial_start(
            {"email": "a@example.com", "product_id": "p"},
            stripe_price_id="price_abc",
            supabase_client=supabase,
            stripe_module=stripe,
        )

        stripe.Customer.create.assert_called_once()
        assert stripe.Customer.create.call_args.kwargs["email"] == "a@example.com"

        sub_kwargs = stripe.Subscription.create.call_args.kwargs
        assert sub_kwargs["customer"] == "cus_123"
        assert sub_kwargs["items"] == [{"price": "price_abc"}]
        assert sub_kwargs["trial_period_days"] == 14

        assert result["stripe_customer_id"] == "cus_123"
        assert result["stripe_subscription_id"] == "sub_456"
        assert result["lead"]["signup_type"] == "trial"


# ──────────────────────────────────────────────────────────────────────────────
# SlackClient
# ──────────────────────────────────────────────────────────────────────────────

class TestSlackClient:
    def test_post_message_success(self):
        http = MagicMock()
        http.post.return_value = FakeResponse(200, {"ok": True, "ts": "123.45"})
        client = SlackClient(bot_token="xoxb-fake", client=http)

        result = client.post_message("#general", "hello")

        assert result["ok"] is True
        http.post.assert_called_once_with("/chat.postMessage", json={"channel": "#general", "text": "hello"})

    def test_slack_not_ok_raises(self):
        http = MagicMock()
        http.post.return_value = FakeResponse(200, {"ok": False, "error": "channel_not_found"})
        client = SlackClient(bot_token="xoxb-fake", client=http)

        with pytest.raises(SlackAPIError, match="channel_not_found"):
            client.post_message("#nope", "hello")

    def test_invite_user_requires_team_id(self):
        client = SlackClient(bot_token="xoxb-fake", team_id=None, client=MagicMock())
        with pytest.raises(SlackAPIError, match="SLACK_TEAM_ID"):
            client.invite_user("a@example.com")


# ──────────────────────────────────────────────────────────────────────────────
# webhook_receiver
# ──────────────────────────────────────────────────────────────────────────────

class TestWebhookReceiver:
    def test_no_secret_configured_accepts(self, monkeypatch):
        monkeypatch.delenv("BREVO_WEBHOOK_SECRET", raising=False)
        assert webhook_receiver.verify_webhook_secret(None) is True

    def test_secret_mismatch_rejected(self, monkeypatch):
        monkeypatch.setenv("BREVO_WEBHOOK_SECRET", "correct-secret")
        assert webhook_receiver.verify_webhook_secret("wrong") is False
        assert webhook_receiver.verify_webhook_secret("correct-secret") is True

    def test_handle_webhook_raises_on_bad_secret(self, monkeypatch):
        monkeypatch.setenv("BREVO_WEBHOOK_SECRET", "correct-secret")
        with pytest.raises(PermissionError):
            webhook_receiver.handle_webhook({"event": "contact_updated", "data": {}}, secret_header="wrong")

    def test_contact_updated_updates_lead(self, monkeypatch):
        monkeypatch.delenv("BREVO_WEBHOOK_SECRET", raising=False)
        supabase = _supabase_client_stub()

        result = webhook_receiver.handle_webhook(
            {"event": "contact_updated", "data": {"email": "jane@example.com", "id": "contact_9", "product_id": "p"}},
            supabase_client=supabase,
        )

        assert result["status"] == "processed"
        update_call = supabase.table.return_value.update.call_args[0][0]
        assert update_call == {"brevo_contact_id": "contact_9"}

    def test_unsubscribed_marks_lead_churned(self, monkeypatch):
        monkeypatch.delenv("BREVO_WEBHOOK_SECRET", raising=False)
        supabase = _supabase_client_stub()

        result = webhook_receiver.handle_webhook(
            {"event": "unsubscribed", "data": {"email": "jane@example.com", "product_id": "p"}},
            supabase_client=supabase,
        )

        assert result["status"] == "processed"
        update_call = supabase.table.return_value.update.call_args[0][0]
        assert update_call == {"stage": "churned"}

    def test_unrecognized_event_ignored(self, monkeypatch):
        monkeypatch.delenv("BREVO_WEBHOOK_SECRET", raising=False)
        result = webhook_receiver.handle_webhook({"event": "something.new", "data": {}})
        assert result["status"] == "ignored"
