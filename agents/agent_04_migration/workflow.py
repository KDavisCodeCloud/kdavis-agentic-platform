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
Agent 04 — Legacy Code & Infrastructure Migration
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

Primarily triggered manually via POST /agents/agent_04_migration/run.
Accepts a code or infrastructure file (or excerpt) and produces:
  - A migration plan
  - Migrated code (for single-file migrations)
  - Post-approval options: create PR | create tracking issue | hold
"""

import logging
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_04_migration.tools import MigrationTools
from core.security import shield

log = logging.getLogger(__name__)

# Maximum source code characters to send to LLM
_MAX_CODE_CHARS = 10_000


# ──────────────────────────────────────────────
# Language / type detection
# ──────────────────────────────────────────────

_EXT_TO_LANGUAGE = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "go": "go", "java": "java", "rb": "ruby", "rs": "rust",
    "tf": "hcl", "yaml": "yaml", "yml": "yaml",
    "json": "json", "sh": "shell", "bash": "shell",
    "dockerfile": "dockerfile",
}

_DOCKER_NAMES = {"docker-compose", "compose", "dockerfile"}


def _detect_language(file_path: str) -> str:
    name = file_path.rsplit("/", 1)[-1].lower()
    if name == "dockerfile" or name.startswith("dockerfile."):
        return "dockerfile"
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    return _EXT_TO_LANGUAGE.get(ext, "unknown")


def _detect_source_type(file_path: str, language: str) -> str:
    if language == "hcl":
        return "terraform"
    if language == "dockerfile":
        return "docker"
    if language == "yaml":
        name = file_path.rsplit("/", 1)[-1].lower().replace(".yaml", "").replace(".yml", "")
        if any(k in name for k in _DOCKER_NAMES):
            return "docker"
        if any(k in name for k in ("deployment", "service", "ingress", "configmap", "statefulset")):
            return "kubernetes"
        return "yaml"
    return "code"


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class MigrationState(TypedDict):
    # Inputs
    workspace_id: str
    cloud_provider: str
    webhook_payload: dict

    # Extracted by ingest
    source_type: str         # "code" | "terraform" | "kubernetes" | "docker" | "yaml"
    source_language: str     # "python" | "javascript" | "hcl" | "yaml" | ...
    repository: str          # "owner/repo"
    file_path: str           # path within the repo
    source_version: str      # e.g. "flask" | "terraform 0.12" | "python2.7"
    target_version: str      # e.g. "fastapi" | "terraform 1.x" | "python3.11"
    migration_context: str   # operator-provided description of the migration goal
    code_excerpt: str        # sanitized source code sent to LLM

    # After diagnose
    incident_id: Optional[str]
    parsed_error: Optional[str]  # migration summary headline
    migration_plan: Optional[str]  # step-by-step plan (markdown)
    migrated_code: Optional[str]   # LLM-generated transformed code
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
# Workflow class
# ──────────────────────────────────────────────

class MigrationWorkflow(BaseAgent):
    """
    Agent 04: Legacy Code & Infrastructure Migration.

    Usage:
        workflow = MigrationWorkflow(db_conn, workspace_id, checkpointer)
        # Manual trigger:
        incident_id = await workflow.run({
            "file_path": "src/api/routes.py",
            "file_content": "...",
            "source_version": "flask",
            "target_version": "fastapi",
            "repository": "acme/backend",
        })
        await workflow.resume(incident_id, selected_option)
    """

    AGENT_ID = "agent_04_migration"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer = checkpointer
        self._tools = MigrationTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(MigrationState)

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

    async def _ingest_node(self, state: MigrationState) -> dict:
        """
        Extract migration target fields from the payload.
        Detects language and source_type from file extension.
        Sanitizes the source code before it reaches the LLM.
        """
        payload = state["webhook_payload"]

        file_path = payload.get("file_path", "")
        file_content = payload.get("file_content", "")
        repository = payload.get("repository", "")
        source_version = payload.get("source_version", "")
        target_version = payload.get("target_version", "")
        migration_context = payload.get("migration_context", "")

        # Override source_type/language if explicitly provided, otherwise detect
        source_language = payload.get("source_language") or _detect_language(file_path)
        source_type = payload.get("source_type") or _detect_source_type(file_path, source_language)

        # Truncate if enormous
        if len(file_content) > _MAX_CODE_CHARS:
            file_content = file_content[:_MAX_CODE_CHARS] + "\n... [truncated]"

        # Sanitize — source code can contain hardcoded secrets
        sanitized = shield.sanitize(file_content, context=self.agent_id)

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent04] Ingested: file=%s type=%s %s→%s",
            file_path, source_type, source_version, target_version,
        )

        return {
            "source_type": source_type,
            "source_language": source_language,
            "repository": repository,
            "file_path": file_path,
            "source_version": source_version,
            "target_version": target_version,
            "migration_context": migration_context,
            "code_excerpt": sanitized.sanitized_text,
            "tokens_used": 0,
            "incident_id": None,
            "parsed_error": None,
            "migration_plan": None,
            "migrated_code": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

    async def _diagnose_node(self, state: MigrationState) -> dict:
        """
        Call LLM to analyze the source code and produce:
        - A migration summary (parsed_error)
        - A step-by-step migration plan (migration_plan)
        - The migrated code (migrated_code), if single-file
        - Options for what to do next
        """
        user_message = (
            f"Migration Request:\n\n"
            f"Repository: {state['repository']}\n"
            f"File: {state['file_path']}\n"
            f"Language: {state['source_language']}\n"
            f"Type: {state['source_type']}\n"
            f"From: {state['source_version']}\n"
            f"To: {state['target_version']}\n"
            f"Context: {state['migration_context']}\n\n"
            f"Source Code:\n```{state['source_language']}\n{state['code_excerpt']}\n```\n\n"
            f"Analyze this code and produce the migration. Return exactly the JSON format specified."
        )

        # Migration can involve large code — budget accordingly
        await self.check_budget(estimated_tokens=8000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="code_migration",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="migration_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {"error": str(exc), "tokens_used": estimated_tokens}

        parsed_error = diagnosis.get("parsed_error", "Migration analysis complete")
        migration_plan = diagnosis.get("migration_plan", "")
        migrated_code = diagnosis.get("migrated_code", "")
        options = diagnosis.get("options", [])
        duration = diagnosis.get("estimated_duration_seconds", 60)

        required_fields = {"id", "title", "description", "impact", "docs_url"}
        for opt in options:
            if not required_fields.issubset(opt.keys()):
                log.warning("[Agent04] Option missing required fields: %s", opt)

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info(
            "[Agent04] Migration analysis: %s (plan_len=%d, code_len=%d)",
            parsed_error[:80], len(migration_plan), len(migrated_code),
        )

        return {
            "parsed_error": parsed_error,
            "migration_plan": migration_plan,
            "migrated_code": migrated_code,
            "remediation_options": options,
            "estimated_duration_seconds": duration,
            "tokens_used": state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: MigrationState) -> dict:
        """
        Save incident to DB and pause for operator approval.
        Governance Rule 11: No autonomous remediation.
        """
        if state.get("error"):
            log.error("[Agent04] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

        incident_id = await self.hitl.create_incident(
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            raw_log=state["code_excerpt"],
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
        log.info("[Agent04] HITL gate — incident %s awaiting operator approval", incident_id)

        selected_option = interrupt({
            "incident_id": incident_id,
            "message": "Awaiting operator approval",
            "options": state["remediation_options"],
        })

        return {
            "incident_id": incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: MigrationState) -> dict:
        """Execute the approved migration action. Only reached after human approval."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent04] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        log.info("[Agent04] Executing approved option: %s", option_id)

        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        owner, _, repo = state["repository"].partition("/")
        source_v = state.get("source_version", "legacy")
        target_v = state.get("target_version", "modern")

        pr_title = f"chore(migrate): {state['file_path']} — {source_v} → {target_v}"
        pr_body = _build_pr_body(
            migration_plan=state.get("migration_plan", ""),
            source_version=source_v,
            target_version=target_v,
            file_path=state["file_path"],
        )

        context = {
            "owner": owner,
            "repo": repo,
            "file_path": state["file_path"],
            "migrated_code": state.get("migrated_code", ""),
            "migration_plan": state.get("migration_plan", ""),
            "source_version": source_v,
            "target_version": target_v,
            "pr_title": pr_title,
            "pr_body": pr_body,
            "issue_title": pr_title,
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: MigrationState) -> dict:
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
        log.info("[Agent04] Workflow complete for incident %s", incident_id)
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
        Trigger the migration workflow with a code/infrastructure payload.
        Returns incident_id after the HITL gate pause.
        """
        import uuid

        initial_state: MigrationState = {
            "workspace_id": self.workspace_id,
            "cloud_provider": cloud_provider,
            "webhook_payload": payload,
            "source_type": "",
            "source_language": "",
            "repository": "",
            "file_path": "",
            "source_version": "",
            "target_version": "",
            "migration_context": "",
            "code_excerpt": "",
            "incident_id": None,
            "parsed_error": None,
            "migration_plan": None,
            "migrated_code": None,
            "remediation_options": None,
            "estimated_duration_seconds": None,
            "tokens_used": 0,
            "selected_option": None,
            "execution_result": None,
            "error": None,
        }

        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent04] Starting migration workflow — thread_id=%s", thread_id)

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

        log.info("[Agent04] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info(
            "[Agent04] Resuming workflow thread=%s with option=%s",
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
    migration_plan: str,
    source_version: str,
    target_version: str,
    file_path: str,
) -> str:
    return (
        f"## Cloud Decoded — Migration: `{source_version}` → `{target_version}`\n\n"
        f"**File:** `{file_path}`\n\n"
        f"### Migration Plan\n\n"
        f"{migration_plan}\n\n"
        f"---\n"
        f"*Generated by Cloud Decoded Agent 04. Review and test before merging.*"
    )
