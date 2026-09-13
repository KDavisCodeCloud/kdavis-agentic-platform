"""
tests/test_workspace_credentials.py
Tests for core/workspace_credentials.py -- per-workspace GitHub/AWS/Azure
credential storage and decryption for Agents 01/05/06/08 (migration 022).

Mirrors kdavis-finops-agent's tests/test_aws_onboarding.py and
test_azure_onboarding.py mocking conventions for the AWS/Azure pieces;
uses this repo's own httpx.AsyncClient mocking convention (see
tests/test_agent01.py's TestCICDTools) for the Azure OAuth2 token flow,
since this module deliberately does a raw httpx call instead of the
azure-identity SDK.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from core.workspace_credentials import (
    AssumeRoleError,
    AzureConnectError,
    build_agent_credentials,
    build_permissions_policy,
    build_trust_policy,
    generate_external_id,
    get_azure_bearer_token,
    verify_role,
    verify_service_principal,
)


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "AssumeRole")


def _httpx_ctx(response) -> AsyncMock:
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    ctx.post = AsyncMock(return_value=response)
    ctx.get = AsyncMock(return_value=response)
    return ctx


class TestGenerateExternalId:
    def test_generates_a_non_trivial_random_value(self):
        a, b = generate_external_id(), generate_external_id()
        assert a != b
        assert len(a) > 16


class TestBuildTrustPolicy:
    def test_scopes_to_our_account_and_the_external_id(self):
        policy = build_trust_policy("111111111111", "ext-abc")
        statement = policy["Statement"][0]
        assert statement["Principal"]["AWS"] == "arn:aws:iam::111111111111:root"
        assert statement["Condition"]["StringEquals"]["sts:ExternalId"] == "ext-abc"


class TestBuildPermissionsPolicy:
    def test_covers_agents_05_06_08_aws_calls(self):
        actions = build_permissions_policy()["Statement"][0]["Action"]
        for required in (
            "iam:CreatePolicyVersion",
            "ce:GetCostAndUsage",
            "ec2:StopInstances",
            "ec2:DeleteVolume",
            "cloudformation:DescribeStacks",
        ):
            assert required in actions


class TestVerifyRole:
    def test_raises_clear_error_on_failure(self):
        with patch("boto3.client") as mock_client:
            mock_client.return_value.assume_role.side_effect = _client_error("AccessDenied")
            with pytest.raises(AssumeRoleError):
                verify_role("arn:aws:iam::222222222222:role/x", "ext-abc")

    def test_succeeds_silently_when_role_is_assumable(self):
        with patch("boto3.client") as mock_client:
            mock_client.return_value.assume_role.return_value = {
                "Credentials": {"AccessKeyId": "a", "SecretAccessKey": "b", "SessionToken": "c"}
            }
            verify_role("arn:aws:iam::222222222222:role/x", "ext-abc")  # no raise


class TestGetAzureBearerToken:
    async def test_returns_access_token_on_success(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"access_token": "real-token"}
        with patch("core.workspace_credentials.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _httpx_ctx(resp)
            token = await get_azure_bearer_token("tid", "cid", "secret")
        assert token == "real-token"

    async def test_raises_on_non_200(self):
        resp = MagicMock(status_code=401, text="invalid_client")
        with patch("core.workspace_credentials.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _httpx_ctx(resp)
            with pytest.raises(AzureConnectError):
                await get_azure_bearer_token("tid", "cid", "bad-secret")


class TestVerifyServicePrincipal:
    async def test_raises_on_token_failure(self):
        resp = MagicMock(status_code=401, text="invalid_client")
        with patch("core.workspace_credentials.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _httpx_ctx(resp)
            with pytest.raises(AzureConnectError):
                await verify_service_principal("tid", "cid", "secret", "sub")

    async def test_succeeds_when_subscription_read_confirms_access(self):
        token_resp = MagicMock(status_code=200)
        token_resp.json.return_value = {"access_token": "real-token"}
        sub_resp = MagicMock(status_code=200)

        with patch("core.workspace_credentials.httpx.AsyncClient") as mock_cls:
            ctx = _httpx_ctx(token_resp)
            ctx.get = AsyncMock(return_value=sub_resp)
            mock_cls.return_value = ctx
            await verify_service_principal("tid", "cid", "secret", "sub")  # no raise


class TestBuildAgentCredentials:
    async def _conn(self, row):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        return conn

    async def test_no_credentials_configured_returns_all_none(self):
        conn = await self._conn({
            "github_pat_encrypted": None,
            "aws_role_arn": None,
            "aws_external_id": None,
            "azure_tenant_id": None,
            "azure_client_id": None,
            "azure_client_secret_encrypted": None,
            "azure_subscription_id": None,
        })
        creds = await build_agent_credentials(conn, str(uuid4()))
        assert creds == {"github_token": None, "aws_session": None, "azure_access_token": None}

    async def test_github_pat_decrypted(self):
        conn = await self._conn({
            "github_pat_encrypted": "cipher",
            "aws_role_arn": None, "aws_external_id": None,
            "azure_tenant_id": None, "azure_client_id": None,
            "azure_client_secret_encrypted": None, "azure_subscription_id": None,
        })
        with patch("core.workspace_credentials.decrypt", return_value="ghp_real"):
            creds = await build_agent_credentials(conn, str(uuid4()))
        assert creds["github_token"] == "ghp_real"
        assert creds["aws_session"] is None
        assert creds["azure_access_token"] is None

    async def test_aws_role_builds_a_session(self):
        conn = await self._conn({
            "github_pat_encrypted": None,
            "aws_role_arn": "arn:aws:iam::222222222222:role/x", "aws_external_id": "ext-abc",
            "azure_tenant_id": None, "azure_client_id": None,
            "azure_client_secret_encrypted": None, "azure_subscription_id": None,
        })
        fake_session = MagicMock()
        with patch("core.workspace_credentials.assume_role_session", return_value=fake_session) as mock_assume:
            creds = await build_agent_credentials(conn, str(uuid4()))
        mock_assume.assert_called_once_with("arn:aws:iam::222222222222:role/x", "ext-abc")
        assert creds["aws_session"] is fake_session

    async def test_azure_creds_mint_a_bearer_token(self):
        conn = await self._conn({
            "github_pat_encrypted": None,
            "aws_role_arn": None, "aws_external_id": None,
            "azure_tenant_id": "tid", "azure_client_id": "cid",
            "azure_client_secret_encrypted": "cipher", "azure_subscription_id": "sub",
        })
        with (
            patch("core.workspace_credentials.decrypt", return_value="real-secret"),
            patch("core.workspace_credentials.get_azure_bearer_token", new=AsyncMock(return_value="bearer-tok")) as mock_token,
        ):
            creds = await build_agent_credentials(conn, str(uuid4()))
        mock_token.assert_awaited_once_with("tid", "cid", "real-secret")
        assert creds["azure_access_token"] == "bearer-tok"

    async def test_workspace_not_found_returns_all_none(self):
        conn = await self._conn(None)
        creds = await build_agent_credentials(conn, str(uuid4()))
        assert creds == {"github_token": None, "aws_session": None, "azure_access_token": None}
