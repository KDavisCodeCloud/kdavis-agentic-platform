"""
tests/test_oauth_state_store.py
2026-09-22 incident fix -- migrations 053/054 replace in-memory OAuth
state dicts (broken under this service's 4-worker production deployment
-- a state minted on one worker was invisible to whichever worker
handled the callback) with Postgres-backed storage in
api/routes/internal_marketing.py (owner-only LinkedIn/Canva connect) and
api/routes/content.py (customer-facing LinkedIn/X connect). Both modules'
_store_oauth_state/_pop_oauth_state helpers share the same shape; tested
against each module directly rather than a shared helper module, since
that's how the code is actually structured (deliberately not merged --
see internal_marketing.py's own docstring on not conflating the two
OAuth flows).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from api.routes import content, internal_marketing


class TestInternalMarketingOAuthState:
    async def test_store_then_pop_round_trips(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"issued_at": datetime.now(timezone.utc), "code_verifier": None}
        )

        await internal_marketing._store_oauth_state(conn, "state-1", "linkedin")
        result = await internal_marketing._pop_oauth_state(conn, "state-1", "linkedin")

        assert conn.execute.await_count == 2  # cleanup delete + insert
        assert result["code_verifier"] is None

    async def test_pop_unknown_state_returns_none(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        result = await internal_marketing._pop_oauth_state(conn, "nonexistent", "linkedin")

        assert result is None

    async def test_pop_is_a_delete_returning_query_not_a_plain_select(self):
        """The whole point is atomic single-use consumption -- a replayed
        callback with the same state must fail exactly like an unknown one,
        which only holds if the pop is DELETE ... RETURNING, not SELECT."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        await internal_marketing._pop_oauth_state(conn, "state-1", "canva")

        query = conn.fetchrow.await_args.args[0]
        assert "DELETE" in query
        assert "RETURNING" in query

    async def test_canva_state_carries_code_verifier(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"issued_at": datetime.now(timezone.utc), "code_verifier": "verifier-abc"}
        )

        result = await internal_marketing._pop_oauth_state(conn, "state-1", "canva")

        assert result["code_verifier"] == "verifier-abc"


class TestContentOAuthState:
    async def test_store_then_pop_round_trips_with_workspace_id(self):
        conn = AsyncMock()
        workspace_id = uuid4()
        conn.fetchrow = AsyncMock(
            return_value={
                "workspace_id": workspace_id,
                "code_verifier": None,
                "issued_at": datetime.now(timezone.utc),
            }
        )

        await content._store_oauth_state(conn, "state-1", str(workspace_id), "linkedin")
        result = await content._pop_oauth_state(conn, "state-1", "linkedin")

        assert result["workspace_id"] == workspace_id

    async def test_pop_unknown_state_returns_none(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        result = await content._pop_oauth_state(conn, "nonexistent", "x")

        assert result is None

    async def test_x_state_carries_pkce_code_verifier(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "workspace_id": uuid4(),
                "code_verifier": "pkce-verifier",
                "issued_at": datetime.now(timezone.utc),
            }
        )

        result = await content._pop_oauth_state(conn, "state-1", "x")

        assert result["code_verifier"] == "pkce-verifier"

    async def test_store_scopes_insert_by_platform(self):
        """linkedin and x must be distinguishable rows -- same workspace
        could have both flows in flight at once."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        workspace_id = str(uuid4())

        await content._store_oauth_state(conn, "state-li", workspace_id, "linkedin")
        await content._store_oauth_state(conn, "state-x", workspace_id, "x", "verifier")

        insert_calls = [c for c in conn.execute.await_args_list if "INSERT" in c.args[0]]
        assert len(insert_calls) == 2
        assert insert_calls[0].args[3] == "linkedin"
        assert insert_calls[1].args[3] == "x"
        assert insert_calls[1].args[4] == "verifier"
