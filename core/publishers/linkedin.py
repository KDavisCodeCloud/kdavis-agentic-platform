"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
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
import httpx

log = logging.getLogger(__name__)

_POSTS_URL = "https://api.linkedin.com/rest/posts"
_IMAGES_URL = "https://api.linkedin.com/rest/images"
_LI_VERSION = "202507"   # LinkedIn API version header (YYYYMM) — LinkedIn
# deprecates versions ~12 months after release. Confirmed live 2026-07-21
# against a real API call after 202501 started failing with 426
# NONEXISTENT_VERSION ("Requested version 20250101 is not active"). Bump
# this again if it starts failing the same way — LinkedIn does not appear
# to offer a "latest" alias, so this needs occasional manual updates.
_TEXT_LIMIT = 3000


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": _LI_VERSION,
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


async def _create_post(access_token: str, payload: dict) -> dict:
    """
    Shared POST-to-/rest/posts + response-shape logic for post_text()
    and post_image() — both send the same envelope, differing only in
    whether payload["content"] is present.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(_POSTS_URL, json=payload, headers=_headers(access_token))
        response.raise_for_status()

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
        response = await client.post(
            f"{_IMAGES_URL}?action=initializeUpload",
            json=payload,
            headers=_headers(access_token),
        )
        response.raise_for_status()

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
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": _LI_VERSION,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get("https://api.linkedin.com/v2/userinfo", headers=headers)
        response.raise_for_status()

    data = response.json()
    sub = data.get("sub", "")
    if not sub:
        raise ValueError("LinkedIn userinfo did not return a 'sub' field")

    return f"urn:li:person:{sub}"
