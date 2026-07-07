"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

import os
from typing import Any, Optional

TABLE_NAME = "audit_log"

_client: Optional[Any] = None


def _get_client() -> Any:
    """Lazy service-role Supabase client — stubbed until providers/ ships (Session 1)."""
    global _client
    if _client is None:
        from supabase import create_client

        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _client


class AuditLog:
    """
    Immutable, append-only audit trail. Every agent start/completion writes
    here via base_agent.py's lifecycle (built next session).

    Intentionally exposes no update or delete methods — once written, an
    entry cannot be changed or removed through this class.
    """

    def __init__(self, client: Optional[Any] = None):
        self._client = client

    def _client_or_default(self) -> Any:
        return self._client if self._client is not None else _get_client()

    def append(
        self,
        actor: str,
        action: str,
        resource: str,
        outcome: str,
        product_id: str,
        tenant_id: str,
    ) -> dict:
        if not product_id or not tenant_id:
            raise ValueError("product_id and tenant_id are required on every audit_log entry")

        row = {
            "actor": actor,
            "action": action,
            "resource": resource,
            "outcome": outcome,
            "product_id": product_id,
            "tenant_id": tenant_id,
        }

        result = self._client_or_default().table(TABLE_NAME).insert(row).execute()
        if not result.data:
            raise RuntimeError(f"Failed to write audit_log entry: {row}")
        return result.data[0]
