"""
tests/test_finops_agent_client.py
Tests for integrations/finops_agent_client.py -- the thin httpx wrapper
around the separately-deployed kdavis-finops-agent Railway service.

Mocks httpx.AsyncClient entirely -- no live network. Verifies:
  - the X-Tenant-Token header is sent when a token is given, and no
    Authorization/other header scheme is used
  - a non-2xx response raises AgentServiceError with the upstream
    status_code attached (not swallowed into a generic failure)
  - a network-level failure (no response at all) raises AgentServiceError
    with status_code None
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from integrations.finops_agent_client import AgentServiceError, create_tenant, get_dashboard, verify_aws_role


def _mock_async_client(response: MagicMock) -> MagicMock:
    client = AsyncMock()
    client.request = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.fixture(autouse=True)
def _api_url():
    with patch.dict("os.environ", {"FINOPS_AGENT_API_URL": "https://finops.example.com"}):
        yield


class TestCreateTenant:
    async def test_happy_path_returns_json_no_tenant_token_header(self):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"id": "t1", "tenant_token": "fo_t_x"})
        client = _mock_async_client(response)

        with patch("httpx.AsyncClient", return_value=client):
            result = await create_tenant("Acme")

        assert result["id"] == "t1"
        _, kwargs = client.request.call_args
        assert kwargs["headers"] == {}  # no tenant exists yet to authenticate as


class TestVerifyAwsRole:
    async def test_sends_x_tenant_token_header(self):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"status": "active"})
        client = _mock_async_client(response)

        with patch("httpx.AsyncClient", return_value=client):
            await verify_aws_role("t1", "fo_t_secret", "arn:aws:iam::1:role/x")

        args, kwargs = client.request.call_args
        assert kwargs["headers"] == {"X-Tenant-Token": "fo_t_secret"}
        assert "arn:aws:iam::1:role/x" in str(kwargs.get("json"))


class TestErrorHandling:
    async def test_http_status_error_raises_agent_service_error_with_status_code(self):
        request = httpx.Request("GET", "https://finops.example.com/api/v1/tenants/t1/dashboard")
        response = httpx.Response(404, request=request, json={"detail": "not found"})
        client = _mock_async_client(MagicMock())
        client.request = AsyncMock(
            return_value=MagicMock(
                raise_for_status=MagicMock(
                    side_effect=httpx.HTTPStatusError("404", request=request, response=response)
                )
            )
        )

        with patch("httpx.AsyncClient", return_value=client):
            with pytest.raises(AgentServiceError) as exc:
                await get_dashboard("t1", "fo_t_secret")

        assert exc.value.status_code == 404

    async def test_request_error_raises_agent_service_error_with_no_status_code(self):
        client = _mock_async_client(MagicMock())
        client.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("httpx.AsyncClient", return_value=client):
            with pytest.raises(AgentServiceError) as exc:
                await get_dashboard("t1", "fo_t_secret")

        assert exc.value.status_code is None
