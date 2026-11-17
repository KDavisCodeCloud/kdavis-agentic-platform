"""
G16 + G13: IaC fix PRs change one reviewed block, pass terraform first, and
find their repo through Settings → Repositories when the alert names none.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.hcl_edit import HclEditError
from core.iac_fix import IacProposal, load_iac_file, open_fix_pr, prepare_proposal
from core.repo_mapping import RepoTarget, match_rule, resolve_repo_target, validate_mapping
from core.terraform_gate import GateResult, check_terraform
from tests.test_hcl_edit import FIXED_SG, STACK

TARGET = RepoTarget("acme", "infra", "main", "aws/main.tf", "rule")
VARS_TF = 'variable "region" {\n  default = "us-east-1"\n}\n'


def _repo(file_text=STACK):
    rt = MagicMock()
    rt.read_file = AsyncMock(side_effect=lambda o, r, path, ref: {"aws/main.tf": file_text,
                                                                  "aws/variables.tf": VARS_TF}.get(path))
    rt.list_files = AsyncMock(return_value=["aws/main.tf", "aws/variables.tf", "aws/README.md"])
    rt.create_branch = AsyncMock()
    rt.push_commit = AsyncMock(return_value="sha")
    rt.create_pr = AsyncMock(return_value={"pr_url": "https://github.com/acme/infra/pull/9", "pr_number": 9})
    return rt


def _proposal() -> IacProposal:
    return prepare_proposal(TARGET, STACK, "aws_security_group.web", FIXED_SG)


# ── prepare_proposal ─────────────────────────────────────────────────────────

def test_proposal_carries_the_exact_diff_for_the_card():
    p = _proposal()
    assert p.diff.startswith("--- a/aws/main.tf\n+++ b/aws/main.tf")
    assert "-    from_port   = 22" in p.diff
    assert IacProposal.from_dict(p.to_dict()) == p


def test_identical_block_is_not_a_fix():
    from core.hcl_edit import resource_block_text
    with pytest.raises(HclEditError, match="identical"):
        prepare_proposal(TARGET, STACK, "aws_security_group.web", resource_block_text(STACK, "aws_security_group.web"))


def test_redaction_placeholder_is_never_written_over_real_config():
    with pytest.raises(HclEditError, match="redacted"):
        prepare_proposal(TARGET, STACK, "aws_security_group.web",
                         FIXED_SG.replace('"cdlab-web"', '"[REDACTED:EMAIL]"'))


# ── open_fix_pr ──────────────────────────────────────────────────────────────

async def test_gate_passes_then_pr_contains_only_the_block_change():
    rt = _repo()
    gate = AsyncMock(return_value=GateResult(True, stage="done"))
    with patch("core.iac_fix.check_terraform", new=gate):
        out = await open_fix_pr(rt, _proposal(), "cloud-decoded/drift/x", "t", "body", "msg")
    assert out["status"] == "pr_created" and out["pr_number"] == 9
    files, workdir, edited = gate.await_args.args[0], gate.await_args.args[1], gate.await_args.args[2]
    assert set(files) == {"aws/main.tf", "aws/variables.tf"} and workdir == "aws" and edited == "aws/main.tf"
    committed = rt.push_commit.await_args.args[3]
    assert list(committed) == ["aws/main.tf"] and committed["aws/main.tf"] == files["aws/main.tf"]
    assert "```diff" in rt.create_pr.await_args.args[4]
    assert gate.await_args.kwargs["original"] == STACK


async def test_gate_failure_opens_nothing_and_says_why():
    rt = _repo()
    with patch("core.iac_fix.check_terraform",
               new=AsyncMock(return_value=GateResult(False, "terraform validate: Unsupported argument", "validate"))):
        out = await open_fix_pr(rt, _proposal(), "b", "t", "body", "msg")
    assert out["status"] == "failed" and "no PR was opened" in out["reason"] and "Unsupported argument" in out["reason"]
    rt.create_branch.assert_not_awaited()
    rt.push_commit.assert_not_awaited()


async def test_block_changed_since_review_is_refused():
    edited_upstream = STACK.replace('name        = "cdlab-web"', 'name        = "cdlab-web-v2"')
    rt = _repo(edited_upstream)
    with patch("core.iac_fix.check_terraform", new=AsyncMock()) as gate:
        out = await open_fix_pr(rt, _proposal(), "b", "t", "body", "msg")
    assert out["status"] == "failed" and "changed after this fix was reviewed" in out["reason"]
    gate.assert_not_awaited()
    rt.create_branch.assert_not_awaited()


async def test_unrelated_upstream_change_is_kept():
    """Another resource changed after review: our block still applies, their change stays."""
    upstream = STACK.replace('instance_type = "t3.micro"', 'instance_type = "t3.small"')
    rt = _repo(upstream)
    with patch("core.iac_fix.check_terraform", new=AsyncMock(return_value=GateResult(True))):
        out = await open_fix_pr(rt, _proposal(), "b", "t", "body", "msg")
    assert out["status"] == "pr_created"
    assert 't3.small' in rt.push_commit.await_args.args[3]["aws/main.tf"]


async def test_file_gone_is_refused():
    rt = _repo(None)
    out = await open_fix_pr(rt, _proposal(), "b", "t", "body", "msg")
    assert out["status"] == "failed" and "no longer exists" in out["reason"]


async def test_gate_fails_closed_without_a_runner(monkeypatch):
    monkeypatch.delenv("TERRAFORM_RUNNER_URL", raising=False)
    result = await check_terraform({"a.tf": ""}, ".", "a.tf", "")
    assert not result.ok and result.stage == "unavailable"
    rt = _repo()
    out = await open_fix_pr(rt, _proposal(), "b", "t", "body", "msg")
    assert out["status"] == "failed" and "isn't available" in out["reason"]
    rt.create_branch.assert_not_awaited()


async def test_gate_reports_runner_verdict(monkeypatch):
    monkeypatch.setenv("TERRAFORM_RUNNER_URL", "https://runner.internal")
    monkeypatch.setenv("TERRAFORM_RUNNER_TOKEN", "t")
    resp = MagicMock(status_code=200, json=lambda: {"ok": False, "stage": "fmt", "reason": "doesn't parse"})
    client = AsyncMock(); client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client); client.__aexit__ = AsyncMock(return_value=False)
    with patch("core.terraform_gate.httpx.AsyncClient", return_value=client):
        result = await check_terraform({"a.tf": "{"}, ".", "a.tf", "")
    assert not result.ok and result.stage == "fmt"
    assert client.post.await_args.kwargs["headers"] == {"Authorization": "Bearer t"}


# ── G13: repo mapping ────────────────────────────────────────────────────────

RULES = [
    {"match_prefix": None, "repository": "acme/infra", "base_branch": "main", "iac_path": "main.tf"},
    {"match_prefix": "/subscriptions/S/resourceGroups/rg-cdlab", "repository": "acme/lab",
     "base_branch": "main", "iac_path": "azure/main.tf"},
    {"match_prefix": "/subscriptions/S/resourceGroups/rg-cdlab/providers/Microsoft.Compute",
     "repository": "acme/lab", "base_branch": "main", "iac_path": "azure/vm.tf"},
]


@pytest.mark.parametrize("resource,expected", [
    ("/subscriptions/S/resourceGroups/RG-CDLAB/providers/Microsoft.Compute/virtualMachines/vm", "azure/vm.tf"),
    ("/subscriptions/S/resourceGroups/rg-cdlab/providers/Microsoft.Network/nsg", "azure/main.tf"),
    ("arn:aws:ec2:us-east-1:1:instance/i-1", "main.tf"),
])
def test_longest_prefix_wins_else_default(resource, expected):
    assert match_rule(RULES, resource)["iac_path"] == expected


def test_no_default_and_no_match_is_none():
    assert match_rule(RULES[1:], "arn:aws:ec2:x") is None


async def test_alert_payload_repo_wins_over_mapping():
    db = MagicMock(); db.fetch = AsyncMock(return_value=RULES)
    target = await resolve_repo_target(db, "ws", "anything", {"owner": "o", "repo": "r", "file_path": "x.tf"})
    assert (target.repository, target.source) == ("o/r", "alert")
    db.fetch.assert_not_awaited()


async def test_lab_a1_sns_alert_without_repo_resolves_through_mapping():
    """A1/Z1: the alert carried no repo, so every fix was `skipped`."""
    db = MagicMock(); db.fetch = AsyncMock(return_value=RULES)
    target = await resolve_repo_target(db, "ws", "arn:aws:ec2:us-east-1:1:instance/i-1", {"AlarmName": "cpu"})
    assert (target.repository, target.iac_path, target.source) == ("acme/infra", "main.tf", "default")


async def test_load_iac_file_explains_a_missing_mapping():
    db = MagicMock(); db.fetch = AsyncMock(return_value=[])
    target, text, note = await load_iac_file(db, "ws", _repo, "i-1", {})
    assert target is None and text is None and "Settings → Repositories" in note


async def test_load_iac_file_explains_an_unreadable_file():
    db = MagicMock(); db.fetch = AsyncMock(return_value=RULES)
    def no_creds():
        raise RuntimeError("no GitHub App installation")
    target, text, note = await load_iac_file(db, "ws", no_creds, "i-1", {})
    assert text is None and "no GitHub App installation" in note


@pytest.mark.parametrize("repo,path,branch,prefix", [
    ("acme", "main.tf", "main", None), ("acme/infra", "main.yaml", "main", None),
    ("acme/infra", "/etc/main.tf", "main", None), ("acme/infra", "../x/main.tf", "main", None),
    ("acme/infra", "main.tf", "", None), ("acme/infra", "main.tf", "main", "  "),
])
def test_bad_mappings_are_rejected(repo, path, branch, prefix):
    with pytest.raises(ValueError):
        validate_mapping(repo, path, branch, prefix)


# ── Agent 08 diagnose, end to end ────────────────────────────────────────────

def _llm(address, block):
    return {"parsed_error": "Port 22 open on cdlab-web", "drift_severity": "HIGH", "drift_summary": "ssh opened",
            "drift_items": [{"key": "ingress.22", "desired_value": "absent", "actual_value": "0.0.0.0/0"}],
            "corrected_content": "", "terraform_address": address, "corrected_block": block,
            "options": [{"id": "opt_1", "title": "x", "description": "", "impact": "LOW", "docs_url": ""},
                        {"id": "opt_3", "title": "x", "description": "", "impact": "LOW", "docs_url": ""}]}


LAB_DEFAULT = [{"match_prefix": None, "repository": "acme/infra", "base_branch": "main", "iac_path": "aws/main.tf"}]


async def _diagnose(mock_db, workspace_id, mock_router, llm, rules=LAB_DEFAULT, file_text=STACK):
    from tests.test_agent08 import _base_state, _make_workflow
    wf = _make_workflow(mock_db, workspace_id, mock_router)
    wf.db = MagicMock(); wf.db.fetch = AsyncMock(return_value=rules)
    state = _base_state(workspace_id)
    state.update({"drift_source": "terraform", "resource_type": "aws_security_group", "resource_id": "sg-1",
                  "desired_state_text": "x", "actual_state_text": "y", "repository": "", "file_path": ""})
    with patch.object(wf, "check_budget", new=AsyncMock()), \
         patch.object(wf._tools, "_repo_tools", return_value=_repo(file_text)), \
         patch.object(wf, "call_llm", return_value=(json.dumps(llm), 10)) as call, \
         patch.object(wf, "parse_llm_json", return_value=llm):
        out = await wf._diagnose_node(state)
    return out, call.call_args.kwargs["messages"][0]["content"]


async def test_agent08_diagnose_puts_the_real_file_and_exact_diff_on_the_card(mock_db, workspace_id, mock_router):
    out, prompt = await _diagnose(mock_db, workspace_id, mock_router, _llm("aws_security_group.web", FIXED_SG))
    assert "## IaC file: aws/main.tf (acme/infra@main)" in prompt and "aws_instance.app" in prompt
    assert out["iac_proposal"]["address"] == "aws_security_group.web"
    opt_1 = next(o for o in out["remediation_options"] if o["id"] == "opt_1")
    assert opt_1["diff"] == out["iac_proposal"]["diff"] and "aws_security_group.web" in opt_1["title"]


async def test_agent08_lab_json_answer_gets_no_pr_option(mock_db, workspace_id, mock_router):
    """Lab run 2: the LLM's 'corrected content' was a JSON dump. Now that means no PR, with the reason."""
    out, _ = await _diagnose(mock_db, workspace_id, mock_router,
                             _llm("aws_security_group.web", '{"aws_security_group": {"web": {}}}'))
    assert out["iac_proposal"] is None and "JSON" in out["iac_note"]
    assert [o["id"] for o in out["remediation_options"]] == ["opt_3", "hold"]


async def test_agent08_without_a_mapped_repo_gets_no_pr_option(mock_db, workspace_id, mock_router):
    out, prompt = await _diagnose(mock_db, workspace_id, mock_router, _llm("", ""), rules=[])
    assert "IaC file" not in prompt and "Settings → Repositories" in out["iac_note"]
    assert "opt_1" not in [o["id"] for o in out["remediation_options"]]


# ── Agent 11 (lab A1/Z1), end to end ─────────────────────────────────────────

LAB_APP = '''resource "aws_instance" "app" {
  ami           = "ami-123"
  instance_type = "t3.micro"
}
'''
SCALED_APP = 'resource "aws_instance" "app" {\n  ami           = "ami-123"\n  instance_type = "t3.small"\n}'


async def test_lab_a1_cpu_alert_without_repo_gets_a_reviewable_pr_and_it_opens(mock_db, workspace_id, mock_router):
    """A1: SNS CPU alarm, no owner/repo in the payload -> every fix was `skipped`. Now: the
    workspace mapping finds the repo, the card shows the one-block diff, and approving opens a
    PR on a branch named for the incident with only that block changed."""
    from tests.test_agent11 import _base_state, _make_workflow
    wf = _make_workflow(mock_db, workspace_id, mock_router)
    wf.db = MagicMock(); wf.db.fetch = AsyncMock(return_value=LAB_DEFAULT)
    rt = _repo(LAB_APP)
    llm = {"parsed_error": "CPU at 100% on cdlab-app", "terraform_address": "aws_instance.app",
           "corrected_block": SCALED_APP, "estimated_duration_seconds": 60,
           "options": [{"id": "opt_1", "title": "x", "description": "", "impact": "low", "docs_url": ""}]}
    state = _base_state(workspace_id, {"AlarmName": "cdlab-cpu"})
    state["resource_id"] = "arn:aws:ec2:us-east-1:1:instance/i-1"
    with patch.object(wf, "check_budget", new=AsyncMock()), patch.object(wf._tools, "_repo_tools", return_value=rt), \
         patch.object(wf, "call_llm", return_value=(json.dumps(llm), 10)), \
         patch.object(wf, "parse_llm_json", return_value=llm):
        out = await wf._diagnose_node(state)
    assert out["iac_repository"] == "acme/infra"
    opt_1 = next(o for o in out["remediation_options"] if o["id"] == "opt_1")
    assert '+  instance_type = "t3.small"' in opt_1["diff"]

    state.update(out, incident_id="aaaaaaaa-0000-4000-8000-000000000001", selected_option=opt_1)
    with patch.object(wf._tools, "_repo_tools", return_value=rt), \
         patch("core.iac_fix.check_terraform", new=AsyncMock(return_value=GateResult(True))):
        result = (await wf._execute_node(state))["execution_result"]
    assert result["status"] == "pr_created"
    assert rt.create_branch.await_args.args[2] == "cloud-decoded/resource-health/aaaaaaaa-0000-4000-8000-000000000001"
    assert rt.push_commit.await_args.args[3]["aws/main.tf"] == SCALED_APP + "\n"
