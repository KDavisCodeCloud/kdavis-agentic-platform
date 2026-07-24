"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Marketing routes — triggers the Wave 2 marketing agents
(agents/marketing/*.py): MKT-LI1, MKT-V1, MKT-N1, MKT-CN1.

Internal-only surface (Kelvin's personal brand + empire-wide content
engine, not a customer-facing workspace feature) — auth is a shared
X-API-Key header (MARKETING_API_KEY), same dev-mode-if-unset shape as
decoded-six's api/auth.py, not the customer X-Workspace-Token flow in
api/middleware/auth.py (that's scoped to paying-customer workspaces,
which doesn't apply here). Mirrors the existing internal shared-secret
pattern already in this repo (api/middleware/auth.py's X-MCP-Service-Key
path) rather than introducing a new auth style.

Every agent call here only drafts into a HITL queue table
(linkedin_content_queue / content_queue / newsletter_queue) —
nothing in this router publishes anything.
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from agents.marketing.mkt_cn1_image_brief import run_cn1_image_brief
from agents.marketing.mkt_li1_linkedin_brand import run_li1_brand_agent
from agents.marketing.mkt_n1_newsletter import run_n1_newsletter
from agents.marketing.mkt_v1_content_multiplier import run_v1_content_multiplier

log = logging.getLogger(__name__)
router = APIRouter(prefix="/marketing", tags=["marketing"])

_MARKETING_API_KEY = os.environ.get("MARKETING_API_KEY", "")
_dev_mode_warned = False


def require_marketing_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> None:
    global _dev_mode_warned
    if not _MARKETING_API_KEY:
        if not _dev_mode_warned:
            log.warning("MARKETING_API_KEY not set — /marketing routes running with no auth (dev mode)")
            _dev_mode_warned = True
        return
    if x_api_key != _MARKETING_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


class LinkedInBrandRequest(BaseModel):
    research_report: dict
    idea_reservoir: list
    kelvin_voice_profile: dict
    build_updates: list = Field(default_factory=list)
    batch_month: Optional[str] = None


class ContentMultiplyRequest(BaseModel):
    research_report: dict
    brand_voice_profile: dict
    target_platforms: list[str]
    high_performers: list = Field(default_factory=list)


class NewsletterRequest(BaseModel):
    research_report: dict
    brand_voice_profile: dict
    list_segment: str
    variant: str = "cloud_decoded"


class ImageBriefRequest(BaseModel):
    image_brief_input: dict
    post_type: str = "square"


@router.post("/linkedin-brand")
def linkedin_brand(body: LinkedInBrandRequest, _: None = Depends(require_marketing_api_key)) -> dict:
    try:
        posts = run_li1_brand_agent(
            body.research_report, body.idea_reservoir, body.kelvin_voice_profile,
            build_updates=body.build_updates,
            batch_month=body.batch_month,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MKT-LI1 failed: {exc}") from exc

    return {
        "success": True,
        "post_count": len(posts),
        "queue_ids": [post["id"] for post in posts if post.get("id")],
        # Full drafted posts (topic/pillar/image_description/id per post) —
        # scripts/monthly_batch.sh saves this response and pipes it into
        # assets_library/extract_image_briefs.py, which needs more than
        # just queue_ids to build Gemini's per-post image briefs.
        "posts": posts,
    }


@router.post("/content-multiply")
def content_multiply(body: ContentMultiplyRequest, _: None = Depends(require_marketing_api_key)) -> dict:
    try:
        drafts = run_v1_content_multiplier(
            body.research_report, body.brand_voice_profile, body.target_platforms,
            high_performers=body.high_performers,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MKT-V1 failed: {exc}") from exc

    return {"success": True, "platform_count": len(body.target_platforms)}


@router.post("/newsletter")
def newsletter(body: NewsletterRequest, _: None = Depends(require_marketing_api_key)) -> dict:
    try:
        draft = run_n1_newsletter(
            body.research_report, body.brand_voice_profile, body.list_segment,
            variant=body.variant,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MKT-N1 failed: {exc}") from exc

    return {"success": True, "newsletter_id": draft.get("id")}


@router.post("/image-brief")
def image_brief(body: ImageBriefRequest, _: None = Depends(require_marketing_api_key)) -> dict:
    try:
        brief = run_cn1_image_brief(body.image_brief_input, post_type=body.post_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MKT-CN1 failed: {exc}") from exc

    return {"success": True, "brief": brief}
