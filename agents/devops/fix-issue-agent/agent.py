"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Fix Issue Agent — DevOps Internal Operations
agents/devops/fix-issue-agent/agent.py

Generates a detailed, step-by-step fix plan for a triaged infrastructure issue.
NEVER executes anything. The plan goes to a human for approval before any action
is taken (Governance Rule 11 — All Remediation Requires Human Approval).

Consumes the output of triage-agent and produces a structured fix plan that
includes pre-conditions, exact steps, rollback instructions, and validation steps.
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a senior DevOps fix-planning agent for the KDavis Agentic Platform.

Your job: given a triaged infrastructure issue, produce a precise, safe, step-by-step fix plan.

Critical governance rules you always follow:
- You NEVER execute commands. You ONLY produce plans.
- Every fix plan requires human approval before execution (Rule 11).
- Every step must include a rollback step — no one-way doors without explicit warning.
- You always reference official vendor documentation, never blogs or Stack Overflow.
- Destructive actions (deletes, IAM changes, scaling down, data store changes) must be
  labeled DESTRUCTIVE in the step and require a separate explicit approval note.
- You always confirm backup requirements — a step that modifies state must note
  what needs to be backed up first.
- You never assume environment details not provided. If critical info is missing,
  you flag it in missing_information instead of guessing.

Output schema (return ONLY this JSON, no other text):
{
  "fix_title": "one-line description of the proposed fix",
  "severity": "p1" or "p2" or "p3",
  "estimated_duration_minutes": integer,
  "risk_level": "low" or "medium" or "high" or "critical",
  "pre_conditions": [
    "list of things that must be true before starting — backups, access, health checks"
  ],
  "fix_steps": [
    {
      "step": 1,
      "action": "exact command or action to take",
      "expected_outcome": "what success looks like",
      "destructive": true or false,
      "rollback_step": "exact command or action to undo this step"
    }
  ],
  "validation_steps": [
    "specific checks to run after the fix to confirm it worked"
  ],
  "documentation_references": [
    {"title": "doc title", "url": "official vendor URL only"}
  ],
  "missing_information": [
    "critical details not provided that the operator must supply before approval"
  ],
  "requires_approval": true,
  "approval_note": "what the approving human needs to verify before signing off"
}
"""


def run(
    issue_title: str,
    issue_body: str,
    triage_result: dict,
    client_stack: dict,
    additional_context: str = "",
) -> dict:
    """
    Generate a fix plan for a triaged infrastructure issue.

    Args:
        issue_title:        Original issue title
        issue_body:         Full issue description
        triage_result:      Output dict from triage-agent
        client_stack:       Client environment details (cloud, k8s version, region, etc.)
        additional_context: Any extra context from the operator (optional)

    Returns:
        Structured fix plan dict. requires_approval is always True.
    """
    user_message = f"""
Issue Title: {issue_title}

Issue Description:
{issue_body}

Triage Classification:
{json.dumps(triage_result, indent=2)}

Client Stack:
{json.dumps(client_stack, indent=2)}

Additional Context from Operator:
{additional_context or "None provided."}

Produce a complete fix plan. Flag any missing information that blocks you from
generating a safe plan. Return only JSON.
"""

    response = complete(
        task_type="fix_planning",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        result["requires_approval"] = True  # hard-enforce Rule 11
        return result
    except json.JSONDecodeError:
        return {
            "fix_title": "parse_error",
            "severity": triage_result.get("severity", "p3"),
            "estimated_duration_minutes": 0,
            "risk_level": "high",
            "pre_conditions": [],
            "fix_steps": [],
            "validation_steps": [],
            "documentation_references": [],
            "missing_information": ["fix-issue-agent returned unparseable response"],
            "requires_approval": True,
            "approval_note": f"Agent parse error: {response[:200]}",
        }


if __name__ == "__main__":
    triage = {
        "decision": "accept",
        "severity": "p2",
        "classification": "Kubernetes pod OOMKilled — memory limit exceeded",
        "reasoning": "Production degradation, 40% request failure rate",
        "escalate_immediately": False,
    }
    stack = {
        "cloud": "aws",
        "kubernetes": "eks",
        "k8s_version": "1.28",
        "namespace": "production",
        "deployment": "prod-api-deployment",
        "region": "us-east-1",
    }
    result = run(
        issue_title="Pod CrashLoopBackOff on prod-api-deployment",
        issue_body=(
            "3 pods in CrashLoopBackOff. OOMKilled — memory limit 512Mi exceeded. "
            "Started 20 minutes after last deployment. 40% of requests returning 503."
        ),
        triage_result=triage,
        client_stack=stack,
    )
    print(json.dumps(result, indent=2))
