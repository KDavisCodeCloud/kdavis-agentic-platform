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
Agent 09 — Context-Aware Onboarding & On-Call Buddy
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

Two query modes:
  onboarding — answers architecture/process questions for new engineers by
               searching the repo for docs, READMEs, and runbook content
  on_call    — provides a rapid context brief when an engineer is paged: relevant
               runbooks, past incident patterns, diagnostic steps, escalation paths

Knowledge retrieval happens inside _diagnose_node (pre-HITL, read-only):
  - GitHub Search API for relevant docs/runbooks
  - DB query for past incidents matching the service name

HITL gate controls publishing: the synthesized response is shown to the operator
who approves saving it as a GitHub issue or posting it to Slack (or holds/discards).

Governance Rule 11: no content is published or shared without operator approval.
"""

import json
import logging
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_09_onboarding_buddy.tools import OnboardingTools
from core.security import shield

log = logging.getLogger(__name__)

_MAX_QUESTION_CHARS  = 2_000
_MAX_SNIPPET_CHARS   = 1_500   # per knowledge snippet
_MAX_SNIPPETS        = 5       # max files to include in LLM context
_MAX_INCIDENTS       = 5       # max past incidents to include
_MAX_INCIDENT_CHARS  = 200     # excerpt length per past incident


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class OnboardingState(TypedDict):
    # Inputs
    workspace_id: str
    cloud_provider: str
    webhook_payload: dict

    # Extracted by ingest
    query_type: str       # onboarding | on_call
    question: str         # sanitized question or alert text
    service_name: str     # which service/component the question is about
    user_role: str        # new_engineer | on_call | manager | any
    repository: str       # "owner/repo" for knowledge search and issue creation
    slack_channel: str    # optional Slack channel override

    # Gathered by diagnose (pre-LLM knowledge retrieval)
    knowledge_snippets: list     # [{path, url, content}]
    past_incidents: list         # [{id, parsed_error, cloud_provider, created_at}]

    # After diagnose (LLM output)
    incident_id: Optional[str]
    parsed_error: Optional[str]      # one-line summary of the query topic
    synthesized_response: Optional[str]
    key_findings: Optional[str]      # 2-3 sentence digest for HITL display
    references: Optional[list]       # [{source, url, excerpt}]
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

_ON_CALL_KEYWORDS = frozenset({
    "alert", "paged", "page", "incident", "on-call", "oncall", "on_call",
    "down", "degraded", "latency", "error rate", "oomkilled", "crashloopbackoff",
    "timeout", "high cpu", "high memory", "disk full", "pod failed", "500",
    "crash", "restart", "unhealthy", "not responding", "failed", "outage",
})


def _detect_query_type(payload: dict) -> str:
    """
    Determine whether this is an onboarding query or on-call support request.
    Explicit query_type field takes priority over keyword detection.
    """
    explicit = payload.get("query_type", "").lower()
    if explicit in ("onboarding", "on_call"):
        return explicit
    text = " ".join([
        str(payload.get("question", "")),
        str(payload.get("alert", "")),
        str(payload.get("incident_context", "")),
    ]).lower()
    if any(kw in text for kw in _ON_CALL_KEYWORDS):
        return "on_call"
    return "onboarding"


# ──────────────────────────────────────────────
# Workflow class
# ──────────────────────────────────────────────

class OnboardingWorkflow(BaseAgent):
    """
    Agent 09: Context-Aware Onboarding & On-Call Buddy.

    Usage:
        workflow = OnboardingWorkflow(db_conn, workspace_id, checkpointer)
        incident_id = await workflow.run({
            "query_type": "onboarding",          # or "on_call"
            "question": "How does payment-service handle failed transactions?",
            "service_name": "payment-service",
            "user_role": "new_engineer",
            "repository": "acme/backend",
            "slack_channel": "#eng-onboarding",  # optional
        }, cloud_provider="aws")
        await workflow.resume(thread_id, selected_option)
    """

    AGENT_ID = "agent_09_onboarding_buddy"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer    = checkpointer
        self._tools           = OnboardingTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph           = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(OnboardingState)

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

    async def _ingest_node(self, state: OnboardingState) -> dict:
        """
        Parse payload fields and sanitize the user's question.
        Knowledge retrieval (GitHub search, incident DB query) happens in diagnose.
        """
        payload = state["webhook_payload"]

        query_type   = _detect_query_type(payload)
        service_name = payload.get("service_name", "")
        user_role    = payload.get("user_role", "any")
        repository   = payload.get("repository", "")
        slack_channel = payload.get("slack_channel", "")

        raw_question = (
            payload.get("question")
            or payload.get("alert")
            or payload.get("incident_context")
            or ""
        )
        if len(raw_question) > _MAX_QUESTION_CHARS:
            raw_question = raw_question[:_MAX_QUESTION_CHARS] + " ... [truncated]"

        sanitized = shield.sanitize(raw_question, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent09] Ingested query: type=%s service=%s role=%s",
            query_type, service_name, user_role,
        )

        return {
            "query_type":         query_type,
            "question":           sanitized.sanitized_text,
            "service_name":       service_name,
            "user_role":          user_role,
            "repository":         repository,
            "slack_channel":      slack_channel,
            "knowledge_snippets": [],
            "past_incidents":     [],
            "tokens_used":        0,
            "incident_id":        None,
            "parsed_error":       None,
            "synthesized_response": None,
            "key_findings":       None,
            "references":         None,
            "remediation_options": None,
            "selected_option":    None,
            "execution_result":   None,
            "error":              None,
        }

    async def _diagnose_node(self, state: OnboardingState) -> dict:
        """
        1. Retrieve knowledge snippets from GitHub (read-only).
        2. Fetch past incidents from DB (read-only).
        3. Call LLM to synthesize a contextual response.
        """
        owner, _, repo = state["repository"].partition("/")

        # ── Knowledge retrieval (pre-LLM) ──
        knowledge_snippets: list[dict] = []
        if owner and repo and self._tools.github_token:
            search_query = f"{state['service_name']} {state['question'][:80]}"
            file_refs = await self._tools.search_github_files(owner, repo, search_query)
            for ref in file_refs[:_MAX_SNIPPETS]:
                file_data = await self._tools.get_github_file(owner, repo, ref["path"])
                if "content" in file_data:
                    knowledge_snippets.append({
                        "path":    file_data["path"],
                        "url":     file_data["url"],
                        "content": file_data["content"][:_MAX_SNIPPET_CHARS],
                    })

        # ── Past incidents (from DB) ──
        past_incidents = await self._fetch_past_incidents(state["service_name"])

        # ── Build LLM context ──
        snippets_text = ""
        if knowledge_snippets:
            snippets_text = "\n\n".join(
                f"### {s['path']}\n```\n{s['content']}\n```"
                for s in knowledge_snippets
            )
        else:
            snippets_text = "(no relevant documentation found in repository)"

        incidents_text = ""
        if past_incidents:
            incidents_text = "\n".join(
                f"- [{i.get('cloud_provider', '?')}] {str(i.get('parsed_error', '?'))[:_MAX_INCIDENT_CHARS]}"
                for i in past_incidents
            )
        else:
            incidents_text = "(no relevant past incidents found)"

        user_message = (
            f"Query Type: {state['query_type']}\n"
            f"User Role: {state['user_role']}\n"
            f"Service / Component: {state['service_name'] or 'not specified'}\n\n"
            f"## Question / Alert\n\n"
            f"{state['question'] or '(no question provided)'}\n\n"
            f"## Relevant Documentation\n\n"
            f"{snippets_text}\n\n"
            f"## Recent Past Incidents (same workspace)\n\n"
            f"{incidents_text}\n\n"
            f"Synthesize a complete, actionable response tailored to the user's role and query type. "
            f"Return exactly the JSON format specified in the system prompt."
        )

        await self.check_budget(estimated_tokens=6000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="onboarding_support",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="onboarding_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {
                "knowledge_snippets": knowledge_snippets,
                "past_incidents": past_incidents,
                "error": str(exc),
                "tokens_used": estimated_tokens,
            }

        parsed_error          = diagnosis.get("parsed_error", f"Knowledge brief for: {state['question'][:60]}")
        synthesized_response  = diagnosis.get("synthesized_response", "")
        key_findings          = diagnosis.get("key_findings", "")
        references            = diagnosis.get("references", [])
        options               = diagnosis.get("options", [])

        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent09] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info(
            "[Agent09] Synthesized response: %d chars, %d references, %d snippets",
            len(synthesized_response), len(references), len(knowledge_snippets),
        )

        return {
            "knowledge_snippets":  knowledge_snippets,
            "past_incidents":      past_incidents,
            "parsed_error":        parsed_error,
            "synthesized_response": synthesized_response,
            "key_findings":        key_findings,
            "references":          references,
            "remediation_options": options,
            "tokens_used":         state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: OnboardingState) -> dict:
        """
        Present the synthesized response to the operator for review.
        Governance Rule 11: no content is published or shared without approval.
        """
        if state.get("error"):
            log.error("[Agent09] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

        raw_log = (
            f"Knowledge Brief — {state['query_type'].upper()}\n"
            f"Service: {state['service_name'] or 'not specified'}\n"
            f"Role: {state['user_role']}\n"
            f"Repository: {state['repository'] or 'not specified'}\n"
            f"Snippets Retrieved: {len(state.get('knowledge_snippets') or [])}\n"
            f"Past Incidents: {len(state.get('past_incidents') or [])}\n\n"
            f"Question:\n{state['question'][:300]}\n\n"
            f"Key Findings:\n{state.get('key_findings', '')[:400]}"
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
            "[Agent09] HITL gate — incident %s | query_type=%s service=%s",
            incident_id, state["query_type"], state["service_name"],
        )

        selected_option = interrupt({
            "incident_id":        incident_id,
            "message":            "Review synthesized knowledge brief and approve publishing action",
            "options":            state["remediation_options"],
            "query_type":         state["query_type"],
            "snippets_retrieved": len(state.get("knowledge_snippets") or []),
        })

        return {
            "incident_id":    incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: OnboardingState) -> dict:
        """Execute the approved publishing action."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent09] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        log.info("[Agent09] Executing approved option: %s", option_id)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        owner, _, repo = state["repository"].partition("/")

        service_label = state["service_name"] or "general"
        query_label   = "On-Call Brief" if state["query_type"] == "on_call" else "Onboarding Guide"
        issue_title   = f"{query_label}: {service_label} — {state['question'][:60]}"

        report_body = _build_knowledge_brief(
            query_type=state["query_type"],
            question=state["question"],
            service_name=state["service_name"],
            user_role=state["user_role"],
            synthesized_response=state.get("synthesized_response", ""),
            key_findings=state.get("key_findings", ""),
            references=state.get("references") or [],
            knowledge_snippets=state.get("knowledge_snippets") or [],
            past_incidents=state.get("past_incidents") or [],
        )

        context = {
            "query_type":   state["query_type"],
            "owner":        owner,
            "repo":         repo,
            "issue_title":  issue_title,
            "report_body":  report_body,
            "slack_message": f"*{issue_title}*\n\n{state.get('key_findings', '')}",
            "slack_channel": state.get("slack_channel", ""),
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: OnboardingState) -> dict:
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
        log.info("[Agent09] Workflow complete for incident %s", incident_id)
        return {}

    # ──────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────

    async def _fetch_past_incidents(self, service_name: str) -> list[dict]:
        """
        Query recent workspace incidents, filtered by service_name when possible.
        Returns a list of dicts with id, parsed_error, cloud_provider, created_at.
        Fails gracefully — never raises.
        """
        import uuid as _uuid
        try:
            ws_uuid = _uuid.UUID(self.workspace_id)
            if service_name:
                rows = await self.db.fetch(
                    "SELECT id, parsed_error, cloud_provider, created_at "
                    "FROM incidents "
                    "WHERE workspace_id = $1 AND parsed_error ILIKE $2 "
                    "ORDER BY created_at DESC LIMIT $3",
                    ws_uuid, f"%{service_name}%", _MAX_INCIDENTS,
                )
            else:
                rows = await self.db.fetch(
                    "SELECT id, parsed_error, cloud_provider, created_at "
                    "FROM incidents "
                    "WHERE workspace_id = $1 "
                    "ORDER BY created_at DESC LIMIT $2",
                    ws_uuid, _MAX_INCIDENTS,
                )
            return [dict(r) for r in (rows or [])]
        except Exception as exc:
            log.warning("[Agent09] Could not fetch past incidents: %s", exc)
            return []

    # ──────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────

    async def run(
        self,
        payload: dict,
        cloud_provider: str = "aws",
        byok_encrypted_key: Optional[str] = None,
    ) -> str:
        """Trigger the onboarding/on-call workflow. Returns incident_id after HITL pause."""
        import uuid

        initial_state: OnboardingState = {
            "workspace_id":       self.workspace_id,
            "cloud_provider":     cloud_provider,
            "webhook_payload":    payload,
            "query_type":         "",
            "question":           "",
            "service_name":       "",
            "user_role":          "any",
            "repository":         "",
            "slack_channel":      "",
            "knowledge_snippets": [],
            "past_incidents":     [],
            "incident_id":        None,
            "parsed_error":       None,
            "synthesized_response": None,
            "key_findings":       None,
            "references":         None,
            "remediation_options": None,
            "tokens_used":        0,
            "selected_option":    None,
            "execution_result":   None,
            "error":              None,
        }

        thread_id = str(uuid.uuid4())
        config    = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent09] Starting onboarding/on-call workflow — thread_id=%s", thread_id)

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

        log.info("[Agent09] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info("[Agent09] Resuming thread=%s with option=%s", thread_id, selected_option.get("id"))
        result = await self._graph.ainvoke(Command(resume=selected_option), config=config)
        return result.get("execution_result", {"status": "completed"})


# ──────────────────────────────────────────────
# Report builder
# ──────────────────────────────────────────────

def _build_knowledge_brief(
    query_type: str,
    question: str,
    service_name: str,
    user_role: str,
    synthesized_response: str,
    key_findings: str,
    references: list,
    knowledge_snippets: list,
    past_incidents: list,
) -> str:
    type_label = "On-Call Brief" if query_type == "on_call" else "Onboarding Guide"

    refs_section = ""
    if references:
        refs_section = "\n\n### References\n\n" + "\n".join(
            f"- [{r.get('source', '?')}]({r.get('url', '')})"
            + (f": _{r.get('excerpt', '')[:100]}_" if r.get("excerpt") else "")
            for r in references
        )

    snippets_section = ""
    if knowledge_snippets:
        snippets_section = f"\n\n### Docs Retrieved ({len(knowledge_snippets)} files)\n\n" + "\n".join(
            f"- [`{s.get('path', '?')}`]({s.get('url', '')})"
            for s in knowledge_snippets
        )

    incidents_section = ""
    if past_incidents:
        incidents_section = f"\n\n### Past Incidents ({len(past_incidents)} found)\n\n" + "\n".join(
            f"- [{i.get('cloud_provider', '?')}] {str(i.get('parsed_error', '?'))[:150]}"
            for i in past_incidents
        )

    return (
        f"## Cloud Decoded — {type_label}\n\n"
        f"**Service:** {service_name or '_not specified_'}  \n"
        f"**User Role:** {user_role}  \n"
        f"**Query Type:** {query_type}\n\n"
        f"### Question / Alert\n\n"
        f"> {question}\n\n"
        f"### Key Findings\n\n"
        f"{key_findings or '_Not available_'}\n\n"
        f"### Full Response\n\n"
        f"{synthesized_response or '_Not available_'}"
        f"{refs_section}"
        f"{snippets_section}"
        f"{incidents_section}\n\n"
        f"---\n"
        f"*Generated by Cloud Decoded Agent 09. Review before sharing with your team.*"
    )
