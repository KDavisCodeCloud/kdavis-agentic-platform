"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Signed, stateless unsubscribe tokens for the Cloud Decoded email lifecycle
system (core/marketing_email.py, api/routes/email_public.py). No new
dependency (itsdangerous et al.) -- HMAC-SHA256 over the recipient email,
same "raise only on first real use, not at import time" convention as
leads/integrations/brevo_client.py's _new_client for a not-yet-configured
integration.

Token shape: base64url(email) + "." + hex(hmac_sha256(email, secret)).
Deliberately NOT time-limited -- an unsubscribe link must keep working
whenever the recipient finally opens the email, weeks later if need be;
there is no security reason to expire the ability to opt out.
"""

import base64
import hashlib
import hmac
import os
from typing import Optional


class UnsubscribeConfigError(RuntimeError):
    """Raised when CD_UNSUBSCRIBE_SECRET is not set. Callers that build
    outbound marketing email must treat this as fail-closed -- a marketing
    send with no working unsubscribe link is a compliance violation, not
    a degraded-but-acceptable state."""


def hmac_secret() -> bytes:
    secret = os.environ.get("CD_UNSUBSCRIBE_SECRET", "")
    if not secret:
        raise UnsubscribeConfigError(
            "CD_UNSUBSCRIBE_SECRET is not set -- cannot build a valid unsubscribe "
            "link, so no marketing email may be sent until this is configured"
        )
    return secret.encode()


def make_token(email: str) -> str:
    payload = email.strip().lower().encode()
    sig = hmac.new(hmac_secret(), payload, hashlib.sha256).hexdigest()
    b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{b64}.{sig}"


def verify_token(token: str) -> Optional[str]:
    """Returns the lowercased email the token was issued for, or None if
    the token is malformed or the signature doesn't match."""
    try:
        b64_payload, sig = token.split(".", 1)
        padded = b64_payload + "=" * (-len(b64_payload) % 4)
        payload = base64.urlsafe_b64decode(padded.encode())
    except Exception:
        return None

    expected = hmac.new(hmac_secret(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    return payload.decode()
