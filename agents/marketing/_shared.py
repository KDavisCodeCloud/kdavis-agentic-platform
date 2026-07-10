"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
Shared helpers for the Wave 2 marketing agents. Kept in one place so the
audit_log / events / sanitize / queue-insert boilerplate isn't
duplicated four times across mkt_li1/mkt_cn1/mkt_v1/mkt_n1.

Schema gap, flagged not silently assumed: linkedin_content_queue,
content_queue, and newsletter_queue do not exist in db/migrations/ yet
(checked before writing this — see reference: verify-schema-before-building).
insert_queue_row() below inserts against the output shapes documented in
knowledge/Marketing/Marketing-Engine-Agent-Specs.md; a migration needs to
land before any of these agents can run against a live DB.
"""

import logging
import os
from typing import Any, Optional

from core.security import shield
from security.audit_log import AuditLog

log = logging.getLogger(__name__)

MARKETING_PRODUCT_ID = "marketing"
MARKETING_TENANT_ID = "internal"


def sanitize(text: Any, context: str = "") -> str:
    """DataSanitizationShield pass — call on every piece of external or
    research-derived text before it goes into an LLM prompt."""
    return shield.sanitize(text, context=context).sanitized_text


def write_audit_log(
    agent_id: str, action: str, resource: str, outcome: str,
    audit_log_client: Optional[AuditLog] = None,
) -> None:
    client = audit_log_client or AuditLog()
    client.append(
        actor=agent_id, action=action, resource=resource, outcome=outcome,
        product_id=MARKETING_PRODUCT_ID, tenant_id=MARKETING_TENANT_ID,
    )


def emit_event(agent_id: str, event_type: str, payload: dict, http_client: Optional[Any] = None) -> None:
    """Best-effort POST /events per CLAUDE.md's non-negotiable. No live
    /events endpoint exists anywhere in this repo yet (checked) — no-ops
    until AGENT_EVENTS_URL is set. Same never-block-the-agent philosophy
    as leads/capture/signup_handler.py's webhook notify."""
    url = os.getenv("AGENT_EVENTS_URL")
    if not url:
        return
    try:
        client = http_client
        if client is None:
            import httpx

            client = httpx
        client.post(url, json={"agent_id": agent_id, "event_type": event_type, "payload": payload}, timeout=5.0)
    except Exception as exc:  # noqa: BLE001 — telemetry must never break the agent
        log.warning("POST /events failed for %s/%s: %s", agent_id, event_type, exc)


def _get_supabase_client(supabase_client: Optional[Any]) -> Any:
    if supabase_client is not None:
        return supabase_client
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def insert_queue_row(table: str, row: dict, supabase_client: Optional[Any] = None) -> dict:
    client = _get_supabase_client(supabase_client)
    response = client.table(table).insert(row).execute()
    data = getattr(response, "data", None)
    if not data:
        raise RuntimeError(f"Failed to insert row into {table}: {row}")
    return data[0]


def get_anthropic_client(anthropic_client: Optional[Any] = None) -> Any:
    """Lazily builds a default Anthropic client if none is injected.

    NOTE: CLAUDE.md's Core Principle 1 says route all LLM calls through
    providers/router.py and never import a provider SDK directly in
    business logic. This session's task spec explicitly names the
    parameter `anthropic_client` on every agent function signature —
    treating that as deliberate, task-directed instruction to call
    Anthropic directly here rather than an unprompted new pattern.
    Flagging per "state any assumption before acting."
    """
    if anthropic_client is not None:
        return anthropic_client
    import anthropic

    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def apportion(ratios: dict[str, float], total: int) -> dict[str, int]:
    """Largest-remainder apportionment: split `total` discrete items
    across categories to best approximate `ratios` (which must sum to
    ~1.0). Used to turn a weekly post count into per-content-type quotas
    that track the 40/30/20/10 mix over time without true randomness."""
    raw = {key: ratio * total for key, ratio in ratios.items()}
    floors = {key: int(value) for key, value in raw.items()}
    remainder = total - sum(floors.values())
    remainders_desc = sorted(raw, key=lambda key: raw[key] - floors[key], reverse=True)
    for key in remainders_desc[:remainder]:
        floors[key] += 1
    return floors
