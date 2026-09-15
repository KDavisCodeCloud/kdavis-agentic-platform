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

from api.middleware.rate_limiter import (
    _tier_limit,
    _webhook_tier_limit,
    _workspace_key,
    get_rate_limit_for_tier,
    get_webhook_rate_limit_for_tier,
    limiter,
)


def _fake_request(headers: dict, tier: str = "starter", query_params: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        headers=headers,
        query_params=query_params or {},
        state=SimpleNamespace(workspace_tier=tier),
    )


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

    def test_reads_token_from_query_param_when_no_header(self):
        """Webhook routes (api/routes/webhooks.py) pass the workspace
        token as ?token=..., not the X-Workspace-Token header --
        confirms the fallback added for webhook rate limiting."""
        request = _fake_request({}, tier="growth", query_params={"token": "cd_ws_querytoken1234567890"})
        key = _workspace_key(request)
        assert key == "ws:growth:cd_ws_querytoken"  # token[:16]

    def test_header_takes_precedence_over_query_param(self):
        request = _fake_request(
            {"X-Workspace-Token": "cd_ws_headertoken"},
            tier="starter",
            query_params={"token": "cd_ws_querytoken"},
        )
        key = _workspace_key(request)
        assert key.startswith("ws:starter:cd_ws_headertoke")  # token[:16], not the query token


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


class TestWebhookTierLimit:
    """_webhook_tier_limit -- higher ceilings than _tier_limit (manual
    agent-trigger routes), applied to api/routes/webhooks.py's 4 routes."""

    def test_parses_each_known_tier(self):
        assert _webhook_tier_limit("ws:starter:abc123") == get_webhook_rate_limit_for_tier("starter")
        assert _webhook_tier_limit("ws:growth:abc123") == get_webhook_rate_limit_for_tier("growth")
        assert _webhook_tier_limit("ws:enterprise:abc123") == get_webhook_rate_limit_for_tier("enterprise")

    def test_unknown_tier_falls_back_to_starter_webhook_limit(self):
        assert _webhook_tier_limit("ws:mystery_tier:abc123") == "60/minute"

    def test_higher_than_manual_trigger_limit_at_every_tier(self):
        for tier in ("starter", "growth", "enterprise"):
            webhook_limit = int(get_webhook_rate_limit_for_tier(tier).split("/")[0])
            manual_limit = int(get_rate_limit_for_tier(tier).split("/")[0])
            assert webhook_limit > manual_limit


class TestWebhookLimiterDecoratorIntegration:
    """Exercises @limiter.limit(_webhook_tier_limit) through a real
    Starlette Request via TestClient -- same integration-gap reasoning as
    TestLimiterDecoratorIntegration above, and specifically proves a
    request that actually exceeds the configured limit gets slowapi's
    registered 429 handler, not an unhandled 500 (the exact requirement
    this test class exists to cover -- Phase 4, scale-readiness build).

    `limiter` is a module-level singleton (api/middleware/rate_limiter.py
    imports one `limiter` shared by the whole app, on purpose -- slowapi
    needs exactly one Limiter registered per FastAPI app). Its in-memory
    counters persist for the life of the process, keyed correctly per
    distinct rate-limit key -- confirmed directly (a fresh token behaves
    correctly even after a different token has been pushed past its
    limit on the *same* app/route). What does NOT work reliably is
    rebuilding a brand new FastAPI app/route/TestClient per test method
    while sharing this one process-wide `limiter`: registering a second
    `@limiter.limit(...)`-decorated closure at the same path corrupts the
    next fresh key's count (observed directly while writing this test).
    Building the app once at class scope and reusing one TestClient
    across all three tests -- with a distinct token per test for
    hygiene, not because it's required for correctness -- sidesteps that
    entirely."""

    @classmethod
    def setup_class(cls):
        app = FastAPI()
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

        @app.middleware("http")
        async def set_tier(request: Request, call_next):
            request.state.workspace_tier = request.headers.get("X-Test-Tier", "starter")
            return await call_next(request)

        @app.post("/webhook-ping")
        @limiter.limit("2/minute")  # deliberately low so a test can trip it without 61 requests
        async def webhook_ping(request: Request):
            return {"ok": True}

        cls.client = TestClient(app)

    def test_requests_within_limit_succeed(self):
        headers = {"X-Workspace-Token": "cd_ws_within_limit_test", "X-Test-Tier": "starter"}
        for _ in range(2):
            response = self.client.post("/webhook-ping", headers=headers)
            assert response.status_code == 200

    def test_exceeding_limit_returns_429_not_500(self):
        headers = {"X-Workspace-Token": "cd_ws_exceed_limit_test", "X-Test-Tier": "starter"}
        for _ in range(2):
            response = self.client.post("/webhook-ping", headers=headers)
            assert response.status_code == 200

        response = self.client.post("/webhook-ping", headers=headers)
        assert response.status_code == 429
        assert response.status_code != 500

    def test_different_workspace_tokens_have_independent_limits(self):
        """A rate-limited workspace must not throttle a different one --
        confirms the key really is per-workspace, not global."""
        exhausted = {"X-Workspace-Token": "cd_ws_exhausted", "X-Test-Tier": "starter"}
        for _ in range(2):
            self.client.post("/webhook-ping", headers=exhausted)
        assert self.client.post("/webhook-ping", headers=exhausted).status_code == 429

        fresh = {"X-Workspace-Token": "cd_ws_fresh_neighbor", "X-Test-Tier": "starter"}
        assert self.client.post("/webhook-ping", headers=fresh).status_code == 200
