"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Resend webhook signature verification (Svix-compatible -- Resend signs
webhooks via Svix, per Resend's own docs as of this writing). No `svix`
package dependency added -- this is a small, self-contained HMAC check
matching Svix's documented scheme: signed content is
"{svix-id}.{svix-timestamp}.{raw body}", HMAC-SHA256 with the base64
portion of the whsec_-prefixed secret, base64-encoded, compared against
one of the space-separated "v1,<sig>" entries in the svix-signature
header.

HONEST GAP (see GAPS.md): this has NOT been verified against a real,
live Resend webhook delivery this session -- Kelvin still needs to
configure the webhook in the Resend dashboard (Kelvin-only action) before
a real payload can exercise this. If Resend's actual header names or
signed-content format differ from what's implemented here, this will
reject every real webhook until corrected against a real delivery.
"""

import base64
import hashlib
import hmac
import os


class WebhookVerificationError(Exception):
    """Raised when RESEND_WEBHOOK_SECRET is unset, required headers are
    missing, or the signature doesn't match."""


def verify_resend_webhook(payload: bytes, headers: dict) -> None:
    secret = os.environ.get("RESEND_WEBHOOK_SECRET", "")
    if not secret:
        raise WebhookVerificationError("RESEND_WEBHOOK_SECRET is not set")

    svix_id = headers.get("svix-id", "")
    svix_timestamp = headers.get("svix-timestamp", "")
    svix_signature = headers.get("svix-signature", "")
    if not (svix_id and svix_timestamp and svix_signature):
        raise WebhookVerificationError("Missing svix-id/svix-timestamp/svix-signature headers")

    secret_bytes = base64.b64decode(secret.split("_", 1)[1]) if secret.startswith("whsec_") else secret.encode()
    signed_content = f"{svix_id}.{svix_timestamp}.{payload.decode()}".encode()
    expected_sig = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode()

    provided_sigs = [part.split(",", 1)[1] for part in svix_signature.split() if "," in part]
    if not any(hmac.compare_digest(expected_sig, sig) for sig in provided_sigs):
        raise WebhookVerificationError("Signature mismatch")
