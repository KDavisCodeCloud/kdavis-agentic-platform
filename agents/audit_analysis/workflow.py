"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Audit Analysis Agent — turns a kdavis-cloud-audit findings submission into a
prioritized, human-approvable remediation plan.

Deliberately NOT a LangGraph StateGraph (unlike agent_01-agent_10): there is
exactly one LLM call, no branching, and — critically — no resume path,
since approving a remediation item never triggers automatic execution
(kdavis-cloud-audit/CLAUDE.md's own non-negotiable). LangGraph's value in
every other agent here is pause-and-resume across separate HTTP requests
via interrupt()/Command(resume=...); this agent needs neither, so it's
plain sequential async code instead of ceremony with no behavioral payoff.

Flow: analyze (LLM groups/prioritizes raw findings into action items) ->
rank (severity, then dollar impact) -> persist (one row per item in
cloud_audit_remediation_items). Any failure in analyze/parse is caught and
recorded on the submission as status='failed' + analysis_error — the
findings themselves are already safely stored by the caller before this
agent ever runs, so a failed analysis never loses data, it just means no
plan was generated yet.
"""

import logging
from typing import Optional

from agents.base_agent import BaseAgent

log = logging.getLogger(__name__)

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_VALID_SEVERITIES = set(_SEVERITY_ORDER)
_VALID_CATEGORIES = {"WASTE", "SECURITY", "COMPLIANCE"}

_SYSTEM_PROMPT = """You are a cloud cost and security remediation planner.
You will be given a JSON array of findings from an automated cloud audit
(AWS or Azure). Each finding already has a title, description, remediation,
severity, category, and dollar impact.

Your job: merge closely-related findings into a smaller set of clear,
prioritized action items a human engineer can act on. Only merge findings
that are genuinely the same underlying issue (e.g. multiple IAM users
missing MFA can become one "Enforce MFA" action item); never merge
unrelated findings just to shorten the list.

Respond with ONLY a JSON array, no prose, no markdown fences. Each item:
{
  "title": "short, specific, plain English",
  "description": "what the problem is, 1-3 sentences",
  "remediation": "what to do about it, 1-3 sentences",
  "severity": "HIGH" | "MEDIUM" | "LOW",
  "category": "WASTE" | "SECURITY" | "COMPLIANCE",
  "estimated_monthly_waste_usd": <sum of the dollar impact of every finding this item covers, 0 if none>
}
"""


class AuditAnalysisAgent(BaseAgent):
    AGENT_ID = "audit_analysis"

    async def run(self, payload: dict, byok_encrypted_key: Optional[str] = None) -> str:
        submission_id = payload["submission_id"]
        findings = payload["findings"]

        try:
            items = self._analyze(findings, byok_encrypted_key)
            items = self._rank(items)
        except Exception as exc:  # noqa: BLE001 - convert any analysis failure into a stored, descriptive error
            log.warning("[%s] analysis failed for submission=%s: %s", self.agent_id, submission_id, exc)
            await self.db.execute(
                "UPDATE cloud_audit_submissions SET status = 'failed', analysis_error = $1 WHERE id = $2",
                str(exc),
                submission_id,
            )
            return submission_id

        await self._persist(submission_id, items)
        return submission_id

    def _analyze(self, findings: list[dict], byok_encrypted_key: Optional[str]) -> list[dict]:
        import json

        response, _tokens = self.call_llm(
            task_type="audit_remediation_plan",
            messages=[{"role": "user", "content": json.dumps(findings)}],
            system_prompt=_SYSTEM_PROMPT,
            byok_encrypted_key=byok_encrypted_key,
        )
        parsed = self.parse_llm_json(response, context="audit_remediation_plan")
        items = parsed if isinstance(parsed, list) else parsed.get("items", [])
        if not items:
            raise ValueError("LLM returned no remediation items")

        validated = []
        for item in items:
            severity = item.get("severity", "").upper()
            category = item.get("category", "").upper()
            if severity not in _VALID_SEVERITIES or category not in _VALID_CATEGORIES:
                raise ValueError(f"LLM returned an invalid severity/category: {item}")
            validated.append(
                {
                    "title": str(item["title"])[:200],
                    "description": str(item["description"])[:2000],
                    "remediation": str(item["remediation"])[:2000],
                    "severity": severity,
                    "category": category,
                    "estimated_monthly_waste_usd": float(item.get("estimated_monthly_waste_usd", 0) or 0),
                }
            )
        return validated

    @staticmethod
    def _rank(items: list[dict]) -> list[dict]:
        ranked = sorted(
            items,
            key=lambda i: (_SEVERITY_ORDER[i["severity"]], -i["estimated_monthly_waste_usd"]),
        )
        for i, item in enumerate(ranked):
            item["priority_rank"] = i + 1
        return ranked

    async def _persist(self, submission_id: str, items: list[dict]) -> None:
        for item in items:
            await self.db.execute(
                """
                INSERT INTO cloud_audit_remediation_items (
                    submission_id, workspace_id, severity, category, title,
                    description, remediation, estimated_monthly_waste_usd, priority_rank
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                submission_id,
                self.workspace_id,
                item["severity"],
                item["category"],
                item["title"],
                item["description"],
                item["remediation"],
                item["estimated_monthly_waste_usd"],
                item["priority_rank"],
            )
        await self.db.execute(
            "UPDATE cloud_audit_submissions SET status = 'ready' WHERE id = $1",
            submission_id,
        )
