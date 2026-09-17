"""
tests/test_workspaces.py
Tests for api/routes/workspaces.py — workspace creation + BYOK LLM key
storage (GAPS.md gap #4: the onboarding wizard previously called neither).

What this file validates:
  - create_workspace: the hash written to the DB equals _hash_token() of the
    raw token returned to the caller — this is the one invariant that must
    hold for api.middleware.auth.get_workspace to ever find this workspace
    again by that token.
  - create_workspace: missing company_name fails Pydantic validation (422
    at the FastAPI layer) before the handler ever runs.
  - create_workspace: missing/invalid contact_email fails Pydantic
    validation the same way (added 2026-09-14 — see GAPS.md: no email
    column meant Cloud Decoded's own code had no address to send a welcome
    email or an Enterprise MCP-invite alert to).
  - save_llm_key: happy path encrypts the raw key (ciphertext written to the
    DB is never the plaintext) and stores the chosen provider, scoped to
    the authenticated workspace's id.
  - save_llm_key: an unsupported provider is rejected with 400 before
    anything is written.

Runs with pytest-asyncio + unittest.mock — no live DB, no live network.
Rate limiting is disabled for these tests (see _no_rate_limit fixture) since
slowapi's decorator requires a real starlette.requests.Request instance,
which these SimpleNamespace-based fakes deliberately are not — matching the
same call-the-handler-directly convention as tests/test_internal_agents.py.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError

from api.middleware.auth import _hash_token
from api.middleware.rate_limiter import limiter
from api.routes import workspaces


@pytest.fixture(autouse=True)
def _no_rate_limit():
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture(autouse=True)
def _encryption_key():
    key = Fernet.generate_key().decode()
    with patch.dict("os.environ", {"ENCRYPTION_KEY": key}):
        yield key


def _make_app_with_db(fetchrow_result=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.execute = AsyncMock(return_value=None)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
    return request, conn


class TestCreateWorkspace:
    async def test_hash_written_matches_returned_token(self):
        fake_id = uuid4()
        request, conn = _make_app_with_db(fetchrow_result={"id": fake_id})

        result = await workspaces.create_workspace(
            workspaces.CreateWorkspaceRequest(
                company_name="Acme Engineering", contact_email="ops@acme.com", tos_accepted=True,
            ),
            request,
        )

        assert result.id == str(fake_id)
        assert result.workspace_token.startswith("cd_ws_")
        assert "not be shown again" in result.warning

        sql, company_name, token_hash, contact_email = conn.fetchrow.await_args.args
        assert "INSERT INTO workspaces" in sql
        assert "tos_accepted_at" in sql
        assert company_name == "Acme Engineering"
        assert token_hash == _hash_token(result.workspace_token)
        # never store the raw token
        assert token_hash != result.workspace_token
        assert contact_email == "ops@acme.com"

    async def test_missing_company_name_fails_validation(self):
        with pytest.raises(ValidationError):
            workspaces.CreateWorkspaceRequest(contact_email="ops@acme.com", tos_accepted=True)

    async def test_missing_contact_email_fails_validation(self):
        with pytest.raises(ValidationError):
            workspaces.CreateWorkspaceRequest(company_name="Acme Engineering", tos_accepted=True)

    async def test_invalid_contact_email_fails_validation(self):
        with pytest.raises(ValidationError):
            workspaces.CreateWorkspaceRequest(
                company_name="Acme Engineering", contact_email="not-an-email", tos_accepted=True,
            )

    async def test_missing_tos_accepted_fails_validation(self):
        with pytest.raises(ValidationError):
            workspaces.CreateWorkspaceRequest(company_name="Acme Engineering", contact_email="ops@acme.com")

    async def test_tos_accepted_false_fails_validation(self):
        with pytest.raises(ValidationError):
            workspaces.CreateWorkspaceRequest(
                company_name="Acme Engineering", contact_email="ops@acme.com", tos_accepted=False,
            )

    async def test_contact_email_normalized_lowercase_and_trimmed(self):
        fake_id = uuid4()
        request, conn = _make_app_with_db(fetchrow_result={"id": fake_id})

        await workspaces.create_workspace(
            workspaces.CreateWorkspaceRequest(
                company_name="Acme", contact_email="  OPS@Acme.COM  ", tos_accepted=True,
            ),
            request,
        )

        _, _, _, contact_email = conn.fetchrow.await_args.args
        assert contact_email == "ops@acme.com"


class TestSaveLlmKey:
    async def test_happy_path_encrypts_and_scopes_to_workspace(self):
        workspace_id = uuid4()
        request, conn = _make_app_with_db()
        fake_workspace = {"id": workspace_id, "company_name": "Acme"}

        result = await workspaces.save_llm_key(
            workspaces.SaveLlmKeyRequest(provider="anthropic", api_key="sk-ant-api03-realkey"),
            request,
            workspace=fake_workspace,
        )

        assert result.status == "ok"
        sql, encrypted_value, provider, bound_workspace_id = conn.execute.await_args.args
        assert "UPDATE workspaces" in sql
        assert "sk-ant-api03-realkey" not in encrypted_value
        assert provider == "anthropic"
        assert bound_workspace_id == workspace_id

    async def test_invalid_provider_rejected_before_write(self):
        request, conn = _make_app_with_db()
        fake_workspace = {"id": uuid4()}

        with pytest.raises(HTTPException) as exc:
            await workspaces.save_llm_key(
                workspaces.SaveLlmKeyRequest(provider="deepseek", api_key="whatever"),
                request,
                workspace=fake_workspace,
            )

        assert exc.value.status_code == 400
        conn.execute.assert_not_called()


class TestSetContactEmail:
    """Kelvin's item 7, 2026-09-17 -- lets a workspace missing
    contact_email (possible via the admin/MCP-invite path, unlike
    self-serve signup where it's required) fix it themselves."""

    async def test_token_authenticated_caller_can_set(self):
        workspace_id = uuid4()
        request, conn = _make_app_with_db()
        fake_workspace = {"id": workspace_id}  # no member_role key -- token path

        result = await workspaces.set_contact_email(
            workspaces.SetContactEmailRequest(contact_email="ops@acme.com"),
            request,
            workspace=fake_workspace,
        )

        assert result.contact_email == "ops@acme.com"
        sql, email, bound_workspace_id = conn.execute.await_args.args
        assert "UPDATE workspaces" in sql
        assert "contact_email" in sql
        assert email == "ops@acme.com"
        assert bound_workspace_id == workspace_id

    async def test_admin_member_can_set(self):
        workspace_id = uuid4()
        request, conn = _make_app_with_db()
        fake_workspace = {"id": workspace_id, "member_role": "admin"}

        result = await workspaces.set_contact_email(
            workspaces.SetContactEmailRequest(contact_email="ops@acme.com"),
            request,
            workspace=fake_workspace,
        )
        assert result.contact_email == "ops@acme.com"

    async def test_non_admin_member_rejected(self):
        request, conn = _make_app_with_db()
        fake_workspace = {"id": uuid4(), "member_role": "viewer"}

        with pytest.raises(HTTPException) as exc:
            await workspaces.set_contact_email(
                workspaces.SetContactEmailRequest(contact_email="ops@acme.com"),
                request,
                workspace=fake_workspace,
            )
        assert exc.value.status_code == 403
        conn.execute.assert_not_called()

    async def test_invalid_email_rejected_at_model_level(self):
        with pytest.raises(ValueError):
            workspaces.SetContactEmailRequest(contact_email="not-an-email")
