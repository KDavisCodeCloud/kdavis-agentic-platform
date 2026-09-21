"""
tests/test_resend_webhook.py
core/resend_webhook.py -- Svix-compatible signature verification.
HONEST GAP: this exercises the implemented HMAC scheme against itself,
not against a real Resend delivery -- see that module's own docstring
for the live-verification gap tracked in GAPS.md.
"""

import base64
import hashlib
import hmac

import pytest

from core.resend_webhook import WebhookVerificationError, verify_resend_webhook


def _sign(secret_b64: str, svix_id: str, svix_timestamp: str, payload: bytes) -> str:
    secret_bytes = base64.b64decode(secret_b64)
    signed_content = f"{svix_id}.{svix_timestamp}.{payload.decode()}".encode()
    sig = base64.b64encode(hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()).decode()
    return f"v1,{sig}"


class TestVerifyResendWebhook:
    def test_valid_signature_passes(self, monkeypatch):
        secret_b64 = base64.b64encode(b"a-test-signing-key").decode()
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", f"whsec_{secret_b64}")
        payload = b'{"type":"email.bounced"}'
        headers = {
            "svix-id": "msg_1", "svix-timestamp": "1700000000",
            "svix-signature": _sign(secret_b64, "msg_1", "1700000000", payload),
        }
        verify_resend_webhook(payload, headers)  # must not raise

    def test_wrong_secret_rejected(self, monkeypatch):
        secret_b64 = base64.b64encode(b"a-test-signing-key").decode()
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", f"whsec_{secret_b64}")
        payload = b'{"type":"email.bounced"}'
        wrong_sig = _sign(base64.b64encode(b"different-key").decode(), "msg_1", "1700000000", payload)
        headers = {"svix-id": "msg_1", "svix-timestamp": "1700000000", "svix-signature": wrong_sig}
        with pytest.raises(WebhookVerificationError):
            verify_resend_webhook(payload, headers)

    def test_missing_secret_rejected(self, monkeypatch):
        monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)
        with pytest.raises(WebhookVerificationError):
            verify_resend_webhook(b"{}", {"svix-id": "x", "svix-timestamp": "1", "svix-signature": "v1,x"})

    def test_missing_headers_rejected(self, monkeypatch):
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_" + base64.b64encode(b"x").decode())
        with pytest.raises(WebhookVerificationError):
            verify_resend_webhook(b"{}", {})

    def test_tampered_payload_rejected(self, monkeypatch):
        secret_b64 = base64.b64encode(b"a-test-signing-key").decode()
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", f"whsec_{secret_b64}")
        payload = b'{"type":"email.bounced"}'
        sig = _sign(secret_b64, "msg_1", "1700000000", payload)
        headers = {"svix-id": "msg_1", "svix-timestamp": "1700000000", "svix-signature": sig}
        with pytest.raises(WebhookVerificationError):
            verify_resend_webhook(b'{"type":"email.complained"}', headers)
