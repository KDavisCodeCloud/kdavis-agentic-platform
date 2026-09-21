"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Click tracking for the Cloud Decoded email lifecycle system (migration
051, cd_email_clicks). Every link in a marketing email's HTML body is
rewritten at SEND time (not at template-authoring time -- the send_id
that a click must be attributed to doesn't exist until the row is about
to be inserted) to point at GET /e/c/{token}, which records the click and
302s to the real destination with UTM params attached.

Reuses CD_UNSUBSCRIBE_SECRET as the HMAC key (core/unsubscribe_token.py)
rather than introducing a second secret env var -- same trust boundary
(this app's own outbound-link signing), no reason to split it.

Deliberately scoped: rewrites <a href="http(s)://..."> in the HTML body
(anything already an absolute http(s) link -- the compliance footer's
unsubscribe link is appended AFTER this runs, so it is never rewritten
and never counted as a marketing click). The plain-text body only gets
its single cta_url rewritten, if present, matching the "one CTA per
email" copy rule -- rewriting arbitrary bare URLs in plain text reliably
is not worth the false-positive risk this build's scope calls for.
"""

import base64
import hashlib
import hmac
import re
from typing import Optional
from urllib.parse import urlencode

from core.unsubscribe_token import hmac_secret

_HREF_RE = re.compile(r'href="(https?://[^"]+)"')


def make_click_token(send_id: str, url: str) -> str:
    payload = f"{send_id}|{url}".encode()
    sig = hmac.new(hmac_secret(), payload, hashlib.sha256).hexdigest()
    b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{b64}.{sig}"


def verify_click_token(token: str) -> Optional[tuple[str, str]]:
    """Returns (send_id, url) or None if the token is malformed or the
    signature doesn't match."""
    try:
        b64_payload, sig = token.split(".", 1)
        padded = b64_payload + "=" * (-len(b64_payload) % 4)
        payload = base64.urlsafe_b64decode(padded.encode()).decode()
    except Exception:
        return None

    expected = hmac.new(hmac_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None

    send_id, _, url = payload.partition("|")
    if not send_id or not url:
        return None
    return send_id, url


def _redirect_url(send_id: str, destination: str, api_base_url: str) -> str:
    token = make_click_token(send_id, destination)
    return f"{api_base_url}/api/v1/e/c/{token}"


def rewrite_links_html(html: str, send_id: str, api_base_url: str) -> str:
    def _replace(match: re.Match) -> str:
        return f'href="{_redirect_url(send_id, match.group(1), api_base_url)}"'
    return _HREF_RE.sub(_replace, html)


def rewrite_cta_text(text: str, send_id: str, cta_url: Optional[str], api_base_url: str) -> str:
    if not cta_url or cta_url not in text:
        return text
    return text.replace(cta_url, _redirect_url(send_id, cta_url, api_base_url))


def append_utm(url: str, utm_source: str, utm_medium: str, utm_campaign: str) -> str:
    separator = "&" if "?" in url else "?"
    params = urlencode({"utm_source": utm_source, "utm_medium": utm_medium, "utm_campaign": utm_campaign})
    return f"{url}{separator}{params}"
