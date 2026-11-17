"""
G17 (Break-It Lab run 2): fix-PR branch names carry the incident ID.

Lab Z2 (NSG :3389) and Z4 (public blob) are different resources in the same
resource group; Agent 08 named both branches `drift-correction/<resource_id>`
truncated to 100 chars, so they collided and Z4's commit failed 409.
"""
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.pr_branch import incident_id_from_branch, pr_branch_name

Z2 = "aaaaaaaa-0000-4000-8000-000000000002"
Z4 = "aaaaaaaa-0000-4000-8000-000000000004"
_RG = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-cdlab/providers"


def test_name_and_parse_round_trip():
    branch = pr_branch_name("drift", Z2)
    assert branch == f"cloud-decoded/drift/{Z2}"
    assert incident_id_from_branch(branch) == Z2


def test_uppercase_uuid_is_normalized():
    assert pr_branch_name("drift", Z2.upper()) == f"cloud-decoded/drift/{Z2}"


@pytest.mark.parametrize("bad", [None, "", "inc-002", "not-a-uuid"])
def test_no_branch_without_a_real_incident_id(bad):
    with pytest.raises(ValueError, match="incident ID"):
        pr_branch_name("drift", bad)


def test_bad_kind_rejected():
    with pytest.raises(ValueError):
        pr_branch_name("Drift Fix", Z2)


@pytest.mark.parametrize("branch", [
    "main", "drift-correction/sg-abc123", f"cloud-decoded/drift/{Z2}/extra",
    f"feature/{Z2}", "cloud-decoded/drift/1234", None,
])
def test_other_branches_belong_to_no_incident(branch):
    assert incident_id_from_branch(branch) is None


async def test_lab_z2_z4_same_resource_group_get_different_branches():
    """Through Agent 08's real execute_option: two drift incidents in one resource group."""
    from agents.agent_08_drift_detection.tools import DriftTools

    tools = DriftTools(github_token="gh")
    branches = []
    for incident_id, resource in ((Z2, f"{_RG}/Microsoft.Network/networkSecurityGroups/nsg-cdlab"),
                                  (Z4, f"{_RG}/Microsoft.Storage/storageAccounts/stcdlab")):
        with patch.object(tools, "create_drift_pr", new=AsyncMock(return_value={"status": "pr_created"})) as pr:
            await tools.execute_option({"id": "opt_1"}, {
                "drift_source": "terraform", "resource_id": resource, "owner": "o", "repo": "r",
                "file_path": "azure/main.tf", "corrected_content": "x", "incident_id": incident_id,
            })
        branches.append(pr.await_args.kwargs["branch_name"])
    assert branches == [f"cloud-decoded/drift/{Z2}", f"cloud-decoded/drift/{Z4}"]


async def test_fix_pr_without_incident_id_opens_nothing():
    from agents.agent_08_drift_detection.tools import DriftTools

    tools = DriftTools(github_token="gh")
    with patch.object(tools, "create_drift_pr", new=AsyncMock()) as pr, pytest.raises(ValueError):
        await tools.execute_option({"id": "opt_1"}, {
            "drift_source": "terraform", "resource_id": "sg-1", "owner": "o", "repo": "r", "corrected_content": "x",
        })
    pr.assert_not_awaited()


@pytest.mark.parametrize("pkg,cls,option_id,ctx,kind", [
    ("agent_04_migration", "MigrationTools", "opt_1",
     {"owner": "o", "repo": "r", "file_path": "a.py", "migrated_code": "x"}, "migration"),
    ("agent_05_iam_minimizer", "IAMMinimizeTools", "opt_2",
     {"cloud_provider": "aws", "owner": "o", "repo": "r"}, "iam-minimize"),
    ("agent_11_resource_health", "ResourceHealthTools", "opt_1",
     {"owner": "o", "repo": "r", "resource_id": "vm"}, "resource-health"),
])
async def test_each_agents_pr_branch_carries_the_incident(pkg, cls, option_id, ctx, kind):
    import importlib
    tools = getattr(importlib.import_module(f"agents.{pkg}.tools"), cls)(github_token="gh")
    pr_method = {"agent_04_migration": "create_migration_pr", "agent_05_iam_minimizer": "create_policy_pr",
                 "agent_11_resource_health": "create_alert_pr"}[pkg]
    with patch.object(tools, pr_method, new=AsyncMock(return_value={"status": "pr_created"})) as pr:
        await tools.execute_option({"id": option_id}, {**ctx, "incident_id": Z2})
    assert pr.await_args.kwargs["branch_name"] == f"cloud-decoded/{kind}/{Z2}"


async def test_agent10_execute_node_names_branch_for_incident(mock_db, workspace_id, mock_router):
    from tests.test_agent10 import _make_workflow
    wf = _make_workflow(mock_db, workspace_id, mock_router)
    state = {
        "incident_id": Z2, "selected_option": {"id": "opt_1"}, "repository": "o/r", "ecosystem": "npm",
        "manifest_path": "package.json", "dependency_count": 1, "vulnerability_count": 1,
        "critical_count": 0, "high_count": 1, "vulnerable_packages": [], "patch_summary": "",
        "patched_manifest": "{}", "manifest_sha": "abc",
    }
    with patch.object(wf._tools, "execute_option", new=AsyncMock(return_value={"status": "pr_created"})) as ex:
        await wf._execute_node(state)
    assert ex.await_args.args[1]["branch_name"] == f"cloud-decoded/security-patch/{Z2}"


def test_no_agent_builds_its_own_pr_branch_name():
    """Static guard: every fix branch goes through core/pr_branch.py."""
    root = Path(__file__).resolve().parents[1] / "agents"
    offenders = [
        f"{p.relative_to(root)}:{n}"
        for p in root.glob("agent_*/*.py")
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if re.search(r"branch_name\s*=\s*f[\"']", line)
    ]
    assert offenders == []
