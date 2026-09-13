"""
tests/test_workspace_credentials_routes.py
Tests for api/routes/workspace_credentials.py -- verify-then-store routes
letting a workspace connect its own GitHub PAT, AWS role, and Azure
Service Principal for Agents 01/05/06/08's real remediation.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from api.routes import workspace_credentials as wc_routes
from core.workspace_credentials import AssumeRoleError, AzureConnectError

_FERNET_KEY = Fernet.generate_key().decode()


def _make_request(fetchrow_return=None) -> tuple:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock(return_value=None)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
    return request, conn


def _httpx_ctx(response) -> AsyncMock:
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    ctx.get = AsyncMock(return_value=response)
    return ctx


class TestConnectGithub:
    async def test_invalid_pat_raises_400(self):
        request, conn = _make_request()
        resp = MagicMock(status_code=401, text="Bad credentials")
        with patch("api.routes.workspace_credentials.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _httpx_ctx(resp)
            with pytest.raises(HTTPException) as exc:
                await wc_routes.connect_github(
                    wc_routes.ConnectGithubRequest(github_pat="bad"),
                    request,
                    workspace={"id": uuid4()},
                )
        assert exc.value.status_code == 400

    async def test_valid_pat_mints_webhook_secret_first_time(self):
        request, conn = _make_request(fetchrow_return={"encrypted_github_webhook_secret": None})
        resp = MagicMock(status_code=200)
        with (
            patch("api.routes.workspace_credentials.httpx.AsyncClient") as mock_cls,
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            mock_cls.return_value = _httpx_ctx(resp)
            result = await wc_routes.connect_github(
                wc_routes.ConnectGithubRequest(github_pat="ghp_real"),
                request,
                workspace={"id": uuid4()},
            )
        assert result.webhook_secret is not None

    async def test_valid_pat_does_not_reissue_existing_webhook_secret(self):
        request, conn = _make_request(fetchrow_return={"encrypted_github_webhook_secret": "already-set"})
        resp = MagicMock(status_code=200)
        with (
            patch("api.routes.workspace_credentials.httpx.AsyncClient") as mock_cls,
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            mock_cls.return_value = _httpx_ctx(resp)
            result = await wc_routes.connect_github(
                wc_routes.ConnectGithubRequest(github_pat="ghp_real"),
                request,
                workspace={"id": uuid4()},
            )
        assert result.webhook_secret is None


class TestSetupAwsRole:
    async def test_missing_platform_account_id_raises_500(self):
        request, conn = _make_request()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(HTTPException) as exc:
                await wc_routes.setup_aws_role(request, workspace={"id": uuid4()})
        assert exc.value.status_code == 500

    async def test_returns_trust_and_permissions_policy(self):
        request, conn = _make_request()
        with patch.dict("os.environ", {"CLOUD_DECODED_AWS_ACCOUNT_ID": "111111111111"}):
            result = await wc_routes.setup_aws_role(request, workspace={"id": uuid4()})
        assert result.trust_policy["Statement"][0]["Principal"]["AWS"] == "arn:aws:iam::111111111111:root"
        assert "iam:CreatePolicyVersion" in result.permissions_policy["Statement"][0]["Action"]


class TestConnectAwsRole:
    async def test_no_external_id_yet_raises_400(self):
        request, conn = _make_request(fetchrow_return={"aws_external_id": None})
        with pytest.raises(HTTPException) as exc:
            await wc_routes.connect_aws_role(
                wc_routes.ConnectAwsRoleRequest(role_arn="arn:aws:iam::222222222222:role/x"),
                request,
                workspace={"id": uuid4()},
            )
        assert exc.value.status_code == 400
        assert "setup" in exc.value.detail

    async def test_unassumable_role_raises_400(self):
        request, conn = _make_request(fetchrow_return={"aws_external_id": "ext-abc"})
        with patch("api.routes.workspace_credentials.verify_role", side_effect=AssumeRoleError("denied")):
            with pytest.raises(HTTPException) as exc:
                await wc_routes.connect_aws_role(
                    wc_routes.ConnectAwsRoleRequest(role_arn="arn:aws:iam::222222222222:role/x"),
                    request,
                    workspace={"id": uuid4()},
                )
        assert exc.value.status_code == 400

    async def test_valid_role_stores_and_returns_status(self):
        workspace_id = uuid4()
        request, conn = _make_request(fetchrow_return={"aws_external_id": "ext-abc"})
        with patch("api.routes.workspace_credentials.verify_role", return_value=None):
            result = await wc_routes.connect_aws_role(
                wc_routes.ConnectAwsRoleRequest(role_arn="arn:aws:iam::222222222222:role/x"),
                request,
                workspace={"id": workspace_id},
            )
        assert result.id == str(workspace_id)
        conn.execute.assert_awaited_once()


class TestConnectAzure:
    async def test_verification_failure_raises_400(self):
        request, conn = _make_request()
        with patch(
            "api.routes.workspace_credentials.verify_service_principal",
            new=AsyncMock(side_effect=AzureConnectError("bad secret")),
        ):
            with pytest.raises(HTTPException) as exc:
                await wc_routes.connect_azure(
                    wc_routes.ConnectAzureRequest(
                        azure_tenant_id="tid", client_id="cid", client_secret="secret", subscription_id="sub"
                    ),
                    request,
                    workspace={"id": uuid4()},
                )
        assert exc.value.status_code == 400

    async def test_valid_service_principal_stores_and_returns_status(self):
        workspace_id = uuid4()
        request, conn = _make_request()
        with (
            patch("api.routes.workspace_credentials.verify_service_principal", new=AsyncMock(return_value=None)),
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            result = await wc_routes.connect_azure(
                wc_routes.ConnectAzureRequest(
                    azure_tenant_id="tid", client_id="cid", client_secret="secret", subscription_id="sub"
                ),
                request,
                workspace={"id": workspace_id},
            )
        assert result.id == str(workspace_id)
        conn.execute.assert_awaited_once()
