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
Agent 02 — Kubernetes Alert Fatigue & Remediation
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

Supports two webhook payload formats:
  - Prometheus AlertManager (most common)
  - Azure Monitor Common Alert Schema (AKS)
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_02_k8s_alert.tools import K8sTools
from core.security import shield

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class K8sAlertState(TypedDict):
    # Inputs
    workspace_id: str
    cloud_provider: str          # "azure" | "aws" | "gcp"
    webhook_payload: dict

    # Extracted by ingest
    namespace: str
    pod_name: str
    deployment_name: str
    cluster_name: str
    container_name: str
    exit_code: int               # 137=OOMKilled, 1=application error, 2=misuse
    restart_count: int
    alert_type: str              # "CrashLoopBackOff" | "OOMKilled" | "ImagePullBackOff" | "Evicted"
    current_memory_limit: str   # e.g. "512Mi" or "unknown"
    current_cpu_limit: str      # e.g. "500m" or "unknown"
    log_excerpt: str

    # After diagnose
    incident_id: Optional[str]
    parsed_error: Optional[str]
    remediation_options: Optional[list]
    estimated_duration_seconds: Optional[int]
    tokens_used: int

    # After HITL approval
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
# Workflow class
# ──────────────────────────────────────────────

class K8sAlertWorkflow(BaseAgent):
    """
    Agent 02: Kubernetes Alert Fatigue & Remediation.

    Usage:
        workflow = K8sAlertWorkflow(db_conn, workspace_id, checkpointer)
        incident_id = await workflow.run(webhook_payload)
        await workflow.resume(incident_id, selected_option)
    """

    AGENT_ID = "agent_02_k8s_alert"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer = checkpointer
        self._tools = K8sTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(K8sAlertState)

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

    async def _ingest_node(self, state: K8sAlertState) -> dict:
        """
        Parse webhook payload into structured K8s alert fields.
        Supports Prometheus AlertManager and Azure Monitor Common Alert Schema.
        """
        payload = state["webhook_payload"]

        namespace = "unknown"
        pod_name = "unknown"
        deployment_name = "unknown"
        cluster_name = "unknown"
        container_name = "unknown"
        exit_code = 0
        restart_count = 0
        alert_type = "CrashLoopBackOff"
        current_memory_limit = "unknown"
        current_cpu_limit = "unknown"

        # ── Prometheus AlertManager format ──
        if "alerts" in payload:
            alerts = payload["alerts"]
            alert = alerts[0] if alerts else {}
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})

            namespace = labels.get("namespace", "unknown")
            pod_name = labels.get("pod", "unknown")
            container_name = labels.get("container", labels.get("pod", "unknown"))
            cluster_name = labels.get("cluster", labels.get("cluster_name", "unknown"))
            alert_type = labels.get("reason", labels.get("alertname", "CrashLoopBackOff"))

            # Derive deployment name by stripping the ReplicaSet hash + pod hash suffix
            parts = pod_name.rsplit("-", 2)
            deployment_name = parts[0] if len(parts) == 3 else pod_name

            description = annotations.get("description", "")
            log_lines = [
                f"Alert: {labels.get('alertname', 'K8s Alert')}",
                f"Cluster: {cluster_name}",
                f"Namespace: {namespace}",
                f"Pod: {pod_name}",
                f"Container: {container_name}",
                f"Reason: {alert_type}",
                f"Description: {description[:300]}",
            ]

        # ── Azure Monitor Common Alert Schema ──
        elif "data" in payload:
            data = payload["data"]
            essentials = data.get("essentials", {})
            alert_context = data.get("alertContext", {})
            custom_props = data.get("customProperties", {})

            namespace = custom_props.get("namespace", "unknown")
            deployment_name = custom_props.get("deployment_name", "unknown")
            cluster_name = custom_props.get("cluster_name", "unknown")

            # Extract from search results table
            tables = alert_context.get("SearchResults", {}).get("tables", [])
            if tables and tables[0].get("rows"):
                row = tables[0]["rows"][0]
                columns = [c["name"] for c in tables[0].get("columns", [])]
                row_dict = dict(zip(columns, row))
                pod_name = row_dict.get("PodName", "unknown")
                namespace = row_dict.get("Namespace", namespace)
                alert_type = row_dict.get("Reason", "CrashLoopBackOff")
                exit_code = int(row_dict.get("ExitCode", 0))
                restart_count = int(row_dict.get("RestartCount", 0))

                # Override deployment_name from pod_name if not in custom_props
                if deployment_name == "unknown" and pod_name != "unknown":
                    parts = pod_name.rsplit("-", 2)
                    deployment_name = parts[0] if len(parts) == 3 else pod_name

            container_name = custom_props.get("container_name", deployment_name)

            log_lines = [
                f"Alert Rule: {essentials.get('alertRule', 'K8s Alert')}",
                f"Severity: {essentials.get('severity', 'unknown')}",
                f"Cluster: {cluster_name}",
                f"Namespace: {namespace}",
                f"Pod: {pod_name}",
                f"Reason: {alert_type}",
                f"Exit Code: {exit_code}",
                f"Restart Count: {restart_count}",
            ]

        else:
            # Unknown format — best-effort extraction
            log.warning("[Agent02] Unknown alert payload format — using raw excerpt")
            log_lines = [f"Alert payload: {json.dumps(payload)[:500]}"]

        log_excerpt = "\n".join(log_lines)
        sanitized = shield.sanitize(log_excerpt, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent02] Ingested: type=%s pod=%s ns=%s cluster=%s",
            alert_type, pod_name, namespace, cluster_name,
        )

        return {
            "namespace": namespace,
            "pod_name": pod_name,
            "deployment_name": deployment_name,
            "cluster_name": cluster_name,
            "container_name": container_name,
            "exit_code": exit_code,
            "restart_count": restart_count,
            "alert_type": alert_type,
            "current_memory_limit": current_memory_limit,
            "current_cpu_limit": current_cpu_limit,
            "log_excerpt": sanitized.sanitized_text,
            "tokens_used": 0,
            "incident_id": None,
            "parsed_error": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

    async def _diagnose_node(self, state: K8sAlertState) -> dict:
        """Call LLM via router to diagnose the K8s alert. Parse JSON response."""
        user_message = (
            f"Kubernetes Alert Report:\n\n"
            f"Cloud Provider: {state['cloud_provider']}\n"
            f"Cluster: {state['cluster_name']}\n"
            f"Namespace: {state['namespace']}\n"
            f"Deployment: {state['deployment_name']}\n"
            f"Pod: {state['pod_name']}\n"
            f"Container: {state['container_name']}\n"
            f"Alert Type: {state['alert_type']}\n"
            f"Exit Code: {state['exit_code']}\n"
            f"Restart Count: {state['restart_count']}\n"
            f"Current Memory Limit: {state['current_memory_limit']}\n"
            f"Current CPU Limit: {state['current_cpu_limit']}\n\n"
            f"Log Excerpt:\n{state['log_excerpt']}\n\n"
            f"Diagnose this alert and return exactly the JSON format specified."
        )

        await self.check_budget(estimated_tokens=3000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="k8s_triage",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="k8s_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {"error": str(exc), "tokens_used": estimated_tokens}

        parsed_error = diagnosis.get("parsed_error", "Unknown K8s alert")
        options = diagnosis.get("options", [])
        duration = diagnosis.get("estimated_duration_seconds", 120)

        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent02] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info("[Agent02] Diagnosed: %s (options=%d)", parsed_error[:80], len(options))

        return {
            "parsed_error": parsed_error,
            "remediation_options": options,
            "estimated_duration_seconds": duration,
            "tokens_used": state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: K8sAlertState) -> dict:
        """
        Save incident to DB, then interrupt() to pause the graph.
        Governance Rule 11: No autonomous remediation.
        """
        if state.get("error"):
            log.error("[Agent02] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

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

        await self.record_token_usage(
            tokens_used=state.get("tokens_used", 0),
            incident_id=incident_id,
        )

        self._write_audit("hitl_gate", "pending_approval", incident_id=incident_id)
        log.info("[Agent02] HITL gate — incident %s awaiting operator approval", incident_id)

        selected_option = interrupt({
            "incident_id": incident_id,
            "message": "Awaiting operator approval",
            "options": state["remediation_options"],
        })

        return {
            "incident_id": incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: K8sAlertState) -> dict:
        """Execute the approved remediation option. Only reached after human approval."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent02] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        log.info("[Agent02] Executing approved option: %s", option_id)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        context = {
            "namespace": state["namespace"],
            "deployment_name": state["deployment_name"],
            "container_name": state["container_name"],
            "cluster_name": state["cluster_name"],
            "cloud_provider": state["cloud_provider"],
            # Sensible defaults for post-approval execution
            "new_memory_limit": "1Gi",
            "hpa_min": 2,
            "hpa_max": 10,
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: K8sAlertState) -> dict:
        """Mark incident as executed and finalize audit trail."""
        incident_id = state.get("incident_id")
        if incident_id:
            exec_result = state.get("execution_result") or {}
            exec_status = exec_result.get("status", "unknown")

            if exec_status == "held":
                await self.hitl._db.execute(
                    "UPDATE incidents SET execution_status = 'held' WHERE id = $1",
                    __import__("uuid").UUID(incident_id),
                )
            else:
                await self.hitl.mark_executed(incident_id, tokens_used=0)

        self._write_audit("complete", "done", incident_id=incident_id)
        log.info("[Agent02] Workflow complete for incident %s", incident_id)
        return {}

    # ──────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────

    async def run(
        self,
        payload: dict,
        cloud_provider: str = "azure",
        byok_encrypted_key: Optional[str] = None,
    ) -> str:
        """
        Trigger the K8s alert workflow from a webhook payload.
        Returns incident_id after the HITL gate pause.
        """
        import uuid

        initial_state: K8sAlertState = {
            "workspace_id": self.workspace_id,
            "cloud_provider": cloud_provider,
            "webhook_payload": payload,
            "namespace": "",
            "pod_name": "",
            "deployment_name": "",
            "cluster_name": "",
            "container_name": "",
            "exit_code": 0,
            "restart_count": 0,
            "alert_type": "",
            "current_memory_limit": "unknown",
            "current_cpu_limit": "unknown",
            "log_excerpt": "",
            "incident_id": None,
            "parsed_error": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "tokens_used": 0,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent02] Starting K8s alert workflow — thread_id=%s", thread_id)

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

        log.info("[Agent02] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info(
            "[Agent02] Resuming workflow thread=%s with option=%s",
            thread_id, selected_option.get("id"),
        )

        result = await self._graph.ainvoke(
            Command(resume=selected_option),
            config=config,
        )

        return result.get("execution_result", {"status": "completed"})
