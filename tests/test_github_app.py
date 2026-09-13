"""
tests/test_github_app.py
Tests for core/github_app.py -- manifest building, the manifest-flow code
exchange, installation-token minting (JWT signing + exchange), and the
signed workspace-state param used to tie GitHub's install-callback redirect
back to a real workspace. No live network, no live GitHub App.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from core.github_app import (
    GitHubAppError,
    build_install_url,
    build_manifest,
    build_registration_url,
    exchange_manifest_code,
    mint_installation_token,
    sign_workspace_state,
    verify_workspace_state,
)


def _resp(status_code: int, json_body=None, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body or {}
    r.text = text
    return r


def _client_ctx(mock_client: AsyncMock) -> AsyncMock:
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _test_private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


class TestBuildManifest:
    def test_includes_fine_grained_permissions_not_broader(self):
        manifest = build_manifest("Cloud Decoded", "https://x.com", "https://x.com/cb", "https://x.com/wh")
        assert manifest["default_permissions"] == {
            "contents": "write", "pull_requests": "write", "metadata": "read",
        }

    def test_is_not_public(self):
        manifest = build_manifest("Cloud Decoded", "https://x.com", "https://x.com/cb", "https://x.com/wh")
        assert manifest["public"] is False

    def test_hook_url_set_from_webhook_url_arg(self):
        manifest = build_manifest("Cloud Decoded", "https://x.com", "https://x.com/cb", "https://x.com/wh")
        assert manifest["hook_attributes"]["url"] == "https://x.com/wh"


class TestBuildRegistrationUrl:
    def test_includes_state(self):
        url = build_registration_url("mystate")
        assert "state=mystate" in url
        assert url.startswith("https://github.com/settings/apps/new")


class TestBuildInstallUrl:
    def test_includes_slug_and_state(self):
        url = build_install_url("cloud-decoded", "signedstate")
        assert "github.com/apps/cloud-decoded/installations/new" in url
        assert "state=signedstate" in url


class TestExchangeManifestCode:
    async def test_returns_app_credentials_on_success(self):
        body = {
            "id": 12345, "slug": "cloud-decoded", "client_id": "Iv1.abc",
            "client_secret": "secret123", "webhook_secret": "whsec", "pem": "-----BEGIN PEM-----",
        }
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(201, body))
        with patch("core.github_app.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await exchange_manifest_code("one-time-code")
        assert result["app_id"] == "12345"
        assert result["slug"] == "cloud-decoded"
        assert result["client_secret"] == "secret123"
        assert result["webhook_secret"] == "whsec"
        assert result["pem"] == "-----BEGIN PEM-----"

    async def test_raises_github_app_error_on_failure(self):
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(404, text="not found"))
        with patch("core.github_app.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(GitHubAppError):
                await exchange_manifest_code("bad-code")

    async def test_raises_on_network_error(self):
        import httpx
        client = AsyncMock()
        client.post = AsyncMock(side_effect=httpx.RequestError("boom"))
        with patch("core.github_app.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(GitHubAppError):
                await exchange_manifest_code("code")


class TestMintInstallationToken:
    async def test_signs_valid_rs256_jwt_and_returns_installation_token(self):
        pem = _test_private_key_pem()
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(201, {"token": "ghs_freshtoken"}))

        captured_headers = {}

        async def _capture_post(url, headers=None, **kwargs):
            captured_headers.update(headers or {})
            return _resp(201, {"token": "ghs_freshtoken"})

        client.post = AsyncMock(side_effect=_capture_post)
        with patch("core.github_app.httpx.AsyncClient", return_value=_client_ctx(client)):
            token = await mint_installation_token("999", pem, "installation-1")

        assert token == "ghs_freshtoken"
        auth_header = captured_headers["Authorization"]
        assert auth_header.startswith("Bearer ")
        app_jwt = auth_header.removeprefix("Bearer ")
        # Decode without verifying signature against the public key -- just
        # confirm the claims shape is what GitHub's App auth flow requires.
        claims = jwt.get_unverified_claims(app_jwt)
        assert claims["iss"] == "999"
        assert claims["exp"] > claims["iat"]
        assert claims["exp"] - int(time.time()) < 600  # well under the 10-minute max

    async def test_raises_on_non_201_response(self):
        pem = _test_private_key_pem()
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(403, text="Suspended installation"))
        with patch("core.github_app.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(GitHubAppError):
                await mint_installation_token("999", pem, "installation-1")

    async def test_raises_on_missing_token_in_response(self):
        pem = _test_private_key_pem()
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(201, {}))
        with patch("core.github_app.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(GitHubAppError):
                await mint_installation_token("999", pem, "installation-1")


class TestWorkspaceState:
    def test_verify_accepts_a_freshly_signed_state(self):
        with patch.dict("os.environ", {"ENCRYPTION_KEY": "test-key"}):
            state = sign_workspace_state("workspace-abc")
            assert verify_workspace_state(state) == "workspace-abc"

    def test_verify_rejects_tampered_workspace_id(self):
        with patch.dict("os.environ", {"ENCRYPTION_KEY": "test-key"}):
            state = sign_workspace_state("workspace-abc")
            payload, ts, sig = state.rsplit(":", 2)
            tampered = f"workspace-evil:{ts}:{sig}"
            assert verify_workspace_state(tampered) is None

    def test_verify_rejects_expired_state(self):
        with patch.dict("os.environ", {"ENCRYPTION_KEY": "test-key"}):
            with patch("core.github_app.time.time", return_value=1_000_000):
                state = sign_workspace_state("workspace-abc")
            with patch("core.github_app.time.time", return_value=1_000_000 + 10_000):
                assert verify_workspace_state(state) is None

    def test_verify_rejects_garbage_input(self):
        with patch.dict("os.environ", {"ENCRYPTION_KEY": "test-key"}):
            assert verify_workspace_state("not-a-real-state") is None
