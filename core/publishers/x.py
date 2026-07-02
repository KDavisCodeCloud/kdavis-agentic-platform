"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
X (Twitter) publisher — official API v2 only.

Posts tweets on behalf of the authenticated user via the X API v2
/2/tweets endpoint using OAuth 2.0 with PKCE (user context).

COMPLIANCE BOUNDARY — the following are explicitly NOT implemented and
must NEVER be added to this file:
  - Direct message (DM) sending
  - Auto-follow or auto-unfollow
  - Auto-like, auto-retweet, or any engagement automation
  - Profile scraping or follower/following data harvesting
  - Browser session simulation or cookie injection
  - Storing X account passwords

X policy explicitly prohibits automation of social actions beyond
content publishing. This file only implements tweet creation.

Reference: https://developer.x.com/en/docs/x-api/tweets/manage-tweets/api-reference/post-tweets
"""

import logging
import httpx

log = logging.getLogger(__name__)

_TWEETS_URL = "https://api.twitter.com/2/tweets"
_X_CHAR_LIMIT = 280


async def post_tweet(
    access_token: str,
    text: str,
) -> dict:
    """
    Post a tweet via X API v2 on behalf of the authenticated user.

    Args:
        access_token:  OAuth 2.0 Bearer access token with tweet.write scope
        text:          Tweet text (max 280 characters)

    Returns:
        {"post_id": "...", "url": "https://x.com/i/web/status/..."}

    Raises:
        ValueError:   If text exceeds 280 characters
        httpx.HTTPStatusError: On API error (non-2xx)
    """
    if len(text) > _X_CHAR_LIMIT:
        raise ValueError(f"Tweet exceeds 280 character limit ({len(text)} chars)")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = client.post(_TWEETS_URL, json={"text": text}, headers=headers)
        response.raise_for_status()

    data = response.json().get("data", {})
    tweet_id = data.get("id", "")
    log.info("[X] Posted tweet — id: %s", tweet_id)

    return {
        "post_id": tweet_id,
        "url": f"https://x.com/i/web/status/{tweet_id}" if tweet_id else "",
    }
