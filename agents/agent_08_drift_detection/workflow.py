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
Agent 08 — Drift Detection & Auto-Correction
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

The LLM compares desired state (from IaC/Git) against actual live infrastructure
state, identifies all drift items with severity, generates corrected content, and
presents the operator with remediation options before any change is applied.

Trigger: Manual via POST /agents/agent_08_drift_detection/run, or invoked by a
scheduled CI drift-detection job that supplies pre-fetched state snapshots.
"""

import json
import logging
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_08_drift_detection.tools import DriftTools
from core.security import shield

log = logging.getLogger(__name__)

_MAX_STATE_CHARS   = 6_000   # per state blob sent to LLM
_MAX_SUMMARY_CHARS = 3_000


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class DriftState(TypedDict):
    # Inputs
    workspace_id: str
    cloud_provider: str
    webhook_payload: dict

    # Extracted by ingest
    drift_source: str        # terraform | kubernetes | cloudformation | generic
    resource_type: str       # aws_security_group | Deployment | AWS::EC2::SG | etc.
    resource_id: str         # resource name, ARN, or namespace/name
    scope: str               # namespace, region, or account
    repository: str          # "owner/repo" for PR/issue creation
    file_path: str           # path to IaC/manifest file for PR commits
    desired_state_text: str  # sanitized desired state (from IaC/Git)
    actual_state_text: str   # sanitized actual state (live infrastructure)

    # After diagnose
    incident_id: Optional[str]
    parsed_error: Optional[str]
    drift_items: Optional[list]
    drift_count: Optional[int]
    drift_severity: Optional[str]
    drift_summary: Optional[str]
    corrected_content: Optional[str]
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

_DRIFT_SOURCE_KEYS = {
    "terraform":        ("terraform_state", "tfstate", "terraform_plan", "terraform_config"),
    "kubernetes":       ("k8s_manifest", "kubernetes_manifest", "manifest", "k8s_live_resource"),
    "cloudformation":   ("cfn_template", "cloudformation_template", "cfn_stack"),
}


def _detect_drift_source(payload: dict) -> str:
    """
    Infer drift source from payload keys.
    Explicit drift_source field takes priority over key-based detection.
    Returns: terraform | kubernetes | cloudformation | generic
    """
    explicit = payload.get("drift_source", "").lower()
    if explicit in ("terraform", "kubernetes", "cloudformation"):
        return explicit
    for source, keys in _DRIFT_SOURCE_KEYS.items():
        if any(k in payload for k in keys):
            return source
    return "generic"


def _normalize_state_text(raw, max_chars: int = _MAX_STATE_CHARS) -> str:
    """
    Convert raw state (dict, list, or string) to a text representation
    suitable for LLM consumption. Truncates at max_chars.
    """
    if raw is None:
        return ""
    if isinstance(raw, (dict, list)):
        try:
            text = json.dumps(raw, indent=2)
        except (TypeError, ValueError):
            text = str(raw)
    else:
        text = str(raw)

    if len(text) > max_chars:
        return text[:max_chars] + "\n... [truncated]"
    return text


# ──────────────────────────────────────────────
# Workflow class
# ──────────────────────────────────────────────

class DriftWorkflow(BaseAgent):
    """
    Agent 08: Drift Detection & Auto-Correction.

    Usage:
        workflow = DriftWorkflow(db_conn, workspace_id, checkpointer)
        incident_id = await workflow.run({
            "resource_type": "aws_security_group",
            "resource_id": "sg-abc123",
            "scope": "us-east-1",
            "repository": "acme/infra",
            "file_path": "terraform/security_groups.tf",
            "desired_state": { <terraform state JSON or HCL content> },
            "actual_state":  { <live AWS describe-security-groups output> },
        }, cloud_provider="aws")
        await workflow.resume(thread_id, selected_option)
    """

    AGENT_ID = "agent_08_drift_detection"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer    = checkpointer
        self._tools           = DriftTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph           = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(DriftState)

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

    async def _ingest_node(self, state: DriftState) -> dict:
        """
        Normalize payload, detect drift source, sanitize state blobs for LLM.
        """
        payload = state["webhook_payload"]

        drift_source  = _detect_drift_source(payload)
        resource_type = payload.get("resource_type", "unknown")
        resource_id   = payload.get("resource_id", payload.get("resource_name", "unknown"))
        scope         = payload.get("scope", payload.get("namespace", payload.get("region", "")))
        repository    = payload.get("repository", "")
        file_path     = payload.get("file_path", "")

        # Desired state — try several key aliases
        desired_raw = (
            payload.get("desired_state")
            or payload.get("terraform_state")
            or payload.get("terraform_config")
            or payload.get("k8s_manifest")
            or payload.get("cfn_template")
            or {}
        )

        # Actual (live) state
        actual_raw = (
            payload.get("actual_state")
            or payload.get("live_state")
            or payload.get("k8s_live_resource")
            or payload.get("cfn_stack")
            or {}
        )

        desired_text = _normalize_state_text(desired_raw)
        actual_text  = _normalize_state_text(actual_raw)

        sanitized_desired = shield.sanitize(desired_text, context=self.agent_id)
        sanitized_actual  = shield.sanitize(actual_text,  context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent08] Ingested drift check: source=%s resource=%s/%s scope=%s",
            drift_source, resource_type, resource_id, scope,
        )

        return {
            "drift_source":       drift_source,
            "resource_type":      resource_type,
            "resource_id":        resource_id,
            "scope":              scope,
            "repository":         repository,
            "file_path":          file_path,
            "desired_state_text": sanitized_desired.sanitized_text,
            "actual_state_text":  sanitized_actual.sanitized_text,
            "tokens_used":        0,
            "incident_id":        None,
            "parsed_error":       None,
            "drift_items":        None,
            "drift_count":        None,
            "drift_severity":     None,
            "drift_summary":      None,
            "corrected_content":  None,
            "remediation_options": None,
            "selected_option":    None,
            "execution_result":   None,
            "error":              None,
        }

    async def _diagnose_node(self, state: DriftState) -> dict:
        """
        LLM compares desired vs actual state, identifies drift items,
        classifies severity, and generates corrected content for the PR/apply path.
        """
        user_message = (
            f"Drift Detection Analysis:\n\n"
            f"Source: {state['drift_source']}\n"
            f"Resource Type: {state['resource_type']}\n"
            f"Resource ID: {state['resource_id']}\n"
            f"Scope: {state['scope'] or 'not specified'}\n\n"
            f"## Desired State (from IaC / Git)\n\n"
            f"{state['desired_state_text'] or '(no desired state provided)'}\n\n"
            f"## Actual State (live infrastructure)\n\n"
            f"{state['actual_state_text'] or '(no actual state provided)'}\n\n"
            f"Compare the two states, identify all drift items, classify overall severity, "
            f"and produce corrected content that would restore the resource to its desired state. "
            f"Return exactly the JSON format specified in the system prompt."
        )

        await self.check_budget(estimated_tokens=5000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="drift_detection",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="drift_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {"error": str(exc), "tokens_used": estimated_tokens}

        parsed_error      = diagnosis.get("parsed_error", f"Drift detected in {state['resource_id']}")
        drift_items       = diagnosis.get("drift_items", [])
        drift_severity    = diagnosis.get("drift_severity", "LOW")
        drift_summary     = diagnosis.get("drift_summary", "")
        corrected_content = diagnosis.get("corrected_content", "")
        options           = diagnosis.get("options", [])

        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent08] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info(
            "[Agent08] Drift: %d items, severity=%s | %s",
            len(drift_items), drift_severity, parsed_error[:80],
        )

        return {
            "parsed_error":      parsed_error,
            "drift_items":       drift_items,
            "drift_count":       len(drift_items),
            "drift_severity":    drift_severity,
            "drift_summary":     drift_summary,
            "corrected_content": corrected_content,
            "remediation_options": options,
            "tokens_used":       state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: DriftState) -> dict:
        """
        Save incident and pause for operator approval.
        Governance Rule 11: No autonomous infrastructure correction.
        """
        if state.get("error"):
            log.error("[Agent08] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

        drift_items = state.get("drift_items") or []

        top_items_text = "\n".join(
            f"  - {d.get('key', '?')}: "
            f"desired={str(d.get('desired_value', '?'))[:50]} | "
            f"actual={str(d.get('actual_value', '?'))[:50]} "
            f"[{d.get('severity', '?')}]"
            for d in drift_items[:5]
        )

        raw_log = (
            f"Drift Detection: {state['drift_source']} / {state['resource_type']}\n"
            f"Resource: {state['resource_id']}\n"
            f"Scope: {state['scope'] or 'not specified'}\n"
            f"Overall Severity: {state.get('drift_severity', 'UNKNOWN')}\n"
            f"Drift Items: {len(drift_items)}\n\n"
            f"Summary:\n{state.get('drift_summary', '')[:400]}\n\n"
            f"Top Drift Items:\n{top_items_text}"
        )

        incident_id = await self.hitl.create_incident(
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            raw_log=raw_log,
            parsed_error=state["parsed_error"],
            remediation_options=state["remediation_options"],
            cloud_provider=state["cloud_provider"],
            tokens_used=state.get("tokens_used", 0),
        )

        await self.record_token_usage(
            tokens_used=state.get("tokens_used", 0),
            incident_id=incident_id,
        )

        self._write_audit("hitl_gate", "pending_approval", incident_id=incident_id)
        log.info(
            "[Agent08] HITL gate — incident %s | resource=%s/%s severity=%s items=%d",
            incident_id, state["drift_source"], state["resource_id"],
            state.get("drift_severity"), len(drift_items),
        )

        selected_option = interrupt({
            "incident_id":   incident_id,
            "message":       "Awaiting operator approval for drift correction",
            "options":       state["remediation_options"],
            "drift_severity": state.get("drift_severity"),
            "drift_count":   state.get("drift_count", 0),
        })

        return {
            "incident_id":    incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: DriftState) -> dict:
        """Execute the approved drift correction action."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent08] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        log.info("[Agent08] Executing approved option: %s", option_id)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        owner, _, repo = state.get("repository", "/").partition("/")

        report_body = _build_drift_report(
            drift_source=state["drift_source"],
            resource_type=state["resource_type"],
            resource_id=state["resource_id"],
            scope=state["scope"],
            drift_severity=state.get("drift_severity", "UNKNOWN"),
            drift_summary=state.get("drift_summary", ""),
            drift_items=state.get("drift_items") or [],
        )

        context = {
            "drift_source":      state["drift_source"],
            "resource_id":       state["resource_id"],
            "resource_type":     state["resource_type"],
            "scope":             state["scope"],
            "namespace":         state["scope"],
            "owner":             owner,
            "repo":              repo,
            "file_path":         state.get("file_path", ""),
            "corrected_content": state.get("corrected_content", ""),
            "drift_summary":     state.get("drift_summary", ""),
            "report_body":       report_body,
            "issue_title":       f"Drift detected: {state['drift_source']}/{state['resource_id']}",
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: DriftState) -> dict:
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
        log.info("[Agent08] Workflow complete for incident %s", incident_id)
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
        """Trigger the drift detection workflow. Returns incident_id after HITL gate pause."""
        import uuid

        initial_state: DriftState = {
            "workspace_id":      self.workspace_id,
            "cloud_provider":    cloud_provider,
            "webhook_payload":   payload,
            "drift_source":      "",
            "resource_type":     "",
            "resource_id":       "",
            "scope":             "",
            "repository":        "",
            "file_path":         "",
            "desired_state_text": "",
            "actual_state_text": "",
            "incident_id":       None,
            "parsed_error":      None,
            "drift_items":       None,
            "drift_count":       None,
            "drift_severity":    None,
            "drift_summary":     None,
            "corrected_content": None,
            "remediation_options": None,
            "tokens_used":       0,
            "selected_option":   None,
            "execution_result":  None,
            "error":             None,
        }

        thread_id = str(uuid.uuid4())
        config    = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent08] Starting drift detection — thread_id=%s", thread_id)

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

        log.info("[Agent08] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info("[Agent08] Resuming thread=%s with option=%s", thread_id, selected_option.get("id"))
        result = await self._graph.ainvoke(Command(resume=selected_option), config=config)
        return result.get("execution_result", {"status": "completed"})


# ──────────────────────────────────────────────
# Report builder
# ──────────────────────────────────────────────

def _build_drift_report(
    drift_source: str,
    resource_type: str,
    resource_id: str,
    scope: str,
    drift_severity: str,
    drift_summary: str,
    drift_items: list,
) -> str:
    severity_icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(drift_severity, "⚪")

    items_rows = "\n".join(
        f"| `{d.get('key', '?')}` | `{str(d.get('desired_value', '?'))[:60]}` | "
        f"`{str(d.get('actual_value', '?'))[:60]}` | {d.get('severity', '?')} |"
        for d in drift_items
    ) or "_(no items)_"

    return (
        f"## Cloud Decoded — Drift Detection Report\n\n"
        f"**Source:** {drift_source}  \n"
        f"**Resource:** `{resource_type}` / `{resource_id}`  \n"
        f"**Scope:** {scope or '_not specified_'}  \n"
        f"**Severity:** {severity_icon} {drift_severity}  \n"
        f"**Drift Items:** {len(drift_items)}\n\n"
        f"### Summary\n\n"
        f"{drift_summary or '_Not available_'}\n\n"
        f"### Drift Items\n\n"
        f"| Key | Desired Value | Actual Value | Severity |\n"
        f"|-----|---------------|--------------|----------|\n"
        f"{items_rows}\n\n"
        f"---\n"
        f"*Generated by Cloud Decoded Agent 08. Review all changes before merging.*"
    )
