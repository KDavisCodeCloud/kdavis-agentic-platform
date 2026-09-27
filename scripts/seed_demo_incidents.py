"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

24-gap-closure build, Phase 6 -- demo/sandbox mode seed script. Inserts
8-10 synthetic incidents (incidents.is_test = true, migration 046)
directly into a target workspace so a prospect or trial customer can see
a realistic, populated HITL Console immediately, without waiting for
real cloud activity.

Approve/reject on these rows genuinely works (api/routes/incidents.py's
approve_incident already short-circuits is_test rows to a simulated
"executed" result instead of resuming any real agent workflow -- see
that route's own comment) -- so this is not a fake read-only demo, it's
real interaction against rows that simply can never trigger a real
cloud-side action. Reject/dismiss already never executed anything for
ANY incident (including real ones), so nothing extra was needed there.

CLI-only wrapper. The live app never shells out to this -- GET /demo
(api/routes/demo.py) and the 30-minute reset loop (api/main.py's
_demo_reset_loop) both call core.demo_sandbox.insert_demo_incidents
directly against the app's own connection pool. This script exists for
manually seeding a non-demo workspace (e.g. a real prospect's trial
workspace, on request) with the same realistic baseline.

Usage:
    python -m scripts.seed_demo_incidents <workspace_id> [--wipe-first]

--wipe-first deletes any existing is_test rows for this workspace before
seeding, so re-running the script is idempotent instead of accumulating
duplicates on every demo reset.
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import asyncpg

from core.demo_sandbox import insert_demo_incidents  # noqa: E402 -- see sys.path insert above


async def seed(workspace_id: str, wipe_first: bool) -> None:
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    ws_uuid = UUID(workspace_id)
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        row = await conn.fetchrow("SELECT id FROM workspaces WHERE id = $1", ws_uuid)
        if not row:
            print(f"No workspace found with id {workspace_id}", file=sys.stderr)
            sys.exit(1)

        count = await insert_demo_incidents(conn, ws_uuid, wipe_first=wipe_first)
        print(f"Seeded {count} demo incidents for workspace {workspace_id}")
    finally:
        await conn.close()


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    workspace_id = sys.argv[1]
    wipe_first = "--wipe-first" in sys.argv
    asyncio.run(seed(workspace_id, wipe_first))


if __name__ == "__main__":
    main()
