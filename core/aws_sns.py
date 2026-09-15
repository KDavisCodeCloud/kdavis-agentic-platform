"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

AWS SNS HTTP(S) subscription handling -- built for Agent 11 (Cloud Resource
Health Monitoring, Phase C): CloudWatch Alarms publish to an SNS topic,
which delivers to api/routes/webhooks.py's /resource-health-alert endpoint
as a plain HTTP POST. This module handles the two message types that
matter here:

  SubscriptionConfirmation -- AWS sends this once, right after a customer
    subscribes our webhook URL to their SNS topic. Nothing is delivered
    until the SubscribeURL in this message is visited once. confirm_subscription()
    does that.

  Notification -- the actual CloudWatch Alarm payload, JSON-encoded inside
    the "Message" field. verify_signature() must pass before this is
    trusted -- an unauthenticated caller could otherwise POST a fake alarm
    to this endpoint and get Agent 11 to open a PR/issue against a
    workspace's repo.

Signature verification follows AWS's documented SNS message signing
algorithm (signature version 1, SHA1WithRSA -- SNS's default and the only
version most topics use as of this writing): build the exact
newline-delimited string described in AWS's docs from specific fields
present per message Type, fetch the signing certificate from
SigningCertURL (validated against AWS's own domain pattern first -- never
fetch and trust an arbitrary URL an attacker could supply in the payload),
and verify the base64-decoded Signature against that string with the
certificate's RSA public key.

This has NOT been live-verified against a real SNS topic in this
codebase -- implemented directly from AWS's published spec. The
subscription-confirmation round trip specifically needs a real SNS topic
to verify (see the build plan's Phase C verification section); do not
treat this as production-hardened until that's been done.
"""

import base64
import logging
import re

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

log = logging.getLogger(__name__)

_MAX_HTTP_TIMEOUT = 15

# AWS-owned SNS endpoints only -- e.g. sns.us-east-1.amazonaws.com. Never
# fetch a SigningCertURL that doesn't match this: the payload is otherwise
# fully attacker-controlled, including this URL.
_SNS_CERT_URL_RE = re.compile(r"^https://sns\.[a-z0-9-]+\.amazonaws\.com/", re.IGNORECASE)

# Field sets to sign, per AWS's documented algorithm -- order matters,
# these become alternating key\nvalue\n lines in the string-to-sign.
_NOTIFICATION_FIELDS = ("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type")
_SUBSCRIBE_FIELDS = ("Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type")


class SnsVerificationError(Exception):
    """Raised when an SNS message's signature can't be verified -- callers
    must treat this the same as any other webhook auth failure: reject the
    request, never process the payload."""


def _build_string_to_sign(message: dict) -> bytes:
    msg_type = message.get("Type", "")
    fields = _SUBSCRIBE_FIELDS if msg_type == "SubscriptionConfirmation" else _NOTIFICATION_FIELDS

    lines = []
    for field in fields:
        if field == "Subject" and "Subject" not in message:
            continue  # Subject is only signed when present, per AWS's spec
        if field not in message:
            continue
        lines.append(field)
        lines.append(str(message[field]))

    return ("\n".join(lines) + "\n").encode("utf-8")


async def verify_signature(message: dict) -> bool:
    """
    Verifies an SNS message's signature against its SigningCertURL.
    Returns True if valid, False if invalid. Never raises for a bad
    signature -- only for a malformed message (missing required fields)
    or an unreachable/untrusted cert URL, both of which are also just
    "reject this request" from the caller's perspective.
    """
    cert_url = message.get("SigningCertURL", "")
    if not _SNS_CERT_URL_RE.match(cert_url):
        log.warning("[SNS] Rejected SigningCertURL not on an AWS-owned domain: %s", cert_url)
        return False

    signature_b64 = message.get("Signature", "")
    if not signature_b64:
        return False

    try:
        signature = base64.b64decode(signature_b64)
    except (ValueError, TypeError):
        return False

    string_to_sign = _build_string_to_sign(message)

    async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
        try:
            resp = await client.get(cert_url)
        except httpx.RequestError as exc:
            log.warning("[SNS] Could not fetch signing certificate: %s", exc)
            return False

    if resp.status_code != 200:
        log.warning("[SNS] Signing certificate fetch failed (%s)", resp.status_code)
        return False

    try:
        cert = x509.load_pem_x509_certificate(resp.content)
        public_key = cert.public_key()
        public_key.verify(signature, string_to_sign, padding.PKCS1v15(), hashes.SHA1())
        return True
    except InvalidSignature:
        return False
    except (ValueError, TypeError) as exc:
        log.warning("[SNS] Could not verify signature: %s", exc)
        return False


async def confirm_subscription(subscribe_url: str) -> bool:
    """
    Visits the SubscribeURL from a SubscriptionConfirmation message once --
    this is what actually activates delivery from the SNS topic. Only call
    this after verify_signature() has already passed for the message that
    contained this URL.
    """
    if not _SNS_CERT_URL_RE.match(subscribe_url):
        log.warning("[SNS] Refusing to confirm subscription at non-AWS URL: %s", subscribe_url)
        return False

    async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
        try:
            resp = await client.get(subscribe_url)
        except httpx.RequestError as exc:
            log.warning("[SNS] Could not confirm subscription: %s", exc)
            return False

    if resp.status_code != 200:
        log.warning("[SNS] Subscription confirmation request failed (%s)", resp.status_code)
        return False

    log.info("[SNS] Subscription confirmed")
    return True
