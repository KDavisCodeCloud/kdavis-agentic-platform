"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

from typing import Any


class IsolationViolationError(Exception):
    """Raised when a query is attempted without a valid (product_id, tenant_id) scope."""


class _ScopedTable:
    """Wraps a Supabase table query builder, auto-injecting product_id/tenant_id."""

    def __init__(self, table: Any, product_id: str, tenant_id: str):
        self._table = table
        self._product_id = product_id
        self._tenant_id = tenant_id

    def _scope_filters(self, builder: Any) -> Any:
        return builder.eq("product_id", self._product_id).eq("tenant_id", self._tenant_id)

    def select(self, *columns: str) -> Any:
        builder = self._table.select(*columns) if columns else self._table.select("*")
        return self._scope_filters(builder)

    def insert(self, data: Any) -> Any:
        scoped_fields = {"product_id": self._product_id, "tenant_id": self._tenant_id}
        if isinstance(data, list):
            data = [{**row, **scoped_fields} for row in data]
        else:
            data = {**data, **scoped_fields}
        return self._table.insert(data)

    def update(self, data: Any) -> Any:
        return self._scope_filters(self._table.update(data))

    def delete(self) -> Any:
        return self._scope_filters(self._table.delete())


class TenantIsolationGuard:
    """
    Wraps a Supabase client so every query issued through it is scoped to a
    single (product_id, tenant_id) pair. select/update/delete get
    `.eq("product_id", ...).eq("tenant_id", ...)` injected automatically;
    insert gets both fields merged into the row payload.

    Raises IsolationViolationError at construction time if either id is
    missing — there is no way to obtain a scoped table without both, which
    is what prevents a cross-tenant query from ever being built.
    """

    def __init__(self, client: Any, product_id: str, tenant_id: str):
        if not product_id or not tenant_id:
            raise IsolationViolationError(
                "product_id and tenant_id are both required to scope a query — "
                f"got product_id={product_id!r}, tenant_id={tenant_id!r}"
            )
        self._client = client
        self.product_id = product_id
        self.tenant_id = tenant_id

    def table(self, name: str) -> _ScopedTable:
        return _ScopedTable(self._client.table(name), self.product_id, self.tenant_id)


def scoped(client: Any, product_id: str, tenant_id: str) -> TenantIsolationGuard:
    """Convenience constructor for TenantIsolationGuard."""
    return TenantIsolationGuard(client, product_id, tenant_id)
