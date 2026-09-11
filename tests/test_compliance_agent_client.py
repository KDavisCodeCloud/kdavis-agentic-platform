"""
tests/test_compliance_agent_client.py
Tests for integrations/compliance_agent_client.py -- mirrors
tests/test_finops_agent_client.py's coverage for the sibling client.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from integrations.compliance_agent_client import AgentServiceError, create_tenant, get_report, verify_aws_role


def _mock_async_client(response: MagicMock) -> MagicMock:
    client = AsyncMock()
    client.request = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.fixture(autouse=True)
def _api_url():
    with patch.dict("os.environ", {"COMPLIANCE_AGENT_API_URL": "https://compliance.example.com"}):
        yield


class TestCreateTenant:
    async def test_happy_path_returns_json_no_tenant_token_header(self):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"id": "t1", "tenant_token": "co_t_x"})
        client = _mock_async_client(response)

        with patch("httpx.AsyncClient", return_value=client):
            result = await create_tenant("Acme")

        assert result["id"] == "t1"
        _, kwargs = client.request.call_args
        assert kwargs["headers"] == {}


class TestVerifyAwsRole:
    async def test_sends_x_tenant_token_header(self):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"status": "active"})
        client = _mock_async_client(response)

        with patch("httpx.AsyncClient", return_value=client):
            await verify_aws_role("t1", "co_t_secret", "arn:aws:iam::1:role/x")

        args, kwargs = client.request.call_args
        assert kwargs["headers"] == {"X-Tenant-Token": "co_t_secret"}


class TestErrorHandling:
    async def test_http_status_error_raises_agent_service_error_with_status_code(self):
        request = httpx.Request("GET", "https://compliance.example.com/api/v1/tenants/t1/report")
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
                await get_report("t1", "co_t_secret")

        assert exc.value.status_code == 404

    async def test_request_error_raises_agent_service_error_with_no_status_code(self):
        client = _mock_async_client(MagicMock())
        client.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("httpx.AsyncClient", return_value=client):
            with pytest.raises(AgentServiceError) as exc:
                await get_report("t1", "co_t_secret")

        assert exc.value.status_code is None
