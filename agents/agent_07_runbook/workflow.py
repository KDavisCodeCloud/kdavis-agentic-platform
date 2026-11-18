"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Agent 07 — Interactive Runbook Automation
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

The LLM acts as a "runbook interpreter" — given a runbook definition and an incident
context, it generates a contextualized execution plan, possibly skipping or reordering
steps that are not relevant to the current incident.

Trigger: Manual via POST /agents/agent_07_runbook/run, or invoked by another agent.

Runbook step execution is disabled (2026-11-18): see tools.py. The card offers
only "file the plan as an issue" or Hold.
"""

import json
import logging
from pathlib import Path
from typing import Optional, TypedDict

import httpx
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_07_runbook.tools import RunbookTools, option_catalog
from core.option_catalog import bind_options, catalog_prompt_block
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

    def __init__(
        self,
        db_conn,
        workspace_id: str,
        checkpointer: AsyncPostgresSaver,
        llm_provider: Optional[str] = None,  # Phase 5 -- workspaces.llm_provider, routed into BaseAgent.call_llm()'s defaults
        byok_encrypted_key: Optional[str] = None,  # Phase 5 -- workspaces.encrypted_llm_key
    ):
        super().__init__(db_conn, workspace_id, llm_provider=llm_provider, byok_encrypted_key=byok_encrypted_key)
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
            # incident_id intentionally NOT returned here -- it's pre-seeded
            # in run()'s initial_state (== the LangGraph thread_id) and must
            # survive this node's update untouched, not get reset to None.
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

        # G12: the LLM may only propose actions this agent can execute (core/option_catalog.py)
        _catalog = option_catalog({})
        user_message = f"{user_message}\n\n{catalog_prompt_block(_catalog)}"

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
        # Runbook execution was removed (tools.py), so filing the plan is
        # always offered, whatever the LLM proposed; an LLM "run it" option
        # has no catalog entry and is dropped.
        diagnosis["options"] = [*(diagnosis.get("options") or []), {"id": "opt_2"}]
        options          = bind_options(diagnosis.get("options", []), _catalog, self.agent_id)
        duration         = diagnosis.get("estimated_duration_seconds", 60)

        # Enforce step cap
        if len(execution_plan) > _MAX_STEPS:
            execution_plan = execution_plan[:_MAX_STEPS]
            log.warning("[Agent07] Execution plan capped at %d steps", _MAX_STEPS)

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
            incident_id = await self.hitl.create_failed_incident(
                workspace_id=self.workspace_id,
                agent_id=self.agent_id,
                error_message=state["error"],
                raw_log=state.get("log_excerpt", ""),
                cloud_provider=state.get("cloud_provider"),
            )
            return {"incident_id": incident_id}

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
            incident_id=state["incident_id"],
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
            f"Runbook Plan: {state['runbook_name']} "
            f"(v{state['runbook_version']}) — {len(plan)} steps"
        )

        context = {
            "plan_steps": plan,
            "owner": owner,
            "repo": repo,
            "report_title": report_title,
            "report_body": _build_plan_report(
                runbook_name=state["runbook_name"],
                runbook_version=state["runbook_version"],
                incident_context=state["incident_context"],
                plan_summary=state.get("plan_summary", ""),
                plan_steps=plan,
                skipped_steps=state.get("skipped_steps") or [],
            ),
        }

        context["incident_id"] = state.get("incident_id")  # G17: fix branches are named for it
        try:
            result = await self._tools.execute_option(selected, context)
        except (EnvironmentError, RuntimeError, httpx.HTTPError) as exc:
            log.warning("[Agent07] Option %s failed: %s", option_id, exc)
            result = {"status": "failed", "reason": str(exc)}

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

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

        # thread_id generated before initial_state so incident_id can be
        # pre-seeded to the same value -- see _hitl_gate_node's
        # create_incident(incident_id=state["incident_id"], ...) call.
        # Real bug found live, 2026-09-15: this agent never adopted that
        # fix (unlike agent_01/05/06/08), so the incidents-table row got a
        # random DB-generated id disconnected from the actual LangGraph
        # checkpoint thread_id -- POST /incidents/{id}/approve then called
        # resume(that_id, ...), which looked up a checkpoint under an id
        # the graph was never invoked with, and LangGraph silently treated
        # every real approval as a fresh __start__ invocation instead
        # (langgraph.errors.InvalidUpdateError, since Command(resume=...)
        # is not valid raw state input for __start__).
        thread_id = str(uuid.uuid4())

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
            "incident_id": thread_id,
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

        config    = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent07] Starting runbook workflow — thread_id=%s", thread_id)

        result = await self._graph.ainvoke(initial_state, config=config)

        interrupt_data = None
        for task in ((await self._graph.aget_state(config)).tasks or []):
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

def _build_plan_report(
    runbook_name: str,
    runbook_version: str,
    incident_context: str,
    plan_summary: str,
    plan_steps: list,
    skipped_steps: list,
) -> str:
    """Markdown body for the runbook-plan issue. Nothing in it has been run."""
    step_lines = "\n".join(
        f"{i}. **{s.get('name') or s.get('id', 'step')}** (`{s.get('type', '?')}`)"
        + (f": `{s['command']}`" if s.get("command") else "")
        + (f" — ⚠️ {s['risk_note']}" if s.get("risk_note") else "")
        for i, s in enumerate(plan_steps, 1)
    ) or "_No steps in the plan._"
    skipped_lines = "\n".join(
        f"- {s.get('name') or s.get('id', 'step')}: {s.get('reason', '')}" for s in skipped_steps
    ) or "_None._"
    return (
        f"## Cloud Decoded — Runbook Plan\n\n"
        f"**Runbook:** {runbook_name} (v{runbook_version})  \n"
        f"**Status:** not executed. Cloud Decoded does not run runbook steps; "
        f"run this plan with your own tooling.\n\n"
        f"### Incident Context\n\n{incident_context or '_Not provided_'}\n\n"
        f"### Plan Summary\n\n{plan_summary or '_Not available_'}\n\n"
        f"### Steps\n\n{step_lines}\n\n"
        f"### Skipped\n\n{skipped_lines}\n\n"
        f"---\n*Generated by Cloud Decoded Agent 07.*"
    )
