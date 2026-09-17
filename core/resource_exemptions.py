"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Settings → Policies, Step 2 (migration 049).

ResourceExemptionGuard.check_and_suppress() is called from agent_08
(Drift Detection) and agent_11 (Resource Health)'s ingest/dedup-check
node — the only two agents whose incidents reliably carry a real
resource_id (migration 029's docstring) — BEFORE their diagnose node
ever runs, so an exempted resource costs zero LLM tokens, not just zero
incident rows. Every other agent has no stable resource_id to key an
exemption on and is unaffected.

A class (mirroring core/hitl.py's HITLGate, instantiated once per agent
as self.exemptions in agents/base_agent.py) rather than a bare function,
specifically so tests can mock wf.exemptions.check_and_suppress the same
way they already mock wf.hitl.find_open_incident -- a bare module-level
function reaching into self.db directly would silently collide with
tests/conftest.py's shared mock_db fixture (its default fetchrow return
is a truthy stand-in row meant for other call sites, so an unmocked
direct query here would always read as "exempted" under that fixture).
"""

import logging
from typing import Optional
from uuid import UUID

log = logging.getLogger(__name__)


class ResourceExemptionGuard:
    def __init__(self, db_conn):
        self._db = db_conn

    async def check_and_suppress(self, workspace_id: str, resource_id: Optional[str]) -> bool:
        """
        Returns True (and increments suppressed_count) if resource_id has
        an active (non-revoked) exemption for this workspace. False for
        no resource_id, or no matching exemption -- caller proceeds to
        diagnose as normal in either case.
        """
        if not resource_id:
            return False

        row = await self._db.fetchrow(
            """
            UPDATE resource_exemptions
            SET suppressed_count = suppressed_count + 1
            WHERE workspace_id = $1 AND resource_id = $2 AND revoked_at IS NULL
            RETURNING id
            """,
            UUID(str(workspace_id)),
            resource_id,
        )
        if row is None:
            return False

        log.info(
            "[ResourceExemptions] Suppressed ingest for exempted resource=%s workspace=%s",
            resource_id, workspace_id,
        )
        return True
