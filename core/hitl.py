"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Human-in-the-Loop state manager.

Governance: Rule 11 — No autonomous remediation. Every fix MUST go through
human approval. Agents pause here; only POST /incident/{id}/approve resumes them.
"""

import asyncio
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
        incident_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        resource_name: Optional[str] = None,
        resource_group: Optional[str] = None,
        metric_name: Optional[str] = None,
        metric_current_value: Optional[float] = None,
        metric_threshold: Optional[float] = None,
        alert_name: Optional[str] = None,
        severity: str = "medium",
    ) -> str:
        """
        Persist a new incident in pending_approval state and write to audit log.
        Returns the incident UUID string.

        severity: critical|high|medium|low (migration 042, GAPS.md 24-gap
        closure Phase 1). Callers derive this via core/severity.py's
        normalize_severity()/severity_from_counts() from whatever real
        signal they already have -- defaults to 'medium' here so every
        pre-existing call site (any agent not yet updated to pass it)
        keeps behaving exactly as before.

        incident_id: pass the same UUID the caller is using as the LangGraph
        checkpoint thread_id (every agent's run() pre-generates one) so the
        DB row's id and the graph's thread_id are the SAME value -- without
        this, resume(incident_id, ...) looks up a checkpoint under an id the
        graph was never actually invoked with, and LangGraph silently treats
        the resume as a fresh __start__ invocation instead (a real, previously
        undiscovered bug found live: every agent's approve->resume path was
        broken this way since none of them had ever been exercised for real
        until this session's live end-to-end test). If omitted, the database
        generates one as before -- kept optional for any other caller.

        resource_id/resource_name/resource_group/metric_*/alert_name: all
        optional, all default None -- only Agent 11 populates these today
        (GAPS.md scale-readiness build, migration 029). Agents 01-10 never
        pass them and their incidents simply get NULL in these columns,
        exactly as before this change.
        """
        raw_log_hash = hashlib.sha256(raw_log.encode()).hexdigest()
        now = datetime.now(timezone.utc)

        if incident_id is not None:
            # ON CONFLICT DO NOTHING: LangGraph re-executes a node's full
            # function body from the top when resuming past an interrupt()
            # call inside it (see agents/agent_01_cicd_triage/workflow.py's
            # _hitl_gate_node) -- this INSERT runs a second time, with the
            # exact same pre-generated id, on every resume. Without this
            # guard that's a real UniqueViolationError found live. Idempotent
            # by design: same id in means same logical incident, not a new one.
            row = await self._db.fetchrow(
                """
                INSERT INTO incidents (
                    id, workspace_id, agent_id, cloud_provider, raw_log_hash,
                    parsed_error, remediation_options, execution_status,
                    tokens_used, estimated_duration_seconds,
                    resource_id, resource_name, resource_group,
                    metric_name, metric_current_value, metric_threshold,
                    alert_name, last_seen_at, severity
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                          $11, $12, $13, $14, $15, $16, $17, $18, $19)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                UUID(incident_id),
                workspace_id,
                agent_id,
                cloud_provider,
                raw_log_hash,
                parsed_error,
                json.dumps(remediation_options),
                STATUS_PENDING,
                tokens_used,
                estimated_duration_seconds,
                resource_id,
                resource_name,
                resource_group,
                metric_name,
                metric_current_value,
                metric_threshold,
                alert_name,
                now,
                severity,
            )
        else:
            row = await self._db.fetchrow(
                """
                INSERT INTO incidents (
                    workspace_id, agent_id, cloud_provider, raw_log_hash,
                    parsed_error, remediation_options, execution_status,
                    tokens_used, estimated_duration_seconds,
                    resource_id, resource_name, resource_group,
                    metric_name, metric_current_value, metric_threshold,
                    alert_name, last_seen_at, severity
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                          $10, $11, $12, $13, $14, $15, $16, $17, $18)
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
                resource_id,
                resource_name,
                resource_group,
                metric_name,
                metric_current_value,
                metric_threshold,
                alert_name,
                now,
                severity,
            )
        if row is None:
            # ON CONFLICT DO NOTHING fired -- this incident already exists
            # (a resumed hitl_gate_node re-running its pre-interrupt code).
            # Same logical incident, not a new one: skip the audit/log noise
            # a second "created" entry would add and just return the id.
            return incident_id

        created_id = str(row["id"])
        self._write_audit_entry(workspace_id, agent_id, created_id, "created", tokens_used)
        log.info(
            f"[HITL] Incident {created_id} created — awaiting operator approval",
            extra={"workspace_id": workspace_id, "agent_id": agent_id, "incident_id": created_id},
        )
        self._fire_notification(
            workspace_id, agent_id, created_id, STATUS_PENDING, parsed_error,
            alert_name=alert_name, resource_name=resource_name,
        )
        return created_id

    async def find_open_incident(
        self,
        workspace_id: str,
        resource_id: Optional[str],
        alert_name: Optional[str],
    ) -> Optional[dict]:
        """
        Dedup lookup (Phase 3, GAPS.md scale-readiness build): an OPEN
        incident (pending_approval or executing) for this exact
        workspace+resource+alert_name combination. A resolved/held/failed/
        budget_exceeded prior incident for the same resource+alert is a
        legitimate new occurrence, not a duplicate of something already
        closed out, so only those two statuses count as "open" here.

        Returns None (never keys a dedup lookup) if resource_id or
        alert_name is missing/"unknown" -- there's nothing meaningful to
        match against, and a bare "unknown"=="unknown" match would
        incorrectly collapse unrelated alerts from different resources
        that both failed to parse a real identifier.
        """
        if not resource_id or resource_id == "unknown" or not alert_name or alert_name == "unknown":
            return None

        row = await self._db.fetchrow(
            """
            SELECT id, occurrence_count
            FROM incidents
            WHERE workspace_id = $1
              AND resource_id = $2
              AND alert_name = $3
              AND execution_status = ANY($4)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            workspace_id,
            resource_id,
            alert_name,
            [STATUS_PENDING, STATUS_EXECUTING],
        )
        return dict(row) if row else None

    async def bump_occurrence(self, incident_id: str) -> None:
        """Increment occurrence_count and refresh last_seen_at on an
        existing open incident -- called instead of create_incident when a
        flapping alert repeats for the same resource+alert_name, so a
        resource alerting every 5 minutes produces one incident row with a
        rising occurrence count, not a new row (and a new LLM call) every
        time."""
        await self._db.execute(
            """
            UPDATE incidents
            SET occurrence_count = occurrence_count + 1, last_seen_at = $2
            WHERE id = $1
            """,
            UUID(str(incident_id)),
            datetime.now(timezone.utc),
        )
        self._write_audit_entry("unknown", "hitl_gate", str(incident_id), "deduplicated", 0)

    async def note_source_resolution(self, incident_id: str) -> None:
        """
        Records that the alert SOURCE (Prometheus Alertmanager / Grafana
        unified alerting) itself reported this incident's underlying
        condition as resolved (GAPS.md scale-readiness build, Agent 11
        Alertmanager/Grafana ingest). Advisory only -- deliberately does
        NOT change execution_status. The incident may still need an
        operator's attention regardless of what the source says (a
        flapping alert, a false resolve, or just a preference to review
        before closing), so this never auto-closes anything the way
        mark_executed does.

        Kept as its own column (source_resolved_at, migration 056) rather
        than overloading resolution_note (migration 038) -- that column's
        own comment documents it as "NULL for every other resolution
        path," and this is exactly that other path: source-reported, not
        operator-reported.
        """
        await self._db.execute(
            "UPDATE incidents SET source_resolved_at = $2 WHERE id = $1",
            UUID(str(incident_id)),
            datetime.now(timezone.utc),
        )
        self._write_audit_entry("unknown", "hitl_gate", str(incident_id), "source_resolved", 0)

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

    async def mark_executed(
        self, incident_id: str, tokens_used: int = 0, before_state: Optional[dict] = None,
    ) -> None:
        """
        before_state: rollback information captured at execution time,
        for a direct cloud API mutation only (migration 042, GAPS.md
        24-gap closure Phase 1). Only agent_02 (K8s) passes this today --
        every other agent's execution step opens a PR, already reversible
        via git revert, confirmed by reading all 11 agents' _execute_node
        methods before adding this rather than assumed.
        """
        row = await self._db.fetchrow(
            """
            UPDATE incidents
            SET execution_status = $1, resolved_at = $2, tokens_used = tokens_used + $3,
                before_state = COALESCE($5, before_state)
            WHERE id = $4
            RETURNING workspace_id, agent_id, resource_name, resource_group, metric_name,
                      parsed_error, selected_option_id, resolved_at, cloud_provider, severity
            """,
            STATUS_EXECUTED,
            datetime.now(timezone.utc),
            tokens_used,
            UUID(incident_id),
            json.dumps(before_state) if before_state is not None else None,
        )
        self._write_audit_entry("unknown", "hitl_gate", incident_id, "executed", tokens_used)
        if row is not None:
            self._fire_ticketing_notification(incident_id, dict(row))

    async def mark_failed(
        self,
        incident_id: str,
        reason: str = "",
        failure_kind: Optional[str] = None,
    ) -> None:
        """
        failure_kind: 'permission_denied' | 'execution_error' | None
        (migration 050). None is kept as a valid value for existing call
        sites (e.g. create_failed_incident's own diagnosis-failure path,
        core/token_budget.py's budget-exceeded path) that predate this
        column and have no specific classification to offer -- the
        incident is still marked failed either way, this only affects
        whether the HITL card can render the specific "insufficient
        permissions, missing action X" treatment versus the generic
        "execution failed" one.
        """
        await self._db.execute(
            "UPDATE incidents SET execution_status = $1, failure_reason = $2, failure_kind = $3 WHERE id = $4",
            STATUS_FAILED,
            reason or None,
            failure_kind,
            UUID(incident_id),
        )
        self._write_audit_entry("unknown", "hitl_gate", incident_id, f"failed:{reason}", 0)

    async def create_failed_incident(
        self,
        workspace_id: str,
        agent_id: str,
        error_message: str,
        raw_log: str = "",
        cloud_provider: Optional[str] = None,
    ) -> str:
        """
        Persist a FAILED incident directly -- no interrupt(), no operator
        approval needed, since there's nothing to approve when diagnosis
        itself never completed. Phase 10, scale-readiness build: this is
        what makes "all failed runs for workspace X in the last 24 hours"
        a single query against incidents (WHERE execution_status =
        'failed') instead of a cross-system stitch between audit_events
        and Sentry.

        Called from every agent's _hitl_gate_node when state["error"] is
        set -- previously that branch just logged and returned {},
        skipping incident creation entirely and silently dropping the
        run with no queryable trace.
        """
        raw_log_hash = hashlib.sha256(raw_log.encode()).hexdigest()
        row = await self._db.fetchrow(
            """
            INSERT INTO incidents (
                workspace_id, agent_id, cloud_provider, raw_log_hash,
                parsed_error, remediation_options, execution_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            workspace_id,
            agent_id,
            cloud_provider,
            raw_log_hash,
            error_message,
            json.dumps([]),
            STATUS_FAILED,
        )
        created_id = str(row["id"])
        self._write_audit_entry(workspace_id, agent_id, created_id, "failed", 0)
        log.info(
            f"[HITL] Incident {created_id} created with status=failed — {error_message[:100]}",
            extra={
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "incident_id": created_id,
                "execution_status": STATUS_FAILED,
            },
        )
        self._fire_notification(workspace_id, agent_id, created_id, STATUS_FAILED, error_message)
        return created_id

    def _fire_notification(
        self,
        workspace_id: str,
        agent_id: str,
        incident_id: str,
        execution_status: str,
        summary: str,
        alert_name: Optional[str] = None,
        resource_name: Optional[str] = None,
    ) -> None:
        """
        Best-effort, fire-and-forget Slack/PagerDuty dispatch — mirrors
        api/routes/internal_workspaces.py's _send_enterprise_alert
        best-effort pattern. A failure to even schedule the task (e.g. no
        running event loop) is caught here so it can never block incident
        creation; the task itself never raises back into this call either
        (see core/notifications.py's notify_incident_channels docstring).
        """
        try:
            from core.notifications import notify_incident_channels

            incident_summary = {
                "incident_id": incident_id,
                "agent_id": agent_id,
                "execution_status": execution_status,
                "summary": summary,
                "alert_name": alert_name,
                "resource_name": resource_name,
            }
            asyncio.create_task(notify_incident_channels(workspace_id, incident_summary))
        except Exception as exc:
            log.warning(
                f"[HITL] Failed to schedule notification dispatch for incident {incident_id}: {exc}",
                extra={"workspace_id": workspace_id, "incident_id": incident_id},
            )

    def _fire_ticketing_notification(self, incident_id: str, row: dict) -> None:
        """
        Best-effort, fire-and-forget ticketing dispatch on resolution --
        mirrors _fire_notification above but fires on execution_status
        becoming STATUS_EXECUTED rather than on creation. See
        core/ticketing.py's notify_resolution for the full non-fatal shape.

        resolved_by is always None on this path: mark_executed runs deep
        inside a resumed LangGraph workflow (agents/agent_0N_*/workflow.py's
        resume(), called from api/routes/incidents.py's approve_incident),
        several calls removed from the approval endpoint that actually knew
        which workspace member approved it -- that identity is not
        currently threaded through the resume() call chain into here. A
        real gap, not invented away: threading member_id through eleven
        separate workflow classes' resume() signatures is a larger, riskier
        change than this ticketing build's scope. api/routes/incidents.py's
        resolve_incident_manually (the OTHER resolution call site) does
        have the approver's member_id available and passes it through.
        """
        try:
            from core.ticketing import schedule_resolution_notification

            incident_summary = {
                "incident_id": incident_id,
                "agent_id": row.get("agent_id"),
                "resource_name": row.get("resource_name"),
                "resource_group": row.get("resource_group"),
                "metric_name": row.get("metric_name"),
                "parsed_error": row.get("parsed_error"),
                "selected_option_id": row.get("selected_option_id"),
                "resolved_at": row["resolved_at"].isoformat() if row.get("resolved_at") else None,
                "cloud_provider": row.get("cloud_provider"),
                "severity": row.get("severity"),
            }
            schedule_resolution_notification(str(row["workspace_id"]), incident_summary, resolved_by=None)
        except Exception as exc:
            log.warning(
                f"[HITL] Failed to schedule ticketing dispatch for incident {incident_id}: {exc}",
                extra={"incident_id": incident_id},
            )

    def _write_audit_entry(
        self,
        workspace_id: str,
        agent_id: str,
        incident_id: str,
        action: str,
        tokens_used: int,
    ) -> None:
        """
        Append to the operator markdown audit log — Rule 9 compliance —
        AND fire a real audit_events DB row (GAPS.md #28, best-effort,
        detached via asyncio.create_task so this stays a synchronous
        method and every one of this method's existing call sites needs
        no change). The markdown file remains a secondary, operator-only
        debugging output; audit_events is now the actual customer-facing,
        per-tenant-queryable audit trail the security page describes.
        """
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

        from core.audit import schedule_audit_event
        schedule_audit_event(
            workspace_id=workspace_id,
            action=action,
            incident_id=incident_id,
            agent_id=agent_id,
            tokens_used=tokens_used,
        )
