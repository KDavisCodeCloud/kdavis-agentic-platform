"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Idempotent seeding of the Cloud Decoded email lifecycle system's
sequences + templates (migration 051) from the generated copy in
core/email_content/*.py. ON CONFLICT DO NOTHING on both tables' natural
keys -- re-running never overwrites a template Kelvin has since approved
or edited (edits go through the approval API's edit-resets-to-pending
path, never this seed script).

Run automatically once at every app startup (api/main.py's lifespan,
right after migrations) -- cheap (under 100 rows, all-or-nothing per
row), and guarantees the approval queue is populated in production
without a manual step. Also runnable standalone:
    python -m core.email_seed
"""

import importlib
import json
import logging

log = logging.getLogger(__name__)

_CONTENT_MODULES = [
    "onboarding", "stall_nudges", "abandoned_checkout", "dunning",
    "winback", "expansion", "trust_drip", "newsletter",
]


async def seed_all(pool) -> dict:
    summary = {"sequences_inserted": 0, "templates_inserted": 0}

    async with pool.acquire() as conn:
        for name in _CONTENT_MODULES:
            module = importlib.import_module(f"core.email_content.{name}")
            sequences = getattr(module, "SEQUENCES", None) or [module.SEQUENCE]

            for seq in sequences:
                result = await conn.execute(
                    """
                    INSERT INTO cd_email_sequences (key, name, description, trigger_type, exit_rules)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    seq["key"], seq["name"], seq["description"], seq["trigger_type"],
                    json.dumps(seq["exit_rules"]),
                )
                if result == "INSERT 0 1":
                    summary["sequences_inserted"] += 1

            default_sequence_key = sequences[0]["key"] if len(sequences) == 1 else None
            templates = list(getattr(module, "TEMPLATES", []))
            templates += list(getattr(module, "OVERFLOW_TEMPLATES", []))

            for t in templates:
                sequence_key = t.get("sequence_key") or default_sequence_key
                if not sequence_key:
                    raise ValueError(
                        f"core.email_content.{name}: template {t['key']!r} has no sequence_key and "
                        f"the module defines more than one sequence -- cannot infer which one it belongs to"
                    )
                result = await conn.execute(
                    """
                    INSERT INTO cd_email_templates
                        (key, sequence_key, step_number, delay_days, subject, preheader,
                         body_html, body_text, cta_url, skip_if, origin)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'generated')
                    ON CONFLICT (key) DO NOTHING
                    """,
                    t["key"], sequence_key, t["step_number"], t["delay_days"], t["subject"],
                    t.get("preheader"), t["body_html"], t["body_text"], t.get("cta_url"), t.get("skip_if"),
                )
                if result == "INSERT 0 1":
                    summary["templates_inserted"] += 1

    log.info("[EmailSeed] %s", summary)
    return summary


if __name__ == "__main__":
    import asyncio
    import os

    async def _main() -> None:
        import asyncpg

        url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2, statement_cache_size=0)
        try:
            result = await seed_all(pool)
            print(result)
        finally:
            await pool.close()

    asyncio.run(_main())
