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
Agent 05 — IAM Policy Minimization
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

Trigger:
  - Manual: POST /agents/agent_05_iam_minimizer/run  (submit policy JSON or principal ID)
  - Scheduled: nightly CloudTrail/Activity Log sweep (coming Phase 7)

Supported clouds: AWS, Azure, GCP
"""

import json
import logging
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_05_iam_minimizer.tools import IAMMinimizeTools, _summarize_permissions
from core.security import shield

log = logging.getLogger(__name__)

# Maximum characters of access log / policy to send to LLM
_MAX_POLICY_CHARS   = 8_000
_MAX_LOG_CHARS      = 6_000


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class IAMMinimizeState(TypedDict):
    # Inputs
    workspace_id: str
    cloud_provider: str        # "aws" | "azure" | "gcp"
    webhook_payload: dict

    # Extracted by ingest
    principal_id: str          # ARN (AWS), object ID (Azure), or member string (GCP)
    principal_type: str        # "role" | "user" | "service_account" | "group"
    principal_name: str        # human-readable name
    resource_scope: str        # policy ARN, subscription ID, or GCP project
    current_policy_summary: str   # flattened permission list for LLM
    access_log_summary: str    # last-30-days used permissions (from CloudTrail or Activity Log)
    repository: str            # optional: "owner/repo" for PR option

    # After diagnose
    incident_id: Optional[str]
    parsed_error: Optional[str]       # risk headline
    minimized_policy: Optional[dict]  # the new minimized policy document
    minimized_policy_str: Optional[str]  # JSON string of minimized_policy
    permissions_removed: Optional[list[str]]  # actions that were stripped
    permissions_kept: Optional[list[str]]     # actions that were retained
    risk_score: Optional[str]          # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    remediation_options: Optional[list]
    estimated_duration_seconds: Optional[int]
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

def _detect_principal_type(payload: dict, cloud: str) -> str:
    t = payload.get("principal_type", "").lower()
    if t:
        return t
    if cloud == "aws":
        arn = payload.get("principal_id", "")
        if ":role/" in arn:
            return "role"
        if ":user/" in arn:
            return "user"
        return "role"
    if cloud == "azure":
        return payload.get("principal_type", "service_principal").lower()
    if cloud in ("gcp", "google"):
        member = payload.get("principal_id", "")
        if member.startswith("serviceAccount:"):
            return "service_account"
        if member.startswith("group:"):
            return "group"
        return "user"
    return "unknown"


def _build_access_log_summary(access_log: list | str, max_chars: int = _MAX_LOG_CHARS) -> str:
    """
    Normalize the access log into a single text block.
    Accepts either a list of API call dicts or a raw string.
    Truncates to max_chars.
    """
    if isinstance(access_log, list):
        lines = []
        for entry in access_log:
            if isinstance(entry, dict):
                action = entry.get("action") or entry.get("eventName") or entry.get("operationName", "")
                ts     = entry.get("eventTime") or entry.get("time") or entry.get("timestamp", "")
                lines.append(f"{ts}: {action}")
            else:
                lines.append(str(entry))
        text = "\n".join(lines)
    else:
        text = str(access_log)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated]"
    return text


# ──────────────────────────────────────────────
# Workflow class
# ──────────────────────────────────────────────

class IAMMinimizeWorkflow(BaseAgent):
    """
    Agent 05: IAM Policy Minimization.

    Usage:
        workflow = IAMMinimizeWorkflow(db_conn, workspace_id, checkpointer)
        incident_id = await workflow.run({
            "principal_id": "arn:aws:iam::123456789012:role/AppRole",
            "current_policy": { <IAM policy document dict> },
            "access_log": [ <list of API call dicts from CloudTrail> ],
            "repository": "acme/infra",  # optional, for PR option
        }, cloud_provider="aws")
        await workflow.resume(thread_id, selected_option)
    """

    AGENT_ID = "agent_05_iam_minimizer"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer = checkpointer
        self._tools = IAMMinimizeTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(IAMMinimizeState)

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

    async def _ingest_node(self, state: IAMMinimizeState) -> dict:
        """
        Extract and normalize IAM principal + policy data from the payload.
        Sanitizes both the policy document and access log before LLM consumption.
        """
        payload      = state["webhook_payload"]
        cloud        = state["cloud_provider"]

        principal_id   = payload.get("principal_id", "")
        principal_name = payload.get("principal_name", principal_id.split("/")[-1] if "/" in principal_id else principal_id)
        principal_type = _detect_principal_type(payload, cloud)
        resource_scope = payload.get("resource_scope") or payload.get("policy_arn") or payload.get("subscription_id") or payload.get("project", "")
        repository     = payload.get("repository", "")

        # Current policy: accept dict or JSON string
        raw_policy = payload.get("current_policy", {})
        if isinstance(raw_policy, str):
            try:
                raw_policy = json.loads(raw_policy)
            except (json.JSONDecodeError, ValueError):
                raw_policy = {}

        # Flatten permissions for LLM summary
        if cloud == "aws":
            permission_list = _summarize_permissions(raw_policy)
            policy_text = json.dumps(raw_policy, indent=2)
        else:
            policy_text = json.dumps(raw_policy, indent=2)
            permission_list = []

        if len(policy_text) > _MAX_POLICY_CHARS:
            policy_text = policy_text[:_MAX_POLICY_CHARS] + "\n... [truncated]"

        # Sanitize policy (may contain resource ARNs with account IDs — keep those, just strip secrets)
        sanitized_policy = shield.sanitize(policy_text, context=self.agent_id)

        # Access log: normalize and truncate
        raw_log = payload.get("access_log", [])
        log_summary = _build_access_log_summary(raw_log)
        sanitized_log = shield.sanitize(log_summary, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent05] Ingested: cloud=%s principal=%s type=%s permissions=%d",
            cloud, principal_id[:60], principal_type, len(permission_list),
        )

        return {
            "principal_id": principal_id,
            "principal_type": principal_type,
            "principal_name": principal_name,
            "resource_scope": resource_scope,
            "current_policy_summary": sanitized_policy.sanitized_text,
            "access_log_summary": sanitized_log.sanitized_text,
            "repository": repository,
            "tokens_used": 0,
            "incident_id": None,
            "parsed_error": None,
            "minimized_policy": None,
            "minimized_policy_str": None,
            "permissions_removed": None,
            "permissions_kept": None,
            "risk_score": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

    async def _diagnose_node(self, state: IAMMinimizeState) -> dict:
        """
        Call LLM to analyze over-permissions and produce a minimized policy.
        The LLM compares granted permissions against the access log to identify
        unused actions and generates a least-privilege replacement policy.
        """
        cloud          = state["cloud_provider"]
        principal_id   = state["principal_id"]
        principal_name = state["principal_name"]
        principal_type = state["principal_type"]

        user_message = (
            f"IAM Minimization Request:\n\n"
            f"Cloud: {cloud.upper()}\n"
            f"Principal Type: {principal_type}\n"
            f"Principal ID: {principal_id}\n"
            f"Principal Name: {principal_name}\n"
            f"Resource Scope: {state['resource_scope']}\n\n"
            f"Current Policy:\n```json\n{state['current_policy_summary']}\n```\n\n"
            f"Access Log (last 30 days of actual API calls):\n"
            f"```\n{state['access_log_summary']}\n```\n\n"
            f"Analyze the gap between granted permissions and observed usage. "
            f"Return the minimized policy and risk assessment in the JSON format specified."
        )

        await self.check_budget(estimated_tokens=6000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="iam_minimization",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="iam_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {"error": str(exc), "tokens_used": estimated_tokens}

        parsed_error       = diagnosis.get("parsed_error", "IAM over-permission analysis complete")
        minimized_policy   = diagnosis.get("minimized_policy", {})
        permissions_removed = diagnosis.get("permissions_removed", [])
        permissions_kept   = diagnosis.get("permissions_kept", [])
        risk_score         = diagnosis.get("risk_score", "MEDIUM")
        options            = diagnosis.get("options", [])
        duration           = diagnosis.get("estimated_duration_seconds", 60)

        minimized_policy_str = json.dumps(minimized_policy, indent=2) if minimized_policy else ""

        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent05] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info(
            "[Agent05] Analysis: %s | risk=%s removed=%d kept=%d",
            parsed_error[:80], risk_score, len(permissions_removed), len(permissions_kept),
        )

        return {
            "parsed_error": parsed_error,
            "minimized_policy": minimized_policy,
            "minimized_policy_str": minimized_policy_str,
            "permissions_removed": permissions_removed,
            "permissions_kept": permissions_kept,
            "risk_score": risk_score,
            "remediation_options": options,
            "estimated_duration_seconds": duration,
            "tokens_used": state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: IAMMinimizeState) -> dict:
        """
        Save incident and pause for operator approval.
        Governance Rule 11: No autonomous IAM changes.
        """
        if state.get("error"):
            log.error("[Agent05] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

        # Construct a raw_log string that surfaces key risk info to the operator
        raw_log = (
            f"Principal: {state['principal_id']}\n"
            f"Risk Score: {state.get('risk_score', 'UNKNOWN')}\n"
            f"Permissions to Remove: {len(state.get('permissions_removed') or [])}\n"
            f"Permissions to Keep: {len(state.get('permissions_kept') or [])}\n\n"
            f"Current Policy (excerpt):\n{state['current_policy_summary'][:500]}"
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
        log.info("[Agent05] HITL gate — incident %s awaiting operator approval (risk=%s)", incident_id, state.get("risk_score"))

        selected_option = interrupt({
            "incident_id": incident_id,
            "message": "Awaiting operator approval",
            "options": state["remediation_options"],
            "risk_score": state.get("risk_score"),
            "permissions_removed_count": len(state.get("permissions_removed") or []),
        })

        return {
            "incident_id": incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: IAMMinimizeState) -> dict:
        """Execute the approved IAM remediation action."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent05] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        cloud     = state["cloud_provider"]
        log.info("[Agent05] Executing approved option: %s (cloud=%s)", option_id, cloud)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        owner, _, repo = state.get("repository", "/").partition("/")

        pr_title = (
            f"security(iam): minimize {state['principal_type']} "
            f"'{state['principal_name']}' — remove {len(state.get('permissions_removed') or [])} permissions"
        )
        pr_body = _build_pr_body(
            principal_id=state["principal_id"],
            principal_name=state["principal_name"],
            risk_score=state.get("risk_score", "UNKNOWN"),
            permissions_removed=state.get("permissions_removed") or [],
            permissions_kept=state.get("permissions_kept") or [],
            cloud=cloud,
        )

        policy_file_path = (
            f"iam/{state['principal_name'].replace('/', '_')}_minimized.json"
            if not repo
            else f"iam/policies/{state['principal_name'].replace('/', '_')}_minimized.json"
        )

        context = {
            "cloud_provider": cloud,
            "policy_arn": state.get("resource_scope", ""),
            "subscription_id": state.get("resource_scope", ""),
            "principal_id": state["principal_id"],
            "role_definition_id": state.get("minimized_policy", {}).get("roleDefinitionId", ""),
            "scope": f"/subscriptions/{state.get('resource_scope', '')}",
            "resource": state.get("resource_scope", ""),
            "resource_type": "projects",
            "minimized_policy": state.get("minimized_policy", {}),
            "minimized_policy_str": state.get("minimized_policy_str", "{}"),
            "owner": owner,
            "repo": repo,
            "file_path": policy_file_path,
            "pr_title": pr_title,
            "pr_body": pr_body,
            "base_branch": "main",
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: IAMMinimizeState) -> dict:
        """Mark incident as executed and close the audit trail."""
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
        log.info("[Agent05] Workflow complete for incident %s", incident_id)
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
        """
        Trigger the IAM minimization workflow.
        Returns incident_id after the HITL gate pause.
        """
        import uuid

        initial_state: IAMMinimizeState = {
            "workspace_id": self.workspace_id,
            "cloud_provider": cloud_provider,
            "webhook_payload": payload,
            "principal_id": "",
            "principal_type": "",
            "principal_name": "",
            "resource_scope": "",
            "current_policy_summary": "",
            "access_log_summary": "",
            "repository": "",
            "incident_id": None,
            "parsed_error": None,
            "minimized_policy": None,
            "minimized_policy_str": None,
            "permissions_removed": None,
            "permissions_kept": None,
            "risk_score": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "tokens_used": 0,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent05] Starting IAM minimization workflow — thread_id=%s", thread_id)

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

        log.info("[Agent05] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info(
            "[Agent05] Resuming thread=%s with option=%s",
            thread_id, selected_option.get("id"),
        )
        result = await self._graph.ainvoke(
            Command(resume=selected_option),
            config=config,
        )
        return result.get("execution_result", {"status": "completed"})


# ──────────────────────────────────────────────
# PR body formatter
# ──────────────────────────────────────────────

def _build_pr_body(
    principal_id: str,
    principal_name: str,
    risk_score: str,
    permissions_removed: list[str],
    permissions_kept: list[str],
    cloud: str,
) -> str:
    removed_block = "\n".join(f"- `{p}`" for p in permissions_removed[:30])
    if len(permissions_removed) > 30:
        removed_block += f"\n- ... and {len(permissions_removed) - 30} more"

    kept_block = "\n".join(f"- `{p}`" for p in permissions_kept[:20])
    if len(permissions_kept) > 20:
        kept_block += f"\n- ... and {len(permissions_kept) - 20} more"

    return (
        f"## Cloud Decoded — IAM Minimization ({cloud.upper()})\n\n"
        f"**Principal:** `{principal_id}`  \n"
        f"**Risk Score:** {risk_score}\n\n"
        f"### Permissions Removed ({len(permissions_removed)})\n\n"
        f"{removed_block or '_None_'}\n\n"
        f"### Permissions Kept ({len(permissions_kept)})\n\n"
        f"{kept_block or '_None_'}\n\n"
        f"---\n"
        f"*Generated by Cloud Decoded Agent 05. Review and validate before merging.*"
    )
