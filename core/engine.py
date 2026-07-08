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
core/engine.py — LangGraph state machine, master orchestrator. CLAUDE.md Phase 1, step 5.

Generic, agent-agnostic engine: validate_input -> sanitize -> execute ->
assert_output -> (confidence/blocklist gate) -> [hitl_gate] -> emit_audit ->
emit_sop. Stateless per run — all state is JSON-serializable and checkpointed,
so a run can pause at the HITL gate and resume from exactly where it paused.

Each agent supplies its own `execute_fn` (an async callable: sanitized_input
dict -> {"output": dict, "confidence": float, "tool_calls": [str, ...],
"tokens_used": int}). This engine owns sanitization, assertion, the HITL
pause/resume lifecycle, and audit/SOP emission so no agent has to reimplement
governance — see CLAUDE.md CORE PRINCIPLES 1-3 and 8-10.
"""

import json
import logging
import os
import uuid
from typing import Any, Awaitable, Callable, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from core.assertion import requires_hitl_for_tool_calls, validate_output
from core.hitl import HITLGate
from security.sanitizer import sanitize

log = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_THRESHOLD = 0.85

ExecuteFn = Callable[[dict], Awaitable[dict]]


class EngineState(TypedDict):
    # Inputs
    workspace_id: str
    product_id: Optional[str]
    tenant_id: Optional[str]
    agent_name: str
    raw_input: dict

    # After validate_input
    input_valid: Optional[bool]

    # After sanitize
    sanitized_input: Optional[dict]
    redaction_log: Optional[list]

    # After execute
    output: Optional[dict]
    confidence: Optional[float]
    tool_calls: Optional[list]
    tokens_used: int

    # After assert_output
    assertion_passed: Optional[bool]
    hitl_required: Optional[bool]
    hitl_reason: Optional[str]

    # After hitl_gate (only set when the run actually paused there)
    incident_id: Optional[str]
    selected_option: Optional[dict]

    # After emit_sop
    sop_written: Optional[bool]

    error: Optional[str]


def _default_sop_client() -> Any:
    """Lazy service-role Supabase client, mirroring security/audit_log.py's pattern."""
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


class Engine:
    """
    Generic per-agent LangGraph engine — every agent workflow is built from this.

    Usage:
        engine = Engine(agent_name="research_agent", execute_fn=my_agent.execute, db_conn=db_conn)
        result = await engine.run(raw_input, workspace_id=..., product_id=..., tenant_id=...)
        if result["hitl_required"]:
            # result["incident_id"] identifies the pending approval; the run
            # is paused — resume it once an operator approves.
            ...
        await engine.resume(result["thread_id"], selected_option)
    """

    def __init__(
        self,
        agent_name: str,
        execute_fn: ExecuteFn,
        db_conn=None,
        audit_log: Optional[Any] = None,
        sop_client_factory: Callable[[], Any] = _default_sop_client,
        output_schema: Optional[dict] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        checkpointer: Optional[Any] = None,
    ) -> None:
        self.agent_name = agent_name
        self._execute_fn = execute_fn
        self._hitl = HITLGate(db_conn)
        self._audit_log = audit_log
        self._sop_client_factory = sop_client_factory
        self._output_schema = output_schema
        self._confidence_threshold = confidence_threshold
        # Defaults to in-memory checkpointing (fine for a single-process run/
        # resume cycle, e.g. tests). Production callers should inject an
        # AsyncPostgresSaver so a paused run survives past this process.
        self._checkpointer = checkpointer or MemorySaver()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(EngineState)

        graph.add_node("validate_input", self._validate_input_node)
        graph.add_node("sanitize", self._sanitize_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("assert_output", self._assert_output_node)
        graph.add_node("hitl_gate", self._hitl_gate_node)
        graph.add_node("emit_audit", self._emit_audit_node)
        graph.add_node("emit_sop", self._emit_sop_node)

        graph.add_edge(START, "validate_input")
        graph.add_edge("validate_input", "sanitize")
        graph.add_edge("sanitize", "execute")
        graph.add_edge("execute", "assert_output")
        graph.add_conditional_edges(
            "assert_output",
            self._route_after_assert,
            {"hitl_gate": "hitl_gate", "emit_audit": "emit_audit"},
        )
        graph.add_edge("hitl_gate", "emit_audit")
        graph.add_edge("emit_audit", "emit_sop")
        graph.add_edge("emit_sop", END)

        return graph.compile(checkpointer=self._checkpointer)

    # ──────────────────────────────────────────────
    # Nodes
    # ──────────────────────────────────────────────

    async def _validate_input_node(self, state: EngineState) -> dict:
        raw_input = state.get("raw_input")
        valid = isinstance(raw_input, dict) and bool(raw_input)
        if not valid:
            log.warning("[%s] validate_input failed: raw_input=%r", self.agent_name, raw_input)
        return {
            "input_valid": valid,
            "error": None if valid else "raw_input must be a non-empty dict",
        }

    async def _sanitize_node(self, state: EngineState) -> dict:
        if not state.get("input_valid"):
            return {"sanitized_input": {}, "redaction_log": []}

        raw_json = json.dumps(state["raw_input"])
        sanitized_text, redaction_log = sanitize(raw_json, product_id=state.get("product_id"))
        sanitized_input = json.loads(sanitized_text)

        if redaction_log:
            log.info(
                "[%s] Sanitized %d PII pattern(s) from input",
                self.agent_name, len(redaction_log),
            )

        return {"sanitized_input": sanitized_input, "redaction_log": redaction_log}

    async def _execute_node(self, state: EngineState) -> dict:
        if not state.get("input_valid"):
            return {"output": {}, "confidence": 0.0, "tool_calls": [], "tokens_used": 0}

        result = await self._execute_fn(state["sanitized_input"])

        return {
            "output": result.get("output", {}),
            "confidence": result.get("confidence", 0.0),
            "tool_calls": result.get("tool_calls", []),
            "tokens_used": state.get("tokens_used", 0) + result.get("tokens_used", 0),
        }

    async def _assert_output_node(self, state: EngineState) -> dict:
        output = state.get("output") or {}
        assertion_passed = validate_output(output, schema=self._output_schema, agent_name=self.agent_name)
        flagged = requires_hitl_for_tool_calls(state.get("tool_calls") or [])
        confidence = state.get("confidence") or 0.0

        reasons = []
        if flagged:
            reasons.append(f"blocklisted tool call(s): {flagged}")
        if confidence < self._confidence_threshold:
            reasons.append(f"confidence {confidence:.2f} below threshold {self._confidence_threshold:.2f}")
        if not assertion_passed:
            reasons.append("output failed schema validation")

        hitl_required = bool(reasons)

        return {
            "assertion_passed": assertion_passed,
            "hitl_required": hitl_required,
            "hitl_reason": "; ".join(reasons) if reasons else None,
        }

    def _route_after_assert(self, state: EngineState) -> str:
        return "hitl_gate" if state.get("hitl_required") else "emit_audit"

    async def _hitl_gate_node(self, state: EngineState) -> dict:
        """
        Persist a pending incident, then interrupt() to pause the graph.
        Governance Rule 2: no execution past this point without human approval.
        """
        incident_id = await self._hitl.create_incident(
            workspace_id=state["workspace_id"],
            agent_id=self.agent_name,
            raw_log=json.dumps(state.get("sanitized_input") or {}),
            parsed_error=state.get("hitl_reason") or "confidence below threshold",
            remediation_options=[
                {"id": "approve", "title": "Approve output", "description": "Accept the agent's output as-is."},
                {"id": "hold", "title": "Hold", "description": "Do nothing — leave for later review."},
            ],
            tokens_used=state.get("tokens_used", 0),
        )

        log.info("[%s] HITL gate — incident %s awaiting operator approval", self.agent_name, incident_id)

        selected_option = interrupt({
            "incident_id": incident_id,
            "message": "Awaiting operator approval",
            "reason": state.get("hitl_reason"),
            "output": state.get("output"),
        })

        return {"incident_id": incident_id, "selected_option": selected_option}

    async def _emit_audit_node(self, state: EngineState) -> dict:
        """Governance Rule 9: audit log entry on every agent action, win or lose."""
        # LangGraph requires every node to write at least one channel, so this
        # always re-writes tokens_used (unchanged) even on the no-op paths.
        no_op_update = {"tokens_used": state.get("tokens_used", 0)}

        if self._audit_log is None:
            return no_op_update

        outcome = (
            "hitl_approved" if state.get("incident_id")
            else "ok" if state.get("assertion_passed")
            else "assertion_failed"
        )
        try:
            self._audit_log.append(
                actor=self.agent_name,
                action="engine_run",
                resource=self.agent_name,
                outcome=outcome,
                product_id=state.get("product_id") or "unknown",
                tenant_id=state.get("tenant_id") or "unknown",
            )
        except Exception as exc:
            # No silent failures — surfaced via log, but a broken audit sink
            # must not take down the run that's already produced output.
            log.error("[%s] emit_audit failed: %s", self.agent_name, exc)
        return no_op_update

    async def _emit_sop_node(self, state: EngineState) -> dict:
        """
        Write a SOP row summarizing this run. Governance Rule 6: agents document
        themselves. Best-effort — a SOP write failure never fails the run itself.
        """
        try:
            client = self._sop_client_factory()
            client.table("sops").insert({
                "product_id": state.get("product_id"),
                "agent_name": self.agent_name,
                "task_summary": state.get("hitl_reason") or "completed",
                "content_md": f"# {self.agent_name}\n\nOutput: {json.dumps(state.get('output'))}",
            }).execute()
            return {"sop_written": True}
        except Exception as exc:
            log.warning("[%s] emit_sop failed (non-fatal): %s", self.agent_name, exc)
            return {"sop_written": False}

    # ──────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────

    async def run(
        self,
        raw_input: dict,
        workspace_id: str,
        product_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> dict:
        """Run the graph to completion, or to the HITL pause point."""
        initial_state: EngineState = {
            "workspace_id": workspace_id,
            "product_id": product_id,
            "tenant_id": tenant_id,
            "agent_name": self.agent_name,
            "raw_input": raw_input,
            "input_valid": None,
            "sanitized_input": None,
            "redaction_log": None,
            "output": None,
            "confidence": None,
            "tool_calls": None,
            "tokens_used": 0,
            "assertion_passed": None,
            "hitl_required": None,
            "hitl_reason": None,
            "incident_id": None,
            "selected_option": None,
            "sop_written": None,
            "error": None,
        }

        thread_id = thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        result = await self._graph.ainvoke(initial_state, config=config)
        result = {**result, **self._extract_interrupt(config)}
        result["thread_id"] = thread_id
        return result

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume a run paused at the HITL gate with the operator's chosen option."""
        config = {"configurable": {"thread_id": thread_id}}
        result = await self._graph.ainvoke(Command(resume=selected_option), config=config)
        result["thread_id"] = thread_id
        return result

    def _extract_interrupt(self, config: dict) -> dict:
        """
        When the graph pauses at interrupt(), ainvoke()'s return value does not
        include that node's own (never-returned) state update. Pull the payload
        passed to interrupt() back out of the checkpoint so callers still see
        incident_id / hitl_required without a second round trip.
        """
        for task in (self._graph.get_state(config).tasks or []):
            if getattr(task, "interrupts", None):
                return {**task.interrupts[0].value, "hitl_required": True}
        return {}
