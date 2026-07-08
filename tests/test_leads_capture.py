"""
tests/test_leads_capture.py
Tests for leads/capture/{signup_handler,trial_handler}.py and
leads/integrations/{systeme_io,slack,webhook_receiver}.py.

What this file validates:
  - signup_handler validates payloads and rejects bad input with
    descriptive errors (no silent failures)
  - process_signup writes the correct leads row shape and never raises
    when the downstream webhook/CRM sync fails (best-effort, warnings
    surfaced instead)
  - trial_handler reuses process_signup, creates a Stripe customer +
    trial subscription, and requires an explicit stripe_price_id
  - SystemeIOClient and SlackClient build correct requests and raise
    on API-level failures
  - webhook_receiver verifies the shared secret and dispatches by
    event type, updating the matching lead

All clients are injected mocks — no real Supabase/Stripe/Systeme.io/
Slack/network calls happen in this suite.
"""

from unittest.mock import MagicMock

import pytest

from leads.capture.signup_handler import process_signup, validate_signup_payload
from leads.capture.trial_handler import process_trial_start
from leads.integrations.systeme_io import SystemeIOClient, SystemeIOError
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

    def test_systeme_failure_produces_warning_not_exception(self):
        supabase = _supabase_client_stub()
        systeme = MagicMock()
        systeme.create_contact.side_effect = SystemeIOError("boom")

        result = process_signup({"email": "jane@example.com", "product_id": "p"}, supabase_client=supabase, systeme_client=systeme)

        assert any("Systeme.io" in w for w in result["warnings"])

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

    def test_trial_tag_differs_from_email_only_tag(self):
        supabase = _supabase_client_stub()
        systeme = MagicMock()

        process_signup({"email": "a@example.com", "product_id": "p", "signup_type": "trial"}, supabase_client=supabase, systeme_client=systeme)
        trial_tag = systeme.create_contact.call_args.kwargs["tags"][0]

        systeme.reset_mock()
        process_signup({"email": "b@example.com", "product_id": "p", "signup_type": "email_only"}, supabase_client=supabase, systeme_client=systeme)
        email_only_tag = systeme.create_contact.call_args.kwargs["tags"][0]

        assert trial_tag == "product_p_trial_active"
        assert email_only_tag == "product_p_interested"


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
# SystemeIOClient
# ──────────────────────────────────────────────────────────────────────────────

class TestSystemeIOClient:
    def test_create_contact_tags_after_creation(self):
        http = MagicMock()
        http.request.side_effect = [
            FakeResponse(200, {"id": "contact_1"}),
            FakeResponse(200, {}),
        ]
        client = SystemeIOClient(api_key="key", client=http)

        contact = client.create_contact("jane@example.com", tags=["product_p_interested"])

        assert contact["id"] == "contact_1"
        assert http.request.call_count == 2
        tag_call = http.request.call_args_list[1]
        assert tag_call.args[1] == "/contacts/contact_1/tags"

    def test_error_status_raises(self):
        http = MagicMock()
        http.request.return_value = FakeResponse(500, {"error": "boom"})
        client = SystemeIOClient(api_key="key", client=http)

        with pytest.raises(SystemeIOError):
            client.get_sequence_stats("seq_1")


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
        monkeypatch.delenv("SYSTEME_WEBHOOK_SECRET", raising=False)
        assert webhook_receiver.verify_webhook_secret(None) is True

    def test_secret_mismatch_rejected(self, monkeypatch):
        monkeypatch.setenv("SYSTEME_WEBHOOK_SECRET", "correct-secret")
        assert webhook_receiver.verify_webhook_secret("wrong") is False
        assert webhook_receiver.verify_webhook_secret("correct-secret") is True

    def test_handle_webhook_raises_on_bad_secret(self, monkeypatch):
        monkeypatch.setenv("SYSTEME_WEBHOOK_SECRET", "correct-secret")
        with pytest.raises(PermissionError):
            webhook_receiver.handle_webhook({"event": "contact.created", "data": {}}, secret_header="wrong")

    def test_contact_created_updates_lead(self, monkeypatch):
        monkeypatch.delenv("SYSTEME_WEBHOOK_SECRET", raising=False)
        supabase = _supabase_client_stub()

        result = webhook_receiver.handle_webhook(
            {"event": "contact.created", "data": {"email": "jane@example.com", "id": "contact_9", "product_id": "p"}},
            supabase_client=supabase,
        )

        assert result["status"] == "processed"
        update_call = supabase.table.return_value.update.call_args[0][0]
        assert update_call == {"systeme_contact_id": "contact_9"}

    def test_unrecognized_event_ignored(self, monkeypatch):
        monkeypatch.delenv("SYSTEME_WEBHOOK_SECRET", raising=False)
        result = webhook_receiver.handle_webhook({"event": "something.new", "data": {}})
        assert result["status"] == "ignored"
