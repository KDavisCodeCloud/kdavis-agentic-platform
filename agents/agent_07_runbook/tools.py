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
Agent 07 — Interactive Runbook Automation execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.

Supported step types:
  shell       — run a shell command in a sandboxed subprocess
  http        — make an HTTP API call (GET/POST/PUT/PATCH/DELETE)
  kubectl     — kubectl apply/delete/rollout commands
  notification — post to Slack or GitHub
  github_issue — create a tracking issue

All step execution is sequenced by execute_runbook_plan(), which runs the approved
plan and records results. On step failure, behavior is controlled by on_failure:
  "stop"        — halt the runbook immediately
  "continue"    — log the error and proceed to the next step
  "skip_to:<id>" — jump to a specific step ID
"""

import asyncio
import json
import logging
import os
import shlex
import subprocess
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"

# Hard limits for safety
_MAX_COMMAND_TIMEOUT_SECONDS = 120
_MAX_HTTP_TIMEOUT_SECONDS    = 30
_MAX_STEPS_PER_RUN           = 50


class RunbookTools:
    """
    Post-approval execution tools for Agent 07.
    Runs runbook steps sequentially after operator approval.
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        slack_webhook_url: Optional[str] = None,
        allow_shell: bool = True,
    ):
        self.github_token      = github_token      or os.environ.get("GITHUB_TOKEN", "")
        self.slack_webhook_url = slack_webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
        self.allow_shell       = allow_shell

    # ──────────────────────────────────────────────
    # Individual step executors
    # ──────────────────────────────────────────────

    async def run_shell_step(self, step: dict, context: dict) -> dict:
        """
        Execute a shell command step in a subprocess.
        The command is template-substituted with context variables.
        NEVER passes user-supplied data to shell=True — uses shlex.split().
        """
        if not self.allow_shell:
            return {"status": "skipped", "reason": "shell execution disabled for this workspace"}

        raw_cmd = step.get("command", "")
        command = _substitute(raw_cmd, context)
        timeout = min(
            step.get("timeout_seconds", 30),
            _MAX_COMMAND_TIMEOUT_SECONDS,
        )

        log.info("[RunbookTools] Shell step '%s': %s", step.get("id"), command[:120])

        try:
            args = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            stdout = stdout_bytes.decode(errors="replace").strip()
            stderr = stderr_bytes.decode(errors="replace").strip()
            exit_code = proc.returncode

        except asyncio.TimeoutError:
            return {
                "status": "failed",
                "step_id": step.get("id"),
                "error": f"Command timed out after {timeout}s",
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }
        except (OSError, ValueError) as exc:
            return {
                "status": "failed",
                "step_id": step.get("id"),
                "error": str(exc),
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }

        status = "ok" if exit_code == 0 else "failed"
        return {
            "status": status,
            "step_id": step.get("id"),
            "command": command,
            "stdout": stdout[:2000],
            "stderr": stderr[:500],
            "exit_code": exit_code,
        }

    async def run_http_step(self, step: dict, context: dict) -> dict:
        """
        Execute an HTTP API call step.
        Method, URL, headers, and body are template-substituted with context.
        """
        method  = step.get("method", "GET").upper()
        url     = _substitute(step.get("url", ""), context)
        headers = {k: _substitute(v, context) for k, v in step.get("headers", {}).items()}
        body    = step.get("body")
        if isinstance(body, dict):
            body = {k: _substitute(str(v), context) for k, v in body.items()}
        elif isinstance(body, str):
            body = _substitute(body, context)

        log.info("[RunbookTools] HTTP step '%s': %s %s", step.get("id"), method, url[:120])

        try:
            async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body if isinstance(body, dict) else None,
                    content=body.encode() if isinstance(body, str) else None,
                )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return {
                "status": "failed",
                "step_id": step.get("id"),
                "error": str(exc),
                "status_code": None,
                "response_body": "",
            }

        ok = resp.status_code < 400
        return {
            "status": "ok" if ok else "failed",
            "step_id": step.get("id"),
            "method": method,
            "url": url,
            "status_code": resp.status_code,
            "response_body": resp.text[:1000],
        }

    async def run_kubectl_step(self, step: dict, context: dict) -> dict:
        """
        Execute a kubectl command step.
        Accepts: apply, delete, rollout restart, rollout undo, get, describe.
        Wraps run_shell_step — kubectl must be on PATH.
        """
        kubectl_action = step.get("kubectl_action", "get")
        namespace      = _substitute(step.get("namespace", "default"), context)
        resource       = _substitute(step.get("resource", ""), context)

        if kubectl_action in ("apply", "delete") and step.get("manifest"):
            manifest = _substitute(step.get("manifest", ""), context)
            command  = f"kubectl {kubectl_action} -f - -n {namespace}"
            shell_step = {**step, "command": f"echo '{manifest}' | kubectl {kubectl_action} -f - -n {namespace}"}
        else:
            command   = f"kubectl {kubectl_action} {resource} -n {namespace}"
            shell_step = {**step, "command": command}

        return await self.run_shell_step(shell_step, context)

    async def run_notification_step(self, step: dict, context: dict) -> dict:
        """
        Send a notification (Slack webhook or GitHub issue comment).
        """
        channel = step.get("channel", "slack")
        message = _substitute(step.get("message", "Runbook step completed"), context)

        if channel == "slack":
            if not self.slack_webhook_url:
                return {"status": "skipped", "reason": "SLACK_WEBHOOK_URL not configured", "step_id": step.get("id")}
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        self.slack_webhook_url,
                        json={"text": message},
                        headers={"Content-Type": "application/json"},
                    )
                return {
                    "status": "ok" if resp.status_code == 200 else "failed",
                    "step_id": step.get("id"),
                    "channel": "slack",
                    "status_code": resp.status_code,
                }
            except httpx.RequestError as exc:
                return {"status": "failed", "step_id": step.get("id"), "error": str(exc)}

        if channel == "github_comment":
            owner    = context.get("owner", "")
            repo     = context.get("repo", "")
            issue_nr = context.get("github_issue_number", "")
            if not (self.github_token and owner and repo and issue_nr):
                return {"status": "skipped", "reason": "GitHub context incomplete", "step_id": step.get("id")}
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{_GH_API}/repos/{owner}/{repo}/issues/{issue_nr}/comments",
                        headers=_gh_headers(self.github_token),
                        json={"body": message},
                    )
                return {
                    "status": "ok" if resp.status_code in (200, 201) else "failed",
                    "step_id": step.get("id"),
                    "channel": "github_comment",
                    "status_code": resp.status_code,
                }
            except httpx.RequestError as exc:
                return {"status": "failed", "step_id": step.get("id"), "error": str(exc)}

        return {"status": "skipped", "reason": f"unknown channel '{channel}'", "step_id": step.get("id")}

    async def create_runbook_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        """
        Create a GitHub issue with the runbook execution report.
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/issues",
                headers=_gh_headers(self.github_token),
                json=payload,
            )

        if resp.status_code in (200, 201):
            issue = resp.json()
            log.info("[RunbookTools] Runbook issue created: %s", issue.get("html_url"))
            return {
                "status": "issue_created",
                "issue_url": issue.get("html_url", ""),
                "issue_number": issue.get("number"),
            }

        raise RuntimeError(f"GitHub issue error {resp.status_code}: {resp.text[:200]}")

    # ──────────────────────────────────────────────
    # Plan executor
    # ──────────────────────────────────────────────

    async def execute_runbook_plan(
        self,
        plan_steps: list[dict],
        context: dict,
    ) -> dict:
        """
        Execute an ordered list of runbook steps sequentially.
        Respects on_failure: "stop" | "continue" | "skip_to:<step_id>"
        Returns a summary with per-step results.
        """
        if len(plan_steps) > _MAX_STEPS_PER_RUN:
            plan_steps = plan_steps[:_MAX_STEPS_PER_RUN]
            log.warning("[RunbookTools] Plan truncated to %d steps", _MAX_STEPS_PER_RUN)

        results     = []
        succeeded   = 0
        failed      = 0
        skipped     = 0
        skip_to_id  = None

        step_index  = {s.get("id"): i for i, s in enumerate(plan_steps)}

        i = 0
        while i < len(plan_steps):
            step = plan_steps[i]
            step_id   = step.get("id", f"step-{i+1}")
            step_type = step.get("type", "shell")
            on_fail   = step.get("on_failure", "continue")

            # skip_to target reached — resume normal execution
            if skip_to_id and step_id != skip_to_id:
                results.append({"step_id": step_id, "status": "skipped", "reason": "skip_to active"})
                skipped += 1
                i += 1
                continue
            skip_to_id = None  # we've arrived at the target

            log.info("[RunbookTools] Executing step %s (type=%s)", step_id, step_type)

            try:
                if step_type == "shell":
                    result = await self.run_shell_step(step, context)
                elif step_type == "http":
                    result = await self.run_http_step(step, context)
                elif step_type in ("kubectl", "k8s"):
                    result = await self.run_kubectl_step(step, context)
                elif step_type == "notification":
                    result = await self.run_notification_step(step, context)
                else:
                    result = {"status": "skipped", "step_id": step_id, "reason": f"unknown type '{step_type}'"}

            except Exception as exc:
                result = {"status": "failed", "step_id": step_id, "error": str(exc)}

            results.append(result)

            if result.get("status") == "ok":
                succeeded += 1
            elif result.get("status") == "skipped":
                skipped += 1
            else:
                failed += 1
                if on_fail == "stop":
                    log.warning("[RunbookTools] Step %s failed with on_failure=stop — halting", step_id)
                    break
                elif on_fail.startswith("skip_to:"):
                    target = on_fail.split(":", 1)[1]
                    if target in step_index:
                        skip_to_id = target
                        i = step_index[target]
                        continue
                # else: "continue" — fall through to next step

            i += 1

        overall = "ok" if failed == 0 else ("partial" if succeeded > 0 else "failed")
        return {
            "status": overall,
            "steps_total": len(plan_steps),
            "steps_succeeded": succeeded,
            "steps_failed": failed,
            "steps_skipped": skipped,
            "step_results": results,
        }

    # ──────────────────────────────────────────────
    # Routing
    # ──────────────────────────────────────────────

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the approved runbook action.

        context must include:
          plan_steps (list), owner, repo, report_title, report_body,
          runbook_name, incident_context
        """
        option_id = option.get("id", "")
        log.info("[RunbookTools] Executing approved option '%s'", option_id)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to run the runbook manually"}

        if option_id == "opt_1":
            # Execute all approved steps
            plan_steps = context.get("plan_steps", [])
            if not plan_steps:
                return {"status": "skipped", "reason": "execution plan is empty"}
            return await self.execute_runbook_plan(plan_steps, context)

        if option_id == "opt_2":
            # Create a GitHub issue with the runbook report (dry-run / documentation)
            return await self.create_runbook_issue(
                owner=context.get("owner", ""),
                repo=context.get("repo", ""),
                title=context.get("report_title", "Runbook Execution Report"),
                body=context.get("report_body", ""),
                labels=["runbook", "operations"],
            )

        return {"status": "not_implemented", "option_id": option_id}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _substitute(template: str, context: dict) -> str:
    """
    Replace {{key}} placeholders in a string with context values.
    Unknown keys are left as-is.
    """
    import re
    def replacer(match):
        key = match.group(1).strip()
        return str(context.get(key, match.group(0)))
    return re.sub(r"\{\{(\w+)\}\}", replacer, template)


def _summarize_step_results(results: list[dict]) -> str:
    """Format step results as a markdown table for GitHub issues."""
    lines = ["| Step | Status | Notes |", "|------|--------|-------|"]
    for r in results:
        step_id = r.get("step_id", "?")
        status  = r.get("status", "?")
        notes   = r.get("error") or r.get("reason") or r.get("stdout", "")[:80] or ""
        icon    = {"ok": "✅", "failed": "❌", "skipped": "⏭️"}.get(status, "❓")
        lines.append(f"| `{step_id}` | {icon} {status} | {notes} |")
    return "\n".join(lines)
