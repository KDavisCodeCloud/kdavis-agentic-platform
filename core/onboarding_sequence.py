"""
DEPRECATED 2026-09-21 -- superseded by the Cloud Decoded email lifecycle
system (migration 051, core/email_scheduler.py). This module used to run
a 3-email day0/day2/day5 sequence (day 0 was always core/email.py's
separate synchronous welcome email; this module added day 2 and day 5 on
a 6-hourly periodic scan). That content and its skip_if gating (real
setup-checklist signals, core/setup_checklist.py) were folded into the
new engine's 'onboarding' sequence as steps 2-3
(core/email_content/onboarding.py's seed data); checkout now enrolls
every new workspace into that sequence directly
(api/routes/stripe_billing.py's _enroll_onboarding_email_sequence).

Running both would double-send the same onboarding nudges, so
run_onboarding_sequence_check is now a no-op -- kept (not deleted) so
api/main.py's existing task registration and the workspace_onboarding_emails
table (migration 041) don't need touching, and so a rollback of the new
engine is a one-line revert of this file rather than restoring deleted
code. The original ~100-line implementation is in git history (this
file, prior to 2026-09-21) if it's ever needed as a reference.
"""

import logging

import asyncpg

log = logging.getLogger(__name__)


async def run_onboarding_sequence_check(pool: asyncpg.Pool) -> dict:
    """No-op -- see module docstring. Returns the same shape the real
    implementation used to, so api/main.py's periodic loop needs no
    changes."""
    log.info("[Onboarding] Retired in favor of the email lifecycle system's 'onboarding' sequence -- no-op")
    return {"day2_checklist": 0, "day5_setup_help": 0}
