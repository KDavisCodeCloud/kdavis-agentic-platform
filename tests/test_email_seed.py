"""
tests/test_email_seed.py
core/email_seed.py -- idempotent seeding of sequences/templates from
core/email_content/*.py, and a content-integrity check across every
module (every template's sequence_key resolves to a real sequence, no
duplicate template keys, step_number/delay_days shape is sane) so a typo
in one of the ~90 seed rows fails a test instead of shipping silently.
"""

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from core import email_seed


def _mock_pool(conn):
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


class TestSeedAllIsIdempotent:
    async def test_on_conflict_do_nothing_used_for_both_tables(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        pool = _mock_pool(conn)

        await email_seed.seed_all(pool)

        sequence_sqls = [c.args[0] for c in conn.execute.await_args_list if "cd_email_sequences" in c.args[0]]
        template_sqls = [c.args[0] for c in conn.execute.await_args_list if "cd_email_templates" in c.args[0]]
        assert sequence_sqls and all("ON CONFLICT (key) DO NOTHING" in s for s in sequence_sqls)
        assert template_sqls and all("ON CONFLICT (key) DO NOTHING" in s for s in template_sqls)

    async def test_second_run_with_all_conflicts_inserts_nothing(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="INSERT 0 0")  # every row already exists
        pool = _mock_pool(conn)

        summary = await email_seed.seed_all(pool)

        assert summary["sequences_inserted"] == 0
        assert summary["templates_inserted"] == 0


class TestContentIntegrity:
    """Real content modules, no mocking -- catches a typo'd sequence_key
    or a duplicate template key before it ever reaches the database."""

    def test_every_module_has_consistent_sequence_keys(self):
        seen_template_keys: set[str] = set()
        for name in email_seed._CONTENT_MODULES:
            module = importlib.import_module(f"core.email_content.{name}")
            sequences = getattr(module, "SEQUENCES", None) or [module.SEQUENCE]
            sequence_keys = {s["key"] for s in sequences}
            default_key = sequence_keys.copy().pop() if len(sequence_keys) == 1 else None

            templates = list(getattr(module, "TEMPLATES", []))
            templates += list(getattr(module, "OVERFLOW_TEMPLATES", []))
            assert templates, f"{name} defines no templates"

            for t in templates:
                key = t.get("sequence_key") or default_key
                assert key in sequence_keys, (
                    f"{name}: template {t['key']!r} references sequence_key {key!r}, "
                    f"not one of {sequence_keys}"
                )
                assert t["key"] not in seen_template_keys, f"duplicate template key: {t['key']!r}"
                seen_template_keys.add(t["key"])
                assert t["step_number"] >= 1
                assert t["delay_days"] >= 0
                assert t["subject"]
                assert t["body_html"]
                assert t["body_text"]

    def test_no_duplicate_sequence_keys_across_modules(self):
        seen: set[str] = set()
        for name in email_seed._CONTENT_MODULES:
            module = importlib.import_module(f"core.email_content.{name}")
            sequences = getattr(module, "SEQUENCES", None) or [module.SEQUENCE]
            for s in sequences:
                assert s["key"] not in seen, f"duplicate sequence key: {s['key']!r}"
                seen.add(s["key"])

    def test_onboarding_day_offsets_match_the_build_spec(self):
        """Steps 1/2/4/6/9/14 -- the spec's day offsets, minus the day-0
        welcome (already sent transactionally, see onboarding.py's
        module docstring for the dedup reasoning)."""
        onboarding = importlib.import_module("core.email_content.onboarding")
        cumulative = 0
        offsets = []
        for t in sorted(onboarding.TEMPLATES, key=lambda x: x["step_number"]):
            cumulative += t["delay_days"]
            offsets.append(cumulative)
        assert offsets == [1, 2, 4, 6, 9, 14]
