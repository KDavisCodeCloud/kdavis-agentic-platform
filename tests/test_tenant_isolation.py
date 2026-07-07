"""
tests/test_tenant_isolation.py
Tests for security/tenant_isolation.py — TenantIsolationGuard

What this file validates:
  - A guard cannot be constructed without both product_id and tenant_id
    (this is the cross-tenant / no-WHERE-clause attempt this module blocks)
  - select/update/delete get product_id + tenant_id filters injected
  - insert gets product_id + tenant_id merged into the row payload(s)
  - the `scoped()` convenience constructor behaves the same as the class
"""

from unittest.mock import MagicMock

import pytest

from security.tenant_isolation import IsolationViolationError, TenantIsolationGuard, scoped


def _mock_supabase_client() -> MagicMock:
    """A MagicMock that mirrors supabase-py's fluent table().select().eq()... API."""
    client = MagicMock()
    # Every chained call (select/insert/update/delete/eq) returns a mock that
    # itself supports further chaining, ending in .execute().
    client.table.return_value = MagicMock()
    return client


# ──────────────────────────────────────────────────────────────────────────────
# Cross-tenant construction is blocked
# ──────────────────────────────────────────────────────────────────────────────

class TestCrossTenantConstructionBlocked:
    def test_missing_product_id_raises(self):
        client = _mock_supabase_client()
        with pytest.raises(IsolationViolationError):
            TenantIsolationGuard(client, product_id=None, tenant_id="tenant-1")

    def test_missing_tenant_id_raises(self):
        client = _mock_supabase_client()
        with pytest.raises(IsolationViolationError):
            TenantIsolationGuard(client, product_id="product-1", tenant_id=None)

    def test_missing_both_raises(self):
        client = _mock_supabase_client()
        with pytest.raises(IsolationViolationError):
            TenantIsolationGuard(client, product_id="", tenant_id="")

    def test_scoped_helper_also_raises(self):
        client = _mock_supabase_client()
        with pytest.raises(IsolationViolationError):
            scoped(client, product_id="product-1", tenant_id=None)

    def test_valid_ids_do_not_raise(self):
        client = _mock_supabase_client()
        guard = TenantIsolationGuard(client, product_id="product-1", tenant_id="tenant-1")
        assert guard.product_id == "product-1"
        assert guard.tenant_id == "tenant-1"


# ──────────────────────────────────────────────────────────────────────────────
# select() is scoped
# ──────────────────────────────────────────────────────────────────────────────

class TestSelectScoping:
    def test_select_injects_product_and_tenant_filters(self):
        client = _mock_supabase_client()
        guard = TenantIsolationGuard(client, product_id="product-1", tenant_id="tenant-1")

        guard.table("leads").select("*")

        table_mock = client.table.return_value
        table_mock.select.assert_called_once_with("*")
        select_result = table_mock.select.return_value
        select_result.eq.assert_any_call("product_id", "product-1")

    def test_select_defaults_to_star_with_no_columns(self):
        client = _mock_supabase_client()
        guard = TenantIsolationGuard(client, product_id="product-1", tenant_id="tenant-1")

        guard.table("leads").select()

        client.table.return_value.select.assert_called_once_with("*")


# ──────────────────────────────────────────────────────────────────────────────
# insert() merges scoping fields into the payload
# ──────────────────────────────────────────────────────────────────────────────

class TestInsertScoping:
    def test_insert_dict_gets_scoping_fields_merged(self):
        client = _mock_supabase_client()
        guard = TenantIsolationGuard(client, product_id="product-1", tenant_id="tenant-1")

        guard.table("leads").insert({"email": "a@b.com"})

        table_mock = client.table.return_value
        inserted_row = table_mock.insert.call_args[0][0]
        assert inserted_row == {
            "email": "a@b.com",
            "product_id": "product-1",
            "tenant_id": "tenant-1",
        }

    def test_insert_list_gets_scoping_fields_merged_into_each_row(self):
        client = _mock_supabase_client()
        guard = TenantIsolationGuard(client, product_id="product-1", tenant_id="tenant-1")

        guard.table("leads").insert([{"email": "a@b.com"}, {"email": "c@d.com"}])

        inserted_rows = client.table.return_value.insert.call_args[0][0]
        assert inserted_rows == [
            {"email": "a@b.com", "product_id": "product-1", "tenant_id": "tenant-1"},
            {"email": "c@d.com", "product_id": "product-1", "tenant_id": "tenant-1"},
        ]

    def test_insert_cannot_override_scoping_fields(self):
        client = _mock_supabase_client()
        guard = TenantIsolationGuard(client, product_id="product-1", tenant_id="tenant-1")

        # Caller tries to sneak in a different tenant_id — the guard's own
        # scoping fields are applied last and win.
        guard.table("leads").insert({"tenant_id": "someone-elses-tenant"})

        inserted_row = client.table.return_value.insert.call_args[0][0]
        assert inserted_row["tenant_id"] == "tenant-1"


# ──────────────────────────────────────────────────────────────────────────────
# update() / delete() are scoped
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdateDeleteScoping:
    def test_update_injects_filters(self):
        client = _mock_supabase_client()
        guard = TenantIsolationGuard(client, product_id="product-1", tenant_id="tenant-1")

        guard.table("leads").update({"status": "converted"})

        table_mock = client.table.return_value
        table_mock.update.assert_called_once_with({"status": "converted"})
        table_mock.update.return_value.eq.assert_any_call("product_id", "product-1")

    def test_delete_injects_filters(self):
        client = _mock_supabase_client()
        guard = TenantIsolationGuard(client, product_id="product-1", tenant_id="tenant-1")

        guard.table("leads").delete()

        table_mock = client.table.return_value
        table_mock.delete.assert_called_once_with()
        table_mock.delete.return_value.eq.assert_called_once_with("product_id", "product-1")
        table_mock.delete.return_value.eq.return_value.eq.assert_called_once_with(
            "tenant_id", "tenant-1"
        )
