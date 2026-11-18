"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Agent 07 — Interactive Runbook Automation tools.

RUNBOOK EXECUTION IS DISABLED (2026-11-18, claims audit). The step executors
ran customer runbook steps — shell commands, HTTP calls, kubectl — as
processes and requests from Cloud Decoded's own shared, multi-tenant API host.
An approved runbook therefore executed on our server with our network position,
not in the customer's environment. They have been removed, not flagged off:
any request to execute a plan is refused here, and the workflow no longer
offers the option. Re-enabling needs a design that runs steps inside the
customer's own environment.

What remains: filing the runbook plan as a GitHub issue (opt_2), or Hold.
"""

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"

EXECUTION_DISABLED_REASON = (
    "Runbook step execution is disabled: steps would run on Cloud Decoded's "
    "shared API host, not in your environment. File the plan as an issue and "
    "run it with your own tooling."
)


class RunbookTools:
    """
    Post-approval tools for Agent 07. Files the runbook plan as a GitHub
    issue; refuses every request to execute runbook steps.
    """

    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN", "")

    async def create_runbook_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        """
        Create a GitHub issue with the runbook plan.
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

    async def execute_runbook_plan(self, plan_steps: list[dict], context: dict) -> dict:
        """Hard refusal. No runbook step is ever executed from this host."""
        log.warning(
            "[RunbookTools] Refused to execute a %d-step runbook plan: execution disabled",
            len(plan_steps or []),
        )
        return {"status": "refused", "reason": EXECUTION_DISABLED_REASON}

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the approved runbook action.

        context must include: owner, repo, report_title, report_body
        """
        option_id = option.get("id", "")
        log.info("[RunbookTools] Executing approved option '%s'", option_id)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to run the runbook manually"}

        if option_id == "opt_1":
            return await self.execute_runbook_plan(context.get("plan_steps", []), context)

        if option_id == "opt_2":
            # File the runbook plan as a GitHub issue. Nothing is executed.
            return await self.create_runbook_issue(
                owner=context.get("owner", ""),
                repo=context.get("repo", ""),
                title=context.get("report_title", "Runbook Plan"),
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
