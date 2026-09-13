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


class TestConnectGithub:
    # Retired as of the item 4 GitHub App migration (decided 2026-09-13) --
    # PATCH /workspace/credentials/github no longer accepts new PATs at all,
    # regardless of whether the PAT itself would have verified. Replaces the
    # PAT-verify-and-store tests that used to live here.
    async def test_always_returns_410_pointing_at_the_app_install_flow(self):
        request, conn = _make_request()
        with pytest.raises(HTTPException) as exc:
            await wc_routes.connect_github(
                wc_routes.ConnectGithubRequest(github_pat="ghp_anything"),
                request,
                workspace={"id": uuid4()},
            )
        assert exc.value.status_code == 410
        assert "install-url" in exc.value.detail
        conn.execute.assert_not_awaited()


class TestGetGithubAppInstallUrl:
    async def test_raises_503_when_app_not_registered(self):
        request, conn = _make_request(fetchrow_return=None)
        with pytest.raises(HTTPException) as exc:
            await wc_routes.get_github_app_install_url(request, workspace={"id": uuid4()})
        assert exc.value.status_code == 503

    async def test_returns_install_url_when_app_registered(self):
        request, conn = _make_request(fetchrow_return={"app_slug": "cloud-decoded"})
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            result = await wc_routes.get_github_app_install_url(request, workspace={"id": uuid4()})
        assert "github.com/apps/cloud-decoded/installations/new" in result["install_url"]


class TestGithubAppInstallCallback:
    async def test_stores_installation_id_on_valid_state(self):
        workspace_id = str(uuid4())
        request, conn = _make_request()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            state = wc_routes.sign_workspace_state(workspace_id)
            result = await wc_routes.github_app_install_callback(
                request, installation_id="inst-123", state=state,
            )
        assert result["status"] == "installed"
        conn.execute.assert_awaited_once()
        args = conn.execute.await_args.args
        assert "inst-123" in args
        assert workspace_id in args

    async def test_rejects_invalid_state(self):
        request, conn = _make_request()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            with pytest.raises(HTTPException) as exc:
                await wc_routes.github_app_install_callback(
                    request, installation_id="inst-123", state="garbage",
                )
        assert exc.value.status_code == 400
        conn.execute.assert_not_awaited()


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


class TestGetConnectionsStatus:
    async def test_reflects_verified_at_columns_directly(self):
        from datetime import datetime, timezone

        workspace = {
            "id": uuid4(),
            "github_pat_verified_at": datetime.now(timezone.utc),
            "aws_role_verified_at": None,
            "azure_verified_at": datetime.now(timezone.utc),
        }

        result = await wc_routes.get_connections_status(workspace=workspace)

        assert result.github_connected is True
        assert result.aws_connected is False
        assert result.azure_connected is True

    async def test_all_false_when_nothing_configured(self):
        workspace = {"id": uuid4()}

        result = await wc_routes.get_connections_status(workspace=workspace)

        assert result.github_connected is False
        assert result.aws_connected is False
        assert result.azure_connected is False
