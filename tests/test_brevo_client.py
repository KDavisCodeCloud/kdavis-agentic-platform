"""
leads/integrations/brevo_client.py — wrapper around the real brevo-python
SDK (v5.0.2), ported from kdavis-microsaas-engine's core/brevo_client.py
(the same provider swap made there 2026-08-14). The SDK client's
`contacts` namespace is mocked at the method level (MagicMock) — this
covers this module's own retry/error-handling logic, not Brevo's actual
live API behavior.
"""
from unittest.mock import MagicMock

import pytest
from brevo import BadRequestError, NotFoundError, TooManyRequestsError

import leads.integrations.brevo_client as bc


def _fake_client():
    return MagicMock()


def test_new_client_raises_configuration_error_when_key_missing(monkeypatch):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    with pytest.raises(bc.ConfigurationError, match="BREVO_API_KEY"):
        bc._new_client()


def test_create_or_update_contact_succeeds_with_valid_mock_response():
    client = _fake_client()
    client.contacts.create_contact.return_value = MagicMock(id=42)

    result = bc.create_or_update_contact(
        email="jane@example.com", first_name="Jane", last_name="Doe",
        attributes={"product_id": "cloud-decoded", "lead_stage": "trial_active"},
        list_ids=[7], brevo_client=client,
    )

    assert result == bc.BrevoContactResult(success=True, contact_id=42, error=None)
    call_kwargs = client.contacts.create_contact.call_args.kwargs
    assert call_kwargs["email"] == "jane@example.com"
    assert call_kwargs["attributes"] == {
        "FIRSTNAME": "Jane", "LASTNAME": "Doe", "PRODUCT_ID": "cloud-decoded", "LEAD_STAGE": "trial_active",
    }
    assert call_kwargs["list_ids"] == [7]
    assert call_kwargs["update_enabled"] is True


def test_create_or_update_contact_returns_typed_failure_on_api_error_without_raising():
    client = _fake_client()
    client.contacts.create_contact.side_effect = BadRequestError(body=MagicMock(message="Attribute not found"))

    result = bc.create_or_update_contact("jane@example.com", "Jane", "Doe", brevo_client=client)

    assert result.success is False
    assert result.error


def test_create_or_update_contact_handles_429_rate_limit_with_retry(monkeypatch):
    monkeypatch.setattr(bc.time, "sleep", lambda *_: None)
    client = _fake_client()
    client.contacts.create_contact.side_effect = [
        TooManyRequestsError(body="rate limited"),
        MagicMock(id=99),
    ]

    result = bc.create_or_update_contact("jane@example.com", "Jane", "Doe", brevo_client=client)

    assert result == bc.BrevoContactResult(success=True, contact_id=99, error=None)


def test_get_contact_returns_none_on_not_found():
    client = _fake_client()
    client.contacts.get_contact_info.side_effect = NotFoundError(body="not found")

    assert bc.get_contact("nobody@example.com", brevo_client=client) is None


def test_get_contact_converts_attributes_to_plain_dict():
    client = _fake_client()
    attrs = MagicMock()
    attrs.model_dump.return_value = {"LEAD_STAGE": "interested"}
    client.contacts.get_contact_info.return_value = MagicMock(
        email="jane@example.com", id=42, attributes=attrs, list_ids=[7],
    )

    contact = bc.get_contact("jane@example.com", brevo_client=client)

    assert contact == bc.BrevoContact(email="jane@example.com", id=42, attributes={"LEAD_STAGE": "interested"}, list_ids=[7])


def test_add_to_list_returns_false_on_api_error():
    client = _fake_client()
    client.contacts.add_contact_to_list.side_effect = BadRequestError(body="bad list id")

    assert bc.add_to_list("jane@example.com", 999, brevo_client=client) is False


def test_add_to_list_returns_true_on_success():
    client = _fake_client()
    client.contacts.add_contact_to_list.return_value = MagicMock()

    assert bc.add_to_list("jane@example.com", 7, brevo_client=client) is True


def test_get_lists_returns_empty_list_on_api_error():
    client = _fake_client()
    client.contacts.get_lists.side_effect = BadRequestError(body="boom")

    assert bc.get_lists(brevo_client=client) == []


def test_get_lists_converts_to_dataclasses():
    client = _fake_client()
    fake_list = MagicMock(id=1)
    fake_list.name = "Cloud Decoded Trials"  # "name" is a reserved MagicMock() kwarg, must set after construction
    client.contacts.get_lists.return_value = MagicMock(lists=[fake_list])

    result = bc.get_lists(brevo_client=client)

    assert result == [bc.BrevoList(id=1, name="Cloud Decoded Trials")]
