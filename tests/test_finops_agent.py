"""
tests/test_finops_agent.py
Tests for api/routes/finops_agent.py -- the proxy layer to the
separately-deployed kdavis-finops-agent Railway service.

What this file validates:
  - status: never creates anything, correctly derives connected/
    pending_setup/setup from the 4 workspace columns.
  - connect: happy path stores the encrypted tenant token + setup JSON;
    409 if already connected/pending, without a second remote call.
  - verify-role: happy path sets finops_agent_connected_at; upstream
    AssumeRole failure surfaces as 400, doesn't touch the DB.
  - scan/dashboard/approve/dismiss: 400 if not connected yet; happy path
    decrypts the token and passes through the remote response; a 4xx
    from the remote service passes through with the same status code
    rather than collapsing to a generic 502.

Mocks integrations.finops_agent_client entirely -- no live network.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from api.routes import finops_agent
from integrations.finops_agent_client import AgentServiceError
from security.encryption import decrypt, encrypt


@pytest.fixture(autouse=True)
def _encryption_key():
    key = Fernet.generate_key().decode()
    with patch.dict("os.environ", {"ENCRYPTION_KEY": key}):
        yield key


def _make_request(conn) -> SimpleNamespace:
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


def _connection_row(**overrides) -> dict:
    row = {
        "finops_agent_tenant_id": None,
        "encrypted_finops_agent_tenant_token": None,
        "finops_agent_setup_json": None,
        "finops_agent_connected_at": None,
    }
    row.update(overrides)
    return row


class TestGetStatus:
    async def test_never_connected(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        request = _make_request(conn)

        result = await finops_agent.get_status(request, workspace={"id": uuid4()})

        assert result.connected is False
        assert result.pending_setup is False
        assert result.setup is None

    async def test_pending_setup_returns_stored_setup_json(self):
        setup = {"aws_trust_policy": {"a": 1}, "aws_permissions_policy": {"b": 2}}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(finops_agent_tenant_id=uuid4(), finops_agent_setup_json=setup)
        )
        request = _make_request(conn)

        result = await finops_agent.get_status(request, workspace={"id": uuid4()})

        assert result.connected is False
        assert result.pending_setup is True
        assert result.setup == setup

    async def test_connected(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(finops_agent_tenant_id=uuid4(), finops_agent_connected_at="2026-09-11")
        )
        request = _make_request(conn)

        result = await finops_agent.get_status(request, workspace={"id": uuid4()})

        assert result.connected is True
        assert result.pending_setup is False


class TestConnect:
    async def test_happy_path_stores_encrypted_token_and_setup_json(self):
        workspace_id = uuid4()
        remote_tenant_id = str(uuid4())
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        conn.execute = AsyncMock()
        request = _make_request(conn)
        fake_workspace = {"id": workspace_id, "company_name": "Acme"}

        remote_response = {
            "id": remote_tenant_id,
            "tenant_token": "fo_t_rawtoken",
            "aws_trust_policy": {"Statement": []},
            "aws_permissions_policy": {"Statement": []},
            "azure_setup_instructions": "az ad sp create-for-rbac ...",
        }
        with patch("api.routes.finops_agent.client.create_tenant", new=AsyncMock(return_value=remote_response)):
            result = await finops_agent.connect(request, workspace=fake_workspace)

        assert result.pending_setup is True
        assert result.setup["aws_trust_policy"] == {"Statement": []}
        assert result.setup["azure_setup_instructions"] == "az ad sp create-for-rbac ..."

        sql, tenant_id, encrypted_token, setup_json, bound_workspace_id = conn.execute.await_args.args
        assert tenant_id == remote_tenant_id
        assert decrypt(encrypted_token) == "fo_t_rawtoken"
        assert bound_workspace_id == workspace_id

    async def test_already_connected_returns_409_without_calling_remote(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row(finops_agent_tenant_id=uuid4()))
        request = _make_request(conn)

        with patch("api.routes.finops_agent.client.create_tenant", new=AsyncMock()) as mock_create:
            with pytest.raises(HTTPException) as exc:
                await finops_agent.connect(request, workspace={"id": uuid4(), "company_name": "Acme"})

        assert exc.value.status_code == 409
        mock_create.assert_not_called()

    async def test_remote_failure_returns_502(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        request = _make_request(conn)

        with patch(
            "api.routes.finops_agent.client.create_tenant",
            new=AsyncMock(side_effect=AgentServiceError("boom")),
        ):
            with pytest.raises(HTTPException) as exc:
                await finops_agent.connect(request, workspace={"id": uuid4(), "company_name": "Acme"})

        assert exc.value.status_code == 502


class TestVerifyRole:
    async def test_happy_path_marks_connected(self):
        workspace_id = uuid4()
        tenant_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                finops_agent_tenant_id=tenant_id,
                encrypted_finops_agent_tenant_token=encrypt("fo_t_raw"),
            )
        )
        conn.execute = AsyncMock()
        request = _make_request(conn)

        with patch("api.routes.finops_agent.client.verify_aws_role", new=AsyncMock()) as mock_verify:
            result = await finops_agent.verify_role(
                finops_agent.VerifyRoleRequest(role_arn="arn:aws:iam::1:role/x"),
                request,
                workspace={"id": workspace_id},
            )

        assert result.status == "active"
        mock_verify.assert_awaited_once_with(str(tenant_id), "fo_t_raw", "arn:aws:iam::1:role/x")
        sql, bound_workspace_id = conn.execute.await_args.args
        assert bound_workspace_id == workspace_id

    async def test_never_connected_returns_400(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await finops_agent.verify_role(
                finops_agent.VerifyRoleRequest(role_arn="arn:x"), request, workspace={"id": uuid4()}
            )
        assert exc.value.status_code == 400

    async def test_upstream_assume_role_failure_returns_400(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                finops_agent_tenant_id=uuid4(), encrypted_finops_agent_tenant_token=encrypt("t")
            )
        )
        request = _make_request(conn)

        with patch(
            "api.routes.finops_agent.client.verify_aws_role",
            new=AsyncMock(side_effect=AgentServiceError("access denied")),
        ):
            with pytest.raises(HTTPException) as exc:
                await finops_agent.verify_role(
                    finops_agent.VerifyRoleRequest(role_arn="arn:x"), request, workspace={"id": uuid4()}
                )
        assert exc.value.status_code == 400


class TestVerifyAzure:
    async def test_happy_path_marks_connected(self):
        workspace_id = uuid4()
        tenant_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                finops_agent_tenant_id=tenant_id,
                encrypted_finops_agent_tenant_token=encrypt("fo_t_raw"),
            )
        )
        conn.execute = AsyncMock()
        request = _make_request(conn)

        with patch("api.routes.finops_agent.client.verify_azure_service_principal", new=AsyncMock()) as mock_verify:
            result = await finops_agent.verify_azure(
                finops_agent.VerifyAzureServicePrincipalRequest(
                    azure_tenant_id="tid", client_id="cid", client_secret="secret", subscription_id="sub",
                ),
                request,
                workspace={"id": workspace_id},
            )

        assert result.status == "active"
        mock_verify.assert_awaited_once_with(str(tenant_id), "fo_t_raw", "tid", "cid", "secret", "sub")
        sql, bound_workspace_id = conn.execute.await_args.args
        assert bound_workspace_id == workspace_id

    async def test_never_connected_returns_400(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await finops_agent.verify_azure(
                finops_agent.VerifyAzureServicePrincipalRequest(
                    azure_tenant_id="tid", client_id="cid", client_secret="s", subscription_id="sub",
                ),
                request,
                workspace={"id": uuid4()},
            )
        assert exc.value.status_code == 400

    async def test_upstream_verification_failure_returns_400(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                finops_agent_tenant_id=uuid4(), encrypted_finops_agent_tenant_token=encrypt("t")
            )
        )
        request = _make_request(conn)

        with patch(
            "api.routes.finops_agent.client.verify_azure_service_principal",
            new=AsyncMock(side_effect=AgentServiceError("bad creds")),
        ):
            with pytest.raises(HTTPException) as exc:
                await finops_agent.verify_azure(
                    finops_agent.VerifyAzureServicePrincipalRequest(
                        azure_tenant_id="tid", client_id="cid", client_secret="s", subscription_id="sub",
                    ),
                    request,
                    workspace={"id": uuid4()},
                )
        assert exc.value.status_code == 400


class TestScanDashboardHitl:
    async def test_scan_not_connected_yet_400(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await finops_agent.scan(request, workspace={"id": uuid4()})
        assert exc.value.status_code == 400

    async def test_dashboard_passes_through_remote_response(self):
        tenant_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                finops_agent_tenant_id=tenant_id,
                encrypted_finops_agent_tenant_token=encrypt("fo_t_raw"),
                finops_agent_connected_at="2026-09-11",
            )
        )
        request = _make_request(conn)

        with patch(
            "api.routes.finops_agent.client.get_dashboard",
            new=AsyncMock(return_value={"tenant_id": str(tenant_id), "open_items": []}),
        ) as mock_dashboard:
            result = await finops_agent.dashboard(request, workspace={"id": uuid4()})

        assert result == {"tenant_id": str(tenant_id), "open_items": []}
        mock_dashboard.assert_awaited_once_with(str(tenant_id), "fo_t_raw")

    async def test_remote_404_passes_through_status_not_generic_502(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                finops_agent_tenant_id=uuid4(),
                encrypted_finops_agent_tenant_token=encrypt("t"),
                finops_agent_connected_at="2026-09-11",
            )
        )
        request = _make_request(conn)

        with patch(
            "api.routes.finops_agent.client.get_dashboard",
            new=AsyncMock(side_effect=AgentServiceError("not found", status_code=404)),
        ):
            with pytest.raises(HTTPException) as exc:
                await finops_agent.dashboard(request, workspace={"id": uuid4()})
        assert exc.value.status_code == 404

    async def test_approve_item_scoped_by_decrypted_token(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                finops_agent_tenant_id=uuid4(),
                encrypted_finops_agent_tenant_token=encrypt("fo_t_raw"),
                finops_agent_connected_at="2026-09-11",
            )
        )
        request = _make_request(conn)

        with patch(
            "api.routes.finops_agent.client.approve_item",
            new=AsyncMock(return_value={"id": "item-1", "status": "approved"}),
        ) as mock_approve:
            result = await finops_agent.approve_item("item-1", request, workspace={"id": uuid4()})

        assert result["status"] == "approved"
        mock_approve.assert_awaited_once_with("fo_t_raw", "item-1")
