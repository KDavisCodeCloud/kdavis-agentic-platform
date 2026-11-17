"""
G13: Settings → Repositories API (api/routes/repo_mappings.py, migration 063).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routes import repo_mappings
from api.routes.repo_mappings import RepoMapping, RepoMappingList

WS = {"id": uuid4()}
DEFAULT = RepoMapping(repository="acme/infra", iac_path="aws/main.tf")
RULE = RepoMapping(match_prefix="/subscriptions/S/resourceGroups/rg-lab", repository="acme/lab",
                   iac_path="azure/main.tf")


def _request(rows=()):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=list(rows))
    conn.execute = AsyncMock()
    scoped = MagicMock()
    scoped.__aenter__ = AsyncMock(return_value=conn)
    scoped.__aexit__ = AsyncMock(return_value=False)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=MagicMock()))), conn, scoped


async def _put(mappings, workspace=WS):
    request, conn, scoped = _request()
    with patch.object(repo_mappings, "workspace_scoped_connection", return_value=scoped), \
         patch.object(repo_mappings, "write_audit_event", new=AsyncMock()) as audit:
        out = await repo_mappings.replace_repo_mappings(RepoMappingList(mappings=mappings), request, workspace)
    return out, conn, audit


async def test_replace_writes_default_and_rules_and_audits():
    out, conn, audit = await _put([DEFAULT, RULE])
    sqls = [c.args[0] for c in conn.execute.await_args_list]
    assert sqls[0].startswith("DELETE FROM workspace_repo_mappings") and len(sqls) == 3
    inserted = [c.args[2:6] for c in conn.execute.await_args_list[1:]]
    assert inserted == [(None, "acme/infra", "main", "aws/main.tf"),
                        ("/subscriptions/S/resourceGroups/rg-lab", "acme/lab", "main", "azure/main.tf")]
    assert len(out.mappings) == 2 and audit.await_args.args[1] == "repo_mappings_updated"


async def test_non_admin_member_cannot_change_mappings():
    with pytest.raises(HTTPException) as exc:
        await _put([DEFAULT], workspace={**WS, "member_role": "approver"})
    assert exc.value.status_code == 403


@pytest.mark.parametrize("bad", [
    [DEFAULT, DEFAULT],                                                   # two defaults
    [RULE, RULE.model_copy(update={"match_prefix": RULE.match_prefix.upper()})],  # same prefix, any case
    [RepoMapping(repository="acme", iac_path="main.tf")],                 # not owner/repo
    [RepoMapping(repository="acme/infra", iac_path="main.yaml")],         # not .tf
    [RepoMapping(repository="acme/infra", iac_path="../main.tf")],        # escapes the repo
])
async def test_invalid_mappings_are_rejected_and_nothing_is_written(bad):
    request, conn, scoped = _request()
    with patch.object(repo_mappings, "workspace_scoped_connection", return_value=scoped):
        with pytest.raises(HTTPException) as exc:
            await repo_mappings.replace_repo_mappings(RepoMappingList(mappings=bad), request, WS)
    assert exc.value.status_code == 400
    conn.execute.assert_not_awaited()


async def test_list_returns_rows_default_first():
    request, conn, scoped = _request([{"match_prefix": None, "repository": "acme/infra",
                                       "base_branch": "main", "iac_path": "aws/main.tf"}])
    with patch.object(repo_mappings, "workspace_scoped_connection", return_value=scoped):
        out = await repo_mappings.list_repo_mappings(request, WS)
    assert out.mappings[0].repository == "acme/infra"
    assert "NULLS FIRST" in conn.fetch.await_args.args[0]


def test_routes_are_mounted_on_the_app():
    """api/routes/policies.py is imported in main.py but never mounted; make sure this one is."""
    from api.main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v1/workspace/repo-mappings" in paths
