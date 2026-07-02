"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Assessment Agent — Sales Operations
agents/sales/assessment-agent/agent.py

Generates an infrastructure assessment report from client-provided stack data.
This is the pre-sales deliverable: a structured analysis of where the client's
DevOps practice is weak and which Cloud Decoded agents would provide the most
immediate value.

Output feeds directly into proposal-agent.
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a cloud infrastructure assessment agent for THD Agentic Systems LLC (Cloud Decoded).

Your job: analyze a prospect's stack and operational context, identify their highest-risk
DevOps gaps, and map those gaps to specific Cloud Decoded agents.

Cloud Decoded agent roster:
  agent_01 — CI/CD Pipeline Failure Triage
  agent_02 — Kubernetes Alert Fatigue & Remediation
  agent_03 — PR Review for Architecture & Security
  agent_04 — Legacy Code & Infrastructure Migration
  agent_05 — IAM Policy Minimization (Least Privilege)
  agent_06 — FinOps Cost Optimization
  agent_07 — Interactive Runbook Automation
  agent_08 — Drift Detection & Auto-Correction
  agent_09 — Context-Aware Onboarding & On-Call Buddy
  agent_10 — Dependency & Vulnerability Patching

Assessment principles:
- Be honest. If there are no risk areas, say so.
- Prioritize by blast radius: what failure would hurt the most if it happened today?
- Quick wins = high impact, low effort, deployable in days.
- Do not recommend agents that do not fit the client's actual stack.
- ROI estimates should be conservative and tied to specific pain (e.g. hours saved per week).

Output schema (return ONLY this JSON, no other text):
{
  "assessment_title": "Infrastructure Assessment — [Company Name]",
  "executive_summary": "3-4 sentences: current state, key risks, and headline opportunity",
  "risk_areas": [
    {
      "area": "name of the risk area",
      "severity": "critical" or "high" or "medium" or "low",
      "description": "specific description of the risk based on the data provided",
      "impact_if_ignored": "what happens in 30-90 days if this is not addressed"
    }
  ],
  "quick_wins": [
    {
      "action": "specific action or agent to deploy",
      "impact": "expected outcome in plain language",
      "effort": "days to deploy and configure",
      "agent_id": "agent_XX or null if not agent-related"
    }
  ],
  "recommended_agents": ["agent_01", "agent_06", "..."],
  "recommended_tier": "starter" or "growth" or "enterprise",
  "estimated_monthly_hours_saved": integer,
  "estimated_monthly_value_usd": integer,
  "confidence": "low" or "medium" or "high",
  "confidence_note": "what additional data would increase confidence in this assessment"
}
"""


def run(
    company: str,
    cloud_provider: str,
    tech_stack: dict,
    team_size: int,
    pain_points: str,
    current_tooling: str = "",
    monthly_cloud_spend_usd: int = 0,
    additional_context: str = "",
) -> dict:
    """
    Generate an infrastructure assessment report.

    Args:
        company:                    Company name
        cloud_provider:             Primary cloud provider (aws / azure / gcp / multi)
        tech_stack:                 Dict of stack details (k8s, ci_cd, languages, databases, etc.)
        team_size:                  Number of engineers
        pain_points:                Their described pain in their own words
        current_tooling:            Monitoring, alerting, and DevOps tools in use (optional)
        monthly_cloud_spend_usd:    Approximate monthly cloud bill in USD (optional, 0 = unknown)
        additional_context:         Other relevant details (optional)

    Returns:
        Infrastructure assessment report dict.
    """
    spend_line = (
        f"Monthly Cloud Spend: ~${monthly_cloud_spend_usd:,}/month"
        if monthly_cloud_spend_usd
        else "Monthly Cloud Spend: not provided"
    )

    user_message = f"""
Company: {company}
Cloud Provider: {cloud_provider}
Engineering Team Size: {team_size} engineers
{spend_line}

Tech Stack:
{json.dumps(tech_stack, indent=2)}

Current Tooling (monitoring, alerting, CI/CD, etc.):
{current_tooling or "Not provided."}

Described Pain Points:
{pain_points}

Additional Context:
{additional_context or "None."}

Generate a full infrastructure assessment. Be specific to their stack — do not give
generic advice. Map every risk to their actual environment. Return only JSON.
"""

    response = complete(
        task_type="infrastructure_assessment",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "assessment_title": f"Infrastructure Assessment — {company}",
            "executive_summary": "Assessment could not be generated — parse error.",
            "risk_areas": [],
            "quick_wins": [],
            "recommended_agents": [],
            "recommended_tier": "starter",
            "estimated_monthly_hours_saved": 0,
            "estimated_monthly_value_usd": 0,
            "confidence": "low",
            "confidence_note": f"Agent parse error: {response[:200]}",
        }


if __name__ == "__main__":
    result = run(
        company="StackBridge Inc.",
        cloud_provider="aws",
        tech_stack={
            "kubernetes": "EKS 1.27",
            "ci_cd": "GitHub Actions",
            "languages": ["Python", "Node.js", "Go"],
            "databases": ["RDS PostgreSQL", "ElastiCache Redis"],
            "infrastructure_as_code": "Terraform",
            "container_registry": "ECR",
        },
        team_size=28,
        pain_points=(
            "CI/CD breaks 3-4x/week, 2hrs triage each time. $14k AWS bill spike last month "
            "from runaway Lambda. IAM roles haven't been audited in 18 months. "
            "On-call is burning out — 4-5 pages per week."
        ),
        current_tooling="Datadog for monitoring, PagerDuty for alerting, no runbook system",
        monthly_cloud_spend_usd=31000,
    )
    print(json.dumps(result, indent=2))
