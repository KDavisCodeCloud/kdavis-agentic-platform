"""
tests/test_compliance_agent.py
Tests for api/routes/compliance_agent.py -- the proxy layer to the
separately-deployed kdavis-compliance-agent Railway service.

Mirrors tests/test_finops_agent.py's coverage exactly, minus the HITL
approve/dismiss cases (compliance reports have no HITL queue) and with
GET /report in place of GET /dashboard.

Mocks integrations.compliance_agent_client entirely -- no live network.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from api.routes import compliance_agent
from integrations.compliance_agent_client import AgentServiceError
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
        "compliance_agent_tenant_id": None,
        "encrypted_compliance_agent_tenant_token": None,
        "compliance_agent_setup_json": None,
        "compliance_agent_connected_at": None,
    }
    row.update(overrides)
    return row


class TestGetStatus:
    async def test_never_connected(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        request = _make_request(conn)

        result = await compliance_agent.get_status(request, workspace={"id": uuid4()})

        assert result.connected is False
        assert result.pending_setup is False

    async def test_pending_setup_returns_stored_setup_json(self):
        setup = {"aws_trust_policy": {"a": 1}, "aws_permissions_policy": {"b": 2}}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(compliance_agent_tenant_id=uuid4(), compliance_agent_setup_json=setup)
        )
        request = _make_request(conn)

        result = await compliance_agent.get_status(request, workspace={"id": uuid4()})

        assert result.pending_setup is True
        assert result.setup == setup

    async def test_connected(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                compliance_agent_tenant_id=uuid4(), compliance_agent_connected_at="2026-09-11"
            )
        )
        request = _make_request(conn)

        result = await compliance_agent.get_status(request, workspace={"id": uuid4()})

        assert result.connected is True


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
            "tenant_token": "co_t_rawtoken",
            "aws_trust_policy": {"Statement": []},
            "aws_permissions_policy": {"Statement": []},
            "azure_setup_instructions": "az ad sp create-for-rbac ...",
        }
        with patch(
            "api.routes.compliance_agent.client.create_tenant", new=AsyncMock(return_value=remote_response)
        ):
            result = await compliance_agent.connect(request, workspace=fake_workspace)

        assert result.pending_setup is True
        sql, tenant_id, encrypted_token, setup_json, bound_workspace_id = conn.execute.await_args.args
        assert tenant_id == remote_tenant_id
        assert decrypt(encrypted_token) == "co_t_rawtoken"
        assert bound_workspace_id == workspace_id

    async def test_already_connected_returns_409_without_calling_remote(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row(compliance_agent_tenant_id=uuid4()))
        request = _make_request(conn)

        with patch("api.routes.compliance_agent.client.create_tenant", new=AsyncMock()) as mock_create:
            with pytest.raises(HTTPException) as exc:
                await compliance_agent.connect(request, workspace={"id": uuid4(), "company_name": "Acme"})

        assert exc.value.status_code == 409
        mock_create.assert_not_called()


class TestVerifyRole:
    async def test_happy_path_marks_connected(self):
        workspace_id = uuid4()
        tenant_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                compliance_agent_tenant_id=tenant_id,
                encrypted_compliance_agent_tenant_token=encrypt("co_t_raw"),
            )
        )
        conn.execute = AsyncMock()
        request = _make_request(conn)

        with patch("api.routes.compliance_agent.client.verify_aws_role", new=AsyncMock()) as mock_verify:
            result = await compliance_agent.verify_role(
                compliance_agent.VerifyRoleRequest(role_arn="arn:aws:iam::1:role/x"),
                request,
                workspace={"id": workspace_id},
            )

        assert result.status == "active"
        mock_verify.assert_awaited_once_with(str(tenant_id), "co_t_raw", "arn:aws:iam::1:role/x")

    async def test_never_connected_returns_400(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await compliance_agent.verify_role(
                compliance_agent.VerifyRoleRequest(role_arn="arn:x"), request, workspace={"id": uuid4()}
            )
        assert exc.value.status_code == 400


class TestVerifyAzure:
    async def test_happy_path_marks_connected(self):
        workspace_id = uuid4()
        tenant_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                compliance_agent_tenant_id=tenant_id,
                encrypted_compliance_agent_tenant_token=encrypt("co_t_raw"),
            )
        )
        conn.execute = AsyncMock()
        request = _make_request(conn)

        with patch("api.routes.compliance_agent.client.verify_azure_service_principal", new=AsyncMock()) as mock_verify:
            result = await compliance_agent.verify_azure(
                compliance_agent.VerifyAzureServicePrincipalRequest(
                    azure_tenant_id="tid", client_id="cid", client_secret="secret", subscription_id="sub",
                ),
                request,
                workspace={"id": workspace_id},
            )

        assert result.status == "active"
        mock_verify.assert_awaited_once_with(str(tenant_id), "co_t_raw", "tid", "cid", "secret", "sub")

    async def test_never_connected_returns_400(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await compliance_agent.verify_azure(
                compliance_agent.VerifyAzureServicePrincipalRequest(
                    azure_tenant_id="tid", client_id="cid", client_secret="s", subscription_id="sub",
                ),
                request,
                workspace={"id": uuid4()},
            )
        assert exc.value.status_code == 400


class TestScanAndReport:
    async def test_scan_not_connected_yet_400(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_connection_row())
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await compliance_agent.scan(request, workspace={"id": uuid4()})
        assert exc.value.status_code == 400

    async def test_report_passes_through_remote_response(self):
        tenant_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                compliance_agent_tenant_id=tenant_id,
                encrypted_compliance_agent_tenant_token=encrypt("co_t_raw"),
                compliance_agent_connected_at="2026-09-11",
            )
        )
        request = _make_request(conn)

        with patch(
            "api.routes.compliance_agent.client.get_report",
            new=AsyncMock(return_value={"tenant_id": str(tenant_id), "report": {"readiness_score": 50}}),
        ) as mock_report:
            result = await compliance_agent.report(request, workspace={"id": uuid4()})

        assert result["report"]["readiness_score"] == 50
        mock_report.assert_awaited_once_with(str(tenant_id), "co_t_raw")

    async def test_remote_404_passes_through_status_not_generic_502(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(
                compliance_agent_tenant_id=uuid4(),
                encrypted_compliance_agent_tenant_token=encrypt("t"),
                compliance_agent_connected_at="2026-09-11",
            )
        )
        request = _make_request(conn)

        with patch(
            "api.routes.compliance_agent.client.get_report",
            new=AsyncMock(side_effect=AgentServiceError("not found", status_code=404)),
        ):
            with pytest.raises(HTTPException) as exc:
                await compliance_agent.report(request, workspace={"id": uuid4()})
        assert exc.value.status_code == 404
