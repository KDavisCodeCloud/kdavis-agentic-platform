"""
Item 3: GitHub App `installation` and `pull_request` closed events.

  - installation created with no claim: recorded as unclaimed, never linked
    (Kelvin: "never auto-link"; lab run 2's install arrived this way).
  - installation deleted: the holding workspace is unlinked.
  - fix PR merged: incident 'proposed' -> 'fix_merged' (awaiting
    verification); only for a Cloud Decoded fix branch naming an incident in
    the installation's own workspace.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch as _patch
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks

from core.github_app_events import handle_fix_pr_closed, handle_installation_event
from core.hitl import manual_resolution_allowed
from core.pr_branch import pr_branch_name

WS = uuid4()
INC = "aaaaaaaa-0000-4000-8000-000000000002"


def _conn(fetchrow=None, fetchval=None, fetch=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetchval = AsyncMock(return_value=fetchval)
    conn.fetch = AsyncMock(return_value=fetch or [])
    conn.execute = AsyncMock(return_value=None)
    return conn


def _sql(conn) -> list[str]:
    return [c.args[0] for c in conn.execute.await_args_list]


def _pr(merged=True, branch=None):
    return {"action": "closed", "pull_request": {
        "merged": merged, "head": {"ref": branch or pr_branch_name("drift", INC)},
        "html_url": "https://github.com/o/r/pull/7", "number": 7, "merge_commit_sha": "abc",
        "merged_at": "2026-11-17T12:00:00Z", "merged_by": {"login": "kelvin"},
    }}


# ── installation ────────────────────────────────────────────────────────────

async def test_unclaimed_install_is_recorded_and_not_linked():
    conn = _conn(fetchval=None)
    out = await handle_installation_event(conn, {
        "action": "created", "installation": {"id": 182810665, "account": {"login": "acme", "type": "Organization"}},
        "sender": {"login": "kelvin"}, "repositories": [{"name": "lab"}],
    })
    assert out["status"] == "accepted" and "not linked" in out["message"]
    (sql,) = _sql(conn)
    assert "INSERT INTO github_app_unclaimed_installations" in sql
    assert not any("UPDATE workspaces" in s for s in _sql(conn))
    assert conn.execute.await_args.args[1:] == ("182810665", "acme", "Organization", "kelvin", 1)


async def test_install_already_linked_is_left_alone():
    conn = _conn(fetchval=WS)
    out = await handle_installation_event(conn, {"action": "created", "installation": {"id": 5}})
    assert out["status"] == "ignored"
    conn.execute.assert_not_awaited()


async def test_uninstall_unlinks_the_workspace_and_audits_it():
    conn = _conn(fetch=[{"id": WS}])
    out = await handle_installation_event(conn, {"action": "deleted", "installation": {"id": 5}})
    assert "unlinked 1" in out["message"]
    assert "github_app_installation_id = $1 RETURNING id" in conn.fetch.await_args.args[0]
    sqls = _sql(conn)
    assert any("DELETE FROM github_app_unclaimed_installations" in s for s in sqls)
    audit = conn.execute.await_args_list[-1].args
    assert "audit_events" in audit[0] and audit[1] == WS and audit[4] == "github_app_uninstalled"


@pytest.mark.parametrize("action", ["suspend", "unsuspend", "new_permissions_accepted"])
async def test_other_installation_actions_change_nothing(action):
    conn = _conn()
    out = await handle_installation_event(conn, {"action": action, "installation": {"id": 5}})
    assert out["status"] == "ignored"
    conn.execute.assert_not_awaited()


# ── pull_request closed ─────────────────────────────────────────────────────

async def test_merged_fix_pr_moves_proposed_to_fix_merged():
    conn = _conn(fetchrow={"id": UUID(INC), "agent_id": "agent_08_drift_detection", "execution_status": "proposed"})
    out = await handle_fix_pr_closed(conn, WS, _pr())
    assert "fix_merged" in out["message"]
    update, audit = conn.execute.await_args_list
    assert update.args[1:] == ("fix_merged", UUID(INC), "proposed")
    assert "AND execution_status = $3" in update.args[0]  # never overwrites a status changed meanwhile
    assert audit.args[4:6] == ("fix_pr_merged", "fix_merged")
    assert json.loads(audit.args[6])["pr_url"] == "https://github.com/o/r/pull/7"
    # incident lookup is scoped to the installation's workspace
    assert conn.fetchrow.await_args_list[0].args[1:] == (UUID(INC), WS)
    # G4: the merge schedules the live re-check (first check after 10 min, 24 h deadline)
    schedule = conn.fetchrow.await_args_list[1].args
    assert "verification_next_at" in schedule[0] and schedule[3] == UUID(INC)
    assert json.loads(audit.args[6])["verification_scheduled"] is True


async def test_merging_does_not_resolve():
    """Merged is not fixed: no resolved_at, and fix_merged isn't a resolution status downstream."""
    from core.ticketing import RESOLVED_STATUSES
    conn = _conn(fetchrow={"id": UUID(INC), "agent_id": "a", "execution_status": "proposed"})
    await handle_fix_pr_closed(conn, WS, _pr())
    assert not any("resolved_at" in s for s in _sql(conn))
    assert "fix_merged" not in RESOLVED_STATUSES
    assert manual_resolution_allowed("fix_merged")  # operator can still close it by hand


async def test_unmerged_close_is_audited_and_incident_unchanged():
    conn = _conn(fetchrow={"id": UUID(INC), "agent_id": "a", "execution_status": "proposed"})
    out = await handle_fix_pr_closed(conn, WS, _pr(merged=False))
    assert "unchanged" in out["message"]
    (audit,) = conn.execute.await_args_list
    assert audit.args[4:6] == ("fix_pr_closed_unmerged", "proposed")


@pytest.mark.parametrize("status", ["resolved_manually", "failed", "fix_merged"])
async def test_merge_never_overrides_a_non_proposed_status(status):
    conn = _conn(fetchrow={"id": UUID(INC), "agent_id": "a", "execution_status": status})
    await handle_fix_pr_closed(conn, WS, _pr())
    assert not any("UPDATE incidents" in s for s in _sql(conn))


@pytest.mark.parametrize("branch", ["main", "drift-correction/sg-1", "feature/x"])
async def test_non_fix_branches_are_ignored(branch):
    conn = _conn()
    out = await handle_fix_pr_closed(conn, WS, _pr(branch=branch))
    assert out["status"] == "ignored"
    conn.fetchrow.assert_not_awaited()


async def test_fix_branch_for_another_workspaces_incident_is_ignored():
    """The branch name is attacker-controllable; the incident must belong to this installation's workspace."""
    conn = _conn(fetchrow=None)
    out = await handle_fix_pr_closed(conn, WS, _pr())
    assert out["status"] == "ignored"
    conn.execute.assert_not_awaited()


# ── through the real webhook route ───────────────────────────────────────────

def _route_request(body: dict, event: str, fetchrow_results: list, secret="s"):
    import hashlib
    import hmac
    from security.encryption import encrypt

    payload = json.dumps(body).encode()
    conn = _conn()
    conn.fetchrow = AsyncMock(side_effect=[{"webhook_secret_encrypted": encrypt(secret)}, *fetchrow_results])
    ctx = AsyncMock(); ctx.__aenter__ = AsyncMock(return_value=conn); ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock(); pool.acquire = MagicMock(return_value=ctx); pool.get_max_size = MagicMock(return_value=10)
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)),
                           body=AsyncMock(return_value=payload),
                           headers={"X-GitHub-Event": event, "X-Hub-Signature-256": sig}), conn


async def test_webhook_routes_installation_event_without_requiring_a_linked_workspace():
    from api.routes import webhooks
    from cryptography.fernet import Fernet
    with _patch.dict("os.environ", {"ENCRYPTION_KEY": Fernet.generate_key().decode()}):
        request, conn = _route_request({"action": "created", "installation": {"id": 9}}, "installation", [])
        out = await webhooks.github_app_webhook(request, BackgroundTasks())
    assert out["status"] == "accepted"
    assert "github_app_unclaimed_installations" in conn.execute.await_args.args[0]


async def test_webhook_routes_merged_pr_and_does_not_start_a_review():
    from api.routes import webhooks
    from cryptography.fernet import Fernet
    workspace = {"id": WS, "stripe_subscription_status": "active", "product_tier": "growth"}
    incident = {"id": UUID(INC), "agent_id": "agent_08_drift_detection", "execution_status": "proposed"}
    body = {**_pr(), "installation": {"id": 9}}
    with _patch.dict("os.environ", {"ENCRYPTION_KEY": Fernet.generate_key().decode()}):
        request, conn = _route_request(body, "pull_request", [workspace, incident, {"id": UUID(INC)}])
        bg = BackgroundTasks()
        out = await webhooks.github_app_webhook(request, bg)
    assert "fix_merged" in out["message"]
    assert bg.tasks == []  # a closed PR never triggers Agent 03
