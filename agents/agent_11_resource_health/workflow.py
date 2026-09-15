"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Agent 11 — Cloud Resource Health Monitoring
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

Supports two webhook payload formats (api/routes/webhooks.py's
/resource-health-alert normalizes both before calling run()):
  - Azure Monitor Common Alert Schema (same shape aks_alert_webhook already
    parses for AKS -- this agent handles the general case, any resource type)
  - AWS CloudWatch Alarm, already unwrapped from its SNS envelope by
    core/aws_sns.py -- see that module for the subscription-confirmation
    handshake and signature verification that happens before this ever runs

Tier gate: Growth+/Enterprise (core/compliance.py's TIER_LIMITS -- growth's
max_agents was bumped from 10 to 11 specifically so this doesn't become
Enterprise-only by numbering accident).
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_11_resource_health.tools import ResourceHealthTools
from core.security import shield

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class ResourceHealthState(TypedDict):
    # Inputs
    workspace_id: str
    cloud_provider: str          # "azure" | "aws" | "gcp"
    webhook_payload: dict

    # Extracted by ingest
    alert_source: str            # "azure_monitor" | "aws_cloudwatch" | "unknown"
    domain: str                  # "iam" | "networking" | "storage" | "compute" | "unknown" -- heuristic, LLM does the real categorization
    resource_id: str
    resource_type: str
    severity: str
    alert_name: str
    log_excerpt: str

    # Structured resource/metric pinpointing (Phase 2, GAPS.md scale-readiness build)
    resource_name: Optional[str]
    resource_group: Optional[str]        # Azure resource group, or AWS account ID
    metric_name: Optional[str]
    metric_current_value: Optional[float]
    metric_threshold: Optional[float]

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
# Heuristic domain classification (context for the LLM, not a gate)
# ──────────────────────────────────────────────

_AZURE_DOMAIN_HINTS = {
    "microsoft.network": "networking",
    "microsoft.storage": "storage",
    "microsoft.compute": "compute",
    "microsoft.web": "compute",
    "microsoft.authorization": "iam",
    "microsoft.keyvault": "iam",
    "microsoft.aad": "iam",
}

_AWS_NAMESPACE_DOMAIN_HINTS = {
    "aws/ec2": "compute",
    "aws/autoscaling": "compute",
    "aws/ebs": "compute",
    "aws/s3": "storage",
    "aws/vpc": "networking",
    "aws/networkelb": "networking",
    "aws/applicationelb": "networking",
    "aws/guardduty": "iam",
}


def _classify_domain_azure(target_resource_type: str) -> str:
    t = (target_resource_type or "").lower()
    for prefix, domain in _AZURE_DOMAIN_HINTS.items():
        if t.startswith(prefix):
            return domain
    return "unknown"


def _classify_domain_aws(namespace: str) -> str:
    n = (namespace or "").lower()
    return _AWS_NAMESPACE_DOMAIN_HINTS.get(n, "unknown")


# ──────────────────────────────────────────────
# Structured resource/metric extraction (Phase 2, scale-readiness build)
# ──────────────────────────────────────────────

def _parse_arm_resource(resource_id: str) -> tuple[str, str]:
    """Extract (resource_name, resource_group) from an Azure ARM resource ID.

    ARM ID shape: /subscriptions/{sub}/resourceGroups/{rg}/providers/{ns}/
    {type}/{name}[/{subtype}/{subname}...]. resource_name is the LAST path
    segment -- the specific resource that actually fired the alert, whatever
    its type (a VM, a SQL database, a storage account). The full ARM ID
    stays available separately in `resource_id` for anyone who needs the
    complete chain (e.g. which SQL *server* a database belongs to) --
    resource_name/resource_group are the short, queryable fields this
    column pair is for, not a replacement for the full path.

    Returns ("unknown", "unknown") if the ID doesn't parse as expected --
    never raises, since a malformed/unexpected ID shouldn't break ingest.
    """
    if not resource_id or resource_id == "unknown":
        return "unknown", "unknown"

    parts = [p for p in resource_id.split("/") if p]
    if not parts:
        return "unknown", "unknown"

    resource_name = parts[-1]
    resource_group = "unknown"
    for i, part in enumerate(parts):
        if part.lower() == "resourcegroups" and i + 1 < len(parts):
            resource_group = parts[i + 1]
            break

    return resource_name, resource_group


def _extract_azure_metric_context(
    payload: dict,
) -> tuple[Optional[str], Optional[float], Optional[float]]:
    """Extract (metric_name, current_value, threshold) from a Metric Alert's
    data.alertContext.condition.allOf[0] -- the structured fields Azure
    Monitor actually sends for a metric threshold alert. Only present for
    Metric Alert type payloads (Microsoft.Insights/metricAlerts); absent
    for other alert types (Activity Log, Service Health, etc.), in which
    case this returns (None, None, None) rather than guessing.

    Previously this data was never read at all -- _ingest_node only parsed
    data.essentials, which doesn't carry metric name/value/threshold.
    """
    try:
        condition = payload["data"]["alertContext"]["condition"]
        all_of = condition.get("allOf") or []
        if not all_of:
            return None, None, None
        first = all_of[0]
        metric_name = first.get("metricName")
        current_value = first.get("metricValue")
        threshold = first.get("threshold")
        return (
            metric_name,
            float(current_value) if current_value is not None else None,
            float(threshold) if threshold is not None else None,
        )
    except (KeyError, TypeError, IndexError, ValueError):
        return None, None, None


# CloudWatch's NewStateReason for a metric alarm is a semi-standard sentence,
# e.g. "Threshold Crossed: 1 datapoint [95.0 (15/09/26 01:00:00)] was
# greater than the threshold (80.0)." -- extracts the datapoint value and
# the threshold value out of that free text into real numbers.
_AWS_REASON_RE = re.compile(
    r"\[\s*(?P<value>-?\d+(?:\.\d+)?)\s*\(.*?\)\s*\]\s+was\s+.*?"
    r"threshold\s*\(\s*(?P<threshold>-?\d+(?:\.\d+)?)\s*\)",
    re.IGNORECASE,
)


def _extract_aws_metric_context(reason: str) -> tuple[Optional[float], Optional[float]]:
    """Structurally parse CloudWatch's NewStateReason for the current value
    and threshold, instead of just truncating it to 300 chars of free text
    and hoping the LLM restates the numbers correctly."""
    match = _AWS_REASON_RE.search(reason or "")
    if not match:
        return None, None
    try:
        return float(match.group("value")), float(match.group("threshold"))
    except (TypeError, ValueError):
        return None, None


def _extract_aws_account_id(alarm: dict) -> str:
    """AWS SNS-delivered CloudWatch alarm notifications usually include a
    top-level AWSAccountId field directly; fall back to parsing it out of
    AlarmArn (arn:aws:cloudwatch:{region}:{account_id}:alarm:{name}) if
    that field is absent."""
    account_id = alarm.get("AWSAccountId")
    if account_id:
        return str(account_id)

    arn_parts = (alarm.get("AlarmArn") or "").split(":")
    if len(arn_parts) >= 5 and arn_parts[0] == "arn":
        return arn_parts[4]

    return "unknown"


# ──────────────────────────────────────────────
# Workflow class
# ──────────────────────────────────────────────

class ResourceHealthWorkflow(BaseAgent):
    """
    Agent 11: Cloud Resource Health Monitoring.

    Usage:
        workflow = ResourceHealthWorkflow(db_conn, workspace_id, checkpointer)
        incident_id = await workflow.run(alert_payload, cloud_provider="azure")
        await workflow.resume(incident_id, selected_option)
    """

    AGENT_ID = "agent_11_resource_health"

    def __init__(
        self,
        db_conn,
        workspace_id: str,
        checkpointer: AsyncPostgresSaver,
        github_token: Optional[str] = None,
        aws_session=None,  # unused -- no live AWS mutation calls in this agent; accepted for uniform **creds spreading
        azure_access_token: Optional[str] = None,  # unused -- no live Azure mutation calls in this agent; accepted for uniform **creds spreading
        azure_devops_token: Optional[str] = None,
        azure_devops_org: Optional[str] = None,
        k8s_api_url: Optional[str] = None,  # unused -- accepted for uniform **creds spreading
        k8s_token: Optional[str] = None,
        k8s_ca_cert: Optional[str] = None,
        llm_provider: Optional[str] = None,
        byok_encrypted_key: Optional[str] = None,
    ):
        super().__init__(db_conn, workspace_id, llm_provider=llm_provider, byok_encrypted_key=byok_encrypted_key)
        self._checkpointer = checkpointer
        self._tools = ResourceHealthTools(
            github_token=github_token,
            azure_devops_token=azure_devops_token, azure_devops_org=azure_devops_org,
        )
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(ResourceHealthState)

        graph.add_node("ingest",         self._ingest_node)
        graph.add_node("dedup_check",    self._dedup_check_node)
        graph.add_node("dedup_complete", self._dedup_complete_node)
        graph.add_node("diagnose",       self._diagnose_node)
        graph.add_node("hitl_gate",      self._hitl_gate_node)
        graph.add_node("execute",        self._execute_node)
        graph.add_node("complete",       self._complete_node)

        graph.add_edge(START,          "ingest")
        graph.add_edge("ingest",       "dedup_check")
        # A flapping alert for a resource+alert_name that already has an
        # open incident short-circuits straight to dedup_complete --
        # bumps occurrence_count, never reaches diagnose, never spends
        # another LLM call on the same underlying problem (Phase 3,
        # GAPS.md scale-readiness build).
        graph.add_conditional_edges(
            "dedup_check", self._route_after_dedup,
            {"existing": "dedup_complete", "new": "diagnose"},
        )
        graph.add_edge("dedup_complete", END)
        graph.add_edge("diagnose",     "hitl_gate")
        graph.add_edge("hitl_gate",    "execute")
        graph.add_edge("execute",      "complete")
        graph.add_edge("complete",     END)

        return graph.compile(checkpointer=self._checkpointer)

    # ──────────────────────────────────────────────
    # Nodes
    # ──────────────────────────────────────────────

    async def _ingest_node(self, state: ResourceHealthState) -> dict:
        """
        Parse the alert payload into structured fields. Supports Azure
        Monitor Common Alert Schema and an already-SNS-unwrapped AWS
        CloudWatch Alarm (see core/aws_sns.py).
        """
        payload = state["webhook_payload"]

        alert_source  = "unknown"
        domain        = "unknown"
        resource_id   = "unknown"
        resource_type = "unknown"
        severity      = "unknown"
        alert_name    = "unknown"

        resource_name         = None
        resource_group        = None
        metric_name            = None
        metric_current_value   = None
        metric_threshold       = None

        # ── Azure Monitor Common Alert Schema ──
        if "data" in payload and "essentials" in payload.get("data", {}):
            alert_source = "azure_monitor"
            essentials = payload["data"]["essentials"]
            alert_name    = essentials.get("alertRule", "unknown")
            severity      = essentials.get("severity", "unknown")
            resource_type = essentials.get("targetResourceType", "unknown")
            affected = essentials.get("alertTargetIDs") or []
            resource_id = affected[0] if affected else "unknown"
            domain = _classify_domain_azure(resource_type)

            resource_name, resource_group = _parse_arm_resource(resource_id)
            metric_name, metric_current_value, metric_threshold = _extract_azure_metric_context(payload)

            log_lines = [
                f"Alert Rule: {alert_name}",
                f"Severity: {severity}",
                f"Target Resource Type: {resource_type}",
                f"Resource: {resource_id}",
                f"Monitor Condition: {essentials.get('monitorCondition', 'unknown')}",
                f"Description: {essentials.get('description', '')[:300]}",
            ]
            if metric_name:
                log_lines.append(
                    f"Metric: {metric_name} = {metric_current_value} (threshold: {metric_threshold})"
                )

        # ── AWS CloudWatch Alarm (already unwrapped from SNS) ──
        elif "cloudwatch_alarm" in payload:
            alert_source = "aws_cloudwatch"
            alarm = payload["cloudwatch_alarm"]
            trigger = alarm.get("Trigger", {})
            alert_name    = alarm.get("AlarmName", "unknown")
            severity      = alarm.get("NewStateValue", "unknown")
            resource_type = trigger.get("Namespace", "unknown")
            dims = trigger.get("Dimensions", [])
            resource_id = dims[0].get("value", "unknown") if dims else alarm.get("AlarmName", "unknown")
            domain = _classify_domain_aws(resource_type)

            resource_name = resource_id
            resource_group = _extract_aws_account_id(alarm)
            metric_name = trigger.get("MetricName")
            reason = alarm.get("NewStateReason", "")
            metric_current_value, metric_threshold = _extract_aws_metric_context(reason)

            log_lines = [
                f"Alarm: {alert_name}",
                f"State: {severity}",
                f"Namespace: {resource_type}",
                f"Resource: {resource_id}",
                f"Metric: {metric_name or 'unknown'}",
                f"Reason: {reason[:300]}",
            ]
            if metric_current_value is not None:
                log_lines.append(f"Parsed value: {metric_current_value} (threshold: {metric_threshold})")

        else:
            log.warning("[Agent11] Unknown alert payload format — using raw excerpt")
            log_lines = [f"Alert payload: {json.dumps(payload)[:500]}"]

        log_excerpt = "\n".join(log_lines)
        sanitized = shield.sanitize(log_excerpt, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent11] Ingested: source=%s domain=%s resource=%s severity=%s metric=%s",
            alert_source, domain, resource_id, severity, metric_name,
        )

        return {
            "alert_source":   alert_source,
            "domain":         domain,
            "resource_id":    resource_id,
            "resource_type":  resource_type,
            "severity":       severity,
            "alert_name":     alert_name,
            "log_excerpt":    sanitized.sanitized_text,
            "resource_name":         resource_name,
            "resource_group":        resource_group,
            "metric_name":            metric_name,
            "metric_current_value":  metric_current_value,
            "metric_threshold":       metric_threshold,
            "tokens_used":    0,
            "incident_id":    None,
            "parsed_error":   None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

    async def _dedup_check_node(self, state: ResourceHealthState) -> dict:
        """
        Look up an existing OPEN incident for this exact
        (workspace_id, resource_id, alert_name) before spending an LLM
        call on what might be the same flapping alert firing again. Runs
        BEFORE diagnose specifically so a repeat delivery genuinely never
        makes a new LLM call, not just never creates a second row.

        Sets incident_id in state when a match is found -- _route_after_
        dedup reads that to route to dedup_complete instead of diagnose.
        """
        if state.get("error"):
            return {}

        existing = await self.hitl.find_open_incident(
            workspace_id=self.workspace_id,
            resource_id=state.get("resource_id"),
            alert_name=state.get("alert_name"),
        )
        if not existing:
            return {}

        existing_id = str(existing["id"])
        await self.hitl.bump_occurrence(existing_id)
        log.info(
            "[Agent11] Deduplicated against existing incident %s (occurrence #%d) — resource=%s alert=%s",
            existing_id, existing.get("occurrence_count", 0) + 1, state.get("resource_id"), state.get("alert_name"),
        )
        return {"incident_id": existing_id}

    def _route_after_dedup(self, state: ResourceHealthState) -> str:
        return "existing" if state.get("incident_id") else "new"

    async def _dedup_complete_node(self, state: ResourceHealthState) -> dict:
        """Terminal node for a deduplicated alert -- incident_id is already
        set in state by _dedup_check_node, nothing left to do but record it."""
        self._write_audit("dedup", "existing_incident_bumped", incident_id=state.get("incident_id"))
        return {}

    async def _diagnose_node(self, state: ResourceHealthState) -> dict:
        """Call LLM via router to diagnose the resource-health alert. Parse JSON response."""
        user_message = (
            f"Cloud Resource Health Alert:\n\n"
            f"Cloud Provider: {state['cloud_provider']}\n"
            f"Alert Source: {state['alert_source']}\n"
            f"Domain (heuristic, confirm/correct in your diagnosis): {state['domain']}\n"
            f"Resource: {state['resource_id']}\n"
            f"Resource Type: {state['resource_type']}\n"
            f"Severity: {state['severity']}\n"
            f"Alert Name: {state['alert_name']}\n\n"
            f"Details:\n{state['log_excerpt']}\n\n"
            f"Diagnose this alert and return exactly the JSON format specified."
        )

        await self.check_budget(estimated_tokens=3000, model="claude-sonnet-4-20250514")

        try:
            response, estimated_tokens = self.call_llm(
                task_type="resource_health_triage",
                messages=[{"role": "user", "content": user_message}],
                system_prompt=self._diagnose_prompt,
            )
        except Exception as exc:
            # Phase 9, scale-readiness build: .llm/router.py already
            # retries transient errors with backoff and fails over across
            # providers before ever raising here -- reaching this means
            # every provider in the failover chain was genuinely
            # exhausted. Returning a degraded-but-normal diagnosis shape
            # (rather than setting state["error"], which _hitl_gate_node
            # treats as "skip creating an incident entirely") means a
            # real incident still gets created and is visible to an
            # operator, instead of the alert silently vanishing.
            log.error("[Agent11] LLM diagnosis unavailable — all providers exhausted: %s", exc)
            self._write_audit("diagnose", "llm_unavailable")
            return {
                "parsed_error": f"LLM diagnosis unavailable — retry manually. (All LLM providers failed: {exc})",
                "remediation_options": [{
                    "id": "hold",
                    "title": "Stay broken / submit custom solution",
                    "description": (
                        "Automated diagnosis could not run because every configured LLM "
                        "provider failed. Review the alert manually — see the incident's "
                        "raw log for details."
                    ),
                    "impact": "low",
                    "docs_url": "",
                }],
                "estimated_duration_seconds": None,
                "tokens_used": state.get("tokens_used", 0),
            }

        try:
            diagnosis = self.parse_llm_json(response, context="resource_health_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {"error": str(exc), "tokens_used": estimated_tokens}

        parsed_error = diagnosis.get("parsed_error", "Unknown resource health alert")
        options = diagnosis.get("options", [])
        duration = diagnosis.get("estimated_duration_seconds", 120)

        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent11] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info("[Agent11] Diagnosed: %s (options=%d)", parsed_error[:80], len(options))

        return {
            "parsed_error": parsed_error,
            "remediation_options": options,
            "estimated_duration_seconds": duration,
            "tokens_used": state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: ResourceHealthState) -> dict:
        """
        Save incident to DB, then interrupt() to pause the graph.
        Governance Rule 11: No autonomous remediation.
        """
        if state.get("error"):
            log.error("[Agent11] Skipping HITL gate due to upstream error: %s", state["error"])
            incident_id = await self.hitl.create_failed_incident(
                workspace_id=self.workspace_id,
                agent_id=self.agent_id,
                error_message=state["error"],
                raw_log=state.get("log_excerpt", ""),
                cloud_provider=state.get("cloud_provider"),
            )
            return {"incident_id": incident_id}

        incident_id = await self.hitl.create_incident(
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            raw_log=state["log_excerpt"],
            parsed_error=state["parsed_error"],
            remediation_options=state["remediation_options"],
            cloud_provider=state["cloud_provider"],
            tokens_used=state.get("tokens_used", 0),
            estimated_duration_seconds=state.get("estimated_duration_seconds"),
            resource_id=state.get("resource_id"),
            resource_name=state.get("resource_name"),
            resource_group=state.get("resource_group"),
            metric_name=state.get("metric_name"),
            metric_current_value=state.get("metric_current_value"),
            metric_threshold=state.get("metric_threshold"),
            alert_name=state.get("alert_name"),
        )

        await self.record_token_usage(
            tokens_used=state.get("tokens_used", 0),
            incident_id=incident_id,
        )

        self._write_audit("hitl_gate", "pending_approval", incident_id=incident_id)
        log.info("[Agent11] HITL gate — incident %s awaiting operator approval", incident_id)

        selected_option = interrupt({
            "incident_id": incident_id,
            "message": "Awaiting operator approval",
            "options": state["remediation_options"],
        })

        return {
            "incident_id": incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: ResourceHealthState) -> dict:
        """Execute the approved option. Only reached after human approval."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent11] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        log.info("[Agent11] Executing approved option: %s", option_id)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        payload = state["webhook_payload"]
        context = {
            "resource_id": state["resource_id"],
            "owner": payload.get("owner", ""),
            "repo": payload.get("repo", ""),
            "file_path": payload.get("file_path", f"infra/{state['resource_id']}"),
            "corrected_content": payload.get("corrected_content", ""),
            "report_body": state.get("parsed_error", ""),
            "issue_title": f"Resource health alert: {state['alert_name']} ({state['resource_id']})",
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: ResourceHealthState) -> dict:
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
        log.info("[Agent11] Workflow complete for incident %s", incident_id)
        return {}

    # ──────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────

    async def run(self, payload: dict, cloud_provider: str = "azure") -> str:
        """
        Trigger the resource-health workflow from a webhook payload.
        Returns incident_id after the HITL gate pause.
        """
        import uuid

        initial_state: ResourceHealthState = {
            "workspace_id": self.workspace_id,
            "cloud_provider": cloud_provider,
            "webhook_payload": payload,
            "alert_source": "",
            "domain": "",
            "resource_id": "",
            "resource_type": "",
            "severity": "",
            "alert_name": "",
            "log_excerpt": "",
            "resource_name": None,
            "resource_group": None,
            "metric_name": None,
            "metric_current_value": None,
            "metric_threshold": None,
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

        log.info("[Agent11] Starting resource health workflow — thread_id=%s", thread_id)

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

        log.info("[Agent11] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info(
            "[Agent11] Resuming workflow thread=%s with option=%s",
            thread_id, selected_option.get("id"),
        )

        result = await self._graph.ainvoke(
            Command(resume=selected_option),
            config=config,
        )

        return result.get("execution_result", {"status": "completed"})
