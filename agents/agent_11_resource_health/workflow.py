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
    START → ingest → resolution_check → dedup_check → diagnose → hitl_gate (interrupt) → execute → complete → END
                            │                  │
                            └→ resolution_complete → END   └→ dedup_complete → END

resolution_check (GAPS.md scale-readiness build) only does anything for a
"resolved"-status Alertmanager/Grafana alert -- every other alert_status
("firing", or the implicit firing-only Azure Monitor/AWS CloudWatch
sources) passes straight through to dedup_check unchanged.

Supports four webhook payload formats (api/routes/webhooks.py's
/resource-health-alert normalizes all of them before calling run()):
  - Azure Monitor Common Alert Schema (same shape aks_alert_webhook already
    parses for AKS -- this agent handles the general case, any resource type)
  - AWS CloudWatch Alarm, already unwrapped from its SNS envelope by
    core/aws_sns.py -- see that module for the subscription-confirmation
    handshake and signature verification that happens before this ever runs
  - Prometheus Alertmanager (webhook_config v4 shape: a top-level "alerts"
    array, each element carrying labels/annotations/status)
  - Grafana unified alerting -- deliberately mirrors Alertmanager's shape;
    a top-level "orgId" field is the only reliable discriminator (same
    detection api/routes/webhooks.py's resource_health_alert_webhook
    already does before ever calling run())

A single Alertmanager/Grafana delivery can carry several alerts in one
"alerts" array (Alertmanager batches by default, commonly mixing newly-
firing and newly-resolved alerts in the same delivery) -- run() fans
those out into one independent graph invocation per alert element (own
thread_id, own dedup/resolution check, own possible incident) rather than
collapsing them into a single ingest. See run()'s docstring for the
resulting return-type difference.

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
from core.severity import normalize_severity

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
    # "firing" | "resolved" -- only Alertmanager/Grafana alerts carry a
    # real status per element; every other source is always "firing" by
    # the time it reaches this agent (Azure Monitor/AWS CloudWatch both
    # already gate on their own "is this actually firing" condition at
    # the webhook route, before this workflow ever runs).
    alert_status: str

    # Structured resource/metric pinpointing (Phase 2, GAPS.md scale-readiness build)
    resource_name: Optional[str]
    resource_group: Optional[str]        # Azure resource group, or AWS account ID
    metric_name: Optional[str]
    metric_current_value: Optional[float]
    metric_threshold: Optional[float]

    # Set True only when _dedup_check_node finds a real existing open
    # incident to collapse against. _route_after_dedup reads this, NOT
    # incident_id's truthiness -- incident_id is now pre-seeded to the
    # real LangGraph thread_id from the very start of run() (see run()'s
    # own comment on why), so it is always truthy and can no longer be
    # used as a "was a dedup match found" signal. Real bug found live,
    # 2026-09-15: routing on incident_id truthiness after that pre-seeding
    # fix landed made _route_after_dedup return "existing" unconditionally,
    # so every alert -- including genuinely new ones -- got silently
    # routed to dedup_complete and NO real incident was ever created.
    is_dedup_match: bool
    # Settings → Policies, Step 2 (migration 049) -- True only when
    # dedup_check routed to dedup_complete because the resource is
    # exempted, not because an existing incident was found.
    is_exempted: bool

    # Set True only by _resolution_check_node -- a "resolved"-status alert
    # either matched an existing open incident (noted via
    # hitl.note_source_resolution, not diagnosed) or had no match at all
    # (nothing to do); both cases short-circuit straight to
    # resolution_complete without ever reaching dedup_check/diagnose.
    is_source_resolved_noop: bool

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
# Structured extraction — Prometheus Alertmanager / Grafana unified
# alerting (GAPS.md scale-readiness build). Both webhook notifiers send
# an identical per-alert shape (labels/annotations/status) inside a
# top-level "alerts" array -- api/routes/webhooks.py's
# resource_health_alert_webhook already tells the two envelopes apart via
# Grafana's orgId field before ever calling run(); _ingest_node mirrors
# that same check since it only ever sees whichever single-alert
# sub-payload run()'s fan-out built.
# ──────────────────────────────────────────────

_ALERTMANAGER_SEVERITY_MAP = {
    "critical": "high",
    "warning": "high",
    "info": "low",
}


def _map_alertmanager_severity(raw: Optional[str]) -> str:
    """
    Deliberately more conservative than core.severity.normalize_severity's
    generic pass-through (which would leave a raw "critical" label as
    "critical" unchanged): a Prometheus/Grafana severity label is set by
    whoever wrote the alerting rule, with no platform-side validation, so
    this caps it at "high" rather than letting an arbitrary rule author
    page as "critical" -- "critical" is reserved for signals the platform
    itself computes. Unmapped or missing labels default to "medium", the
    same convention normalize_severity itself uses.
    """
    return _ALERTMANAGER_SEVERITY_MAP.get((raw or "").strip().lower(), "medium")


def _extract_alertmanager_resource(labels: dict) -> tuple[str, str, str]:
    """
    (resource_id, resource_name, resource_group) from an Alertmanager/
    Grafana alert's labels. A K8s-origin alert (kube-state-metrics and
    similar exporters commonly set pod+namespace labels) is preferred over
    the generic `instance` scrape-target label when present -- namespace/
    pod pinpoints the actual unhealthy resource; `instance` is just the
    host:port Prometheus scraped, which for a K8s exporter is rarely the
    resource that's actually failing.
    """
    pod = labels.get("pod")
    namespace = labels.get("namespace")
    if pod:
        resource_name = pod
        resource_id = f"{namespace}/{pod}" if namespace else pod
    else:
        resource_name = labels.get("instance", "unknown")
        resource_id = resource_name
    resource_group = namespace or labels.get("job") or "unknown"
    return resource_id, resource_name, resource_group


def _extract_grafana_metric_value(alert: dict) -> Optional[float]:
    """
    Grafana unified alerting includes a `values` map on each alert element
    -- the last-evaluated value per query/condition ref ID (e.g.
    {"B": 95.2}). Alertmanager proper has no equivalent field, so this is
    only ever called from the Grafana branch. Takes the first value
    present -- most Grafana alert rules have exactly one query, and there
    is no ref-ID convention to prefer one over another in the general
    case.
    """
    values = alert.get("values") or {}
    if not values:
        return None
    first = next(iter(values.values()), None)
    try:
        return float(first) if first is not None else None
    except (TypeError, ValueError):
        return None


def _parse_alertmanager_alert(alert: dict) -> dict:
    """
    Shared field extraction for a single Alertmanager/Grafana alert
    element. Both webhook shapes carry identical per-alert structure
    (labels/annotations/status) -- the two branches in _ingest_node that
    call this differ only in alert_source labeling and (Grafana only)
    the extra values{} metric read, done separately by the caller.
    """
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    status = alert.get("status", "firing")

    alert_name = labels.get("alertname", "unknown")
    resource_id, resource_name, resource_group = _extract_alertmanager_resource(labels)
    severity = _map_alertmanager_severity(labels.get("severity"))

    summary = annotations.get("summary", "")
    description = annotations.get("description", "")
    log_lines = [
        f"Alert: {alert_name}",
        f"Status: {status}",
        f"Severity (raw label): {labels.get('severity', 'unknown')}",
        f"Resource: {resource_id}",
        f"Namespace/Job: {resource_group}",
        f"Summary: {summary[:300]}",
        f"Description: {description[:300]}",
    ]

    return {
        "alert_name": alert_name,
        "resource_id": resource_id,
        "resource_name": resource_name,
        "resource_group": resource_group,
        # No reliable domain signal in Alertmanager/Grafana labels --
        # "unknown" here, same as every other source's fallback; the LLM
        # categorizes for real during diagnosis.
        "domain": "unknown",
        "severity": severity,
        "alert_status": status,
        "log_lines": log_lines,
    }


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

        graph.add_node("ingest",              self._ingest_node)
        graph.add_node("resolution_check",    self._resolution_check_node)
        graph.add_node("resolution_complete", self._resolution_complete_node)
        graph.add_node("dedup_check",         self._dedup_check_node)
        graph.add_node("dedup_complete",      self._dedup_complete_node)
        graph.add_node("diagnose",            self._diagnose_node)
        graph.add_node("hitl_gate",           self._hitl_gate_node)
        graph.add_node("execute",             self._execute_node)
        graph.add_node("complete",            self._complete_node)

        graph.add_edge(START,             "ingest")
        graph.add_edge("ingest",          "resolution_check")
        # A "resolved"-status Alertmanager/Grafana alert must never reach
        # diagnose -- there's nothing to diagnose once the source itself
        # says the condition cleared. Short-circuits straight to
        # resolution_complete instead, same shape as dedup's own
        # short-circuit below (GAPS.md scale-readiness build).
        graph.add_conditional_edges(
            "resolution_check", self._route_after_resolution_check,
            {"resolved": "resolution_complete", "firing": "dedup_check"},
        )
        graph.add_edge("resolution_complete", END)
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
        alert_status  = "firing"

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

        # ── Grafana unified alerting (checked BEFORE plain Alertmanager
        # below -- Grafana payloads also carry a top-level "alerts" array,
        # and orgId is the only field that tells the two apart) ──
        elif "alerts" in payload and "orgId" in payload:
            alert_source = "grafana"
            alerts = payload.get("alerts") or []
            alert = alerts[0] if alerts else {}
            parsed = _parse_alertmanager_alert(alert)

            alert_name     = parsed["alert_name"]
            resource_id    = parsed["resource_id"]
            resource_name  = parsed["resource_name"]
            resource_group = parsed["resource_group"]
            severity       = parsed["severity"]
            domain         = parsed["domain"]
            alert_status   = parsed["alert_status"]
            log_lines      = list(parsed["log_lines"])

            metric_current_value = _extract_grafana_metric_value(alert)
            if metric_current_value is not None:
                log_lines.append(f"Value: {metric_current_value}")

        # ── Prometheus Alertmanager (webhook_config v4 shape) ──
        elif "alerts" in payload:
            alert_source = "prometheus_alertmanager"
            alerts = payload.get("alerts") or []
            alert = alerts[0] if alerts else {}
            parsed = _parse_alertmanager_alert(alert)

            alert_name     = parsed["alert_name"]
            resource_id    = parsed["resource_id"]
            resource_name  = parsed["resource_name"]
            resource_group = parsed["resource_group"]
            severity       = parsed["severity"]
            domain         = parsed["domain"]
            alert_status   = parsed["alert_status"]
            log_lines      = parsed["log_lines"]

        else:
            log.warning("[Agent11] Unknown alert payload format — using raw excerpt")
            log_lines = [f"Alert payload: {json.dumps(payload)[:500]}"]

        log_excerpt = "\n".join(log_lines)
        sanitized = shield.sanitize(log_excerpt, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent11] Ingested: source=%s domain=%s resource=%s severity=%s metric=%s status=%s",
            alert_source, domain, resource_id, severity, metric_name, alert_status,
        )

        return {
            "alert_source":   alert_source,
            "domain":         domain,
            "resource_id":    resource_id,
            "resource_type":  resource_type,
            "severity":       severity,
            "alert_name":     alert_name,
            "alert_status":   alert_status,
            "log_excerpt":    sanitized.sanitized_text,
            "resource_name":         resource_name,
            "resource_group":        resource_group,
            "metric_name":            metric_name,
            "metric_current_value":  metric_current_value,
            "metric_threshold":       metric_threshold,
            "tokens_used":    0,
            # incident_id intentionally NOT returned here -- it's pre-seeded
            # in run()'s initial_state (== the LangGraph thread_id) and must
            # survive this node's update untouched, never reset back to a
            # null value. Real bug found live, 2026-09-15: this key used to
            # be returned here set to a null value, which silently undid
            # run()'s pre-seeding on every single run, well after that
            # pre-seeding fix was first written elsewhere in this same file
            # -- the two fixes have to both be present, not just one.
            "parsed_error":   None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

    async def _resolution_check_node(self, state: ResourceHealthState) -> dict:
        """
        A "resolved"-status Alertmanager/Grafana alert must never reach
        diagnose (there's nothing to diagnose -- the condition already
        cleared) or create a new incident. If an open incident exists for
        the same dedup key (workspace_id + resource_id + alert_name),
        this notes the source-reported resolution on that record
        (hitl.note_source_resolution); otherwise there's nothing to do at
        all. Every other alert -- "firing", or the implicit firing-only
        Azure Monitor/AWS CloudWatch sources -- passes straight through
        unchanged, since both of those already gate on their own "is this
        actually firing" condition at the webhook route before this
        workflow ever runs.
        """
        if state.get("error"):
            return {}
        if state.get("alert_status") != "resolved":
            return {}

        existing = await self.hitl.find_open_incident(
            workspace_id=self.workspace_id,
            resource_id=state.get("resource_id"),
            alert_name=state.get("alert_name"),
        )
        if not existing:
            log.info(
                "[Agent11] Resolved alert with no matching open incident — nothing to do "
                "(resource=%s alert=%s)", state.get("resource_id"), state.get("alert_name"),
            )
            self._write_audit("resolution_check", "resolved_no_match")
            return {"incident_id": None, "is_source_resolved_noop": True}

        existing_id = str(existing["id"])
        await self.hitl.note_source_resolution(existing_id)
        log.info(
            "[Agent11] Source-reported resolution noted on incident %s (resource=%s alert=%s)",
            existing_id, state.get("resource_id"), state.get("alert_name"),
        )
        self._write_audit("resolution_check", "resolved_noted", incident_id=existing_id)
        return {"incident_id": existing_id, "is_source_resolved_noop": True}

    def _route_after_resolution_check(self, state: ResourceHealthState) -> str:
        return "resolved" if state.get("is_source_resolved_noop") else "firing"

    async def _resolution_complete_node(self, state: ResourceHealthState) -> dict:
        """Terminal node for a source-reported resolution -- incident_id
        is already set (the matched incident's real id, or None for a
        no-match) by _resolution_check_node."""
        return {}

    async def _dedup_check_node(self, state: ResourceHealthState) -> dict:
        """
        Look up an existing OPEN incident for this exact
        (workspace_id, resource_id, alert_name) before spending an LLM
        call on what might be the same flapping alert firing again. Runs
        BEFORE diagnose specifically so a repeat delivery genuinely never
        makes a new LLM call, not just never creates a second row.

        Sets is_dedup_match=True (and overwrites incident_id with the
        REAL existing incident's id, replacing run()'s thread_id seed)
        only when a match is found -- _route_after_dedup reads
        is_dedup_match, not incident_id's truthiness, to route to
        dedup_complete instead of diagnose.
        """
        if state.get("error"):
            return {}

        # Settings → Policies, Step 2 (migration 049): an exempted resource
        # is skipped here, before find_open_incident/diagnose, so it costs
        # zero LLM tokens -- not just zero duplicate incident rows.
        if await self.exemptions.check_and_suppress(self.workspace_id, state.get("resource_id")):
            return {"is_dedup_match": True, "is_exempted": True}

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
        return {"incident_id": existing_id, "is_dedup_match": True}

    def _route_after_dedup(self, state: ResourceHealthState) -> str:
        return "existing" if state.get("is_dedup_match") else "new"

    async def _dedup_complete_node(self, state: ResourceHealthState) -> dict:
        """Terminal node for a deduplicated OR exempted alert -- incident_id
        is already set in state by _dedup_check_node for the dedup case
        (None for an exemption, since no incident was ever created)."""
        if state.get("is_exempted"):
            self._write_audit("dedup", "resource_exemption_suppressed")
        else:
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
            incident_id=state["incident_id"],
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
            severity=normalize_severity(state.get("severity")),
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

    async def run(self, payload: dict, cloud_provider: str = "azure") -> "str | list":
        """
        Trigger the resource-health workflow from a webhook payload.

        A single Alertmanager/Grafana delivery can carry several alerts in
        one top-level "alerts" array (Alertmanager batches by default,
        commonly mixing newly-firing and newly-resolved alerts together
        in the same delivery). Each element gets its OWN independent
        graph run -- own thread_id, own resolution/dedup check, own
        possible incident -- so a multi-alert delivery fans out here and
        returns a list of incident_ids (None for a resolved alert that
        matched nothing and created no incident) instead of the single
        string every other case returns.

        Azure Monitor, AWS CloudWatch, and a single-alert Alertmanager/
        Grafana delivery are untouched by this -- always exactly one
        alert, same single incident_id string return as before.
        """
        alerts = payload.get("alerts")
        if isinstance(alerts, list) and len(alerts) > 1:
            results = []
            for alert in alerts:
                sub_payload: dict = {"alerts": [alert]}
                if "orgId" in payload:
                    sub_payload["orgId"] = payload["orgId"]
                results.append(await self._run_single(sub_payload, cloud_provider))
            return results

        return await self._run_single(payload, cloud_provider)

    async def _run_single(self, payload: dict, cloud_provider: str = "azure") -> Optional[str]:
        """
        Runs exactly one graph invocation for one alert (or for a non-
        Alertmanager/Grafana payload, which is always exactly one alert
        already). Returns the created/matched incident_id, or None for a
        resolved alert that matched no open incident.
        """
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
            "alert_status": "firing",
            "log_excerpt": "",
            "resource_name": None,
            "resource_group": None,
            "metric_name": None,
            "metric_current_value": None,
            "metric_threshold": None,
            "is_dedup_match": False,
            "is_exempted": False,
            "is_source_resolved_noop": False,
            "incident_id": thread_id,
            "parsed_error": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "tokens_used": 0,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

        config = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent11] Starting resource health workflow — thread_id=%s", thread_id)

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

        log.info("[Agent11] Workflow run complete — incident_id=%s", incident_id)
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
