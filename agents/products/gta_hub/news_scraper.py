"""
Agent 04 - Decoded Six News Scraper
agents/products/gta_hub/news_scraper.py

Scrapes GTA 6 news sources every 6 hours (triggered by n8n cron),
summarizes via the platform LLM router, publishes to Supabase.

LLM calls route through .llm/router.py — never import provider SDKs directly.
"""

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from supabase import create_client, Client

log = logging.getLogger(__name__)

PRODUCT_ID = "gta-hub"
AGENT_NAME = "agent-04-news-scraper"
PROMPT_VERSION = "v1.0.0"

# Load the platform LLM router (same pattern as base_agent.py)
_router_path = Path(__file__).parent.parent.parent.parent / ".llm" / "router.py"
_spec = importlib.util.spec_from_file_location("llm_router", _router_path)
_router_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_router_module)
router = _router_module

NEWS_SOURCES = [
    {
        "name": "Reddit r/GTA6",
        "url": "https://www.reddit.com/r/GTA6/.rss",
        "category_hint": "rumor",
    },
    {
        "name": "Rockstar Newswire",
        "url": "https://www.rockstargames.com/newswire/feed",
        "category_hint": "news",
    },
    {
        "name": "Push Square",
        "url": "https://www.pushsquare.com/feeds/latest",
        "category_hint": "news",
    },
    {
        "name": "IGN GTA",
        "url": "https://feeds.feedburner.com/ign/games-articles",
        "category_hint": "news",
    },
    {
        "name": "GTA BOOM",
        "url": "https://www.gtaboom.com/feed/",
        "category_hint": "news",
    },
]

GTA6_KEYWORDS = [
    "gta 6", "gta6", "grand theft auto 6", "gta vi",
    "vice city", "leonida", "lucia", "jason gta",
    "gta online 6", "rockstar 2026", "rockstar 2027",
]

SUMMARIZE_SYSTEM = (
    "You are a precise JSON generator for Decoded Six, an independent GTA 6 news site. "
    "Return ONLY valid JSON. No markdown. No explanation. No code fences."
)

SUMMARIZE_PROMPT = """Write an original summary of this GTA 6 news item for our readers.
Do NOT copy the source text. Write original content in a clear, engaging style.

Source title: {title}
Source content: {content}
Source: {source_name}

Return a JSON object with these exact fields:
- "title": Original headline (6-12 words, improve on source if needed)
- "excerpt": 1-2 sentence hook (60-100 words)
- "content": Full body (300-500 words, original writing, paragraph breaks with double newline)
- "category": one of: news, rumor, guide, event, update"""


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].rstrip("-")


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:8]


def is_gta6_relevant(title: str, description: str) -> bool:
    text = f"{title} {description}".lower()
    return any(kw in text for kw in GTA6_KEYWORDS)


async def fetch_rss(url: str, client: httpx.AsyncClient) -> list[dict]:
    try:
        resp = await client.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []

        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            if title_el is not None and link_el is not None:
                items.append({
                    "title": (title_el.text or "").strip(),
                    "link": (link_el.text or "").strip(),
                    "description": (desc_el.text or "")[:600].strip() if desc_el is not None else "",
                })

        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            summary_el = entry.find("atom:summary", ns)
            if title_el is not None and link_el is not None:
                items.append({
                    "title": (title_el.text or "").strip(),
                    "link": link_el.get("href", ""),
                    "description": (summary_el.text or "")[:600].strip() if summary_el is not None else "",
                })

        return items[:10]
    except Exception as e:
        log.warning("RSS fetch error for %s: %s", url, e)
        return []


def article_exists(supabase_client: Client, source_url: str) -> bool:
    result = (
        supabase_client.table("articles")
        .select("id")
        .eq("source_url", source_url)
        .limit(1)
        .execute()
    )
    return len(result.data) > 0


def process_item(item: dict, source: dict) -> Optional[dict]:
    """Call LLM router to summarize one news item. Returns insert-ready dict or None."""
    if not item.get("title") or not item.get("link"):
        return None

    if not is_gta6_relevant(item["title"], item.get("description", "")):
        return None

    prompt = SUMMARIZE_PROMPT.format(
        title=item["title"],
        content=item.get("description", item["title"]),
        source_name=source["name"],
    )

    try:
        response = router.complete(
            task_type="content_generation",
            messages=[{"role": "user", "content": prompt}],
            system_prompt=SUMMARIZE_SYSTEM,
            max_tokens=900,
        )
        parsed = json.loads(response)
    except Exception as e:
        log.warning("LLM error for '%s': %s", item["title"], e)
        return None

    title = parsed.get("title", item["title"])
    slug = f"{slugify(title)}-{url_hash(item['link'])}"

    return {
        "product_id": PRODUCT_ID,
        "title": title,
        "slug": slug,
        "excerpt": parsed.get("excerpt", ""),
        "content": parsed.get("content", ""),
        "source_url": item["link"],
        "source_name": source["name"],
        "category": parsed.get("category", source["category_hint"]),
        "status": "published",
        "agent_generated": True,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }


async def run_scraper() -> dict:
    """
    Main scraper loop. Called by FastAPI background task from n8n webhook.
    Returns summary dict with published count and any errors.
    """
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_SERVICE_KEY"]
    supabase_client = create_client(supabase_url, supabase_key)

    log_row = (
        supabase_client.table("agents_log")
        .insert({
            "product_id": PRODUCT_ID,
            "agent_name": AGENT_NAME,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        .execute()
    )
    log_id = log_row.data[0]["id"]

    published = 0
    errors: list[str] = []

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "DecodedSix/1.0 (GTA6 News Aggregator; +https://decodedsix.com)"},
        ) as client:
            for source in NEWS_SOURCES:
                log.info("Fetching source: %s", source["name"])
                items = await fetch_rss(source["url"], client)

                for item in items:
                    try:
                        if article_exists(supabase_client, item.get("link", "")):
                            continue

                        article = process_item(item, source)
                        if article:
                            supabase_client.table("articles").insert(article).execute()
                            published += 1
                            log.info("Published: %s", article["title"])

                    except Exception as e:
                        msg = f"{item.get('title', '?')}: {e}"
                        errors.append(msg)
                        log.warning("Item error: %s", msg)

                await asyncio.sleep(1)

        supabase_client.table("agents_log").update({
            "status": "success",
            "records_processed": published,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", log_id).execute()

    except Exception as e:
        supabase_client.table("agents_log").update({
            "status": "error",
            "error_message": str(e)[:500],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", log_id).execute()
        raise

    return {
        "published": published,
        "sources_checked": len(NEWS_SOURCES),
        "errors": errors,
    }
