"""
tests/test_api_status.py
Tests for api/main.py's _check_db and /api/status (Phase 5, real status
page -- replaces the /status placeholder).

What this file validates:
  _check_db():
    - Returns ("ok", "connected") when the query succeeds
    - Returns ("error", <detail>) when the pool/query raises

  api_status():
    - Returns overall "ok" with all three services "ok" when DB and
      frontend HEAD both succeed
    - Backend is always reported "ok" -- this response happening at all
      is the proof
    - Database status/detail come from _check_db, not a second query
    - Frontend "error" when the HEAD request raises (network failure)
    - Frontend "error" when the HEAD response is 5xx
    - Frontend "degraded" when the HEAD response is 4xx
    - Overall status is "error" if any service is "error", "degraded" if
      none are "error" but at least one is not "ok"
    - Response includes an ISO timestamp
"""

from unittest.mock import AsyncMock, MagicMock, patch

from api.main import _check_db, api_status


def _mock_pool(*, fetchval_result=1, fetchval_error=None):
    conn = AsyncMock()
    if fetchval_error:
        conn.fetchval = AsyncMock(side_effect=fetchval_error)
    else:
        conn.fetchval = AsyncMock(return_value=fetchval_result)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _make_request(pool):
    request = MagicMock()
    request.app.state.db_pool = pool
    return request


def _httpx_ctx(resp=None, side_effect=None):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    if side_effect is not None:
        ctx.head = AsyncMock(side_effect=side_effect)
    else:
        ctx.head = AsyncMock(return_value=resp)
    return ctx


class TestCheckDb:
    async def test_returns_ok_connected_on_success(self):
        status_, detail = await _check_db(_mock_pool())
        assert status_ == "ok"
        assert detail == "connected"

    async def test_returns_error_on_exception(self):
        status_, detail = await _check_db(_mock_pool(fetchval_error=RuntimeError("connection refused")))
        assert status_ == "error"
        assert "connection refused" in detail


class TestApiStatus:
    async def test_all_ok_when_db_and_frontend_healthy(self):
        resp = MagicMock(status_code=200)
        request = _make_request(_mock_pool())

        with patch("api.main.httpx.AsyncClient", MagicMock(return_value=_httpx_ctx(resp=resp))):
            result = await api_status(request)

        assert result["status"] == "ok"
        assert result["services"]["backend"]["status"] == "ok"
        assert result["services"]["database"]["status"] == "ok"
        assert result["services"]["frontend"]["status"] == "ok"
        assert "timestamp" in result

    async def test_database_error_reflected_from_check_db(self):
        resp = MagicMock(status_code=200)
        request = _make_request(_mock_pool(fetchval_error=RuntimeError("db down")))

        with patch("api.main.httpx.AsyncClient", MagicMock(return_value=_httpx_ctx(resp=resp))):
            result = await api_status(request)

        assert result["services"]["database"]["status"] == "error"
        assert "db down" in result["services"]["database"]["detail"]
        assert result["status"] == "error"

    async def test_frontend_error_on_network_failure(self):
        import httpx as real_httpx

        request = _make_request(_mock_pool())
        with patch(
            "api.main.httpx.AsyncClient",
            MagicMock(return_value=_httpx_ctx(side_effect=real_httpx.RequestError("dns failed"))),
        ):
            result = await api_status(request)

        assert result["services"]["frontend"]["status"] == "error"
        assert result["status"] == "error"

    async def test_frontend_error_on_5xx(self):
        resp = MagicMock(status_code=503)
        request = _make_request(_mock_pool())

        with patch("api.main.httpx.AsyncClient", MagicMock(return_value=_httpx_ctx(resp=resp))):
            result = await api_status(request)

        assert result["services"]["frontend"]["status"] == "error"
        assert "503" in result["services"]["frontend"]["detail"]

    async def test_frontend_degraded_on_4xx(self):
        resp = MagicMock(status_code=404)
        request = _make_request(_mock_pool())

        with patch("api.main.httpx.AsyncClient", MagicMock(return_value=_httpx_ctx(resp=resp))):
            result = await api_status(request)

        assert result["services"]["frontend"]["status"] == "degraded"
        assert result["status"] == "degraded"

    async def test_backend_is_always_ok(self):
        resp = MagicMock(status_code=200)
        request = _make_request(_mock_pool(fetchval_error=RuntimeError("db down")))

        with patch("api.main.httpx.AsyncClient", MagicMock(return_value=_httpx_ctx(resp=resp))):
            result = await api_status(request)

        assert result["services"]["backend"]["status"] == "ok"
