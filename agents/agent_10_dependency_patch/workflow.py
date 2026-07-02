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
Agent 10 — Dependency & Vulnerability Patching
LangGraph state machine with Postgres checkpointing and HITL interrupt gate.

State flow:
    START → ingest → diagnose → hitl_gate (interrupt) → execute → complete → END

Supported ecosystems: npm, pip, go, maven, ruby, cargo

Diagnose phase (read-only, pre-HITL):
  1. Fetch manifest from GitHub
  2. Parse dependencies via tools.parse_manifest()
  3. Query OSV.dev for each dependency (up to _MAX_OSV_QUERIES packages)
  4. Call LLM for analysis and patched manifest generation

HITL gate controls:
  opt_1 — Create Patch PR (updates manifest to fixed versions)
  opt_2 — Create Vulnerability Issue (tracking only, no code change)
  opt_3 — Create Patch PR + Vulnerability Issue
  hold  — Review only; operator handles manually

Governance Rule 11: no PR or issue is created without operator approval.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.base_agent import BaseAgent
from agents.agent_10_dependency_patch.tools import DependencyPatchTools

log = logging.getLogger(__name__)

_MAX_MANIFEST_CHARS = 8_000    # manifest content sent to LLM
_MAX_OSV_IN_PROMPT  = 20       # max vulnerable packages included in LLM context


# ──────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────

class PatchState(TypedDict):
    # Inputs
    workspace_id:    str
    cloud_provider:  str
    webhook_payload: dict

    # Extracted by ingest
    repository:    str       # "owner/repo"
    ecosystem:     str       # npm | pip | go | maven | ruby | cargo
    manifest_path: str       # path within repo, e.g. "requirements.txt"
    ref:           str       # git ref to scan (default: HEAD)
    base_branch:   str       # target branch for the patch PR

    # Gathered by diagnose
    manifest_content:    str        # raw manifest file content
    manifest_sha:        str        # GitHub blob SHA (needed for patch commit)
    parsed_dependencies: list       # [{name, version}]
    dependency_count:    int
    vulnerability_results: list     # [{package, version, vulnerabilities: [...]}]
    vulnerability_count: int        # number of packages with ≥1 vuln
    critical_count:      int
    high_count:          int

    # LLM output
    incident_id:          Optional[str]
    parsed_error:         Optional[str]
    patch_summary:        Optional[str]    # 2-3 sentence digest for HITL display
    vulnerable_packages:  Optional[list]   # [{package, current_version, fixed_version, severity, cve_ids, description}]
    patched_manifest:     Optional[str]    # full patched manifest content
    remediation_options:  Optional[list]

    tokens_used:      int
    selected_option:  Optional[dict]
    execution_result: Optional[dict]
    error:            Optional[str]


# ──────────────────────────────────────────────
# Ecosystem detection
# ──────────────────────────────────────────────

_ECOSYSTEM_FROM_FILENAME = {
    "package.json":       "npm",
    "package-lock.json":  "npm",
    "requirements.txt":   "pip",
    "pipfile":            "pip",
    "pipfile.lock":       "pip",
    "pyproject.toml":     "pip",
    "go.mod":             "go",
    "go.sum":             "go",
    "pom.xml":            "maven",
    "gemfile":            "ruby",
    "gemfile.lock":       "ruby",
    "cargo.toml":         "cargo",
    "cargo.lock":         "cargo",
}


def _detect_ecosystem(payload: dict) -> str:
    """
    Determine dependency ecosystem.
    Explicit 'ecosystem' field in the payload takes priority.
    Falls back to inference from the manifest filename.
    """
    explicit = payload.get("ecosystem", "").lower().strip()
    if explicit in _ECOSYSTEM_FROM_FILENAME.values():
        return explicit

    manifest_path = payload.get("manifest_path", "").lower()
    filename = manifest_path.split("/")[-1] if "/" in manifest_path else manifest_path
    return _ECOSYSTEM_FROM_FILENAME.get(filename, "unknown")


def _load_diagnose_prompt() -> str:
    path = Path(__file__).parent / "prompts" / "diagnose.md"
    return path.read_text()


# ──────────────────────────────────────────────
# Severity helpers
# ──────────────────────────────────────────────

def _count_severity(vulnerability_results: list, target: str) -> int:
    """Count packages that have at least one vulnerability at the given severity."""
    target = target.upper()
    return sum(
        1 for pkg in vulnerability_results
        if any(v.get("severity", "").upper() == target for v in pkg.get("vulnerabilities", []))
    )


# ──────────────────────────────────────────────
# Workflow class
# ──────────────────────────────────────────────

class DependencyPatchWorkflow(BaseAgent):
    """
    Agent 10: Dependency & Vulnerability Patching.

    Usage:
        workflow = DependencyPatchWorkflow(db_conn, workspace_id, checkpointer)
        incident_id = await workflow.run({
            "repository":    "acme/backend",
            "ecosystem":     "pip",             # or auto-detected from manifest_path
            "manifest_path": "requirements.txt",
            "ref":           "main",            # optional, default HEAD
            "base_branch":   "main",            # optional
        }, cloud_provider="aws")
        await workflow.resume(thread_id, selected_option)
    """

    AGENT_ID = "agent_10_dependency_patch"

    def __init__(self, db_conn, workspace_id: str, checkpointer: AsyncPostgresSaver):
        super().__init__(db_conn, workspace_id)
        self._checkpointer    = checkpointer
        self._tools           = DependencyPatchTools()
        self._diagnose_prompt = _load_diagnose_prompt()
        self._graph           = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(PatchState)

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

    async def _ingest_node(self, state: PatchState) -> dict:
        """Parse payload fields. Manifest is fetched in diagnose (allows richer error reporting)."""
        payload       = state["webhook_payload"]
        repository    = payload.get("repository", "")
        ecosystem     = _detect_ecosystem(payload)
        manifest_path = payload.get("manifest_path", "")
        ref           = payload.get("ref", "HEAD")
        base_branch   = payload.get("base_branch", "main")

        self._write_audit("ingest", "ok")
        log.info(
            "[Agent10] Ingested: repo=%s ecosystem=%s manifest=%s",
            repository, ecosystem, manifest_path,
        )

        return {
            "repository":            repository,
            "ecosystem":             ecosystem,
            "manifest_path":         manifest_path,
            "ref":                   ref,
            "base_branch":           base_branch,
            "manifest_content":      "",
            "manifest_sha":          "",
            "parsed_dependencies":   [],
            "dependency_count":      0,
            "vulnerability_results": [],
            "vulnerability_count":   0,
            "critical_count":        0,
            "high_count":            0,
            "tokens_used":           0,
            "incident_id":           None,
            "parsed_error":          None,
            "patch_summary":         None,
            "vulnerable_packages":   None,
            "patched_manifest":      None,
            "remediation_options":   None,
            "selected_option":       None,
            "execution_result":      None,
            "error":                 None,
        }

    async def _diagnose_node(self, state: PatchState) -> dict:
        """
        1. Fetch manifest from GitHub.
        2. Parse into dependency list.
        3. Query OSV.dev for vulnerabilities.
        4. Call LLM for analysis and patched manifest.
        """
        owner, _, repo = state["repository"].partition("/")
        if not owner or not repo:
            return {"error": f"Invalid repository '{state['repository']}' — expected owner/repo format"}

        # ── Fetch manifest ──
        manifest_data = await self._tools.fetch_manifest(
            owner, repo, state["manifest_path"], state["ref"]
        )
        if "error" in manifest_data:
            return {"error": f"Manifest fetch failed: {manifest_data['error']}"}

        manifest_content = manifest_data["content"]
        manifest_sha     = manifest_data["sha"]

        # ── Parse dependencies ──
        parsed_deps = self._tools.parse_manifest(manifest_content, state["ecosystem"])
        dependency_count = len(parsed_deps)

        # ── OSV vulnerability scan ──
        vulnerability_results = await self._tools.query_osv_batch(parsed_deps, state["ecosystem"])
        vulnerability_count = len(vulnerability_results)
        critical_count = _count_severity(vulnerability_results, "CRITICAL")
        high_count     = _count_severity(vulnerability_results, "HIGH")

        log.info(
            "[Agent10] Scan complete: %d deps, %d vulnerable, %d critical, %d high",
            dependency_count, vulnerability_count, critical_count, high_count,
        )

        # ── Build LLM context ──
        vuln_text = _format_osv_results_for_prompt(vulnerability_results[:_MAX_OSV_IN_PROMPT])
        manifest_excerpt = manifest_content[:_MAX_MANIFEST_CHARS]
        if len(manifest_content) > _MAX_MANIFEST_CHARS:
            manifest_excerpt += "\n... [truncated]"

        user_message = (
            f"Ecosystem: {state['ecosystem']}\n"
            f"Manifest Path: {state['manifest_path']}\n"
            f"Repository: {state['repository']}\n\n"
            f"## Manifest Content\n\n```\n{manifest_excerpt}\n```\n\n"
            f"## Vulnerability Scan Results (OSV.dev)\n\n"
            f"Total dependencies scanned: {dependency_count}\n"
            f"Vulnerable packages found: {vulnerability_count}\n"
            f"Critical: {critical_count} | High: {high_count}\n\n"
            f"{vuln_text}\n\n"
            f"Analyze the vulnerabilities, generate a patched manifest with vulnerable dependencies "
            f"updated to their fixed versions, and return the JSON format specified in the system prompt."
        )

        await self.check_budget(estimated_tokens=8000, model="claude-sonnet-4-20250514")

        response, estimated_tokens = self.call_llm(
            task_type="vulnerability_analysis",
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self._diagnose_prompt,
        )

        try:
            diagnosis = self.parse_llm_json(response, context="dependency_diagnose_node")
        except ValueError as exc:
            self._write_audit("diagnose", "parse_error")
            return {
                "manifest_content":      manifest_content,
                "manifest_sha":          manifest_sha,
                "parsed_dependencies":   parsed_deps,
                "dependency_count":      dependency_count,
                "vulnerability_results": vulnerability_results,
                "vulnerability_count":   vulnerability_count,
                "critical_count":        critical_count,
                "high_count":            high_count,
                "error":                 str(exc),
                "tokens_used":           estimated_tokens,
            }

        parsed_error       = diagnosis.get("parsed_error", f"Vulnerability scan: {vulnerability_count} packages affected")
        patch_summary      = diagnosis.get("patch_summary", "")
        vulnerable_packages = diagnosis.get("vulnerable_packages", [])
        patched_manifest   = diagnosis.get("patched_manifest", "")
        options            = diagnosis.get("options", [])

        self._write_audit("diagnose", "ok", tokens_used=estimated_tokens)
        log.info(
            "[Agent10] LLM analysis complete: %d vuln packages, patched manifest %d chars",
            len(vulnerable_packages), len(patched_manifest),
        )

        await self.record_token_usage(
            tokens_used=estimated_tokens,
            incident_id=None,
        )

        return {
            "manifest_content":      manifest_content,
            "manifest_sha":          manifest_sha,
            "parsed_dependencies":   parsed_deps,
            "dependency_count":      dependency_count,
            "vulnerability_results": vulnerability_results,
            "vulnerability_count":   vulnerability_count,
            "critical_count":        critical_count,
            "high_count":            high_count,
            "parsed_error":          parsed_error,
            "patch_summary":         patch_summary,
            "vulnerable_packages":   vulnerable_packages,
            "patched_manifest":      patched_manifest,
            "remediation_options":   options,
            "tokens_used":           state.get("tokens_used", 0) + estimated_tokens,
        }

    async def _hitl_gate_node(self, state: PatchState) -> dict:
        """
        Present vulnerability report to operator for approval.
        Governance Rule 11: no code change or issue creation without approval.
        """
        if state.get("error"):
            log.error("[Agent10] Skipping HITL gate due to upstream error: %s", state["error"])
            return {}

        severity_line = (
            f"CRITICAL: {state['critical_count']} | "
            f"HIGH: {state['high_count']} | "
            f"Total Vulnerable: {state['vulnerability_count']}"
        )

        raw_log = (
            f"Dependency Vulnerability Scan — {state['ecosystem'].upper()}\n"
            f"Repository: {state['repository']}\n"
            f"Manifest: {state['manifest_path']}\n"
            f"Dependencies Scanned: {state['dependency_count']}\n"
            f"{severity_line}\n\n"
            f"Patch Summary:\n{state.get('patch_summary', '')[:400]}"
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
            "[Agent10] HITL gate — incident=%s vuln_count=%d critical=%d",
            incident_id, state["vulnerability_count"], state["critical_count"],
        )

        selected_option = interrupt({
            "incident_id":        incident_id,
            "message":            "Review vulnerability scan and approve remediation action",
            "options":            state["remediation_options"],
            "vulnerability_count": state["vulnerability_count"],
            "critical_count":     state["critical_count"],
            "high_count":         state["high_count"],
        })

        return {
            "incident_id":    incident_id,
            "selected_option": selected_option,
        }

    async def _execute_node(self, state: PatchState) -> dict:
        """Execute the approved remediation action."""
        selected = state.get("selected_option")
        if not selected:
            log.warning("[Agent10] Execute node reached with no selected_option")
            return {"execution_result": {"status": "skipped", "reason": "no option selected"}}

        option_id = selected.get("id", "")
        self._write_audit(
            f"execute:{option_id}", "executing",
            incident_id=state.get("incident_id"),
        )

        owner, _, repo = state["repository"].partition("/")
        branch_name    = f"cloud-decoded/security-patch-{uuid.uuid4().hex[:8]}"

        report_body = _build_vulnerability_report(
            ecosystem=state["ecosystem"],
            repository=state["repository"],
            manifest_path=state["manifest_path"],
            dependency_count=state["dependency_count"],
            vulnerability_count=state["vulnerability_count"],
            critical_count=state["critical_count"],
            high_count=state["high_count"],
            vulnerable_packages=state.get("vulnerable_packages") or [],
            patch_summary=state.get("patch_summary", ""),
        )

        vuln_count = state["vulnerability_count"]
        crit       = state["critical_count"]
        pr_title   = (
            f"chore(deps): security patch — {vuln_count} vulnerable "
            f"{'dependency' if vuln_count == 1 else 'dependencies'}"
            + (f" ({crit} CRITICAL)" if crit else "")
        )
        issue_title = (
            f"[Security] {vuln_count} vulnerable "
            f"{'dependency' if vuln_count == 1 else 'dependencies'} in "
            f"{state['manifest_path']} [{state['ecosystem']}]"
        )

        context = {
            "owner":           owner,
            "repo":            repo,
            "branch_name":     branch_name,
            "file_path":       state["manifest_path"],
            "file_sha":        state["manifest_sha"],
            "patched_content": state.get("patched_manifest", ""),
            "pr_body":         report_body,
            "pr_title":        pr_title,
            "base_branch":     state.get("base_branch", "main"),
            "issue_title":     issue_title,
            "issue_body":      report_body,
        }

        result = await self._tools.execute_option(selected, context)

        self._write_audit(
            f"execute:{option_id}", result.get("status", "done"),
            incident_id=state.get("incident_id"),
        )

        return {"execution_result": result}

    async def _complete_node(self, state: PatchState) -> dict:
        """Mark incident as executed and write final audit record."""
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
        log.info("[Agent10] Workflow complete for incident %s", incident_id)
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
        """Trigger the dependency patch workflow. Returns incident_id after HITL pause."""
        initial_state: PatchState = {
            "workspace_id":          self.workspace_id,
            "cloud_provider":        cloud_provider,
            "webhook_payload":       payload,
            "repository":            "",
            "ecosystem":             "",
            "manifest_path":         "",
            "ref":                   "HEAD",
            "base_branch":           "main",
            "manifest_content":      "",
            "manifest_sha":          "",
            "parsed_dependencies":   [],
            "dependency_count":      0,
            "vulnerability_results": [],
            "vulnerability_count":   0,
            "critical_count":        0,
            "high_count":            0,
            "tokens_used":           0,
            "incident_id":           None,
            "parsed_error":          None,
            "patch_summary":         None,
            "vulnerable_packages":   None,
            "patched_manifest":      None,
            "remediation_options":   None,
            "selected_option":       None,
            "execution_result":      None,
            "error":                 None,
        }

        thread_id = str(uuid.uuid4())
        config    = {"configurable": {"thread_id": thread_id}}

        log.info("[Agent10] Starting dependency patch workflow — thread_id=%s", thread_id)

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

        log.info("[Agent10] Workflow paused at HITL gate — incident_id=%s", incident_id)
        return incident_id

    async def resume(self, thread_id: str, selected_option: dict) -> dict:
        """Resume the paused workflow after operator approval."""
        config = {"configurable": {"thread_id": thread_id}}
        log.info("[Agent10] Resuming thread=%s option=%s", thread_id, selected_option.get("id"))
        result = await self._graph.ainvoke(Command(resume=selected_option), config=config)
        return result.get("execution_result", {"status": "completed"})


# ──────────────────────────────────────────────
# Report and prompt helpers
# ──────────────────────────────────────────────

_SEVERITY_ICON = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🟢",
    "UNKNOWN":  "⚪",
}


def _build_vulnerability_report(
    ecosystem: str,
    repository: str,
    manifest_path: str,
    dependency_count: int,
    vulnerability_count: int,
    critical_count: int,
    high_count: int,
    vulnerable_packages: list,
    patch_summary: str,
) -> str:
    """Build the Markdown body used for both the patch PR description and the tracking issue."""
    severity_line = (
        f"🔴 CRITICAL: **{critical_count}** | "
        f"🟠 HIGH: **{high_count}** | "
        f"Total Vulnerable: **{vulnerability_count}** / {dependency_count} scanned"
    )

    pkg_table = ""
    if vulnerable_packages:
        rows = []
        for pkg in vulnerable_packages:
            icon     = _SEVERITY_ICON.get(pkg.get("severity", "").upper(), "⚪")
            cve_ids  = ", ".join(pkg.get("cve_ids", [])[:3])
            fixed    = pkg.get("fixed_version", "") or "_not available_"
            rows.append(
                f"| `{pkg.get('package', '?')}` | `{pkg.get('current_version', '?')}` | "
                f"`{fixed}` | {icon} {pkg.get('severity', 'UNKNOWN')} | {cve_ids} |"
            )
        pkg_table = (
            "\n\n### Vulnerable Packages\n\n"
            "| Package | Current | Fixed Version | Severity | CVE IDs |\n"
            "|---|---|---|---|---|\n"
            + "\n".join(rows)
        )

    return (
        f"## Cloud Decoded — Dependency Vulnerability Report\n\n"
        f"**Repository:** `{repository}`  \n"
        f"**Ecosystem:** {ecosystem}  \n"
        f"**Manifest:** `{manifest_path}`\n\n"
        f"### Severity Summary\n\n"
        f"{severity_line}\n\n"
        f"### Patch Summary\n\n"
        f"{patch_summary or '_Not available_'}"
        f"{pkg_table}\n\n"
        f"---\n"
        f"*Generated by Cloud Decoded Agent 10. Review all version changes before merging.*"
    )


def _format_osv_results_for_prompt(vulnerability_results: list) -> str:
    """Format OSV scan results into a compact, LLM-readable block."""
    if not vulnerability_results:
        return "No vulnerabilities found by OSV.dev scan."

    lines = []
    for pkg in vulnerability_results:
        lines.append(f"\n**{pkg['package']}** @ {pkg['version']}")
        for v in pkg.get("vulnerabilities", []):
            fixed = v.get("fixed_in") or "no fix available"
            aliases = ", ".join(v.get("aliases", [])[:3]) or v.get("id", "")
            lines.append(
                f"  - {v.get('id', '?')} | {v.get('severity', 'UNKNOWN')} | "
                f"Fixed in: {fixed} | IDs: {aliases}\n"
                f"    Summary: {v.get('summary', '')[:150]}"
            )
    return "\n".join(lines)
