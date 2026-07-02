"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Publish Agent — Content Operations
agents/content/publish-agent/agent.py

Takes an approved draft from review-agent and formats it for scheduling.
Validates platform compliance (character limits, hashtag rules, format)
and produces a publish-ready package with metadata.

This agent does NOT post content. It prepares the package that a human
or scheduling tool uses to publish. External communications require human
approval on first use per client (Governance Rule per MISSION.md).
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a content publishing preparation agent for THD Agentic Systems LLC (Cloud Decoded).

Your job: take an approved content draft and format it into a publish-ready package
with platform compliance checks and scheduling metadata.

Platform compliance rules:
  LinkedIn:
    - Max 3,000 characters (warn above 2,500)
    - Max 5 hashtags recommended (flag if more than 5)
    - No @mentions unless specifically provided
    - Images: flag if visual recommendation is needed but none provided
    - Native documents (carousels): flag if format suggests one

  X (Twitter):
    - Main post: 280 characters max (hard limit)
    - Thread posts: 280 characters each
    - Max 2 hashtags in main post recommended
    - Media alt-text: flag if image mentioned but no alt-text provided

  Short-form video (TikTok/Reels/Shorts):
    - Script under 150 words for 60-second video
    - First line must work as on-screen caption
    - Flag if hook is longer than 15 words
    - Provide caption text separate from script

Your output is NOT for the agent to post. It is a package for the human operator
or scheduling tool to use. Flag anything that requires human decision before posting.

Output schema (return ONLY this JSON, no other text):
{
  "platform": "linkedin" or "x" or "video",
  "publish_ready": true or false,
  "compliance_passed": true or false,
  "compliance_notes": ["list of any compliance flags — empty if all clear"],
  "publish_package": {
    "main_text": "the final post text, ready to copy-paste",
    "character_count": integer,
    "hashtags": ["formatted hashtag list — empty if none"],
    "thread_posts": ["for X threads only — list of follow-on post texts, empty otherwise"],
    "caption_text": "for video only — what appears on screen, empty otherwise",
    "alt_text_needed": true or false,
    "visual_recommendation": "describe what image/visual would strengthen this post, or empty string"
  },
  "scheduling_metadata": {
    "campaign_tag": "campaign identifier if provided, else empty string",
    "recommended_post_time": "best time to post for this platform and audience (e.g. Tue-Thu 8-10am EST)",
    "content_pillar": "education" or "credibility" or "awareness" or "lead_gen"
  },
  "operator_flags": ["anything the human must decide before posting — empty if none"]
}
"""


def run(
    approved_draft: str,
    platform: str,
    brief: dict,
    scheduled_time: str = "",
    campaign_tag: str = "",
    visual_provided: bool = False,
) -> dict:
    """
    Format an approved draft into a publish-ready package.

    Args:
        approved_draft:    The approved text from review-agent's approved_draft field
        platform:          "linkedin", "x", or "video"
        brief:             Original content brief from brief-agent (for metadata)
        scheduled_time:    ISO timestamp or readable time if already scheduled (optional)
        campaign_tag:      Campaign identifier for tracking (optional)
        visual_provided:   Whether a visual/image has already been prepared (optional)

    Returns:
        Publish-ready package dict.
    """
    user_message = f"""
Platform: {platform}
Visual Provided: {"yes" if visual_provided else "no"}
Campaign Tag: {campaign_tag or "none"}
Scheduled Time: {scheduled_time or "not yet set"}

Approved Draft:
{approved_draft}

Original Brief (for metadata):
{json.dumps(brief, indent=2)}

Validate compliance for {platform} and produce the publish package.
Flag anything requiring human decision. Return only JSON.
"""

    response = complete(
        task_type="content_publish_prep",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "platform": platform,
            "publish_ready": False,
            "compliance_passed": False,
            "compliance_notes": ["Publish agent returned unparseable response"],
            "publish_package": {
                "main_text": approved_draft,
                "character_count": len(approved_draft),
                "hashtags": [],
                "thread_posts": [],
                "caption_text": "",
                "alt_text_needed": False,
                "visual_recommendation": "",
            },
            "scheduling_metadata": {
                "campaign_tag": campaign_tag,
                "recommended_post_time": "",
                "content_pillar": brief.get("goal", "education"),
            },
            "operator_flags": [f"Parse error: {response[:200]}"],
        }


if __name__ == "__main__":
    approved = """Your engineers are losing 2 hours per CI/CD failure to diagnosis alone.

Not fixing. Not shipping. Just triaging.

3 failures per week. 2 hours each. That is 6 engineer-hours before a single fix begins.

Autonomous triage agents cut that to under 10 minutes.

The diagnosis phase is the part nobody talks about. It is also the part that is fully automatable today.

Ask your on-call engineer: how long did your last triage take?

#DevOps #CloudEngineering #PlatformEngineering #SRE #CloudDecoded"""

    brief = {"goal": "education", "platform": "linkedin", "brief_title": "Hidden cost of CI/CD triage"}

    result = run(
        approved_draft=approved,
        platform="linkedin",
        brief=brief,
        campaign_tag="q3-education-series",
    )
    print(json.dumps(result, indent=2))
