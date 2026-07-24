"""
tests/test_audit_log.py
Tests for security/audit_log.py — AuditLog

What this file validates:
  - append() writes a fully-scoped row and returns the inserted record
  - product_id / tenant_id are required — missing either raises before any write
  - the class exposes no update or delete methods (immutability by omission)
  - a failed insert (no returned rows) raises rather than failing silently
"""

from unittest.mock import MagicMock

import pytest

from security.audit_log import AuditLog, TABLE_NAME


def _mock_client_returning(row: dict) -> MagicMock:
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [row]
    return client


class TestAppend:
    def test_append_writes_real_schema_columns_not_actor_or_resource(self):
        # Real table (information_schema.columns, checked 2026-07-23): id,
        # agent_id, action, outcome, product_id (uuid), tenant_id (uuid),
        # metadata (jsonb), created_at. No "actor" or "resource" column —
        # the old shape here silently never wrote a single real row
        # (PGRST204 "column not found"), only ever exercised via mocks.
        client = _mock_client_returning({"id": "audit-1"})
        log = AuditLog(client=client)

        result = log.append(
            actor="agent_research",
            action="scrape_completed",
            resource="lead:123",
            outcome="success",
            product_id="11111111-1111-1111-1111-111111111111",
            tenant_id="22222222-2222-2222-2222-222222222222",
        )

        client.table.assert_called_once_with(TABLE_NAME)
        inserted_row = client.table.return_value.insert.call_args[0][0]
        assert inserted_row == {
            "agent_id": "agent_research",
            "action": "scrape_completed",
            "outcome": "success",
            "product_id": "11111111-1111-1111-1111-111111111111",
            "tenant_id": "22222222-2222-2222-2222-222222222222",
            "metadata": {"resource": "lead:123"},
        }
        assert result == {"id": "audit-1"}

    def test_non_uuid_product_and_tenant_id_fall_back_to_metadata(self):
        # agents/marketing/_shared.py passes literal "marketing"/"internal"
        # strings — not valid UUIDs, and product_id/tenant_id are uuid-typed
        # columns. Must degrade to metadata, never raise and never attempt
        # a doomed Postgres type cast.
        client = _mock_client_returning({"id": "audit-1"})
        log = AuditLog(client=client)

        log.append(
            actor="mkt-li1",
            action="monthly_batch_generated",
            resource="12 posts",
            outcome="success",
            product_id="marketing",
            tenant_id="internal",
        )

        inserted_row = client.table.return_value.insert.call_args[0][0]
        assert inserted_row["product_id"] is None
        assert inserted_row["tenant_id"] is None
        assert inserted_row["metadata"] == {
            "resource": "12 posts",
            "product_id": "marketing",
            "tenant_id": "internal",
        }

    def test_valid_uuid_product_id_with_non_uuid_tenant_id_mixed(self):
        client = _mock_client_returning({"id": "audit-1"})
        log = AuditLog(client=client)

        log.append(
            actor="agent_x", action="run", resource="r", outcome="success",
            product_id="11111111-1111-1111-1111-111111111111", tenant_id="internal",
        )

        inserted_row = client.table.return_value.insert.call_args[0][0]
        assert inserted_row["product_id"] == "11111111-1111-1111-1111-111111111111"
        assert inserted_row["tenant_id"] is None
        assert inserted_row["metadata"] == {"resource": "r", "tenant_id": "internal"}

    def test_missing_product_id_raises_before_write(self):
        client = _mock_client_returning({"id": "audit-1"})
        log = AuditLog(client=client)

        with pytest.raises(ValueError):
            log.append(
                actor="agent_research",
                action="scrape_completed",
                resource="lead:123",
                outcome="success",
                product_id=None,
                tenant_id="tenant-1",
            )
        client.table.assert_not_called()

    def test_missing_tenant_id_raises_before_write(self):
        client = _mock_client_returning({"id": "audit-1"})
        log = AuditLog(client=client)

        with pytest.raises(ValueError):
            log.append(
                actor="agent_research",
                action="scrape_completed",
                resource="lead:123",
                outcome="success",
                product_id="product-1",
                tenant_id=None,
            )
        client.table.assert_not_called()

    def test_empty_insert_result_raises(self):
        client = MagicMock()
        client.table.return_value.insert.return_value.execute.return_value.data = []
        log = AuditLog(client=client)

        with pytest.raises(RuntimeError):
            log.append(
                actor="agent_research",
                action="scrape_completed",
                resource="lead:123",
                outcome="failure",
                product_id="product-1",
                tenant_id="tenant-1",
            )


class TestImmutability:
    def test_no_update_method(self):
        assert not hasattr(AuditLog, "update")

    def test_no_delete_method(self):
        assert not hasattr(AuditLog, "delete")
