"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Qualify Agent — Sales Operations
agents/sales/qualify-agent/agent.py

Scores an inbound lead against the Cloud Decoded ideal client profile.
Returns a structured qualification decision for the operator to act on.

Ideal client profile:
  - Engineering team of 5-100 engineers
  - Active cloud infrastructure (AWS, Azure, or GCP)
  - Recurring DevOps pain: CI/CD failures, K8s instability, IAM sprawl,
    cost waste, security compliance gaps, or toil-heavy operations
  - Budget authority at Starter ($299/mo) to Enterprise ($2,499+/mo) tier
  - NOT: solo devs, pure frontend teams, no cloud infra, or pre-revenue startups
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a sales qualification agent for Cloud Decoded by THD Agentic Systems LLC.

Cloud Decoded sells autonomous DevOps agents to mid-market engineering teams ($299–$2,499/month).

Your job: evaluate an inbound lead and decide if they are a strong fit.

Ideal Client Profile (ICP):
- Engineering team: 5–100 engineers
- Active cloud infrastructure on AWS, Azure, or GCP
- Real DevOps pain: CI/CD failures, Kubernetes instability, IAM policy sprawl,
  cloud cost waste, security/compliance gaps, or heavy operational toil
- Decision-maker or influencer: Engineering Manager, VP Eng, CTO, DevOps Lead, or SRE Lead
- Budget range: $299–$2,499/month (mid-market, NOT enterprise Fortune 500 procurement cycles)
- NOT a fit: solo developers, pure frontend teams, no cloud infra, pre-revenue startups,
  teams that want to self-host and manage agents themselves

Fit score guide (1-10):
  9-10 — Perfect ICP match. Book a call immediately.
  7-8  — Strong fit. Minor gaps. Book a call with light qualification questions.
  5-6  — Partial fit. Nurture with content before booking a call.
  1-4  — Poor fit. Do not pursue.

Output schema (return ONLY this JSON, no other text):
{
  "qualified": true or false,
  "fit_score": 1-10,
  "tier_recommendation": "starter" or "growth" or "enterprise" or "not_a_fit",
  "icp_matches": ["list of ICP criteria this lead satisfies"],
  "disqualifiers": ["list of flags that reduce fit — empty if none"],
  "recommended_action": "book_call" or "nurture" or "reject",
  "talk_track": "2-3 sentences: what pain to open with on the call, specific to this lead",
  "reasoning": "brief explanation of the qualification decision"
}
"""


def run(
    lead_name: str,
    company: str,
    role: str,
    team_size: str,
    cloud_provider: str,
    pain_points: str,
    how_they_found_us: str,
    additional_context: str = "",
) -> dict:
    """
    Qualify an inbound lead against the Cloud Decoded ICP.

    Args:
        lead_name:          Contact's name
        company:            Company name
        role:               Their title / role
        team_size:          Engineering team size (e.g. "12 engineers")
        cloud_provider:     Cloud stack (e.g. "AWS EKS + RDS")
        pain_points:        What they described as their biggest problem
        how_they_found_us:  Referral, LinkedIn, content, etc.
        additional_context: Any other relevant info (optional)

    Returns:
        Qualification decision dict.
    """
    user_message = f"""
Lead: {lead_name} — {role} at {company}
Team Size: {team_size}
Cloud Stack: {cloud_provider}
How They Found Us: {how_they_found_us}

Pain Points (in their words):
{pain_points}

Additional Context:
{additional_context or "None provided."}

Qualify this lead against the Cloud Decoded ICP and return your decision as JSON.
"""

    response = complete(
        task_type="lead_qualification",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "qualified": False,
            "fit_score": 0,
            "tier_recommendation": "not_a_fit",
            "icp_matches": [],
            "disqualifiers": ["qualification agent returned unparseable response"],
            "recommended_action": "reject",
            "talk_track": "",
            "reasoning": f"Parse error: {response[:200]}",
        }


if __name__ == "__main__":
    result = run(
        lead_name="Marcus Webb",
        company="StackBridge Inc.",
        role="VP of Engineering",
        team_size="28 engineers",
        cloud_provider="AWS — EKS, RDS, Lambda, S3",
        pain_points=(
            "Our CI/CD pipeline breaks 3-4 times a week and the on-call engineer spends "
            "2 hours triaging each time. We also got hit with a $14k AWS bill spike last month "
            "from a runaway Lambda and had no alert until finance noticed."
        ),
        how_they_found_us="LinkedIn post about autonomous DevOps agents",
    )
    print(json.dumps(result, indent=2))
