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

from core.github_app import GitHubAppError
from core.workspace_credentials import (
    AssumeRoleError,
    AzureConnectError,
    build_agent_credentials,
    build_permissions_policy,
    build_trust_policy,
    generate_external_id,
    get_azure_bearer_token,
    mint_github_app_token,
    resolve_k8s_context,
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


class TestResolveK8sContext:
    def test_maps_aws_via_env_var(self):
        with patch.dict("os.environ", {"K8S_CONTEXT_AWS": "eks-demo"}, clear=False):
            assert resolve_k8s_context("aws") == "eks-demo"

    def test_maps_azure_via_env_var(self):
        with patch.dict("os.environ", {"K8S_CONTEXT_AZURE": "aks-demo"}, clear=False):
            assert resolve_k8s_context("azure") == "aks-demo"

    def test_returns_none_when_env_var_unset(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("K8S_CONTEXT_GCP", None)
            assert resolve_k8s_context("gcp") is None

    def test_returns_none_for_unknown_provider(self):
        assert resolve_k8s_context("oracle-cloud") is None


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
            "github_app_installation_id": None,
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
            "github_app_installation_id": None,
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
            "github_app_installation_id": None,
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
            "github_app_installation_id": None,
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

    async def test_github_app_installation_takes_priority_over_stored_pat(self):
        # Item 4 migration decision: App-based access wins over a legacy PAT
        # when both happen to be present on the same workspace.
        conn = await self._conn({
            "github_pat_encrypted": "legacy-cipher",
            "github_app_installation_id": "inst-123",
            "aws_role_arn": None, "aws_external_id": None,
            "azure_tenant_id": None, "azure_client_id": None,
            "azure_client_secret_encrypted": None, "azure_subscription_id": None,
        })
        with patch(
            "core.workspace_credentials.mint_github_app_token",
            new=AsyncMock(return_value="ghs_fresh_install_token"),
        ) as mock_mint:
            creds = await build_agent_credentials(conn, str(uuid4()))
        mock_mint.assert_awaited_once_with(conn, "inst-123")
        assert creds["github_token"] == "ghs_fresh_install_token"

    async def test_falls_back_to_legacy_pat_when_no_app_installation(self):
        conn = await self._conn({
            "github_pat_encrypted": "legacy-cipher",
            "github_app_installation_id": None,
            "aws_role_arn": None, "aws_external_id": None,
            "azure_tenant_id": None, "azure_client_id": None,
            "azure_client_secret_encrypted": None, "azure_subscription_id": None,
        })
        with patch("core.workspace_credentials.decrypt", return_value="ghp_legacy_real"):
            creds = await build_agent_credentials(conn, str(uuid4()))
        assert creds["github_token"] == "ghp_legacy_real"


class TestMintGithubAppToken:
    async def test_raises_when_app_not_registered(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with pytest.raises(GitHubAppError):
            await mint_github_app_token(conn, "inst-123")

    async def test_decrypts_private_key_and_mints_token(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"app_id": "999", "private_key_encrypted": "cipher"})
        with (
            patch("core.workspace_credentials.decrypt", return_value="-----BEGIN PEM-----"),
            patch(
                "core.workspace_credentials.mint_installation_token",
                new=AsyncMock(return_value="ghs_fresh"),
            ) as mock_mint,
        ):
            token = await mint_github_app_token(conn, "inst-123")
        mock_mint.assert_awaited_once_with("999", "-----BEGIN PEM-----", "inst-123")
        assert token == "ghs_fresh"
