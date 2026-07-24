"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
dispatch_scheduled_posts.py — the "approve once, it runs itself the rest
of the month" half of the monthly batch cadence.

Runs on a cron (.github/workflows/linkedin-dispatch.yml). Finds every
linkedin_content_queue row that is status='approved', has a scheduled_for
in the past, and hasn't been published yet, and publishes each one via
api.routes.internal_marketing.publish_queue_row — the exact same logic
the dashboard's manual publish button uses (refactored out of that route
2026-07-23 specifically so this script and the route share one
implementation, not two that could drift).

Runs with its own asyncpg connection rather than going through the HTTP
route: this script runs unattended (no human present to hold a live
admin Supabase session JWT, which api.middleware.internal_auth.
get_internal_user requires) — the same reason job_queue/worker.py and
the other standalone scripts in this repo (image_indexer.py,
asset_selector.py) talk to Supabase/Postgres directly instead of through
FastAPI.

One bad row never blocks the rest of the batch — matches
job_queue/worker.py's "isolate one bad message from the rest" pattern.
Every outcome (success or failure) is printed so the GitHub Actions log
is a complete record of what did and didn't go out.
"""

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

from api.routes.internal_marketing import PublishError, publish_queue_row  # noqa: E402


async def dispatch_due_posts(conn) -> dict:
    due_rows = await conn.fetch(
        """
        SELECT id FROM linkedin_content_queue
        WHERE status = 'approved'
          AND scheduled_for <= now()
          AND published_at IS NULL
        ORDER BY scheduled_for
        """
    )

    published = 0
    failed = 0
    results: list[str] = []

    for row in due_rows:
        queue_id = str(row["id"])
        try:
            result = await publish_queue_row(conn, queue_id)
            published += 1
            results.append(f"OK   {queue_id} -> {result['url']}")
        except PublishError as exc:
            failed += 1
            results.append(f"FAIL {queue_id}: [{exc.status_code}] {exc.detail}")
        except Exception as exc:  # noqa: BLE001 — one row's failure must never stop the rest
            failed += 1
            results.append(f"FAIL {queue_id}: unexpected error: {exc}")

    return {"due": len(due_rows), "published": published, "failed": failed, "results": results}


async def main() -> None:
    database_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(database_url, statement_cache_size=0)
    try:
        summary = await dispatch_due_posts(conn)
    finally:
        await conn.close()

    print(f"{summary['due']} due, {summary['published']} published, {summary['failed']} failed")
    for line in summary["results"]:
        print(f"  {line}")

    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
