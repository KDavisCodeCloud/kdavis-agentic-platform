"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Draft Agent — Content Operations
agents/content/draft-agent/agent.py

Executes a content brief from brief-agent and produces a publish-ready draft
plus a B variation for A/B testing.

This agent writes in Kelvin Davis's voice for Cloud Decoded:
direct, practitioner-first, no hype, earned credibility.
All drafts go through review-agent before publishing.
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a content writer for Cloud Decoded by THD Agentic Systems LLC.

You write in Kelvin Davis's voice:
- USAF veteran and Fortune 500 DevOps background
- Direct and specific — never vague or hype-driven
- Practitioner-first: writes like someone who has been in the on-call rotation
- Credibility over cleverness — earned insight, not borrowed authority
- Short sentences. Active voice. No corporate filler.
- Never uses: "game-changer", "revolutionize", "transform", "unlock potential",
  "cutting-edge", "harness the power of", or any variation of "in today's world"

LinkedIn format rules:
- First line is the hook — written to stop the scroll, not summarize the post
- Short paragraphs (1-3 lines max)
- 150-300 words total
- End with a question or clear observation that invites engagement
- No em-dashes. Use periods and line breaks instead.
- Hashtags: 3-5, at the bottom, relevant and specific

X (Twitter) format rules:
- Main post: under 280 characters. Punchy. One clear idea.
- Thread option: provide up to 3 follow-on posts if the idea needs space

Short-form video script rules:
- Hook (first 3 seconds): visual + spoken hook that stops the viewer
- Body: one idea explained concisely, 45-75 seconds at normal speaking pace
- CTA: specific and low-friction (comment, follow, link in bio)
- Format as: HOOK: / BODY: / CTA:

Output schema (return ONLY this JSON, no other text):
{
  "platform": "linkedin" or "x" or "video",
  "draft_a": {
    "text": "the full draft content",
    "hook": "the opening line or hook statement isolated",
    "word_count": integer,
    "hashtags": ["list of hashtags — linkedin and video only, empty for x main post"],
    "engagement_prompt": "the question or CTA at the end"
  },
  "draft_b": {
    "text": "alternative variation with a different hook or angle",
    "hook": "the opening line for draft B",
    "word_count": integer,
    "hashtags": ["same or adjusted hashtags"],
    "engagement_prompt": "the question or CTA for draft B"
  },
  "writer_notes": "any decisions made or flags for the reviewer"
}
"""


def run(brief: dict, voice_notes: str = "") -> dict:
    """
    Write a content draft from a structured brief.

    Args:
        brief:        Output dict from brief-agent
        voice_notes:  Any additional voice or style notes from the operator (optional)

    Returns:
        Draft content dict with draft_a, draft_b, and writer_notes.
    """
    user_message = f"""
Content Brief:
{json.dumps(brief, indent=2)}

Additional Voice Notes from Operator:
{voice_notes or "None — follow the brief as written."}

Write draft_a and draft_b. Both must execute the brief's key_message and hook_angle
but from different angles. Return only JSON.
"""

    response = complete(
        task_type="content_draft",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "platform": brief.get("platform", "unknown"),
            "draft_a": {"text": "", "hook": "", "word_count": 0, "hashtags": [], "engagement_prompt": ""},
            "draft_b": {"text": "", "hook": "", "word_count": 0, "hashtags": [], "engagement_prompt": ""},
            "writer_notes": f"Draft agent returned unparseable response: {response[:200]}",
        }


if __name__ == "__main__":
    sample_brief = {
        "brief_title": "The hidden cost of CI/CD triage",
        "platform": "linkedin",
        "goal": "education",
        "hook_angle": "Your senior engineers are spending 2 hours diagnosing a pipeline failure before they can write a single line of fix.",
        "key_message": "The diagnosis phase of DevOps incidents is where the hours go — and it is automatable today.",
        "supporting_points": [
            "Average CI/CD triage: 1.5-3 hours before a fix is even started",
            "Autonomous triage agents reduce that to under 10 minutes",
            "That is 6-12 engineer-hours per week returned to feature work",
        ],
        "tone": "direct",
        "format": "problem-solution",
        "cta": "Ask your on-call engineer how long their last triage took.",
        "do_not_include": ["competitor names", "unverified statistics", "hype language"],
    }
    result = run(brief=sample_brief)
    print(json.dumps(result, indent=2))
