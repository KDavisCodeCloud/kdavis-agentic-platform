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
Agent 07 — Interactive Runbook Automation
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

The LLM acts as a "runbook interpreter" — given a runbook definition and an incident
context, it generates a contextualized execution plan, possibly skipping or reordering
steps that are not relevant to the current incident.

Trigger: Manual via POST /agents/agent_07_runbook/run, or invoked by another agent.
"""

import json
import logging
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_07_runbook.tools import RunbookTools, _summarize_step_results
from core.security import shield

log = logging.getLogger(__name__)

_MAX_RUNBOOK_CHARS  = 6_000
_MAX_INCIDENT_CHARS = 3_000
_MAX_STEPS          = 50


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class RunbookState(TypedDict):
    # Inputs
    workspace_id: str
    cloud_provider: str
    webhook_payload: dict

    # Extracted by ingest
    runbook_name: str
    runbook_version: str
    runbook_steps_raw: list        # original steps from payload
    runbook_steps_text: str        # sanitized text representation for LLM
    incident_context: str          # sanitized triggering incident description
    repository: str                # optional "owner/repo" for issue creation
    trigger_source: str            # "manual" | "agent_01" | "agent_02" | etc.

    # After diagnose
    incident_id: Optional[str]
    parsed_error: Optional[str]     # runbook execution summary / risk headline
    execution_plan: Optional[list]  # LLM-ordered list of steps to execute
    plan_summary: Optional[str]     # human-readable plan description
    skipped_steps: Optional[list]   # steps LLM decided not to execute
    estimated_duration_seconds: Optional[int]
    remediation_options: Optional[list]
    tokens_used: int

    # After HITL
    selected_option: Optional[dict]

    # After execute
    execution_result: Optional[dict]

    error: Optional[str]


# ──────────────────────────────────────────────
# Prompt loader
# ──────────────────────────────────────────────

def _load_diagnose_prompt() -> str:
    path = Path(__file__).parent / "prompts" / "diagnose.md"
    return path.read_text()


# ──────────────────────────────────────────────
# Ingest helpers
# ──────────────────────────────────────────────

def _normalize_runbook_steps(steps: list | dict | str) -> tuple[list, str]:
    """
    Normalize runbook steps into a canonical list + human-readable text.
    Accepts: list of step dicts, a dict with a 'steps' key, or a JSON string.
    Returns (canonical_steps_list, text_for_llm).
    """
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except (json.JSONDecodeError, ValueError):
            return [], steps[:_MAX_RUNBOOK_CHARS]

    if isinstance(steps, dict):
        steps = steps.get("steps", [steps])

    if not isinstance(steps, list):
        return [], str(steps)[:_MAX_RUNBOOK_CHARS]

    steps = steps[:_MAX_STEPS]

    lines = []
    for i, step in enumerate(steps, 1):
        step_id   = step.get("id", f"step-{i:02d}")
        step_name = step.get("name", step_id)
        step_type = step.get("type", "shell")
        cmd       = step.get("command") or step.get("url") or step.get("manifest", "")[:80]
        on_fail   = step.get("on_failure", "continue")
        lines.append(f"{i}. [{step_id}] {step_name} (type={step_type}, on_failure={on_fail}): {cmd}")

    text = "\n".join(lines)
    if len(text) > _MAX_RUNBOOK_CHARS:
        text = text[:_MAX_RUNBOOK_CHARS] + "\n... [truncated]"

    return steps, text


# ──────────────────────────────────────────────
# Workflow class
# ──────────────────────────────────────────────

class RunbookWorkflow(BaseAgent):
    """
    Agent 07: Interactive Runbook Automation.

    Usage:
        workflow = RunbookWorkflow(db_conn, workspace_id, checkpointer)
        incident_id = await workflow.run({
            "runbook_name": "OOMKilled Recovery",
            "runbook_version": "1.2",
            "steps": [ <list of step dicts> ],
            "incident_context": "payment-service OOMKilled 4 times in 10 min",
            "repository": "acme/ops",
        }, cloud_provider="aws")
        await workflow.resume(thread_id, selected_option)
    """

    AGENT_ID = "agent_07_runbook"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer = checkpointer
        self._tools = RunbookTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(RunbookState)

        graph.add_node("ingest",    self._ingest_node)
        graph.add_node("diagnose",  self._diagnose_node)
        graph.add_node("hitl_gate", self._hitl_gate_node)
        graph.add_node("execute",   self._execute_node)
        graph.add_node("complete",  self._complete_node)

        graph.add_edge(START,       "ingest")
        graph.add_edge("ingest",    "diagnose")
        graph.add_edge("diagnose",  "hitl_gate")
        graph.add_edge("hitl_gate", "execute")
        graph.add_edge("execute",   "complete")
        graph.add_edge("complete",  END)

        return graph.compile(checkpointer=self._checkpointer)

    # ──────────────────────────────────────────────
    # Nodes
    # ──────────────────────────────────────────────

    async def _ingest_node(self, state: RunbookState) -> dict:
        """
        Parse and normalize the runbook definition and incident context.
        Sanitizes both before LLM consumption.
        """
        payload = state["webhook_payload"]

        runbook_name    = payload.get("runbook_name", "Unnamed Runbook")
        runbook_version = payload.get("runbook_version", "1.0")
        repository      = payload.get("repository", "")
        trigger_source  = payload.get("trigger_source", "manual")
        incident_ctx    = payload.get("incident_context", "")

        # Normalize steps
        raw_steps = payload.get("steps", payload.get("runbook_steps", []))
        canonical_steps, steps_text = _normalize_runbook_steps(raw_steps)

        # Sanitize steps text and incident context
        sanitized_steps = shield.sanitize(steps_text, context=self.agent_id)

        if len(incident_ctx) > _MAX_INCIDENT_CHARS:
            incident_ctx = incident_ctx[:_MAX_INCIDENT_CHARS] + " ... [truncated]"
        sanitized_incident = shield.sanitize(incident_ctx, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent07] Ingested runbook='%s' v%s steps=%d trigger=%s",
            runbook_name, runbook_version, len(canonical_steps), trigger_source,
        )

        return {
            "runbook_name": runbook_name,
            "runbook_version": runbook_version,
            "runbook_steps_raw": canonical_steps,
            "runbook_steps_text": sanitized_steps.sanitized_text,
            "incident_context": sanitized_incident.sanitized_text,
            "repository": repository,
            "trigger_source": trigger_source,
            "tokens_used": 0,
            "incident_id": None,
            "parsed_error": None,
            "execution_plan": None,
            "plan_summary": None,
            "skipped_steps": None,
            "estimated_duration_seconds": None,
            "remediation_options": None,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

    async def _diagnose_node(self, state: RunbookState) -> dict:
        """
        LLM interprets the runbook in the context of the triggering incident and
        produces a contextualized execution plan — potentially skipping irrelevant
        steps or adding warnings about risky ones.
        """
        user_message = (
            f"Runbook Automation Request:\n\n"
            f"Runbook: {state['runbook_name']} (v{state['runbook_version']})\n"
            f"Triggered By: {state['trigger_source']}\n\n"
            f"Incident Context:\n{state['incident_context'] or '(no incident context provided — running full runbook)'}\n\n"
            f"Runbook Steps:\n{state['runbook_steps_text']}\n\n"
            f"Analyze the runbook against the incident context. Determine which steps are "
            f"relevant, flag any risky steps, and produce a contextualized execution plan. "
            f"Return exactly the JSON format specified."
        )

        await self.check_budget(estimated_tokens=4000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="runbook_automation",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="runbook_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {"error": str(exc), "tokens_used": estimated_tokens}

        parsed_error     = diagnosis.get("parsed_error", f"Runbook '{state['runbook_name']}' ready to execute")
        execution_plan   = diagnosis.get("execution_plan", state["runbook_steps_raw"])
        plan_summary     = diagnosis.get("plan_summary", "")
        skipped_steps    = diagnosis.get("skipped_steps", [])
        options          = diagnosis.get("options", [])
        duration         = diagnosis.get("estimated_duration_seconds", 60)

        # Enforce step cap
        if len(execution_plan) > _MAX_STEPS:
            execution_plan = execution_plan[:_MAX_STEPS]
            log.warning("[Agent07] Execution plan capped at %d steps", _MAX_STEPS)

        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent07] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info(
            "[Agent07] Plan: %d steps to execute, %d skipped | %s",
            len(execution_plan), len(skipped_steps), parsed_error[:80],
        )

        return {
            "parsed_error": parsed_error,
            "execution_plan": execution_plan,
            "plan_summary": plan_summary,
            "skipped_steps": skipped_steps,
            "estimated_duration_seconds": duration,
            "remediation_options": options,
            "tokens_used": state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: RunbookState) -> dict:
        """
        Save incident and pause for operator approval.
        Governance Rule 11: No autonomous runbook execution.
        """
        if state.get("error"):
            log.error("[Agent07] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

        plan      = state.get("execution_plan") or []
        skipped   = state.get("skipped_steps") or []

        raw_log = (
            f"Runbook: {state['runbook_name']} v{state['runbook_version']}\n"
            f"Trigger: {state['trigger_source']}\n"
            f"Steps to Execute: {len(plan)}\n"
            f"Steps Skipped: {len(skipped)}\n"
            f"Est. Duration: {state.get('estimated_duration_seconds', '?')}s\n\n"
            f"Plan Summary:\n{state.get('plan_summary', '')[:400]}\n\n"
            f"Incident Context:\n{state['incident_context'][:300]}"
        )

        incident_id = await self.hitl.create_incident(
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            raw_log=raw_log,
            parsed_error=state["parsed_error"],
            remediation_options=state["remediation_options"],
            cloud_provider=state["cloud_provider"],
            tokens_used=state.get("tokens_used", 0),
            estimated_duration_seconds=state.get("estimated_duration_seconds"),
        )

        await self.record_token_usage(
            tokens_used=state.get("tokens_used", 0),
            incident_id=incident_id,
        )

        self._write_audit("hitl_gate", "pending_approval", incident_id=incident_id)
        log.info(
            "[Agent07] HITL gate — incident %s | runbook=%s steps=%d",
            incident_id, state["runbook_name"], len(plan),
        )

        selected_option = interrupt({
            "incident_id": incident_id,
            "message": "Awaiting operator approval to execute runbook",
            "options": state["remediation_options"],
            "steps_count": len(plan),
            "skipped_count": len(skipped),
            "plan_summary": state.get("plan_summary"),
        })

        return {
            "incident_id": incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: RunbookState) -> dict:
        """Execute the approved runbook plan."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent07] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        log.info("[Agent07] Executing approved option: %s", option_id)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        owner, _, repo = state.get("repository", "/").partition("/")

        plan = state.get("execution_plan") or []
        report_title = (
            f"Runbook Execution: {state['runbook_name']} "
            f"(v{state['runbook_version']}) — {len(plan)} steps"
        )

        context = {
            "runbook_name": state["runbook_name"],
            "runbook_version": state["runbook_version"],
            "incident_context": state["incident_context"],
            "trigger_source": state["trigger_source"],
            "plan_steps": plan,
            "owner": owner,
            "repo": repo,
            "report_title": report_title,
            "report_body": "",  # filled after execution for opt_1 pre-report (opt_2 dry-run)
        }

        result = await self._tools.execute_option(selected, context)

        # For opt_1 (execution), build a post-execution report and create an issue if repo available
        if option_id == "opt_1" and result.get("status") in ("ok", "partial", "failed") and owner and repo:
            step_results = result.get("step_results", [])
            report_body = _build_execution_report(
                runbook_name=state["runbook_name"],
                runbook_version=state["runbook_version"],
                incident_context=state["incident_context"],
                plan_summary=state.get("plan_summary", ""),
                step_results=step_results,
                skipped_steps=state.get("skipped_steps") or [],
                overall_status=result.get("status", "unknown"),
            )
            try:
                issue_result = await self._tools.create_runbook_issue(
                    owner=owner, repo=repo,
                    title=report_title,
                    body=report_body,
                    labels=["runbook", "operations"],
                )
                result["report_issue"] = issue_result
            except (EnvironmentError, RuntimeError) as exc:
                log.warning("[Agent07] Could not create execution report issue: %s", exc)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: RunbookState) -> dict:
        """Mark incident as executed and finalize audit trail."""
        incident_id = state.get("incident_id")
        if incident_id:
            exec_result = state.get("execution_result") or {}
            if exec_result.get("status") == "held":
                await self.hitl._db.execute(
                    "UPDATE incidents SET execution_status = 'held' WHERE id = $1",
                    __import__("uuid").UUID(incident_id),
                )
            else:
                await self.hitl.mark_executed(incident_id, tokens_used=0)

        self._write_audit("complete", "done", incident_id=incident_id)
        log.info("[Agent07] Workflow complete for incident %s", incident_id)
        return {}

    # ──────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────

    async def run(
        self,
        payload: dict,
        cloud_provider: str = "aws",
        byok_encrypted_key: Optional[str] = None,
    ) -> str:
        """Trigger the runbook workflow. Returns incident_id after HITL gate pause."""
        import uuid

        initial_state: RunbookState = {
            "workspace_id": self.workspace_id,
            "cloud_provider": cloud_provider,
            "webhook_payload": payload,
            "runbook_name": "",
            "runbook_version": "",
            "runbook_steps_raw": [],
            "runbook_steps_text": "",
            "incident_context": "",
            "repository": "",
            "trigger_source": "manual",
            "incident_id": None,
            "parsed_error": None,
            "execution_plan": None,
            "plan_summary": None,
            "skipped_steps": None,
            "estimated_duration_seconds": None,
            "remediation_options": None,
            "tokens_used": 0,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

        thread_id = str(uuid.uuid4())
        config    = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent07] Starting runbook workflow — thread_id=%s", thread_id)

        result = await self._graph.ainvoke(initial_state, config=config)

        interrupt_data = None
        for task in (self._graph.get_state(config).tasks or []):
            if hasattr(task, "interrupts") and task.interrupts:
                interrupt_data = task.interrupts[0].value
                break

        incident_id = (
            interrupt_data.get("incident_id") if interrupt_data
            else result.get("incident_id", thread_id)
        )

        log.info("[Agent07] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info("[Agent07] Resuming thread=%s with option=%s", thread_id, selected_option.get("id"))
        result = await self._graph.ainvoke(Command(resume=selected_option), config=config)
        return result.get("execution_result", {"status": "completed"})


# ──────────────────────────────────────────────
# Report builders
# ──────────────────────────────────────────────

def _build_execution_report(
    runbook_name: str,
    runbook_version: str,
    incident_context: str,
    plan_summary: str,
    step_results: list[dict],
    skipped_steps: list,
    overall_status: str,
) -> str:
    status_icon = {"ok": "✅", "partial": "⚠️", "failed": "❌"}.get(overall_status, "❓")
    succeeded = sum(1 for r in step_results if r.get("status") == "ok")
    failed    = sum(1 for r in step_results if r.get("status") == "failed")
    skip_cnt  = sum(1 for r in step_results if r.get("status") == "skipped")

    return (
        f"## Cloud Decoded — Runbook Execution Report\n\n"
        f"**Runbook:** {runbook_name} (v{runbook_version})  \n"
        f"**Overall Status:** {status_icon} {overall_status.upper()}\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Steps Executed | {len(step_results)} |\n"
        f"| Succeeded | {succeeded} |\n"
        f"| Failed | {failed} |\n"
        f"| Skipped | {skip_cnt + len(skipped_steps)} |\n\n"
        f"### Incident Context\n\n"
        f"{incident_context or '_Not provided_'}\n\n"
        f"### Execution Plan Summary\n\n"
        f"{plan_summary or '_Not available_'}\n\n"
        f"### Step Results\n\n"
        f"{_summarize_step_results(step_results)}\n\n"
        f"---\n"
        f"*Generated by Cloud Decoded Agent 07. Review step outputs before marking incident resolved.*"
    )
