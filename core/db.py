"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
core/db.py — shared asyncpg connection setup.

asyncpg has no built-in jsonb/json decoding: without a codec registered,
every jsonb column comes back as a raw JSON string instead of a parsed
dict/list. Confirmed live 2026-08-03 as the root cause of every LinkedIn
dispatch cron run failing ("dictionary update sequence element #0 has
length 1; 2 is required" -- dict() on a raw '{}' string iterates its
characters, not key/value pairs). Neither api/main.py's pool nor
scripts/dispatch_scheduled_posts.py's raw connect() had this registered,
so the bug hit both the cron and the dashboard's manual publish button
identically -- this is registered on both via init= so any future
asyncpg connection in this repo gets it automatically by using this helper.
"""

import json


async def register_jsonb_codec(conn) -> None:
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
