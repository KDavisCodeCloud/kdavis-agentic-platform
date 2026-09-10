"""
tests/test_rate_limiter.py
Tests for api/middleware/rate_limiter.py — specifically GAPS.md gap #5:
_tier_limit used to take `request: Request`, but slowapi==0.1.9's
LimitGroup.__iter__ only ever calls a callable limit-value provider as
fn(key) or fn(), never fn(request). That crashed every call to
POST /api/v1/agents/{agent_id}/run with a TypeError the moment a real
workspace existed to authenticate against (discovered 2026-09-10).

What this file validates:
  - _workspace_key embeds the tier from request.state.workspace_tier into
    the key, and falls back to the caller's IP when there's no token
  - _tier_limit parses the tier back out of that key correctly, including
    the "ws" prefix and the IP-fallback (non-"ws") case
  - the full @limiter.limit(_tier_limit) decorator actually works end to
    end through a real Starlette Request (via TestClient) — this is
    exactly the integration point that unit-testing the plain functions
    alone had missed, letting the bug ship unnoticed
"""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.middleware.rate_limiter import _tier_limit, _workspace_key, get_rate_limit_for_tier, limiter


def _fake_request(headers: dict, tier: str = "starter") -> SimpleNamespace:
    return SimpleNamespace(headers=headers, state=SimpleNamespace(workspace_tier=tier))


class TestWorkspaceKey:
    def test_embeds_tier_and_token_prefix(self):
        key = _workspace_key(_fake_request({"X-Workspace-Token": "cd_ws_abcdefghijklmnopqrstuvwxyz"}, tier="growth"))
        assert key == "ws:growth:cd_ws_abcdefghij"

    def test_defaults_to_starter_tier_when_state_missing_attribute(self):
        request = SimpleNamespace(headers={"X-Workspace-Token": "sometoken1234567890"}, state=SimpleNamespace())
        key = _workspace_key(request)
        assert key.startswith("ws:starter:")

    def test_falls_back_to_ip_without_token(self):
        with patch("api.middleware.rate_limiter.get_remote_address", return_value="203.0.113.5"):
            key = _workspace_key(_fake_request({}))
        assert key == "203.0.113.5"


class TestTierLimit:
    def test_parses_each_known_tier(self):
        assert _tier_limit("ws:starter:abc123") == get_rate_limit_for_tier("starter")
        assert _tier_limit("ws:growth:abc123") == get_rate_limit_for_tier("growth")
        assert _tier_limit("ws:enterprise:abc123") == get_rate_limit_for_tier("enterprise")

    def test_unknown_tier_falls_back_to_starter_limit(self):
        assert _tier_limit("ws:mystery_tier:abc123") == "30/minute"

    def test_ip_fallback_key_defaults_to_starter(self):
        assert _tier_limit("203.0.113.5") == "30/minute"

    def test_takes_a_single_string_argument_not_a_request(self):
        # The whole point of the fix: this must NOT require a Request.
        import inspect

        params = inspect.signature(_tier_limit).parameters
        assert list(params) == ["key"]


class TestLimiterDecoratorIntegration:
    """Exercises @limiter.limit(_tier_limit) through a real Starlette
    Request via TestClient — the exact call path that a plain unit test
    calling the route function directly (as tests/test_internal_agents.py
    does for its own, unrelated, non-rate-limited routes) would miss."""

    def _build_app(self) -> FastAPI:
        app = FastAPI()
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

        @app.middleware("http")
        async def set_tier(request: Request, call_next):
            request.state.workspace_tier = request.headers.get("X-Test-Tier", "starter")
            return await call_next(request)

        @app.get("/ping")
        @limiter.limit(_tier_limit)
        async def ping(request: Request):
            return {"ok": True}

        return app

    def test_request_with_token_succeeds_without_crashing(self):
        client = TestClient(self._build_app())
        response = client.get(
            "/ping",
            headers={"X-Workspace-Token": "cd_ws_realtoken", "X-Test-Tier": "growth"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_request_without_token_falls_back_to_ip_and_still_succeeds(self):
        client = TestClient(self._build_app())
        response = client.get("/ping")
        assert response.status_code == 200
