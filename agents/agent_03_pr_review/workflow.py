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
Agent 03 — PR Review for Architecture & Security
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

The ingest node fetches the PR diff from GitHub so the diagnose node has
full file-level context for the LLM review.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, TypedDict

import httpx

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_03_pr_review.tools import PRReviewTools, _gh_headers
from core.security import shield

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"

# Maximum diff characters sent to LLM — keeps tokens reasonable
_MAX_DIFF_CHARS = 12_000
# Maximum changed files included in full detail
_MAX_FILES_DETAIL = 20


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class PRReviewState(TypedDict):
    # Inputs
    workspace_id: str
    cloud_provider: str          # "github" | "azure_devops" (future)
    webhook_payload: dict

    # Extracted by ingest
    owner: str
    repo: str
    pr_number: int
    pr_title: str
    pr_description: str
    pr_author: str
    base_branch: str
    head_branch: str
    head_sha: str
    changed_files_count: int
    diff_summary: str            # truncated diff sent to LLM

    # After diagnose
    incident_id: Optional[str]
    parsed_error: Optional[str]  # one-sentence finding headline
    review_body: Optional[str]   # full markdown review for GitHub
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
# Diff formatting
# ──────────────────────────────────────────────

def _build_diff_summary(files: list[dict], max_chars: int = _MAX_DIFF_CHARS) -> str:
    """
    Assemble a truncated diff summary for LLM context.
    Prioritizes files with most changes; truncates large patches.
    """
    # Sort by total changes descending — most-changed files first
    sorted_files = sorted(files, key=lambda f: f.get("changes", 0), reverse=True)
    detail_files = sorted_files[:_MAX_FILES_DETAIL]

    lines = [
        f"Changed files: {len(files)} total",
        "",
    ]
    chars_used = 0

    for f in detail_files:
        header = (
            f"--- {f['filename']} "
            f"[{f.get('status', 'modified')} +{f.get('additions', 0)} -{f.get('deletions', 0)}]"
        )
        lines.append(header)

        patch = f.get("patch", "")
        if patch:
            remaining = max_chars - chars_used - len(header)
            if remaining > 200:
                chunk = patch[:remaining]
                if len(patch) > remaining:
                    chunk += "\n... [truncated]"
                lines.append(chunk)
                chars_used += len(chunk)
        else:
            lines.append("[binary or large file — no patch available]")

        lines.append("")
        if chars_used >= max_chars:
            lines.append(f"... [{len(files) - len(detail_files)} more files not shown]")
            break

    return "\n".join(lines)


# ──────────────────────────────────────────────
# Workflow class
# ──────────────────────────────────────────────

class PRReviewWorkflow(BaseAgent):
    """
    Agent 03: PR Review for Architecture & Security.

    Usage:
        workflow = PRReviewWorkflow(db_conn, workspace_id, checkpointer)
        incident_id = await workflow.run(webhook_payload)
        await workflow.resume(incident_id, selected_option)
    """

    AGENT_ID = "agent_03_pr_review"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer = checkpointer
        self._tools = PRReviewTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(PRReviewState)

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

    async def _ingest_node(self, state: PRReviewState) -> dict:
        """
        Extract PR metadata from webhook payload and fetch the diff from GitHub.
        The diff is the raw material for the LLM code review.
        """
        payload = state["webhook_payload"]
        pr = payload.get("pull_request", {})
        repo_info = payload.get("repository", {})

        full_name = repo_info.get("full_name", "/")
        owner, _, repo = full_name.partition("/")

        pr_number = pr.get("number", 0)
        pr_title = pr.get("title", "")
        pr_description = (pr.get("body") or "")[:500]
        pr_author = pr.get("user", {}).get("login", "unknown")
        base_branch = pr.get("base", {}).get("ref", "main")
        head_branch = pr.get("head", {}).get("ref", "")
        head_sha = pr.get("head", {}).get("sha", "")

        diff_summary = ""
        changed_files_count = 0

        if pr_number and owner and repo:
            try:
                files = await self._tools.get_pr_files(owner, repo, pr_number)
                changed_files_count = len(files)
                diff_summary = _build_diff_summary(files)
            except Exception as exc:
                log.warning("[Agent03] Could not fetch PR diff: %s", exc)
                diff_summary = f"Diff unavailable: {exc}"

        # Sanitize before LLM — PR diffs can contain credentials
        sanitized = shield.sanitize(diff_summary, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent03] Ingested PR#%d %s/%s — %d files changed",
            pr_number, owner, repo, changed_files_count,
        )

        return {
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "pr_title": pr_title,
            "pr_description": pr_description,
            "pr_author": pr_author,
            "base_branch": base_branch,
            "head_branch": head_branch,
            "head_sha": head_sha,
            "changed_files_count": changed_files_count,
            "diff_summary": sanitized.sanitized_text,
            "tokens_used": 0,
            "incident_id": None,
            "parsed_error": None,
            "review_body": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

    async def _diagnose_node(self, state: PRReviewState) -> dict:
        """Call LLM to review the PR diff for architecture and security issues."""
        user_message = (
            f"Pull Request Review Request:\n\n"
            f"Repository: {state['owner']}/{state['repo']}\n"
            f"PR #{state['pr_number']}: {state['pr_title']}\n"
            f"Author: {state['pr_author']}\n"
            f"Base: {state['base_branch']} ← Head: {state['head_branch']}\n"
            f"Files changed: {state['changed_files_count']}\n\n"
            f"PR Description:\n{state['pr_description']}\n\n"
            f"Diff:\n{state['diff_summary']}\n\n"
            f"Review this PR for architecture and security issues. Return exactly the JSON format specified."
        )

        # PR diffs can be large — budget for more tokens
        await self.check_budget(estimated_tokens=6000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="code_review",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="pr_review_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {"error": str(exc), "tokens_used": estimated_tokens}

        parsed_error = diagnosis.get("parsed_error", "PR review complete")
        review_body = diagnosis.get("review_body", parsed_error)
        options = diagnosis.get("options", [])
        duration = diagnosis.get("estimated_duration_seconds", 10)

        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent03] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info("[Agent03] Review complete: %s (options=%d)", parsed_error[:80], len(options))

        return {
            "parsed_error": parsed_error,
            "review_body": review_body,
            "remediation_options": options,
            "estimated_duration_seconds": duration,
            "tokens_used": state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: PRReviewState) -> dict:
        """
        Save incident to DB and pause for operator approval.
        Governance Rule 11: No autonomous remediation.
        """
        if state.get("error"):
            log.error("[Agent03] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

        incident_id = await self.hitl.create_incident(
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            raw_log=state["diff_summary"],
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
        log.info("[Agent03] HITL gate — incident %s awaiting operator approval", incident_id)

        selected_option = interrupt({
            "incident_id": incident_id,
            "message": "Awaiting operator approval",
            "options": state["remediation_options"],
        })

        return {
            "incident_id": incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: PRReviewState) -> dict:
        """Post the approved review action to GitHub. Only reached after human approval."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent03] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        log.info("[Agent03] Executing approved option: %s", option_id)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        context = {
            "owner": state["owner"],
            "repo": state["repo"],
            "pr_number": state["pr_number"],
            "review_body": state.get("review_body") or state.get("parsed_error", ""),
            "head_sha": state.get("head_sha"),
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: PRReviewState) -> dict:
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
        log.info("[Agent03] Workflow complete for incident %s", incident_id)
        return {}

    # ──────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────

    async def run(
        self,
        payload: dict,
        cloud_provider: str = "github",
        byok_encrypted_key: Optional[str] = None,
    ) -> str:
        """
        Trigger the PR review workflow from a GitHub pull_request webhook payload.
        Returns incident_id after the HITL gate pause.
        """
        import uuid

        initial_state: PRReviewState = {
            "workspace_id": self.workspace_id,
            "cloud_provider": cloud_provider,
            "webhook_payload": payload,
            "owner": "",
            "repo": "",
            "pr_number": 0,
            "pr_title": "",
            "pr_description": "",
            "pr_author": "",
            "base_branch": "",
            "head_branch": "",
            "head_sha": "",
            "changed_files_count": 0,
            "diff_summary": "",
            "incident_id": None,
            "parsed_error": None,
            "review_body": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "tokens_used": 0,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent03] Starting PR review workflow — thread_id=%s", thread_id)

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

        log.info("[Agent03] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info(
            "[Agent03] Resuming workflow thread=%s with option=%s",
            thread_id, selected_option.get("id"),
        )

        result = await self._graph.ainvoke(
            Command(resume=selected_option),
            config=config,
        )

        return result.get("execution_result", {"status": "completed"})
