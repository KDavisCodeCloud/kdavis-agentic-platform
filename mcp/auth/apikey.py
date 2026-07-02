"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
API key validation for MCP server auth (Starter + Growth tiers only).

Key format:  cd_mcp_<22 random base64url chars>
             e.g. cd_mcp_X7gKpL2mNqRsT4vW8yZa1b

Storage:     SHA-256 hash stored in mcp_api_keys. Raw key never stored.
Display:     First 12 chars of the raw key stored as key_prefix for UI display.
Expiry:      Hard enforced — max 90 days. No infinite-lifetime keys.
Tier rule:   Enterprise workspaces are rejected here — OAuth 2.1 required.

Per-request: look up hash, check revoked/expired, touch last_used_at.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timezone

import asyncpg

from config import OAUTH_REQUIRED_TIERS
from auth.models import CallerIdentity, AuthError

log = logging.getLogger(__name__)

API_KEY_PREFIX   = "cd_mcp_"
API_KEY_RAND_LEN = 22   # random suffix bytes (base64url → ~30 chars)
MAX_EXPIRY_DAYS  = 90


def generate_raw_key() -> str:
    """
    Generate a new raw API key. Called by the dashboard API route that
    creates keys — never called during validation.

    Returns the raw key (shown to user once, never stored).
    """
    rand = secrets.token_urlsafe(API_KEY_RAND_LEN)
    return f"{API_KEY_PREFIX}{rand}"


def hash_key(raw_key: str) -> str:
    """SHA-256 the raw key. This is what gets stored and compared."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def key_prefix(raw_key: str) -> str:
    """First 12 chars of the raw key — safe to store, used for UI display."""
    return raw_key[:12]


async def validate_api_key(raw_key: str, db_pool: asyncpg.Pool) -> CallerIdentity:
    """
    Validate an API key by hashing it and looking up the hash in the DB.

    Rejects:
      - Keys not starting with cd_mcp_
      - Unknown hash (not in DB)
      - Revoked keys
      - Expired keys
      - Enterprise-tier workspaces (must use OAuth 2.1)
    """
    if not raw_key.startswith(API_KEY_PREFIX):
        raise AuthError("Invalid API key format")

    key_hash = hash_key(raw_key)
    now = datetime.now(timezone.utc)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT k.id,
                   k.workspace_id,
                   k.scopes,
                   k.expires_at,
                   k.revoked_at,
                   w.product_tier
            FROM   mcp_api_keys k
            JOIN   workspaces w ON w.id = k.workspace_id
            WHERE  k.key_hash = $1
            """,
            key_hash,
        )

    if not row:
        # Constant-time non-response — don't leak whether key existed
        raise AuthError("Invalid API key")

    if row["revoked_at"] is not None:
        raise AuthError("API key has been revoked")

    if row["expires_at"] < now:
        raise AuthError("API key has expired")

    tier: str = row["product_tier"]

    if tier in OAUTH_REQUIRED_TIERS:
        raise AuthError(
            f"Enterprise tier requires OAuth 2.1 authentication. "
            f"API keys are not permitted for Enterprise workspaces.",
            status_code=403,
        )

    # Fire-and-forget last_used_at update — don't block the request on it
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE mcp_api_keys SET last_used_at = NOW() WHERE id = $1",
            row["id"],
        )

    return CallerIdentity(
        workspace_id=str(row["workspace_id"]),
        workspace_tier=tier,
        auth_method="api_key",
        scopes=frozenset(row["scopes"]),
        subject=str(row["id"]),
        api_key_id=str(row["id"]),
    )
