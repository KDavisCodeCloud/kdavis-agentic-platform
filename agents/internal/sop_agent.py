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
sop_agent — turns a completed agent_run record into an Obsidian-compatible
SOP markdown file and pushes it to the vault via obsidian/vault_sync.py.

Like research_agent, this does not extend agents/base_agent.py and holds no
Supabase connection of its own — it takes an agent_run dict shaped like a
row from the `agent_runs` table (see CLAUDE.md SUPABASE SCHEMA) and returns
markdown, or pushes it if a vault is configured. Triggering this
automatically after every agent run (base_agent.emit_sop() /
sop-sync.yml on `sops` table INSERT) is wired up in a later integration
session.
"""

from datetime import datetime, timezone
from typing import Optional

from obsidian.vault_sync import push_sop

SOP_TEMPLATE = """# SOP: {agent_name} — {task_summary}
Date: {timestamp}
Agent version: {version}
Product: {product_id}

## What was done
{what_was_done}

## Why it was done
{why_it_was_done}

## Input received
{input_received}

## Output produced
{output_produced}

## Decisions made (HITL approvals)
{decisions_made}

## Outcome
{outcome}

## If this fails next time
{if_this_fails_next_time}
"""

_NOT_RECORDED = "Not recorded."


class SOPAgent:
    AGENT_NAME = "sop_agent"

    def generate(self, agent_run: dict) -> str:
        """Render the SOP markdown for a completed agent_run record."""
        agent_name = agent_run.get("agent_name")
        task_summary = agent_run.get("task_summary")
        if not agent_name or not task_summary:
            raise ValueError("agent_run must include agent_name and task_summary")

        decisions = agent_run.get("hitl_decisions")
        if isinstance(decisions, list):
            decisions_made = "\n".join(f"- {d}" for d in decisions) if decisions else _NOT_RECORDED
        else:
            decisions_made = decisions or _NOT_RECORDED

        timestamp = agent_run.get("completed_at") or datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

        return SOP_TEMPLATE.format(
            agent_name=agent_name,
            task_summary=task_summary,
            timestamp=timestamp,
            version=agent_run.get("version", "v1.0.0"),
            product_id=agent_run.get("product_id") or "internal",
            what_was_done=agent_run.get("what_was_done") or _NOT_RECORDED,
            why_it_was_done=agent_run.get("why_it_was_done") or _NOT_RECORDED,
            input_received=agent_run.get("input_received") or _NOT_RECORDED,
            output_produced=agent_run.get("output_produced") or _NOT_RECORDED,
            decisions_made=decisions_made,
            outcome=agent_run.get("outcome") or _NOT_RECORDED,
            if_this_fails_next_time=agent_run.get("if_this_fails_next_time") or _NOT_RECORDED,
        )

    def run(self, agent_run: dict) -> str:
        """Generate the SOP and push it to the vault. Returns the file path."""
        content = self.generate(agent_run)
        return push_sop(
            content=content,
            agent_name=agent_run["agent_name"],
            task_summary=agent_run["task_summary"],
        )
