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
from core.workspace_credentials import AssumeRoleError, AzureConnectError, AzureDevOpsConnectError, K8sConnectError

_FERNET_KEY = Fernet.generate_key().decode()


def _make_request(fetchrow_return=None) -> tuple:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetchval = AsyncMock(return_value=None)
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
    """
    Linking needs proof of ownership (GitHub OAuth during install: the
    installing user's token must list installation_id) AND proof of workspace
    (our signed state, or a claim redeemed by the logged-in dashboard).
    installation_id alone is a query param anyone can type.
    """

    APP_ROW = {"client_id": "Iv1.abc", "client_secret_encrypted": None}

    def _request(self, holder=None):
        from security.encryption import encrypt
        request, conn = _make_request(fetchrow_return={**self.APP_ROW, "client_secret_encrypted": encrypt("sec")})
        conn.fetchval = AsyncMock(return_value=holder)
        return request, conn

    async def _callback(self, request, *, state=None, code="oauth-code", can_access=True, installation_id="inst-123"):
        with patch.object(wc_routes, "exchange_user_code", new=AsyncMock(return_value="ghu_user")) as exchange, \
             patch.object(wc_routes, "user_can_access_installation",
                          new=AsyncMock(return_value=can_access)) as access:
            result = await wc_routes.github_app_install_callback(
                request, installation_id=installation_id, state=state, code=code,
            )
        return result, exchange, access

    @staticmethod
    def _sqls(conn):
        return [c.args[0] for c in conn.execute.await_args_list]

    async def test_verified_owner_with_valid_state_is_linked(self):
        workspace_id = str(uuid4())
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            request, conn = self._request()
            state = wc_routes.sign_workspace_state(workspace_id)
            result, exchange, access = await self._callback(request, state=state)
        assert result.headers["location"].endswith("/dashboard?connected=github")
        assert exchange.await_args.args == ("Iv1.abc", "sec", "oauth-code")
        assert access.await_args.args == ("ghu_user", "inst-123")
        link = conn.execute.await_args_list[0]
        assert "UPDATE workspaces" in link.args[0] and link.args[1:] == ("inst-123", workspace_id)

    async def test_hijack_valid_state_but_user_cannot_access_installation(self):
        """The attack: a real customer's signed state + someone else's installation_id."""
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            request, conn = self._request()
            state = wc_routes.sign_workspace_state(str(uuid4()))
            result, _, _ = await self._callback(request, state=state, can_access=False, installation_id="victim-999")
        assert "github=unverified" in result.headers["location"]
        assert not any("UPDATE workspaces" in s for s in self._sqls(conn))
        unclaimed = conn.execute.await_args_list[-1]
        assert "github_app_unclaimed_installations" in unclaimed.args[0] and unclaimed.args[1] == "victim-999"

    async def test_hijack_typed_url_without_oauth_code_is_never_linked(self):
        """Lab-style hand-completed callback (state, no code): unverified -> unclaimed."""
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            request, conn = self._request()
            state = wc_routes.sign_workspace_state(str(uuid4()))
            result, exchange, _ = await self._callback(request, state=state, code=None)
        exchange.assert_not_awaited()
        assert "github=unverified" in result.headers["location"]
        assert not any("UPDATE workspaces" in s for s in self._sqls(conn))

    async def test_github_refusing_the_code_is_unverified(self):
        from core.github_app import GitHubAppError
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            request, conn = self._request()
            with patch.object(wc_routes, "exchange_user_code", new=AsyncMock(side_effect=GitHubAppError("bad_code"))):
                result = await wc_routes.github_app_install_callback(
                    request, installation_id="inst-123", state=wc_routes.sign_workspace_state(str(uuid4())),
                    code="stale")
        assert "github=unverified" in result.headers["location"]
        assert not any("UPDATE workspaces" in s for s in self._sqls(conn))

    async def test_verified_owner_without_state_gets_a_claim_not_a_link(self):
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            request, conn = self._request()
            result, _, _ = await self._callback(request, state=None)
            location = result.headers["location"]
            assert "github_claim=" in location
            from urllib.parse import parse_qs, urlparse
            claim = parse_qs(urlparse(location).query)["github_claim"][0]
            assert wc_routes.verify_installation_claim(claim) == "inst-123"
        assert not any("UPDATE workspaces" in s for s in self._sqls(conn))

    async def test_verified_owner_cannot_take_an_installation_another_workspace_holds(self):
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            request, conn = self._request(holder=uuid4())
            state = wc_routes.sign_workspace_state(str(uuid4()))
            with pytest.raises(HTTPException) as exc:
                await self._callback(request, state=state)
        assert exc.value.status_code == 409
        assert not any("UPDATE workspaces" in s for s in self._sqls(conn))


class TestGithubAppClaim:
    async def test_logged_in_workspace_redeems_a_verified_claim(self):
        workspace_id = uuid4()
        request, conn = _make_request()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            claim = wc_routes.sign_installation_claim("inst-123")
            out = await wc_routes.claim_github_app_installation(
                wc_routes.GithubAppClaimRequest(claim=claim), request, workspace={"id": workspace_id})
        assert out == {"status": "linked", "installation_id": "inst-123"}
        assert conn.execute.await_args_list[0].args[1:] == ("inst-123", str(workspace_id))

    @pytest.mark.parametrize("claim", ["garbage", "inst-123", "claim.inst-123:1:deadbeef"])
    async def test_forged_claims_are_rejected(self, claim):
        request, conn = _make_request()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            with pytest.raises(HTTPException) as exc:
                await wc_routes.claim_github_app_installation(
                    wc_routes.GithubAppClaimRequest(claim=claim), request, workspace={"id": uuid4()})
        assert exc.value.status_code == 400
        conn.execute.assert_not_awaited()

    async def test_expired_claim_is_rejected(self):
        import time as _time
        request, conn = _make_request()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            claim = wc_routes.sign_installation_claim("inst-123")
            with patch("core.github_app.time.time", return_value=_time.time() + 3600):
                with pytest.raises(HTTPException):
                    await wc_routes.claim_github_app_installation(
                        wc_routes.GithubAppClaimRequest(claim=claim), request, workspace={"id": uuid4()})
        conn.execute.assert_not_awaited()

    async def test_a_workspace_state_is_not_a_claim(self):
        """The two signed tokens must not be interchangeable."""
        request, conn = _make_request()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            state = wc_routes.sign_workspace_state("inst-123")
            with pytest.raises(HTTPException):
                await wc_routes.claim_github_app_installation(
                    wc_routes.GithubAppClaimRequest(claim=state), request, workspace={"id": uuid4()})


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

    async def test_client_secret_expiry_persisted_and_clears_prior_warned_flag(self):
        """24-gap-closure Phase 5."""
        from datetime import datetime, timezone
        workspace_id = uuid4()
        request, conn = _make_request()
        expiry = datetime(2027, 1, 1, tzinfo=timezone.utc)
        with (
            patch("api.routes.workspace_credentials.verify_service_principal", new=AsyncMock(return_value=None)),
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            await wc_routes.connect_azure(
                wc_routes.ConnectAzureRequest(
                    azure_tenant_id="tid", client_id="cid", client_secret="secret",
                    subscription_id="sub", client_secret_expires_at=expiry,
                ),
                request,
                workspace={"id": workspace_id},
            )
        sql, *params = conn.execute.await_args.args
        assert "azure_client_secret_expires_at" in sql
        assert "azure_client_secret_expiry_warned_at = NULL" in sql
        assert expiry in params


class TestConnectAzureDevOps:
    async def test_verification_failure_raises_400(self):
        request, conn = _make_request()
        with patch(
            "api.routes.workspace_credentials.verify_azure_devops_pat",
            new=AsyncMock(side_effect=AzureDevOpsConnectError("bad pat")),
        ):
            with pytest.raises(HTTPException) as exc:
                await wc_routes.connect_azure_devops(
                    wc_routes.ConnectAzureDevOpsRequest(org="acme-org", pat="bad-pat"),
                    request,
                    workspace={"id": uuid4()},
                )
        assert exc.value.status_code == 400
        conn.execute.assert_not_awaited()

    async def test_first_connect_mints_and_returns_webhook_secret(self):
        workspace_id = uuid4()
        # `existing` fetchrow (no prior secret) -- conn.execute isn't queried again by _make_request
        request, conn = _make_request(fetchrow_return={"encrypted_azure_devops_webhook_secret": None})
        with (
            patch("api.routes.workspace_credentials.verify_azure_devops_pat", new=AsyncMock(return_value=None)),
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            result = await wc_routes.connect_azure_devops(
                wc_routes.ConnectAzureDevOpsRequest(org="acme-org", pat="pat123"),
                request,
                workspace={"id": workspace_id},
            )
        assert result.webhook_secret is not None
        conn.execute.assert_awaited_once()

    async def test_reconnect_does_not_remint_webhook_secret(self):
        workspace_id = uuid4()
        request, conn = _make_request(fetchrow_return={"encrypted_azure_devops_webhook_secret": "already-set-cipher"})
        with (
            patch("api.routes.workspace_credentials.verify_azure_devops_pat", new=AsyncMock(return_value=None)),
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            result = await wc_routes.connect_azure_devops(
                wc_routes.ConnectAzureDevOpsRequest(org="acme-org", pat="pat123"),
                request,
                workspace={"id": workspace_id},
            )
        assert result.webhook_secret is None  # not shown again -- was already minted on a prior connect
        conn.execute.assert_awaited_once()

    async def test_pat_expiry_persisted_on_first_connect(self):
        """24-gap-closure Phase 5."""
        from datetime import datetime, timezone
        workspace_id = uuid4()
        request, conn = _make_request(fetchrow_return={"encrypted_azure_devops_webhook_secret": None})
        expiry = datetime(2027, 1, 1, tzinfo=timezone.utc)
        with (
            patch("api.routes.workspace_credentials.verify_azure_devops_pat", new=AsyncMock(return_value=None)),
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            await wc_routes.connect_azure_devops(
                wc_routes.ConnectAzureDevOpsRequest(org="acme-org", pat="pat123", pat_expires_at=expiry),
                request,
                workspace={"id": workspace_id},
            )
        sql, *params = conn.execute.await_args.args
        assert "azure_devops_pat_expires_at" in sql
        assert expiry in params

    async def test_pat_expiry_persisted_on_reconnect(self):
        """24-gap-closure Phase 5."""
        from datetime import datetime, timezone
        workspace_id = uuid4()
        request, conn = _make_request(fetchrow_return={"encrypted_azure_devops_webhook_secret": "already-set-cipher"})
        expiry = datetime(2027, 1, 1, tzinfo=timezone.utc)
        with (
            patch("api.routes.workspace_credentials.verify_azure_devops_pat", new=AsyncMock(return_value=None)),
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            await wc_routes.connect_azure_devops(
                wc_routes.ConnectAzureDevOpsRequest(org="acme-org", pat="pat123", pat_expires_at=expiry),
                request,
                workspace={"id": workspace_id},
            )
        sql, *params = conn.execute.await_args.args
        assert "azure_devops_pat_expiry_warned_at = NULL" in sql
        assert expiry in params


class TestGetConnectionsStatus:
    async def test_reflects_verified_at_columns_directly(self):
        from datetime import datetime, timezone

        workspace = {
            "id": uuid4(),
            "github_pat_verified_at": datetime.now(timezone.utc),
            "aws_role_verified_at": None,
            "azure_verified_at": datetime.now(timezone.utc),
            "azure_devops_pat_verified_at": datetime.now(timezone.utc),
            "k8s_verified_at": datetime.now(timezone.utc),
        }

        result = await wc_routes.get_connections_status(workspace=workspace)

        assert result.github_connected is True
        assert result.github_via_legacy_pat is True
        assert result.aws_connected is False
        assert result.azure_connected is True
        assert result.azure_devops_connected is True
        assert result.k8s_connected is True

    async def test_has_contact_email_reflects_column_presence(self):
        """Kelvin's item 7, 2026-09-17."""
        result = await wc_routes.get_connections_status(workspace={"id": uuid4(), "contact_email": "ops@acme.com"})
        assert result.has_contact_email is True

        result = await wc_routes.get_connections_status(workspace={"id": uuid4(), "contact_email": None})
        assert result.has_contact_email is False

        result = await wc_routes.get_connections_status(workspace={"id": uuid4()})
        assert result.has_contact_email is False

    async def test_github_app_installation_also_counts_as_connected(self):
        # github_connected must reflect an App-based connection too, not just
        # a legacy PAT's github_pat_verified_at -- a workspace that connected
        # via the item 4 GitHub App has no PAT at all.
        workspace = {
            "id": uuid4(),
            "github_pat_verified_at": None,
            "github_app_installation_id": "inst-123",
        }

        result = await wc_routes.get_connections_status(workspace=workspace)

        assert result.github_connected is True
        # App installed -- not the legacy PAT path, no migration nudge needed
        assert result.github_via_legacy_pat is False

    async def test_legacy_pat_flagged_for_migration_even_if_app_also_present(self):
        # A workspace mid-migration (kept its old PAT verified while also
        # installing the App) should not be nudged -- the App takes over.
        from datetime import datetime, timezone

        workspace = {
            "id": uuid4(),
            "github_pat_verified_at": datetime.now(timezone.utc),
            "github_app_installation_id": "inst-456",
        }

        result = await wc_routes.get_connections_status(workspace=workspace)

        assert result.github_connected is True
        assert result.github_via_legacy_pat is False

    async def test_all_false_when_nothing_configured(self):
        workspace = {"id": uuid4()}

        result = await wc_routes.get_connections_status(workspace=workspace)

        assert result.github_connected is False
        assert result.github_via_legacy_pat is False
        assert result.aws_connected is False
        assert result.azure_connected is False
        assert result.azure_devops_connected is False
        assert result.k8s_connected is False
        assert result.llm_configured is False
        assert result.llm_provider is None

    async def test_llm_key_configured_reflects_encrypted_key_presence(self):
        workspace = {"id": uuid4(), "encrypted_llm_key": "gAAAAA...", "llm_provider": "anthropic"}

        result = await wc_routes.get_connections_status(workspace=workspace)

        assert result.llm_configured is True
        assert result.llm_provider == "anthropic"


class TestConnectK8s:
    async def test_verification_failure_raises_400(self):
        request, conn = _make_request()
        with patch(
            "api.routes.workspace_credentials.verify_k8s_connection",
            new=AsyncMock(side_effect=K8sConnectError("bad token")),
        ):
            with pytest.raises(HTTPException) as exc:
                await wc_routes.connect_k8s(
                    wc_routes.ConnectK8sRequest(api_url="https://cluster.example.com", token="bad-token"),
                    request,
                    workspace={"id": uuid4()},
                )
        assert exc.value.status_code == 400
        conn.execute.assert_not_awaited()

    async def test_valid_cluster_stores_and_returns_status(self):
        workspace_id = uuid4()
        request, conn = _make_request()
        with (
            patch("api.routes.workspace_credentials.verify_k8s_connection", new=AsyncMock(return_value=None)),
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            result = await wc_routes.connect_k8s(
                wc_routes.ConnectK8sRequest(api_url="https://cluster.example.com", token="real-token"),
                request,
                workspace={"id": workspace_id},
            )
        assert result.id == str(workspace_id)
        conn.execute.assert_awaited_once()

    async def test_ca_cert_is_optional(self):
        workspace_id = uuid4()
        request, conn = _make_request()
        with (
            patch("api.routes.workspace_credentials.verify_k8s_connection", new=AsyncMock(return_value=None)) as mock_verify,
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            await wc_routes.connect_k8s(
                wc_routes.ConnectK8sRequest(api_url="https://cluster.example.com", token="real-token"),
                request,
                workspace={"id": workspace_id},
            )
        mock_verify.assert_awaited_once_with("https://cluster.example.com", "real-token", None)


class TestGetConnectionsStatusMemberRole:
    # Onboarding completeness build, item 4: get_connections_status widened
    # from get_workspace to get_workspace_or_member -- member_role must
    # pass through so the frontend knows whether to show the Workspace
    # Token card's rotate action.
    async def test_member_role_passed_through_when_present(self):
        workspace = {"id": uuid4(), "member_role": "viewer"}
        result = await wc_routes.get_connections_status(workspace=workspace)
        assert result.member_role == "viewer"

    async def test_member_role_none_for_token_authenticated_caller(self):
        workspace = {"id": uuid4()}
        result = await wc_routes.get_connections_status(workspace=workspace)
        assert result.member_role is None


class TestGetWorkspaceTokenStatus:
    async def test_token_authenticated_caller_always_allowed(self):
        workspace = {"id": uuid4(), "workspace_token_last4": "ab12", "workspace_token_rotated_at": None}
        result = await wc_routes.get_workspace_token_status(workspace=workspace)
        assert result.last4 == "ab12"
        assert result.rotated_at is None

    async def test_admin_member_allowed(self):
        workspace = {"id": uuid4(), "member_role": "admin", "workspace_token_last4": "cd34", "workspace_token_rotated_at": None}
        result = await wc_routes.get_workspace_token_status(workspace=workspace)
        assert result.last4 == "cd34"

    async def test_viewer_member_rejected(self):
        workspace = {"id": uuid4(), "member_role": "viewer", "workspace_token_last4": "ef56"}
        with pytest.raises(HTTPException) as exc:
            await wc_routes.get_workspace_token_status(workspace=workspace)
        assert exc.value.status_code == 403

    async def test_approver_member_rejected(self):
        # Deliberately stricter than incidents.py's _APPROVAL_ROLES
        # (admin OR approver) -- token rotation is more sensitive than
        # approving a remediation, admin-only here.
        workspace = {"id": uuid4(), "member_role": "approver"}
        with pytest.raises(HTTPException) as exc:
            await wc_routes.get_workspace_token_status(workspace=workspace)
        assert exc.value.status_code == 403

    async def test_serializes_rotated_at_to_isoformat(self):
        from datetime import datetime, timezone
        rotated = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
        workspace = {"id": uuid4(), "workspace_token_last4": "gh78", "workspace_token_rotated_at": rotated}
        result = await wc_routes.get_workspace_token_status(workspace=workspace)
        assert result.rotated_at == rotated.isoformat()


class TestRotateWorkspaceTokenSelfServe:
    async def test_viewer_member_rejected_before_any_db_write(self):
        request, conn = _make_request()
        workspace = {"id": uuid4(), "member_role": "viewer"}
        with pytest.raises(HTTPException) as exc:
            await wc_routes.rotate_workspace_token_self_serve(request, workspace=workspace)
        assert exc.value.status_code == 403
        conn.execute.assert_not_awaited()

    async def test_admin_member_can_rotate(self):
        from datetime import datetime, timedelta, timezone
        rotated = datetime.now(timezone.utc)
        grace_ends = rotated + timedelta(hours=72)
        workspace_id = uuid4()
        request, conn = _make_request(fetchrow_return={
            "workspace_token_rotated_at": rotated, "previous_workspace_token_expires_at": grace_ends,
        })
        workspace = {"id": workspace_id, "member_role": "admin"}

        with patch("api.routes.workspace_credentials.write_audit_event", new=AsyncMock()) as mock_audit:
            result = await wc_routes.rotate_workspace_token_self_serve(request, workspace=workspace)

        assert result.workspace_token.startswith("cd_ws_")
        assert result.last4 == result.workspace_token[-4:]
        assert result.rotated_at == rotated.isoformat()
        assert result.grace_period_ends_at == grace_ends.isoformat()
        assert len(result.alert_source_checklist) > 0
        conn.fetchrow.assert_awaited_once()
        mock_audit.assert_awaited_once()
        assert mock_audit.await_args.kwargs["action"] == "workspace_token_rotated"
        assert mock_audit.await_args.kwargs["workspace_id"] == str(workspace_id)

    async def test_token_authenticated_caller_always_allowed(self):
        from datetime import datetime, timedelta, timezone
        rotated = datetime.now(timezone.utc)
        request, conn = _make_request(fetchrow_return={
            "workspace_token_rotated_at": rotated,
            "previous_workspace_token_expires_at": rotated + timedelta(hours=72),
        })
        workspace = {"id": uuid4()}  # no member_role key at all -- token path

        with patch("api.routes.workspace_credentials.write_audit_event", new=AsyncMock()):
            result = await wc_routes.rotate_workspace_token_self_serve(request, workspace=workspace)

        assert result.workspace_token.startswith("cd_ws_")

    async def test_new_token_is_hashed_before_storage_not_stored_raw(self):
        from datetime import datetime, timedelta, timezone
        rotated = datetime.now(timezone.utc)
        request, conn = _make_request(fetchrow_return={
            "workspace_token_rotated_at": rotated,
            "previous_workspace_token_expires_at": rotated + timedelta(hours=72),
        })
        workspace = {"id": uuid4()}

        with patch("api.routes.workspace_credentials.write_audit_event", new=AsyncMock()):
            result = await wc_routes.rotate_workspace_token_self_serve(request, workspace=workspace)

        update_sql, token_hash_arg, last4_arg, workspace_id_arg = conn.fetchrow.await_args.args
        assert "UPDATE workspaces SET" in update_sql
        assert "workspace_token = $1" in update_sql
        # A previously issued token keeps a grace window; a never-issued one doesn't (migration 071).
        assert "previous_workspace_token_hash = CASE WHEN workspace_token_issued_at IS NULL" in update_sql
        assert "THEN NULL ELSE workspace_token END" in update_sql
        assert "workspace_token_issued_at = NOW()" in update_sql
        assert token_hash_arg != result.workspace_token  # never the raw token
        assert last4_arg == result.last4

    async def test_first_generation_has_no_grace_window(self):
        from datetime import datetime, timezone
        request, _ = _make_request(fetchrow_return={
            "workspace_token_rotated_at": datetime.now(timezone.utc),
            "previous_workspace_token_expires_at": None,
        })
        with patch("api.routes.workspace_credentials.write_audit_event", new=AsyncMock()):
            result = await wc_routes.rotate_workspace_token_self_serve(request, workspace={"id": uuid4()})
        assert result.grace_period_ends_at is None
        assert result.workspace_token.startswith("cd_ws_")

    async def test_token_status_reports_whether_a_token_was_ever_issued(self):
        admin = {"id": uuid4(), "member_role": "admin"}
        never = await wc_routes.get_workspace_token_status(workspace={**admin, "workspace_token_issued_at": None})
        issued = await wc_routes.get_workspace_token_status(
            workspace={**admin, "workspace_token_issued_at": "2026-11-18", "workspace_token_last4": "abcd"})
        assert never.issued is False and issued.issued is True

    async def test_each_rotation_generates_a_distinct_token(self):
        from datetime import datetime, timedelta, timezone
        rotated = datetime.now(timezone.utc)
        request, _ = _make_request(fetchrow_return={
            "workspace_token_rotated_at": rotated,
            "previous_workspace_token_expires_at": rotated + timedelta(hours=72),
        })
        workspace = {"id": uuid4()}

        with patch("api.routes.workspace_credentials.write_audit_event", new=AsyncMock()):
            first = await wc_routes.rotate_workspace_token_self_serve(request, workspace=workspace)
            second = await wc_routes.rotate_workspace_token_self_serve(request, workspace=workspace)

        assert first.workspace_token != second.workspace_token


class TestConnectionModeDefault:
    """Migration 067: a connection with no stored mode reads as Read-Only, never Execute."""

    async def test_missing_mode_reports_read_only(self):
        out = await wc_routes.get_connections_status(workspace={"id": uuid4()})
        assert out.aws_connection_mode == "read_only"
        assert out.azure_connection_mode == "read_only"

    async def test_stored_execute_is_reported_as_is(self):
        out = await wc_routes.get_connections_status(
            workspace={"id": uuid4(), "aws_connection_mode": "execute", "azure_connection_mode": "read_only"},
        )
        assert out.aws_connection_mode == "execute"
        assert out.azure_connection_mode == "read_only"

    def test_response_model_default_is_read_only(self):
        assert wc_routes.ConnectionsStatusResponse.model_fields["aws_connection_mode"].default == "read_only"
        assert wc_routes.ConnectionsStatusResponse.model_fields["azure_connection_mode"].default == "read_only"
