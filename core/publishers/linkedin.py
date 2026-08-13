"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

LinkedIn publisher — official Posts API + Images API only.

Uses the LinkedIn Posts API (v2) with OAuth 2.0 access tokens. Posts
text content, optionally with a single attached image, on behalf of
the authenticated member. Image attachment uses LinkedIn's documented
Images API (register upload -> upload binary -> reference the
resulting image URN in the post), never anything undocumented.

COMPLIANCE BOUNDARY — the following are explicitly NOT implemented and
must NEVER be added to this file:
  - Connection request automation
  - Direct message (DM) sending
  - Auto-follow or auto-unfollow
  - Auto-engagement (likes, comments, reposts)
  - Profile scraping or data harvesting
  - Any action that reads as "automating engagement"
  - Browser session simulation or cookie injection

If any caller attempts to invoke functionality outside post_text() /
post_image(), raise NotImplementedError with a compliance message.
Attaching an image to your own authored post is a standard, documented
use of the same Posts API already in use here — it does not cross the
boundary above, which is about engagement automation, not media.

Reference: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
Reference: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api
"""

import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

_POSTS_URL = "https://api.linkedin.com/rest/posts"
_IMAGES_URL = "https://api.linkedin.com/rest/images"
_TEXT_LIMIT = 3000

# LinkedIn's REST API version header is YYYYMM and has no "latest" alias
# (confirmed with LinkedIn support docs and by hitting the API directly).
# A hardcoded version string goes stale and silently kills every publish —
# this is the second time it's happened: a version bumped 2026-07-21 used
# "202507" (July *2025*, a year-old off-by-one-year mistake) and every
# dispatch run failed with 426 NONEXISTENT_VERSION until caught live
# 2026-08-04. Rather than hardcode another string that will go stale the
# same way, _resolve_version() computes candidates from the real clock and
# _request_with_version_fallback() below tries them in order, live, on
# every cold start — confirmed live 2026-08-04 that the labeled *current*
# month (202608) is not active yet but the prior 3 months all are, so this
# always has real headroom. The working version is cached in-process so a
# single dispatch run (multiple posts) only pays the retry cost once.
_working_version: str | None = None


def _candidate_versions() -> list[str]:
    now = datetime.now(timezone.utc)
    versions = []
    for months_back in range(0, 5):  # current month first, then 4 months back
        y, m = now.year, now.month - months_back
        while m <= 0:
            m += 12
            y -= 1
        versions.append(f"{y:04d}{m:02d}")
    return versions


def _headers(access_token: str, version: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": version,
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


async def _request_with_version_fallback(
    client: httpx.AsyncClient, method: str, url: str, access_token: str, **kwargs,
) -> httpx.Response:
    """
    Sends one request, retrying with progressively older LinkedIn-Version
    values only when LinkedIn's own response says the version itself is
    the problem (426 NONEXISTENT_VERSION) — any other error (auth, rate
    limit, bad payload) is never retried here, it raises immediately via
    raise_for_status() so it surfaces as a real PublishError, never masked
    as a version issue.
    """
    global _working_version
    candidates = [_working_version] + _candidate_versions() if _working_version else _candidate_versions()
    send = client.get if method == "GET" else client.post

    last_response: httpx.Response | None = None
    for version in candidates:
        response = await send(url, headers=_headers(access_token, version), **kwargs)
        if response.status_code == 426 and "NONEXISTENT_VERSION" in response.text:
            last_response = response
            continue
        _working_version = version
        response.raise_for_status()
        return response

    # Every candidate was rejected as a nonexistent version -- raise the
    # last real response so the error message shows LinkedIn's own text,
    # not a generic "all retries failed."
    assert last_response is not None
    last_response.raise_for_status()
    raise AssertionError("unreachable")  # raise_for_status() above always raises on a 426


async def _create_post(access_token: str, payload: dict) -> dict:
    """
    Shared POST-to-/rest/posts + response-shape logic for post_text()
    and post_image() — both send the same envelope, differing only in
    whether payload["content"] is present.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        response = await _request_with_version_fallback(client, "POST", _POSTS_URL, access_token, json=payload)

    # LinkedIn returns the post URN in the X-RestLi-Id header, not the body.
    post_urn = response.headers.get("x-restli-id", "")
    log.info("[LinkedIn] Posted successfully — URN: %s", post_urn)

    return {
        "post_id": post_urn,
        "url": f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else "",
    }


async def post_text(
    access_token: str,
    author_urn: str,
    text: str,
) -> dict:
    """
    Post a text-only update to LinkedIn on behalf of the authenticated member.

    Args:
        access_token:  OAuth 2.0 access token with w_member_social scope
        author_urn:    LinkedIn member URN — format "urn:li:person:{id}"
                       Obtained during OAuth callback via /v2/userinfo
        text:          The post body text (max 3,000 characters)

    Returns:
        {"post_id": "urn:li:share:...", "url": "https://www.linkedin.com/feed/update/..."}

    Raises:
        ValueError:   If text exceeds 3,000 characters
        httpx.HTTPStatusError: On API error (non-2xx)
    """
    if len(text) > _TEXT_LIMIT:
        raise ValueError(f"LinkedIn post exceeds {_TEXT_LIMIT} character limit ({len(text)} chars)")

    payload = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    return await _create_post(access_token, payload)


async def register_image_upload(access_token: str, author_urn: str) -> tuple[str, str]:
    """
    Step 1 of image posting — registers an upload with LinkedIn and gets
    back a pre-signed upload URL plus the image URN that will identify
    it once uploaded.

    Returns: (upload_url, image_urn) — pass both to upload_image_binary()
    and post_image() respectively.
    """
    payload = {"initializeUploadRequest": {"owner": author_urn}}

    async with httpx.AsyncClient(timeout=30) as client:
        response = await _request_with_version_fallback(
            client, "POST", f"{_IMAGES_URL}?action=initializeUpload", access_token, json=payload,
        )

    value = response.json()["value"]
    upload_url = value["uploadUrl"]
    image_urn = value["image"]
    log.info("[LinkedIn] Image upload registered — URN: %s", image_urn)
    return upload_url, image_urn


async def upload_image_binary(upload_url: str, image_bytes: bytes) -> None:
    """
    Step 2 of image posting — PUTs the raw image bytes to the pre-signed
    URL from register_image_upload(). No LinkedIn auth headers here —
    the upload URL itself is the credential, per LinkedIn's Images API.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.put(upload_url, content=image_bytes)
        response.raise_for_status()
    log.info("[LinkedIn] Image binary uploaded (%d bytes)", len(image_bytes))


async def post_image(
    access_token: str,
    author_urn: str,
    text: str,
    image_bytes: bytes,
    alt_text: str = "",
) -> dict:
    """
    Post an update with a single attached image, on behalf of the
    authenticated member. Runs the full 3-step LinkedIn flow: register
    upload -> upload binary -> create post referencing the image URN.

    Args:
        access_token:  OAuth 2.0 access token with w_member_social scope
        author_urn:    LinkedIn member URN — format "urn:li:person:{id}"
        text:          The post body text (max 3,000 characters)
        image_bytes:   Raw image file bytes (PNG/JPEG)
        alt_text:      Optional accessibility text for the image

    Returns:
        {"post_id": "urn:li:share:...", "url": "https://www.linkedin.com/feed/update/..."}

    Raises:
        ValueError:   If text exceeds 3,000 characters
        httpx.HTTPStatusError: On API error (non-2xx) at any of the 3 steps
    """
    if len(text) > _TEXT_LIMIT:
        raise ValueError(f"LinkedIn post exceeds {_TEXT_LIMIT} character limit ({len(text)} chars)")

    upload_url, image_urn = await register_image_upload(access_token, author_urn)
    await upload_image_binary(upload_url, image_bytes)

    payload = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {
            "media": {"id": image_urn, "title": alt_text} if alt_text else {"id": image_urn},
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    return await _create_post(access_token, payload)


async def get_author_urn(access_token: str) -> str:
    """
    Fetch the member's URN from the LinkedIn userinfo endpoint.
    Called once during OAuth callback to store the author URN.

    Returns: "urn:li:person:{id}"
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await _request_with_version_fallback(
            client, "GET", "https://api.linkedin.com/v2/userinfo", access_token,
        )

    data = response.json()
    sub = data.get("sub", "")
    if not sub:
        raise ValueError("LinkedIn userinfo did not return a 'sub' field")

    return f"urn:li:person:{sub}"
