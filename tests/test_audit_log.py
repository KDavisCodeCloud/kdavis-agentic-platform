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
    def test_append_writes_scoped_row(self):
        client = _mock_client_returning({"id": "audit-1"})
        log = AuditLog(client=client)

        result = log.append(
            actor="agent_research",
            action="scrape_completed",
            resource="lead:123",
            outcome="success",
            product_id="product-1",
            tenant_id="tenant-1",
        )

        client.table.assert_called_once_with(TABLE_NAME)
        inserted_row = client.table.return_value.insert.call_args[0][0]
        assert inserted_row == {
            "actor": "agent_research",
            "action": "scrape_completed",
            "resource": "lead:123",
            "outcome": "success",
            "product_id": "product-1",
            "tenant_id": "tenant-1",
        }
        assert result == {"id": "audit-1"}

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
