"""
tests/test_onboarding_sequence.py
core/onboarding_sequence.py was retired 2026-09-21 in favor of the Cloud
Decoded email lifecycle system's 'onboarding' sequence (migration 051,
core/email_scheduler.py) -- see that module's docstring. This just
confirms the no-op contract api/main.py's existing periodic task depends
on: same return shape, and never touches the pool (no lock, no query, no
send) now that there's nothing left for it to do.
"""

from unittest.mock import MagicMock

from core import onboarding_sequence


class TestRunOnboardingSequenceCheckIsRetired:
    async def test_returns_the_legacy_shape_with_zero_counts(self):
        pool = MagicMock()
        result = await onboarding_sequence.run_onboarding_sequence_check(pool)
        assert result == {"day2_checklist": 0, "day5_setup_help": 0}

    async def test_never_touches_the_pool(self):
        pool = MagicMock()
        await onboarding_sequence.run_onboarding_sequence_check(pool)
        pool.acquire.assert_not_called()
