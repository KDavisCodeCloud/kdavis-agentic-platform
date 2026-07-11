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
MKT-09 — HITL Queue Manager.

Routes a compliance-scanned content item into the right queue table with
status='pending_review', and to the right reviewer tier per spec
(knowledge/Marketing/Marketing-Engine-Agent-Specs.md GOVERNANCE section):
  Tier 2 — wife reviews product marketing + newsletter content
  Tier 3 — Kelvin reviews personal brand/LinkedIn posts + escalations

Does not call MKT-10 itself, by this session's task design: each output
agent runs run_compliance_guard() first and folds the result into
content_item (mkt10_passed/mkt10_notes, or hitl_notes where there's no
dedicated column), then hands off here. MKT-09 only decides table + tier
and writes the row.

Table routing is inferred from content_item's shape rather than an
explicit "queue_type" field, since none of the three output agents
(mkt_li1/mkt_v1/mkt_n1) attach one — the three row shapes defined in
db/migrations/007_marketing_queues.sql are already distinguishable by
their required fields.

Schema note: only linkedin_content_queue has a hitl_reviewer column
(checked db/migrations/007_marketing_queues.sql) — content_queue and
newsletter_queue don't. The tier/reviewer decision is always written to
the audit log regardless of table, and additionally set on hitl_reviewer
when the target table has that column, rather than silently dropped for
the other two.
"""

import logging
from typing import Any, Optional

from agents.marketing._shared import insert_queue_row, write_audit_log

log = logging.getLogger(__name__)

AGENT_ID = "mkt-09"

TIER_REVIEWERS = {2: "wife", 3: "kelvin"}

_LINKEDIN_TABLE = "linkedin_content_queue"
_CONTENT_TABLE = "content_queue"
_NEWSLETTER_TABLE = "newsletter_queue"

# Only this table has a hitl_reviewer column (db/migrations/007_marketing_queues.sql).
_TABLES_WITH_HITL_REVIEWER = {_LINKEDIN_TABLE}


def _infer_table(content_item: dict) -> str:
    if "post_copy" in content_item and "hook_variants" in content_item:
        return _LINKEDIN_TABLE
    if "platform" in content_item and "content_json" in content_item:
        return _CONTENT_TABLE
    if "subject_lines" in content_item or "variant" in content_item:
        return _NEWSLETTER_TABLE
    raise ValueError(
        "queue_for_review: could not infer target table from content_item shape "
        f"(keys={sorted(content_item.keys())}) — expected linkedin_content_queue "
        "(post_copy/hook_variants), content_queue (platform/content_json), or "
        "newsletter_queue (subject_lines/variant) shaped input"
    )


def queue_for_review(
    content_item: dict,
    tier: int,
    product_id: str,
    supabase_client: Optional[Any] = None,
) -> dict:
    if tier not in TIER_REVIEWERS:
        raise ValueError(f"queue_for_review: tier must be 2 (wife) or 3 (kelvin), got {tier!r}")

    table = _infer_table(content_item)
    reviewer = TIER_REVIEWERS[tier]

    row = {key: value for key, value in content_item.items() if key != "id"}
    row["product_id"] = product_id
    row["status"] = "pending_review"
    if table in _TABLES_WITH_HITL_REVIEWER:
        row["hitl_reviewer"] = reviewer

    resource = f"{table}:tier={tier}:reviewer={reviewer}"
    try:
        inserted = insert_queue_row(table, row, supabase_client)
        write_audit_log(AGENT_ID, "queued_for_review", resource=resource, outcome="success")
        return {"id": inserted.get("id"), "table": table, "tier": tier, "reviewer": reviewer}
    except Exception as exc:
        write_audit_log(AGENT_ID, "queued_for_review", resource=resource, outcome=f"failure: {exc}")
        raise
