"""
Tests for auth/apikey.py -- the real customer auth path for Starter/Growth
workspaces (Enterprise is OAuth-only, see auth/oauth.py). Previously zero
test coverage existed anywhere in mcp/, despite this being the exact
function every non-Enterprise MCP tool call runs through.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from auth.apikey import (
    API_KEY_PREFIX,
    generate_raw_key,
    hash_key,
    key_prefix,
    validate_api_key,
)
from auth.models import AuthError


def _make_pool(row: dict | None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    conn.execute = AsyncMock()
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return pool, conn


def _row(**overrides) -> dict:
    base = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "scopes": ["mcp:read"],
        "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
        "revoked_at": None,
        "product_tier": "growth",
    }
    base.update(overrides)
    return base


class TestKeyGeneration:
    def test_generate_raw_key_has_prefix(self):
        key = generate_raw_key()
        assert key.startswith(API_KEY_PREFIX)

    def test_generate_raw_key_is_unique(self):
        assert generate_raw_key() != generate_raw_key()

    def test_hash_key_is_deterministic(self):
        key = generate_raw_key()
        assert hash_key(key) == hash_key(key)

    def test_hash_key_differs_for_different_keys(self):
        assert hash_key(generate_raw_key()) != hash_key(generate_raw_key())

    def test_key_prefix_is_first_12_chars(self):
        key = generate_raw_key()
        assert key_prefix(key) == key[:12]
        assert len(key_prefix(key)) == 12


class TestValidateApiKey:
    async def test_rejects_wrong_prefix(self):
        pool, _ = _make_pool(None)
        with pytest.raises(AuthError, match="Invalid API key format"):
            await validate_api_key("sk_live_notanmcpkey", pool)

    async def test_rejects_unknown_key(self):
        pool, _ = _make_pool(None)
        with pytest.raises(AuthError, match="Invalid API key"):
            await validate_api_key(f"{API_KEY_PREFIX}doesnotexist", pool)

    async def test_rejects_revoked_key(self):
        pool, _ = _make_pool(_row(revoked_at=datetime.now(timezone.utc)))
        with pytest.raises(AuthError, match="revoked"):
            await validate_api_key(f"{API_KEY_PREFIX}revoked", pool)

    async def test_rejects_expired_key(self):
        pool, _ = _make_pool(_row(expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
        with pytest.raises(AuthError, match="expired"):
            await validate_api_key(f"{API_KEY_PREFIX}expired", pool)

    async def test_rejects_enterprise_tier(self):
        """The real tier gate: Enterprise must use OAuth 2.1, never an API key."""
        pool, _ = _make_pool(_row(product_tier="enterprise"))
        with pytest.raises(AuthError, match="OAuth 2.1") as exc:
            await validate_api_key(f"{API_KEY_PREFIX}entkey", pool)
        assert exc.value.status_code == 403

    @pytest.mark.parametrize("tier", ["starter", "growth"])
    async def test_accepts_valid_non_enterprise_key(self, tier):
        row = _row(product_tier=tier)
        pool, _ = _make_pool(row)
        identity = await validate_api_key(f"{API_KEY_PREFIX}valid", pool)
        assert identity.workspace_id == str(row["workspace_id"])
        assert identity.workspace_tier == tier
        assert identity.auth_method == "api_key"
        assert identity.scopes == frozenset({"mcp:read"})
        assert identity.api_key_id == str(row["id"])

    async def test_touches_last_used_at_on_success(self):
        row = _row()
        pool, conn = _make_pool(row)
        await validate_api_key(f"{API_KEY_PREFIX}valid", pool)
        conn.execute.assert_awaited_once()
        sql = conn.execute.await_args.args[0]
        assert "last_used_at" in sql

    async def test_does_not_leak_hash_or_raw_key_lookup(self):
        """The query looks up by hash, never by the raw key value."""
        row = _row()
        pool, conn = _make_pool(row)
        raw_key = f"{API_KEY_PREFIX}sometoken"
        await validate_api_key(raw_key, pool)
        bound_hash = conn.fetchrow.await_args.args[1]
        assert bound_hash == hash_key(raw_key)
        assert bound_hash != raw_key
