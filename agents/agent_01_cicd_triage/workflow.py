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
Agent 01 — CI/CD Pipeline Failure Triage
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

The graph pauses at hitl_gate via interrupt(). It resumes when the FastAPI
POST /incidents/{id}/approve endpoint calls graph.ainvoke(Command(resume=...)).
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, TypedDict, Annotated

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_01_cicd_triage.tools import CICDTools
from core.security import shield

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class CICDTriageState(TypedDict):
    # Inputs (set on initial invocation)
    workspace_id: str
    cloud_provider: str           # "github" | "azure_devops"
    webhook_payload: dict         # sanitized raw webhook data

    # Extracted from webhook (set by ingest node)
    job_name: str
    repository: str
    branch: str
    run_id: int
    log_excerpt: str
    pr_number: Optional[int]
    owner_or_org: str             # GitHub owner or Azure DevOps org

    # After diagnose
    incident_id: Optional[str]
    parsed_error: Optional[str]
    remediation_options: Optional[list]
    estimated_duration_seconds: Optional[int]
    tokens_used: int

    # After HITL approval (set by hitl_gate node on resume)
    selected_option: Optional[dict]

    # After execute
    execution_result: Optional[dict]

    # Error / status
    error: Optional[str]


# ──────────────────────────────────────────────
# Prompt loader
# ──────────────────────────────────────────────

def _load_diagnose_prompt() -> str:
    path = Path(__file__).parent / "prompts" / "diagnose.md"
    return path.read_text()


# ──────────────────────────────────────────────
# Workflow class
# ──────────────────────────────────────────────

class CICDTriageWorkflow(BaseAgent):
    """
    Agent 01: CI/CD Pipeline Failure Triage.

    Usage:
        workflow = CICDTriageWorkflow(db_conn, workspace_id)
        # Initial trigger (from webhook):
        incident_id = await workflow.run(webhook_payload)
        # On operator approval (from API):
        await workflow.resume(incident_id, selected_option)
    """

    AGENT_ID = "agent_01_cicd_triage"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer = checkpointer
        self._tools = CICDTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(CICDTriageState)

        graph.add_node("ingest", self._ingest_node)
        graph.add_node("diagnose", self._diagnose_node)
        graph.add_node("hitl_gate", self._hitl_gate_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("complete", self._complete_node)

        graph.add_edge(START, "ingest")
        graph.add_edge("ingest", "diagnose")
        graph.add_edge("diagnose", "hitl_gate")
        graph.add_edge("hitl_gate", "execute")
        graph.add_edge("execute", "complete")
        graph.add_edge("complete", END)

        return graph.compile(checkpointer=self._checkpointer)

    # ──────────────────────────────────────────────
    # Nodes
    # ──────────────────────────────────────────────

    async def _ingest_node(self, state: CICDTriageState) -> dict:
        """Extract structured fields from the webhook payload. Sanitize everything."""
        payload = state["webhook_payload"]
        provider = state["cloud_provider"]

        if provider == "github":
            run = payload.get("workflow_run", {})
            head_commit = run.get("head_commit", {})
            pr_list = run.get("pull_requests", [])

            job_name = run.get("name", "unknown-job")
            repository = payload.get("repository", {}).get("full_name", "unknown/unknown")
            owner_or_org = repository.split("/")[0] if "/" in repository else "unknown"
            repo_name = repository.split("/")[1] if "/" in repository else repository
            branch = run.get("head_branch", "main")
            run_id = run.get("id", 0)
            pr_number = pr_list[0].get("number") if pr_list else None

            # Extract log excerpt from conclusion + head commit message
            log_lines = [
                f"Job: {job_name}",
                f"Status: {run.get('conclusion', 'failure')}",
                f"Branch: {branch}",
                f"Commit: {head_commit.get('message', '')[:200]}",
                f"Run URL: {run.get('html_url', '')}",
            ]
            log_excerpt = "\n".join(log_lines)

        elif provider == "azure_devops":
            resource = payload.get("resource", {})
            definition = resource.get("definition", {})
            project = payload.get("resourceContainers", {}).get("project", {})

            job_name = definition.get("name", "unknown-pipeline")
            repository = resource.get("repository", {}).get("id", "unknown")
            owner_or_org = payload.get("resourceContainers", {}).get("account", {}).get("id", "unknown")
            branch = resource.get("sourceBranch", "main").replace("refs/heads/", "")
            run_id = resource.get("id", 0)
            pr_number = None

            log_lines = [
                f"Pipeline: {job_name}",
                f"Status: {resource.get('result', 'failed')}",
                f"Branch: {branch}",
                f"Project: {project.get('name', 'unknown')}",
            ]
            log_excerpt = "\n".join(log_lines)
            repo_name = repository

        else:
            log.warning("[Agent01] Unknown cloud_provider: %s", provider)
            job_name = "unknown"
            repository = "unknown/unknown"
            owner_or_org = "unknown"
            repo_name = "unknown"
            branch = "main"
            run_id = 0
            pr_number = None
            log_excerpt = json.dumps(payload)[:500]

        # Sanitize the log excerpt before it goes anywhere else
        sanitized = shield.sanitize(log_excerpt, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent01] Ingested: job=%s repo=%s branch=%s run_id=%s",
            job_name, repository, branch, run_id
        )

        return {
            "job_name": job_name,
            "repository": repository,
            "owner_or_org": owner_or_org,
            "branch": branch,
            "run_id": run_id,
            "log_excerpt": sanitized.sanitized_text,
            "pr_number": pr_number,
            "tokens_used": 0,
            "incident_id": None,
            "parsed_error": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

    async def _diagnose_node(self, state: CICDTriageState) -> dict:
        """Call LLM via router to diagnose the failure. Parse JSON response."""
        user_message = (
            f"CI/CD Pipeline Failure Report:\n\n"
            f"Provider: {state['cloud_provider']}\n"
            f"Job: {state['job_name']}\n"
            f"Repository: {state['repository']}\n"
            f"Branch: {state['branch']}\n"
            f"Run ID: {state['run_id']}\n\n"
            f"Log Excerpt:\n{state['log_excerpt']}\n\n"
            f"Diagnose this failure and return exactly the JSON format specified."
        )

        # Budget check before LLM call
        await self.check_budget(estimated_tokens=3000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="issue_triage",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {"error": str(exc), "tokens_used": estimated_tokens}

        parsed_error = diagnosis.get("parsed_error", "Unknown error")
        options = diagnosis.get("options", [])
        duration = diagnosis.get("estimated_duration_seconds", 120)

        # Validate option structure
        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent01] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info("[Agent01] Diagnosed: %s (options=%d)", parsed_error[:80], len(options))

        return {
            "parsed_error": parsed_error,
            "remediation_options": options,
            "estimated_duration_seconds": duration,
            "tokens_used": state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: CICDTriageState) -> dict:
        """
        Save incident to DB, then interrupt() to pause the graph.
        Execution resumes when POST /incidents/{id}/approve is called.
        Governance Rule 11: No autonomous remediation.
        """
        if state.get("error"):
            log.error("[Agent01] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

        # Save incident to DB before pausing
        incident_id = await self.hitl.create_incident(
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            raw_log=state["log_excerpt"],
            parsed_error=state["parsed_error"],
            remediation_options=state["remediation_options"],
            cloud_provider=state["cloud_provider"],
            tokens_used=state.get("tokens_used", 0),
            estimated_duration_seconds=state.get("estimated_duration_seconds"),
        )

        # Record token usage against workspace budget
        await self.record_token_usage(
            tokens_used=state.get("tokens_used", 0),
            incident_id=incident_id,
        )

        self._write_audit("hitl_gate", "pending_approval", incident_id=incident_id)
        log.info("[Agent01] HITL gate — incident %s awaiting operator approval", incident_id)

        # Pause graph here. Resumes when Command(resume=selected_option) is sent.
        selected_option = interrupt({
            "incident_id": incident_id,
            "message": "Awaiting operator approval",
            "options": state["remediation_options"],
        })

        return {
            "incident_id": incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: CICDTriageState) -> dict:
        """Execute the approved remediation option. Only reached after human approval."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent01] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        log.info("[Agent01] Executing approved option: %s", option_id)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id")
        )

        context = {
            "cloud_provider": state["cloud_provider"],
            "owner": state["owner_or_org"],
            "org": state["owner_or_org"],
            "repo": state["repository"].split("/")[-1] if "/" in state["repository"] else state["repository"],
            "project": state["repository"],
            "run_id": state["run_id"],
            "pr_number": state.get("pr_number"),
            "parsed_error": state.get("parsed_error", ""),
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id")
        )

        return {"execution_result": result}

    async def _complete_node(self, state: CICDTriageState) -> dict:
        """Mark incident as executed and finalize audit trail."""
        incident_id = state.get("incident_id")
        if incident_id:
            exec_result = state.get("execution_result", {}) or {}
            exec_status = exec_result.get("status", "unknown")

            if exec_status == "held":
                await self.hitl._db.execute(
                    "UPDATE incidents SET execution_status = 'held' WHERE id = $1",
                    __import__("uuid").UUID(incident_id),
                )
            else:
                await self.hitl.mark_executed(incident_id, tokens_used=0)

        self._write_audit("complete", "done", incident_id=incident_id)
        log.info("[Agent01] Workflow complete for incident %s", incident_id)
        return {}

    # ──────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────

    async def run(
        self,
        payload: dict,
        cloud_provider: str = "github",
        byok_encrypted_key: Optional[str] = None,
    ) -> str:
        """
        Trigger the triage workflow from a webhook payload.
        Returns immediately with incident_id after the HITL gate pause.
        """
        initial_state: CICDTriageState = {
            "workspace_id": self.workspace_id,
            "cloud_provider": cloud_provider,
            "webhook_payload": payload,
            "job_name": "",
            "repository": "",
            "branch": "",
            "run_id": 0,
            "owner_or_org": "",
            "log_excerpt": "",
            "pr_number": None,
            "incident_id": None,
            "parsed_error": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "tokens_used": 0,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

        # Generate a unique thread ID for this workflow run
        import uuid
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent01] Starting triage workflow — thread_id=%s", thread_id)

        # Run until the interrupt() pause in hitl_gate_node
        result = await self._graph.ainvoke(initial_state, config=config)

        # The thread_id IS the incident tracking key for resume
        # The actual incident_id is stored in the graph state after hitl_gate runs
        interrupt_data = None
        for task in (self._graph.get_state(config).tasks or []):
            if hasattr(task, "interrupts") and task.interrupts:
                interrupt_data = task.interrupts[0].value
                break

        incident_id = (
            interrupt_data.get("incident_id") if interrupt_data
            else result.get("incident_id", thread_id)
        )

        log.info("[Agent01] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """
        Resume the paused workflow after operator approval.
        Called by POST /incidents/{id}/approve via the API layer.
        """
        config = {"configurable": {"thread_id": thread_id}}
        log.info(
            "[Agent01] Resuming workflow thread=%s with option=%s",
            thread_id, selected_option.get("id")
        )

        result = await self._graph.ainvoke(
            Command(resume=selected_option),
            config=config,
        )

        return result.get("execution_result", {"status": "completed"})
