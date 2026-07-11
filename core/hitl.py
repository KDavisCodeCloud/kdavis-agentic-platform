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
Human-in-the-Loop state manager.

Governance: Rule 11 — No autonomous remediation. Every fix MUST go through
human approval. Agents pause here; only POST /incident/{id}/approve resumes them.
"""

import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

log = logging.getLogger(__name__)

# Execution status values — keep in sync with db/schema.sql
STATUS_PENDING    = "pending_approval"
STATUS_EXECUTING  = "executing"
STATUS_EXECUTED   = "executed"
STATUS_HELD       = "held"           # operator chose "stay broken"
STATUS_FAILED     = "failed"
STATUS_BUDGET_EXC = "budget_exceeded"


class HITLGate:
    """
    Manages the pause/resume lifecycle of agent workflows.

    Usage:
        gate = HITLGate(db_conn)
        incident_id = await gate.create_incident(workspace_id, agent_id, raw_log, diagnosis)
        # agent pauses — returns incident_id to API
        # operator approves via POST /incident/{id}/approve
        option = await gate.get_approved_option(incident_id)
        # agent resumes with option
    """

    def __init__(self, db_conn):
        """
        db_conn: an async asyncpg connection or SQLAlchemy async session.
        Passed in from FastAPI dependency injection.
        """
        self._db = db_conn

    async def create_incident(
        self,
        workspace_id: str,
        agent_id: str,
        raw_log: str,
        parsed_error: str,
        remediation_options: list[dict],
        cloud_provider: Optional[str] = None,
        tokens_used: int = 0,
        estimated_duration_seconds: Optional[int] = None,
    ) -> str:
        """
        Persist a new incident in pending_approval state and write to audit log.
        Returns the incident UUID string.
        """
        raw_log_hash = hashlib.sha256(raw_log.encode()).hexdigest()

        row = await self._db.fetchrow(
            """
            INSERT INTO incidents (
                workspace_id, agent_id, cloud_provider, raw_log_hash,
                parsed_error, remediation_options, execution_status,
                tokens_used, estimated_duration_seconds
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            workspace_id,
            agent_id,
            cloud_provider,
            raw_log_hash,
            parsed_error,
            json.dumps(remediation_options),
            STATUS_PENDING,
            tokens_used,
            estimated_duration_seconds,
        )
        incident_id = str(row["id"])
        self._write_audit_entry(workspace_id, agent_id, incident_id, "created", tokens_used)
        log.info(f"[HITL] Incident {incident_id} created — awaiting operator approval")
        return incident_id

    async def get_approved_option(self, incident_id: str) -> Optional[dict]:
        """
        Returns the approved option dict if the incident is approved, else None.
        Agents should poll this or be re-invoked via the approve endpoint.
        """
        row = await self._db.fetchrow(
            "SELECT execution_status, selected_option_id, remediation_options, custom_solution_input "
            "FROM incidents WHERE id = $1",
            UUID(incident_id),
        )
        if not row:
            raise ValueError(f"Incident {incident_id} not found")

        status = row["execution_status"]

        if status == STATUS_HELD:
            log.info(f"[HITL] Incident {incident_id} is HELD — operator chose 'stay broken'")
            return None

        if status not in (STATUS_EXECUTING, STATUS_EXECUTED):
            log.info(f"[HITL] Incident {incident_id} status={status} — not yet approved")
            return None

        options = json.loads(row["remediation_options"])
        selected_id = row["selected_option_id"]

        if selected_id == "custom":
            return {
                "id": "custom",
                "title": "Custom solution",
                "custom_input": row["custom_solution_input"],
            }

        return next((o for o in options if o["id"] == selected_id), None)

    async def approve_incident(
        self,
        incident_id: str,
        selected_option_id: str,
        custom_solution_input: Optional[str] = None,
        approved_by: Optional[str] = None,
    ) -> None:
        """
        Called by POST /incident/{id}/approve.
        Sets status to 'executing' and records the selected option.
        """
        if selected_option_id == "hold":
            new_status = STATUS_HELD
        else:
            new_status = STATUS_EXECUTING

        await self._db.execute(
            """
            UPDATE incidents
            SET execution_status = $1,
                selected_option_id = $2,
                custom_solution_input = $3
            WHERE id = $4
            """,
            new_status,
            selected_option_id,
            custom_solution_input,
            UUID(incident_id),
        )
        action = f"approved:{selected_option_id}" if new_status == STATUS_EXECUTING else "held"
        self._write_audit_entry("unknown", "hitl_gate", incident_id, action, 0)
        log.info(f"[HITL] Incident {incident_id} -> {new_status} (option={selected_option_id})")

    async def mark_executed(self, incident_id: str, tokens_used: int = 0) -> None:
        await self._db.execute(
            """
            UPDATE incidents
            SET execution_status = $1, resolved_at = $2, tokens_used = tokens_used + $3
            WHERE id = $4
            """,
            STATUS_EXECUTED,
            datetime.now(timezone.utc),
            tokens_used,
            UUID(incident_id),
        )
        self._write_audit_entry("unknown", "hitl_gate", incident_id, "executed", tokens_used)

    async def mark_failed(self, incident_id: str, reason: str = "") -> None:
        await self._db.execute(
            "UPDATE incidents SET execution_status = $1 WHERE id = $2",
            STATUS_FAILED,
            UUID(incident_id),
        )
        self._write_audit_entry("unknown", "hitl_gate", incident_id, f"failed:{reason}", 0)

    def _write_audit_entry(
        self,
        workspace_id: str,
        agent_id: str,
        incident_id: str,
        action: str,
        tokens_used: int,
    ) -> None:
        """Append to the operator audit log — Rule 9 compliance."""
        from pathlib import Path
        log_path = Path("knowledge/operator/llm-audit.md")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"| {timestamp} | {agent_id} | {workspace_id} | "
            f"{action} | incident:{incident_id} | {tokens_used} |\n"
        )
        if not log_path.exists():
            with open(log_path, "w") as f:
                f.write("# LLM Audit Log\n\n")
                f.write("| Timestamp | Agent | Workspace | Action | Status | Tokens |\n")
                f.write("|-----------|-------|-----------|--------|--------|--------|\n")
        with open(log_path, "a") as f:
            f.write(entry)
