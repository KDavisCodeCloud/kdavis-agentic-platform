"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Brief Agent — Content Operations
agents/content/brief-agent/agent.py

Turns a raw content idea into a structured brief that the draft-agent
can execute without ambiguity. One brief per piece of content.

This agent does NOT write the content. It defines the strategy:
hook angle, key message, tone, format, and what to avoid.
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a content strategist for THD Agentic Systems LLC (brand: Cloud Decoded).

Cloud Decoded sells autonomous DevOps agents to mid-market engineering teams.
The content voice is direct, practitioner-first, and credibility-driven.
No hype. No vague "AI will change everything" takes. Specific, useful, earned.

Brand context:
- Founder: Kelvin Davis — USAF veteran, Fortune 500 DevOps background
- Audience: Engineering Managers, DevOps leads, SRE leads, CTOs at mid-market companies
- Core message: Your team is drowning in toil. Autonomous agents handle the triage,
  diagnosis, and options — your engineer approves and moves on.
- Tone: Direct. Confident. Not salesy. Written like a practitioner, not a marketer.

Platform-specific rules:
  LinkedIn: 150-300 words. Hook in first line. Short paragraphs. No fluff.
  X (Twitter): Under 280 characters for main post. Punchy. Conversation-starter.
  Short-form video: 60-90 second script. Hook in first 3 seconds. One clear idea.

Your job: turn a raw idea into a structured brief.

Output schema (return ONLY this JSON, no other text):
{
  "brief_title": "internal working title for this piece",
  "platform": "linkedin" or "x" or "video",
  "goal": "awareness" or "education" or "credibility" or "lead_gen",
  "hook_angle": "the specific angle that makes someone stop scrolling — one sentence",
  "key_message": "the one thing the audience should walk away believing",
  "supporting_points": ["up to 3 specific facts, stats, or examples that back the key message"],
  "tone": "direct" or "story" or "provocative" or "educational",
  "format": "list" or "narrative" or "problem-solution" or "hot-take" or "script",
  "cta": "what you want the reader to do or think after reading",
  "do_not_include": ["things to avoid — competitor names, unverified claims, buzzwords, etc."]
}
"""


def run(
    raw_idea: str,
    platform: str,
    goal: str,
    target_audience: str = "Engineering Managers and DevOps leads",
    additional_constraints: str = "",
) -> dict:
    """
    Generate a content brief from a raw idea.

    Args:
        raw_idea:               The unstructured idea or topic to build from
        platform:               "linkedin", "x", or "video"
        goal:                   "awareness", "education", "credibility", or "lead_gen"
        target_audience:        Who this specific piece is for (optional override)
        additional_constraints: Anything to avoid or include (optional)

    Returns:
        Structured content brief dict.
    """
    user_message = f"""
Raw Idea:
{raw_idea}

Platform: {platform}
Goal: {goal}
Target Audience: {target_audience}
Additional Constraints: {additional_constraints or "None."}

Turn this into a structured content brief. Return only JSON.
"""

    response = complete(
        task_type="content_brief",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "brief_title": "parse_error",
            "platform": platform,
            "goal": goal,
            "hook_angle": "",
            "key_message": "",
            "supporting_points": [],
            "tone": "direct",
            "format": "narrative",
            "cta": "",
            "do_not_include": [],
            "_error": f"Brief agent returned unparseable response: {response[:200]}",
        }


if __name__ == "__main__":
    result = run(
        raw_idea=(
            "Most engineering teams don't know how much time their on-call engineers "
            "spend triaging CI/CD failures before they can even start fixing them. "
            "We've seen 2-3 hours per incident just on diagnosis. Agents cut that to minutes."
        ),
        platform="linkedin",
        goal="education",
    )
    print(json.dumps(result, indent=2))
