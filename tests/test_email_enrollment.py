"""
tests/test_email_enrollment.py
core/email_enrollment.py -- subscriber upsert, enroll/exit helpers, and
the has_ever_enrolled_by_email guard scheduled scans depend on to avoid
re-enrolling (and re-sending step 1) on every pass.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

from core import email_enrollment as ee


class TestGetOrCreateSubscriber:
    async def test_upserts_by_lower_email(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": uuid4()})
        await ee.get_or_create_subscriber(conn, "Jane@Example.com", "newsletter_signup")
        sql, email_arg, source_arg, workspace_arg = conn.fetchrow.await_args.args
        assert "ON CONFLICT (lower(email))" in sql
        assert email_arg == "jane@example.com"
        assert source_arg == "newsletter_signup"
        assert workspace_arg is None


class TestEnroll:
    async def test_enroll_resets_to_step_zero_on_reenrollment(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": uuid4()})
        await ee.enroll(conn, str(uuid4()), "onboarding")
        sql = conn.fetchrow.await_args.args[0]
        assert "current_step = 0, status = 'active', next_send_at = NOW()" in sql
        assert "ON CONFLICT (subscriber_id, sequence_key)" in sql


class TestExitAllEnrollments:
    async def test_excludes_named_sequences(self):
        conn = AsyncMock()
        await ee.exit_all_enrollments(conn, str(uuid4()), "workspace_canceled", except_sequences=("winback",))
        args = conn.execute.await_args.args
        assert args[2] == "workspace_canceled"
        assert args[3] == ["winback"]


class TestHasEverEnrolledByEmail:
    async def test_true_when_a_row_exists(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"1": 1})
        assert await ee.has_ever_enrolled_by_email(conn, "a@b.com", "stall_nudges") is True

    async def test_false_when_no_row(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        assert await ee.has_ever_enrolled_by_email(conn, "a@b.com", "stall_nudges") is False


class TestExitByEmailNoSubscriber:
    async def test_noop_when_subscriber_does_not_exist(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # get_subscriber_id_by_email finds nothing
        await ee.exit_by_email(conn, "ghost@b.com", "onboarding", "converted")
        # Only the lookup happened -- no UPDATE was attempted for a subscriber that doesn't exist.
        update_calls = [c for c in conn.execute.await_args_list if "UPDATE cd_email_enrollments" in c.args[0]]
        assert len(update_calls) == 0
