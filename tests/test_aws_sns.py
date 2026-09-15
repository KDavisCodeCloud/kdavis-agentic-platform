"""
tests/test_aws_sns.py
Tests for core/aws_sns.py -- SNS subscription-confirmation handshake and
message signature verification, built for Agent 11's CloudWatch Alarm
ingestion path.

Signature verification is tested against a real, self-signed RSA
certificate generated at test time (not a mock of the crypto library) --
this proves the verify/sign round trip actually works, not just that the
code calls the right functions. What this can't prove: that AWS's real
SNS signing certificates parse and verify the same way -- that needs a
live SNS topic (see the build plan's Phase C verification section).
"""

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from core import aws_sns


def _self_signed_cert_and_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns-test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return cert, key


def _sign_message(message: dict, key) -> str:
    string_to_sign = aws_sns._build_string_to_sign(message)
    signature = key.sign(string_to_sign, padding.PKCS1v15(), hashes.SHA1())
    return base64.b64encode(signature).decode()


def _httpx_ctx(response) -> AsyncMock:
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    ctx.get = AsyncMock(return_value=response)
    return ctx


class TestBuildStringToSign:
    def test_notification_fields_in_documented_order(self):
        message = {
            "Type": "Notification", "MessageId": "id-1", "TopicArn": "arn:1",
            "Message": "hello", "Timestamp": "2026-01-01T00:00:00Z",
        }
        result = aws_sns._build_string_to_sign(message)
        assert result == b"Message\nhello\nMessageId\nid-1\nTimestamp\n2026-01-01T00:00:00Z\nTopicArn\narn:1\nType\nNotification\n"

    def test_subject_included_only_when_present(self):
        without_subject = aws_sns._build_string_to_sign({
            "Type": "Notification", "MessageId": "id-1", "TopicArn": "arn:1",
            "Message": "hello", "Timestamp": "t",
        })
        with_subject = aws_sns._build_string_to_sign({
            "Type": "Notification", "MessageId": "id-1", "TopicArn": "arn:1",
            "Message": "hello", "Timestamp": "t", "Subject": "an alarm fired",
        })
        assert b"Subject" not in without_subject
        assert b"Subject\nan alarm fired\n" in with_subject

    def test_subscription_confirmation_uses_subscribe_fields(self):
        message = {
            "Type": "SubscriptionConfirmation", "MessageId": "id-1", "TopicArn": "arn:1",
            "Message": "confirm", "Timestamp": "t", "Token": "tok-1",
            "SubscribeURL": "https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription",
        }
        result = aws_sns._build_string_to_sign(message)
        assert b"SubscribeURL" in result
        assert b"Token" in result


class TestVerifySignature:
    async def test_rejects_non_aws_cert_url(self):
        message = {"Type": "Notification", "SigningCertURL": "https://evil.example.com/cert.pem", "Signature": "abc"}
        assert await aws_sns.verify_signature(message) is False

    async def test_rejects_missing_signature(self):
        message = {"Type": "Notification", "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem"}
        assert await aws_sns.verify_signature(message) is False

    async def test_rejects_unparseable_base64_signature(self):
        message = {
            "Type": "Notification",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
            "Signature": "not valid base64!!!",
        }
        assert await aws_sns.verify_signature(message) is False

    async def test_valid_signature_verifies_true(self):
        cert, key = _self_signed_cert_and_key()
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)

        message = {
            "Type": "Notification", "MessageId": "id-1", "TopicArn": "arn:1",
            "Message": "hello", "Timestamp": "t",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
        }
        message["Signature"] = _sign_message(message, key)

        cert_resp = MagicMock(status_code=200, content=cert_pem)
        with patch("core.aws_sns.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _httpx_ctx(cert_resp)
            result = await aws_sns.verify_signature(message)

        assert result is True

    async def test_tampered_message_fails_verification(self):
        cert, key = _self_signed_cert_and_key()
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)

        message = {
            "Type": "Notification", "MessageId": "id-1", "TopicArn": "arn:1",
            "Message": "hello", "Timestamp": "t",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
        }
        message["Signature"] = _sign_message(message, key)
        message["Message"] = "tampered"  # signature no longer matches this content

        cert_resp = MagicMock(status_code=200, content=cert_pem)
        with patch("core.aws_sns.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _httpx_ctx(cert_resp)
            result = await aws_sns.verify_signature(message)

        assert result is False

    async def test_cert_fetch_failure_returns_false(self):
        message = {
            "Type": "Notification",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
            "Signature": base64.b64encode(b"whatever").decode(),
        }
        cert_resp = MagicMock(status_code=404, content=b"")
        with patch("core.aws_sns.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _httpx_ctx(cert_resp)
            result = await aws_sns.verify_signature(message)

        assert result is False


class TestConfirmSubscription:
    async def test_rejects_non_aws_url(self):
        result = await aws_sns.confirm_subscription("https://evil.example.com/subscribe")
        assert result is False

    async def test_confirms_on_200(self):
        resp = MagicMock(status_code=200)
        with patch("core.aws_sns.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _httpx_ctx(resp)
            result = await aws_sns.confirm_subscription("https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription")

        assert result is True

    async def test_fails_on_non_200(self):
        resp = MagicMock(status_code=500)
        with patch("core.aws_sns.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _httpx_ctx(resp)
            result = await aws_sns.confirm_subscription("https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription")

        assert result is False

    async def test_network_error_returns_false(self):
        import httpx as real_httpx

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(side_effect=real_httpx.RequestError("dns failed"))

        with patch("core.aws_sns.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = ctx
            result = await aws_sns.confirm_subscription("https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription")

        assert result is False
