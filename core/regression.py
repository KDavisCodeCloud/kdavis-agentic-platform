"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Regression linking (G2, item 5).

Break-It Lab step 6: every problem re-injected after a fix (A2, A3, A4, Z2,
Z3, Z4, Z5) came back as a fresh incident with no link to the one that
"fixed" it. Agents 05/06/08 stored no resource identity at all, so there was
nothing to link on.

Each agent now passes a deterministic regression_key -- what was wrong and
where, never LLM text -- when it creates an incident. create_incident links
the new incident to the most recent earlier one with the same workspace,
agent and key:

  previous_incident_id  always, when one exists
  is_regression         only when that earlier incident was fixed, or said
                        it was (executed / fix_merged / verified /
                        resolved_manually). A recurrence of something never
                        fixed (pending, proposed, failed, verification_failed)
                        is linked but is not a regression.

If the earlier incident is still waiting on post-fix verification (G4), its
check is pulled forward to now: the problem re-appearing is the strongest
hint that the fix didn't hold, and verification re-reads live state to say
so deterministically.
"""

import logging
from typing import Optional
from uuid import UUID

log = logging.getLogger(__name__)

# The earlier incident claimed the problem was fixed.
FIXED_STATUSES = frozenset({"executed", "fix_merged", "verified", "resolved_manually"})


def _key(*parts) -> Optional[str]:
    """Join non-empty parts; None when any part is missing (never key on a blank)."""
    cleaned = [str(p).strip() for p in parts]
    if not all(cleaned) or any(p.lower() == "unknown" for p in cleaned):
        return None
    return ":".join(cleaned)


def iam_key(cloud: str, scope: str, principal_id: str = "") -> Optional[str]:
    """Agent 05: the policy (AWS) or the principal's assignments at a scope (Azure)."""
    if cloud == "azure":
        return _key("azure", "iam", scope, principal_id)
    return _key(cloud, "iam", scope)


def compute_key(cloud: str, resource_ids: list) -> Optional[str]:
    """Agent 06: the exact set of idle instances/VMs recommended for stopping."""
    ids = sorted({str(r).strip() for r in (resource_ids or []) if str(r).strip()})
    return _key(cloud, "compute", ",".join(ids)) if ids else None


def drift_key(resource_id: str) -> Optional[str]:
    """Agent 08: the drifted resource."""
    return _key("drift", resource_id)


def alert_key(resource_id: str, alert_name: str) -> Optional[str]:
    """Agent 11 (and any resource+alert incident): the same alert on the same resource."""
    return _key("alert", resource_id, alert_name)


async def link_previous(db, workspace_id: str, agent_id: str, regression_key: Optional[str],
                        incident_id: str) -> Optional[dict]:
    """Link incident_id to its predecessor. Returns {"id", "execution_status",
    "is_regression"} or None when this is the first occurrence."""
    if not regression_key:
        return None
    prev = await db.fetchrow(
        """
        SELECT id, execution_status FROM incidents
        WHERE workspace_id = $1 AND agent_id = $2 AND regression_key = $3 AND id <> $4
        ORDER BY created_at DESC LIMIT 1
        """,
        workspace_id, agent_id, regression_key, UUID(str(incident_id)),
    )
    if not prev:
        return None
    is_regression = prev["execution_status"] in FIXED_STATUSES
    await db.execute(
        "UPDATE incidents SET previous_incident_id = $1, is_regression = $2 WHERE id = $3",
        prev["id"], is_regression, UUID(str(incident_id)),
    )
    # The fix may not have held: verify the earlier incident now rather than at its next slot.
    await db.execute(
        "UPDATE incidents SET verification_next_at = NOW() "
        "WHERE id = $1 AND verification_next_at IS NOT NULL AND execution_status IN ('executed', 'fix_merged')",
        prev["id"],
    )
    log.info("[Regression] incident %s follows %s (%s)%s", incident_id, prev["id"],
             prev["execution_status"], " — REGRESSION" if is_regression else "")
    return {"id": str(prev["id"]), "execution_status": prev["execution_status"], "is_regression": is_regression}


def regression_summary(summary: str, link: Optional[dict]) -> str:
    """Notification text: say plainly that a fixed problem came back."""
    if not link or not link["is_regression"]:
        return summary
    return f"REGRESSION — this came back after incident {link['id']} ({link['execution_status']}). {summary}"
