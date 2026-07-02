"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
LinkedIn publisher — official Posts API only.

Uses the LinkedIn Posts API (v2) with OAuth 2.0 access tokens.
Only posts text content on behalf of the authenticated member.

COMPLIANCE BOUNDARY — the following are explicitly NOT implemented and
must NEVER be added to this file:
  - Connection request automation
  - Direct message (DM) sending
  - Auto-follow or auto-unfollow
  - Auto-engagement (likes, comments, reposts)
  - Profile scraping or data harvesting
  - Any action that reads as "automating engagement"
  - Browser session simulation or cookie injection

If any caller attempts to invoke functionality outside post_text(),
raise NotImplementedError with a compliance message.

Reference: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
"""

import logging
import httpx

log = logging.getLogger(__name__)

_POSTS_URL = "https://api.linkedin.com/rest/posts"
_LI_VERSION = "202501"   # LinkedIn API version header (YYYYMM)


async def post_text(
    access_token: str,
    author_urn: str,
    text: str,
) -> dict:
    """
    Post a text update to LinkedIn on behalf of the authenticated member.

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
    if len(text) > 3000:
        raise ValueError(f"LinkedIn post exceeds 3,000 character limit ({len(text)} chars)")

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

    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": _LI_VERSION,
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = client.post(_POSTS_URL, json=payload, headers=headers)
        response.raise_for_status()

    # LinkedIn returns the post URN in the X-RestLi-Id header
    post_urn = response.headers.get("x-restli-id", "")
    log.info("[LinkedIn] Posted successfully — URN: %s", post_urn)

    return {
        "post_id": post_urn,
        "url": f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else "",
    }


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
        response = client.get("https://api.linkedin.com/v2/userinfo", headers=headers)
        response.raise_for_status()

    data = response.json()
    sub = data.get("sub", "")
    if not sub:
        raise ValueError("LinkedIn userinfo did not return a 'sub' field")

    return f"urn:li:person:{sub}"
