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
import uuid as _uuid
from typing import Any, Optional

TABLE_NAME = "audit_log"


def _as_uuid_or_none(value: str) -> Optional[str]:
    try:
        return str(_uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None

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
        """
        Found 2026-07-23 while running the first real end-to-end MKT-LI1
        batch: this method has apparently never successfully written a row
        against the live audit_log table. Two mismatches, both fixed here:

        1. The real table has no "actor" column — it's agent_id (confirmed
           via information_schema.columns). Every existing row in the live
           table (113 as of this fix) was written through a completely
           different code path with real agent_id values
           ("factory-brief-generator", "human-review", etc.) — none of them
           went through this class, which would have hit the exact same
           PGRST204 "column not found" error every other caller does
           (agents/mse/opportunity_finder.py and friends use this same
           actor=/resource= call shape and would fail identically).

        2. product_id/tenant_id are uuid-typed columns. Real per-product
           callers (agents/mse/*) pass genuine UUIDs and those still go
           straight into the dedicated columns. The marketing agents
           (agents/marketing/_shared.py) pass literal "marketing"/"internal"
           strings, which are not valid UUIDs and would fail a Postgres
           type cast — those fall back to metadata instead of raising, so
           a non-UUID caller degrades gracefully rather than never being
           able to log at all.

        resource has no dedicated column either — folded into metadata
        jsonb rather than dropped, so it's still queryable, just not a
        first-class column.
        """
        if not product_id or not tenant_id:
            raise ValueError("product_id and tenant_id are required on every audit_log entry")

        product_uuid = _as_uuid_or_none(product_id)
        tenant_uuid = _as_uuid_or_none(tenant_id)

        metadata: dict = {"resource": resource}
        if product_uuid is None:
            metadata["product_id"] = product_id
        if tenant_uuid is None:
            metadata["tenant_id"] = tenant_id

        row = {
            "agent_id": actor,
            "action": action,
            "outcome": outcome,
            "product_id": product_uuid,
            "tenant_id": tenant_uuid,
            "metadata": metadata,
        }

        result = self._client_or_default().table(TABLE_NAME).insert(row).execute()
        if not result.data:
            raise RuntimeError(f"Failed to write audit_log entry: {row}")
        return result.data[0]
