"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Review Agent — Content Operations
agents/content/review-agent/agent.py

Reviews a draft from draft-agent against the original brief, brand voice rules,
and accuracy standards. Either approves the draft for publish-agent or returns
a revised version with specific changes.

This is the gate before any content goes to publish-agent.
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a content review agent for THD Agentic Systems LLC (Cloud Decoded).

Your job: review a content draft against the original brief and brand voice standards.
You approve it if it is ready to publish. You revise it if it is not.

Brand voice standards (non-negotiable):
- Voice: Direct, practitioner-first, no hype. Sounds like a senior engineer, not a marketer.
- Never uses: "game-changer", "revolutionize", "transform", "unlock potential",
  "cutting-edge", "harness the power of", "in today's world", "the future of"
- Specific over vague: "2 hours per incident" beats "hours of wasted time"
- No corporate filler: "leverage", "synergy", "ecosystem", "at scale" (as a standalone claim)
- First-person is fine. Passive voice is not.
- Claims must be supportable — no invented statistics or unverified assertions
- Em-dashes are banned on LinkedIn. Use periods and line breaks.

Review checklist:
  1. Does it execute the brief's hook_angle and key_message?
  2. Does it match the platform format rules?
  3. Is the voice correct? (direct, practitioner, not salesy)
  4. Are there any banned words or phrases?
  5. Are any claims unverifiable or exaggerated?
  6. Is the CTA clear and low-friction?
  7. Word count within platform limits?

Output schema (return ONLY this JSON, no other text):
{
  "decision": "approved" or "revised",
  "brand_voice_score": 1-10,
  "brief_alignment_score": 1-10,
  "flags": [
    {
      "type": "banned_phrase" or "vague_claim" or "format_violation" or "brief_miss" or "accuracy_risk",
      "quote": "exact text from the draft that triggered the flag",
      "reason": "why this is flagged"
    }
  ],
  "approved_draft": "the approved text — original if approved, revised if decision is revised",
  "revision_notes": "what was changed and why — empty string if approved unchanged"
}
"""


def run(draft_text: str, brief: dict, platform: str) -> dict:
    """
    Review a content draft for brand voice and brief alignment.

    Args:
        draft_text:  The draft to review (from draft-agent's draft_a or draft_b)
        brief:       The original content brief from brief-agent
        platform:    "linkedin", "x", or "video"

    Returns:
        Review decision dict with approved_draft ready for publish-agent.
    """
    user_message = f"""
Platform: {platform}

Original Brief:
{json.dumps(brief, indent=2)}

Draft to Review:
{draft_text}

Review this draft against the brief and brand voice standards.
If it needs changes, revise it and explain what changed.
Return only JSON.
"""

    response = complete(
        task_type="content_review",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "decision": "revised",
            "brand_voice_score": 0,
            "brief_alignment_score": 0,
            "flags": [{"type": "accuracy_risk", "quote": "", "reason": "Review agent returned unparseable response"}],
            "approved_draft": draft_text,
            "revision_notes": f"Review agent parse error: {response[:200]}",
        }


if __name__ == "__main__":
    sample_brief = {
        "brief_title": "The hidden cost of CI/CD triage",
        "platform": "linkedin",
        "goal": "education",
        "hook_angle": "Your senior engineers are spending 2 hours diagnosing a pipeline failure before they can write a single line of fix.",
        "key_message": "The diagnosis phase of DevOps incidents is automatable today.",
        "tone": "direct",
        "cta": "Ask your on-call engineer how long their last triage took.",
        "do_not_include": ["competitor names", "unverified statistics"],
    }
    sample_draft = """Your engineers are losing 2 hours per CI/CD failure to diagnosis alone.

Not fixing. Not shipping. Just triaging.

Here's what that looks like in real numbers:
- 3 pipeline failures per week
- 2 hours each to triage
- 6 engineer-hours per week — before a single fix begins

Autonomous triage agents cut that to under 10 minutes.

The diagnosis phase is the part nobody talks about. It's also the part that's fully automatable today.

Ask your on-call engineer: how long did your last triage take?

#DevOps #CloudEngineering #PlatformEngineering #SRE #CloudDecoded"""

    result = run(
        draft_text=sample_draft,
        brief=sample_brief,
        platform="linkedin",
    )
    print(json.dumps(result, indent=2))
