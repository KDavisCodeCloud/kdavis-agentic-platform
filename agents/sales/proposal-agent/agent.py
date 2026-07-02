"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Proposal Agent — Sales Operations
agents/sales/proposal-agent/agent.py

Drafts a Cloud Decoded engagement proposal from the output of assessment-agent.
Produces a structured proposal that Kelvin reviews and customizes before sending.

This agent does NOT send anything. Output is a draft for human review.
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a proposal-writing agent for THD Agentic Systems LLC (Cloud Decoded).

Cloud Decoded product tiers:
  Starter    — $299/month  — up to 3 agents, 2 repos, 1 cloud provider
  Growth     — $699/month  — up to 10 agents, 15 repos, AWS + Azure
  Enterprise — $2,499+/month — custom agents, custom repos, VPC-deployed, dedicated support

BYOK (Bring Your Own LLM Key) is required on all tiers.

Your job: produce a structured, professional engagement proposal draft based on
the client's assessment results and qualification context.

Proposal principles:
- Lead with their pain, not your product. The first paragraph should make them feel understood.
- Every feature mentioned must tie directly to a risk or pain point from the assessment.
- ROI estimates must be conservative and derived from the assessment data — not invented.
- Pricing is presented as investment vs. cost of inaction, not as a line item.
- Do not make commitments about implementation timelines — those are confirmed after contract.
- This is a draft. Flag anything that needs Kelvin to customize with [CUSTOMIZE] markers.

Output schema (return ONLY this JSON, no other text):
{
  "proposal_title": "Cloud Decoded Engagement Proposal — [Company Name]",
  "prepared_for": "company name and contact name",
  "executive_summary": "3-4 sentences: the problem, the solution, the expected outcome",
  "problem_statement": "2-3 paragraphs restating their pain in specific, earned terms",
  "proposed_solution": "2-3 paragraphs describing what Cloud Decoded does for them specifically",
  "agent_breakdown": [
    {
      "agent_name": "e.g. CI/CD Pipeline Failure Triage",
      "agent_id": "agent_01",
      "use_case": "specific use case for this client",
      "expected_outcome": "measurable outcome they can expect"
    }
  ],
  "recommended_tier": "starter" or "growth" or "enterprise",
  "monthly_investment": "$X/month",
  "roi_case": "3-4 sentences: specific ROI math based on assessment data",
  "cost_of_inaction": "what happens if they do nothing — specific to their situation",
  "success_metrics": ["list of 3-5 measurable outcomes to track in the first 90 days"],
  "next_steps": ["ordered list of concrete next steps to move forward"],
  "customize_flags": ["list of [CUSTOMIZE] items that need Kelvin's personal input"]
}
"""


def run(
    company: str,
    contact_name: str,
    contact_role: str,
    assessment_result: dict,
    qualification_result: dict,
    engagement_notes: str = "",
) -> dict:
    """
    Draft an engagement proposal from qualification and assessment data.

    Args:
        company:             Company name
        contact_name:        Primary contact's name
        contact_role:        Their title
        assessment_result:   Output dict from assessment-agent
        qualification_result: Output dict from qualify-agent
        engagement_notes:    Notes from discovery call or operator (optional)

    Returns:
        Structured proposal draft dict.
    """
    user_message = f"""
Company: {company}
Contact: {contact_name} — {contact_role}

Qualification Result:
{json.dumps(qualification_result, indent=2)}

Infrastructure Assessment:
{json.dumps(assessment_result, indent=2)}

Engagement Notes (from discovery call or operator):
{engagement_notes or "No additional notes."}

Draft a proposal that leads with their pain and ties every recommendation
directly to their specific situation. Flag anything that needs customization.
Return only JSON.
"""

    response = complete(
        task_type="proposal_draft",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "proposal_title": f"Cloud Decoded Engagement Proposal — {company}",
            "prepared_for": f"{company} / {contact_name}",
            "executive_summary": "Proposal could not be generated — parse error.",
            "problem_statement": "",
            "proposed_solution": "",
            "agent_breakdown": [],
            "recommended_tier": assessment_result.get("recommended_tier", "growth"),
            "monthly_investment": "$699/month",
            "roi_case": "",
            "cost_of_inaction": "",
            "success_metrics": [],
            "next_steps": [],
            "customize_flags": [f"Agent parse error: {response[:200]}"],
        }


if __name__ == "__main__":
    qual = {
        "qualified": True, "fit_score": 9, "tier_recommendation": "growth",
        "recommended_action": "book_call",
        "talk_track": "Open with the $14k bill spike and the on-call burnout.",
    }
    assess = {
        "assessment_title": "Infrastructure Assessment — StackBridge Inc.",
        "executive_summary": "High CI/CD failure rate and unaudited IAM posture are the top risks.",
        "risk_areas": [
            {"area": "CI/CD Reliability", "severity": "high",
             "description": "3-4 pipeline failures/week at 2hrs triage each",
             "impact_if_ignored": "On-call burnout, slower release velocity"},
            {"area": "Cloud Cost Control", "severity": "high",
             "description": "Unmonitored Lambda spend caused $14k spike",
             "impact_if_ignored": "Continued unbudgeted overages"},
        ],
        "recommended_agents": ["agent_01", "agent_06", "agent_05"],
        "recommended_tier": "growth",
        "estimated_monthly_hours_saved": 48,
        "estimated_monthly_value_usd": 9600,
    }
    result = run(
        company="StackBridge Inc.",
        contact_name="Marcus Webb",
        contact_role="VP of Engineering",
        assessment_result=assess,
        qualification_result=qual,
        engagement_notes="Marcus mentioned the board is asking about cloud costs. Budget is not the blocker.",
    )
    print(json.dumps(result, indent=2))
