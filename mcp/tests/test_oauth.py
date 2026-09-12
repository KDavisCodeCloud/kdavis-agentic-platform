"""
Tests for auth/oauth.py -- the Enterprise-tier auth path. Previously zero
coverage. Uses a real HS256-signed JWT (PyJWT), not a mock, since the whole
point of this module is verifying a real signature/audience/claims contract.
"""

import time
from unittest.mock import patch

import jwt
import pytest

from auth.models import AuthError
from auth.oauth import validate_oauth_token

TEST_SECRET = "test-jwt-secret"  # matches conftest.py's SUPABASE_JWT_SECRET
TEST_AUDIENCE = "mcp.theclouddecoded.com"  # matches conftest.py's MCP_AUDIENCE


def _make_token(**claim_overrides) -> str:
    claims = {
        "sub": "user-123",
        "aud": TEST_AUDIENCE,
        "exp": int(time.time()) + 3600,
        "app_metadata": {
            "workspace_id": "ws-abc",
            "workspace_tier": "enterprise",
            "mcp_scopes": ["mcp:read", "mcp:write"],
        },
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, TEST_SECRET, algorithm="HS256")


class TestValidateOauthToken:
    async def test_accepts_valid_token(self):
        identity = await validate_oauth_token(_make_token())
        assert identity.workspace_id == "ws-abc"
        assert identity.workspace_tier == "enterprise"
        assert identity.auth_method == "oauth"
        assert identity.scopes == frozenset({"mcp:read", "mcp:write"})
        assert identity.subject == "user-123"
        assert identity.user_id == "user-123"

    async def test_rejects_expired_token(self):
        token = _make_token(exp=int(time.time()) - 10)
        with pytest.raises(AuthError, match="expired"):
            await validate_oauth_token(token)

    async def test_rejects_wrong_audience(self):
        token = _make_token(aud="some-other-service")
        with pytest.raises(AuthError, match="audience"):
            await validate_oauth_token(token)

    async def test_rejects_bad_signature(self):
        token = jwt.encode(
            {"sub": "x", "aud": TEST_AUDIENCE, "exp": int(time.time()) + 3600},
            "wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(AuthError):
            await validate_oauth_token(token)

    async def test_rejects_missing_sub(self):
        claims = {
            "aud": TEST_AUDIENCE,
            "exp": int(time.time()) + 3600,
            "app_metadata": {"workspace_id": "ws-abc"},
        }
        token = jwt.encode(claims, TEST_SECRET, algorithm="HS256")
        with pytest.raises(AuthError, match="sub"):
            await validate_oauth_token(token)

    async def test_rejects_missing_workspace_id(self):
        token = _make_token(app_metadata={"workspace_tier": "enterprise"})
        with pytest.raises(AuthError, match="workspace_id"):
            await validate_oauth_token(token)

    async def test_defaults_tier_to_starter_when_missing(self):
        token = _make_token(app_metadata={"workspace_id": "ws-abc"})
        identity = await validate_oauth_token(token)
        assert identity.workspace_tier == "starter"

    async def test_unknown_scopes_are_dropped_and_defaults_to_read(self):
        token = _make_token(app_metadata={"workspace_id": "ws-abc", "mcp_scopes": ["mcp:delete_everything"]})
        identity = await validate_oauth_token(token)
        assert identity.scopes == frozenset({"mcp:read"})

    async def test_workspace_id_from_top_level_claim_as_fallback(self):
        """Custom JWT templates may place workspace_id at the top level
        instead of app_metadata -- both are documented as supported."""
        token = _make_token(app_metadata={}, workspace_id="ws-top-level")
        identity = await validate_oauth_token(token)
        assert identity.workspace_id == "ws-top-level"

    async def test_missing_secret_raises_server_misconfiguration(self):
        with patch("auth.oauth.SUPABASE_JWT_SECRET", ""):
            with pytest.raises(AuthError, match="misconfiguration") as exc:
                await validate_oauth_token(_make_token())
            assert exc.value.status_code == 500
