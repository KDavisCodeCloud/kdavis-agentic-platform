"""
GTA Hub API routes
api/routes/gta_hub.py

Receives n8n webhook triggers for Agent 04 and exposes agent status.
Wire into api/main.py: app.include_router(gta_hub.router)
"""

import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gta-hub", tags=["gta-hub"])

_SERVICE_KEY = os.environ.get("GTA_HUB_SERVICE_KEY", "")


def _verify_key(x_service_key: str = Header(default="")):
    if _SERVICE_KEY and x_service_key != _SERVICE_KEY:
        raise HTTPException(status_code=403, detail="Invalid service key")
    return x_service_key


class RunResponse(BaseModel):
    status: str
    message: str


@router.post("/agents/news-scraper", response_model=RunResponse)
async def trigger_news_scraper(
    background_tasks: BackgroundTasks,
    _: str = Depends(_verify_key),
):
    """
    Trigger Agent 04 news scraper.
    n8n cron calls this endpoint every 6 hours.
    Agent runs in background to avoid HTTP timeout.

    n8n HTTP Request node config:
      Method: POST
      URL: https://api.theclouddecoded.com/api/v1/gta-hub/agents/news-scraper
      Header: X-Service-Key: {GTA_HUB_SERVICE_KEY}
    """
    from agents.products.gta_hub.news_scraper import run_scraper

    background_tasks.add_task(run_scraper)
    log.info("Agent 04 triggered via n8n webhook")

    return RunResponse(
        status="started",
        message="Agent 04 news scraper running in background",
    )


@router.get("/agents/status")
async def get_agent_status(_: str = Depends(_verify_key)):
    """Return last 10 agent runs from agents_log table."""
    import os
    from supabase import create_client

    client = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )
    result = (
        client.table("agents_log")
        .select("*")
        .eq("product_id", "gta-hub")
        .order("started_at", desc=True)
        .limit(10)
        .execute()
    )
    return {"logs": result.data}


@router.get("/articles/count")
async def get_article_count(_: str = Depends(_verify_key)):
    """Quick count of published articles for monitoring."""
    import os
    from supabase import create_client

    client = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )
    result = (
        client.table("articles")
        .select("id", count="exact")
        .eq("product_id", "gta-hub")
        .eq("status", "published")
        .execute()
    )
    return {"published_articles": result.count}
