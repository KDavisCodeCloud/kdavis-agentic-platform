"""
tests/test_github_app_admin.py
Tests for api/routes/github_app_admin.py -- the one-time platform bootstrap
for the item 4 GitHub App migration (register -> manifest -> callback).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from api.routes import github_app_admin
from core.github_app import GitHubAppError

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


class TestRegisterGithubApp:
    async def test_returns_manifest_and_registration_url_when_not_yet_registered(self):
        request, conn = _make_request(fetchrow_return=None)
        result = await github_app_admin.register_github_app(request, admin={"id": "kelvin"})
        assert "manifest" in result
        assert result["manifest"]["public"] is False
        assert "registration_url" in result

    async def test_raises_409_when_already_registered(self):
        request, conn = _make_request(fetchrow_return={"id": "singleton"})
        with pytest.raises(HTTPException) as exc:
            await github_app_admin.register_github_app(request, admin={"id": "kelvin"})
        assert exc.value.status_code == 409


class TestGithubAppManifestCallback:
    async def test_stores_app_config_on_successful_exchange(self):
        request, conn = _make_request(fetchrow_return=None)
        app_creds = {
            "app_id": "999", "slug": "cloud-decoded", "client_id": "Iv1.abc",
            "client_secret": "secret", "webhook_secret": "whsec", "pem": "-----BEGIN PEM-----",
        }
        with (
            patch("api.routes.github_app_admin.exchange_manifest_code", AsyncMock(return_value=app_creds)),
            patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}),
        ):
            result = await github_app_admin.github_app_manifest_callback(request, code="one-time-code")

        assert result["status"] == "registered"
        assert result["app_id"] == "999"
        conn.execute.assert_awaited_once()

    async def test_raises_409_when_already_registered(self):
        request, conn = _make_request(fetchrow_return={"id": "singleton"})
        with pytest.raises(HTTPException) as exc:
            await github_app_admin.github_app_manifest_callback(request, code="code")
        assert exc.value.status_code == 409

    async def test_raises_400_on_exchange_failure(self):
        request, conn = _make_request(fetchrow_return=None)
        with patch(
            "api.routes.github_app_admin.exchange_manifest_code",
            AsyncMock(side_effect=GitHubAppError("bad code")),
        ):
            with pytest.raises(HTTPException) as exc:
                await github_app_admin.github_app_manifest_callback(request, code="bad-code")
        assert exc.value.status_code == 400
