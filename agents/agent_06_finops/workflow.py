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
Agent 06 — FinOps Cost Optimization
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

Trigger:
  - Manual: POST /agents/agent_06_finops/run
  - Scheduled: monthly billing cycle (coming Phase 7)

Accepts pre-fetched billing data (Cost Explorer JSON, Azure Cost Management export,
or GCP BigQuery export) or a freeform spend summary. The LLM produces a ranked list
of recommendations with estimated monthly savings.
"""

import json
import logging
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_06_finops.tools import FinOpsTools, _format_currency
from core.security import shield

log = logging.getLogger(__name__)

_MAX_COST_DATA_CHARS  = 8_000
_MAX_RESOURCE_CHARS   = 4_000


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class FinOpsState(TypedDict):
    # Inputs
    workspace_id: str
    cloud_provider: str       # "aws" | "azure" | "gcp"
    webhook_payload: dict

    # Extracted by ingest
    billing_period: str       # "2026-06" or "2026-05-01/2026-05-31"
    account_id: str           # AWS account / Azure subscription / GCP project
    repository: str           # optional "owner/repo" for issue creation
    cost_data_summary: str    # sanitized cost data sent to LLM
    resource_inventory: str   # sanitized idle resource list (optional)
    total_spend: float        # total spend for the period in USD
    currency: str             # "USD", "EUR", etc.

    # After diagnose
    incident_id: Optional[str]
    parsed_error: Optional[str]        # cost risk headline
    cost_report: Optional[str]         # full markdown cost optimization report
    recommendations: Optional[list]    # ranked list of specific recommendations
    quick_win_resources: Optional[dict] # idle resources safe to stop/delete
    estimated_monthly_savings: Optional[float]
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

def _normalize_cost_data(raw: dict | list | str, cloud: str, max_chars: int) -> tuple[str, float]:
    """
    Normalize cloud billing API output into a text block for the LLM.
    Returns (text_summary, total_spend_usd).
    """
    total = 0.0

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            text = raw[:max_chars]
            return text, 0.0

    if cloud == "aws":
        # AWS Cost Explorer: ResultsByTime[].Groups[].{Keys, Metrics.UnblendedCost.Amount}
        lines = []
        for period in raw.get("ResultsByTime", []):
            time_str = period.get("TimePeriod", {}).get("Start", "")
            for grp in period.get("Groups", []):
                svc    = grp.get("Keys", ["unknown"])[0]
                amount = float(grp.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0))
                total += amount
                lines.append(f"{time_str} | {svc}: ${amount:,.2f}")
        text = "\n".join(lines)

    elif cloud == "azure":
        # Azure Cost Management: properties.rows (columns: Cost, ServiceName, Currency)
        lines = []
        props = raw.get("properties", raw)
        cols  = [c.get("name", "") for c in props.get("columns", [])]
        for row in props.get("rows", []):
            row_dict = dict(zip(cols, row))
            svc    = row_dict.get("ServiceName", row_dict.get("serviceName", "unknown"))
            amount = float(row_dict.get("Cost", row_dict.get("cost", 0)))
            total += amount
            lines.append(f"{svc}: ${amount:,.2f}")
        text = "\n".join(lines)

    elif cloud in ("gcp", "google"):
        # GCP: may be a BigQuery export or a simple service list
        if isinstance(raw, list):
            lines = [f"{item.get('displayName', item.get('name', 'unknown'))}" for item in raw]
            text  = "\n".join(lines)
        else:
            text = json.dumps(raw, indent=2)

    else:
        text = json.dumps(raw, indent=2) if isinstance(raw, (dict, list)) else str(raw)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated]"

    return text, total


def _normalize_resource_inventory(raw: dict | list | str, max_chars: int) -> str:
    """Convert idle resource inventory to a text block."""
    if isinstance(raw, str):
        text = raw
    else:
        text = json.dumps(raw, indent=2)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated]"
    return text


# ──────────────────────────────────────────────
# Workflow class
# ──────────────────────────────────────────────

class FinOpsWorkflow(BaseAgent):
    """
    Agent 06: FinOps Cost Optimization.

    Usage:
        workflow = FinOpsWorkflow(db_conn, workspace_id, checkpointer)
        incident_id = await workflow.run({
            "billing_period": "2026-06",
            "account_id": "123456789012",
            "cost_data": { <AWS Cost Explorer response> },
            "resource_inventory": { <idle resources> },
            "repository": "acme/infra",
        }, cloud_provider="aws")
        await workflow.resume(thread_id, selected_option)
    """

    AGENT_ID = "agent_06_finops"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer = checkpointer
        self._tools = FinOpsTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(FinOpsState)

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

    async def _ingest_node(self, state: FinOpsState) -> dict:
        """
        Extract and normalize billing data from the payload.
        Sanitizes cost data before LLM consumption.
        """
        payload = state["webhook_payload"]
        cloud   = state["cloud_provider"]

        billing_period     = payload.get("billing_period", "")
        account_id         = payload.get("account_id", "") or payload.get("subscription_id", "") or payload.get("project", "")
        repository         = payload.get("repository", "")
        currency           = payload.get("currency", "USD")

        raw_cost_data  = payload.get("cost_data", {})
        raw_inventory  = payload.get("resource_inventory", {})

        # Normalize cost data to text + extract total spend
        cost_text, total_spend = _normalize_cost_data(raw_cost_data, cloud, _MAX_COST_DATA_CHARS)

        # Sanitize — cost data can include account IDs, project names; strip any secrets
        sanitized_cost = shield.sanitize(cost_text, context=self.agent_id)

        # Normalize resource inventory (idle resources identified by the operator)
        inv_text = _normalize_resource_inventory(raw_inventory, _MAX_RESOURCE_CHARS)
        sanitized_inv = shield.sanitize(inv_text, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent06] Ingested: cloud=%s period=%s account=%s total_spend=%.2f",
            cloud, billing_period, account_id, total_spend,
        )

        return {
            "billing_period": billing_period,
            "account_id": account_id,
            "repository": repository,
            "currency": currency,
            "cost_data_summary": sanitized_cost.sanitized_text,
            "resource_inventory": sanitized_inv.sanitized_text,
            "total_spend": total_spend,
            "tokens_used": 0,
            "incident_id": None,
            "parsed_error": None,
            "cost_report": None,
            "recommendations": None,
            "quick_win_resources": None,
            "estimated_monthly_savings": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

    async def _diagnose_node(self, state: FinOpsState) -> dict:
        """
        Call LLM to analyze the cost data, identify waste, and rank savings opportunities.
        """
        cloud          = state["cloud_provider"]
        billing_period = state["billing_period"]
        total_spend    = state["total_spend"]
        currency       = state["currency"]

        user_message = (
            f"FinOps Cost Optimization Request:\n\n"
            f"Cloud: {cloud.upper()}\n"
            f"Billing Period: {billing_period}\n"
            f"Account/Project: {state['account_id']}\n"
            f"Total Spend: {_format_currency(total_spend, currency)}\n\n"
            f"Cost Breakdown by Service:\n```\n{state['cost_data_summary']}\n```\n\n"
            f"Idle / Unattached Resources:\n```json\n{state['resource_inventory']}\n```\n\n"
            f"Analyze this spend data. Identify waste and generate a ranked list of "
            f"cost optimization recommendations. Return exactly the JSON format specified."
        )

        await self.check_budget(estimated_tokens=6000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="finops_optimization",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="finops_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {"error": str(exc), "tokens_used": estimated_tokens}

        parsed_error              = diagnosis.get("parsed_error", "Cost optimization analysis complete")
        cost_report               = diagnosis.get("cost_report", "")
        recommendations           = diagnosis.get("recommendations", [])
        quick_win_resources       = diagnosis.get("quick_win_resources", {})
        estimated_monthly_savings = float(diagnosis.get("estimated_monthly_savings", 0))
        options                   = diagnosis.get("options", [])
        duration                  = diagnosis.get("estimated_duration_seconds", 60)

        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent06] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info(
            "[Agent06] Analysis: %s | savings=%.2f recommendations=%d",
            parsed_error[:80], estimated_monthly_savings, len(recommendations),
        )

        return {
            "parsed_error": parsed_error,
            "cost_report": cost_report,
            "recommendations": recommendations,
            "quick_win_resources": quick_win_resources,
            "estimated_monthly_savings": estimated_monthly_savings,
            "remediation_options": options,
            "estimated_duration_seconds": duration,
            "tokens_used": state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: FinOpsState) -> dict:
        """
        Save incident and pause for operator approval.
        Governance Rule 11: No autonomous resource termination.
        """
        if state.get("error"):
            log.error("[Agent06] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

        savings_str = _format_currency(state.get("estimated_monthly_savings", 0), state.get("currency", "USD"))
        raw_log = (
            f"Cloud: {state['cloud_provider'].upper()}\n"
            f"Billing Period: {state['billing_period']}\n"
            f"Total Spend: {_format_currency(state['total_spend'], state.get('currency', 'USD'))}\n"
            f"Estimated Monthly Savings: {savings_str}\n"
            f"Recommendations: {len(state.get('recommendations') or [])}\n\n"
            f"Cost Summary (excerpt):\n{state['cost_data_summary'][:400]}"
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
            "[Agent06] HITL gate — incident %s | estimated_savings=%s",
            incident_id, savings_str,
        )

        selected_option = interrupt({
            "incident_id": incident_id,
            "message": "Awaiting operator approval",
            "options": state["remediation_options"],
            "estimated_monthly_savings": state.get("estimated_monthly_savings"),
            "recommendations_count": len(state.get("recommendations") or []),
        })

        return {
            "incident_id": incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: FinOpsState) -> dict:
        """Execute the approved FinOps action."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent06] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        cloud     = state["cloud_provider"]
        log.info("[Agent06] Executing approved option: %s (cloud=%s)", option_id, cloud)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        owner, _, repo = state.get("repository", "/").partition("/")

        savings_str = _format_currency(state.get("estimated_monthly_savings", 0), state.get("currency", "USD"))
        report_title = (
            f"FinOps: {state['billing_period']} Cost Optimization — "
            f"{savings_str}/mo potential savings ({cloud.upper()})"
        )
        report_body = _build_report_body(
            billing_period=state["billing_period"],
            account_id=state["account_id"],
            cloud=cloud,
            total_spend=state["total_spend"],
            currency=state.get("currency", "USD"),
            estimated_monthly_savings=state.get("estimated_monthly_savings", 0),
            recommendations=state.get("recommendations") or [],
            cost_report=state.get("cost_report", ""),
        )

        slack_message = (
            f":money_with_wings: *Cloud Decoded FinOps Alert*\n"
            f"*Cloud:* {cloud.upper()} | *Period:* {state['billing_period']}\n"
            f"*Total Spend:* {_format_currency(state['total_spend'], state.get('currency', 'USD'))}\n"
            f"*Potential Savings:* {savings_str}/mo\n"
            f"*Top Recommendation:* {(state.get('recommendations') or [{}])[0].get('title', 'See report')}"
        )

        context = {
            "cloud_provider": cloud,
            "owner": owner,
            "repo": repo,
            "report_title": report_title,
            "report_body": report_body,
            "slack_message": slack_message,
            "quick_win_resources": state.get("quick_win_resources") or {},
            "subscription_id": state["account_id"] if cloud == "azure" else "",
            "project": state["account_id"] if cloud in ("gcp", "google") else "",
            "resource_group": (state.get("quick_win_resources") or {}).get("resource_group", ""),
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: FinOpsState) -> dict:
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
        log.info("[Agent06] Workflow complete for incident %s", incident_id)
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
        Trigger the FinOps optimization workflow.
        Returns incident_id after the HITL gate pause.
        """
        import uuid

        initial_state: FinOpsState = {
            "workspace_id": self.workspace_id,
            "cloud_provider": cloud_provider,
            "webhook_payload": payload,
            "billing_period": "",
            "account_id": "",
            "repository": "",
            "currency": "USD",
            "cost_data_summary": "",
            "resource_inventory": "",
            "total_spend": 0.0,
            "incident_id": None,
            "parsed_error": None,
            "cost_report": None,
            "recommendations": None,
            "quick_win_resources": None,
            "estimated_monthly_savings": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "tokens_used": 0,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

        thread_id = str(uuid.uuid4())
        config    = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent06] Starting FinOps workflow — thread_id=%s", thread_id)

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

        log.info("[Agent06] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info(
            "[Agent06] Resuming thread=%s with option=%s",
            thread_id, selected_option.get("id"),
        )
        result = await self._graph.ainvoke(
            Command(resume=selected_option),
            config=config,
        )
        return result.get("execution_result", {"status": "completed"})


# ──────────────────────────────────────────────
# Report body builder
# ──────────────────────────────────────────────

def _build_report_body(
    billing_period: str,
    account_id: str,
    cloud: str,
    total_spend: float,
    currency: str,
    estimated_monthly_savings: float,
    recommendations: list,
    cost_report: str,
) -> str:
    recs_block = ""
    for i, rec in enumerate(recommendations[:10], 1):
        savings = rec.get("estimated_monthly_savings", 0)
        recs_block += (
            f"{i}. **{rec.get('title', 'Recommendation')}** — "
            f"Save {_format_currency(savings, currency)}/mo\n"
            f"   {rec.get('description', '')}\n\n"
        )
    if len(recommendations) > 10:
        recs_block += f"*... and {len(recommendations) - 10} more recommendations. See full report below.*\n\n"

    return (
        f"## Cloud Decoded — FinOps Cost Optimization Report\n\n"
        f"**Cloud:** {cloud.upper()} | **Period:** {billing_period} | "
        f"**Account:** `{account_id}`\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Total Spend | {_format_currency(total_spend, currency)} |\n"
        f"| Potential Monthly Savings | {_format_currency(estimated_monthly_savings, currency)} |\n"
        f"| Annualized Savings | {_format_currency(estimated_monthly_savings * 12, currency)} |\n\n"
        f"## Top Recommendations\n\n"
        f"{recs_block}"
        f"## Full Analysis\n\n"
        f"{cost_report}\n\n"
        f"---\n"
        f"*Generated by Cloud Decoded Agent 06. Review and validate before applying changes.*"
    )
