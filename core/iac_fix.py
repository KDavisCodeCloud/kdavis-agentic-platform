"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

IaC fix PRs that change one resource block and pass terraform first (G16).
Shared by Agent 08 (drift) and Agent 11 (resource health).

Before approval (diagnose):
  prepare_proposal() reads the real .tf file from the repo, splices the
  LLM's corrected block in for one resource address (core/hcl_edit.py), and
  returns the exact diff that goes on the approval card.

After approval (execute):
  open_fix_pr() re-reads the file and refuses if that block changed since
  the diff was approved. Then it re-splices, runs terraform fmt + validate
  in the isolated runner (core/terraform_gate.py), and only then branches,
  commits and opens the PR. Every refusal is a `failed` result with the
  reason, so the incident says why no PR exists.
"""

import logging
import posixpath
import re
from dataclasses import asdict, dataclass
from typing import Optional

from core.hcl_edit import (
    HclEditError, replace_resource_block, resource_addresses, resource_block_text, unified_diff,
)
from core.option_catalog import OptionSpec
from core.repo_mapping import RepoTarget, resolve_repo_target
from core.security import shield
from core.terraform_gate import check_terraform

log = logging.getLogger(__name__)

_MODULE_EXTRAS = (".terraform.lock.hcl",)
# DataSanitizationShield placeholders (core/security.py). The LLM only ever
# sees the sanitized file, so a redacted value it echoes back must never be
# committed in place of the real one.
_REDACTION = re.compile(r"\[REDACTED[:_]")


@dataclass
class IacProposal:
    owner: str
    repo: str
    base_branch: str
    file_path: str
    address: str
    original_block: str
    corrected_block: str
    diff: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["IacProposal"]:
        if not data:
            return None
        return cls(**{k: data[k] for k in cls.__dataclass_fields__})


async def load_iac_file(db, workspace_id, make_repo_tools, resource_id: str,
                        payload: dict) -> tuple[Optional[RepoTarget], Optional[str], Optional[str]]:
    """(target, file text, reason-if-unavailable). Never raises: no IaC file
    just means no PR option, and the reason says why on the card."""
    target = await resolve_repo_target(db, workspace_id, resource_id, payload)
    if target is None:
        return None, None, ("no repository is mapped for this resource -- add one in "
                            "Settings → Repositories to get a PR option")
    try:
        text = await read_iac_file(make_repo_tools(), target)
    except Exception as exc:  # no credential, 404, a directory, not .tf -- all mean "no PR option"
        log.warning("[IacFix] IaC file unavailable for %s (%s): %s", resource_id, target.repository, exc)
        return target, None, f"couldn't read {target.iac_path or 'the IaC file'} from {target.repository}: {exc}"
    return target, text, None


def iac_prompt_block(target: RepoTarget, file_text: str, agent_id: str) -> str:
    """The real .tf file for the LLM -- sanitized first, like every input -- and
    the one-block contract it must answer in."""
    try:
        addresses = ", ".join(resource_addresses(file_text)) or "(none found)"
    except HclEditError:
        addresses = "(file could not be scanned)"
    sanitized = shield.sanitize(file_text, context=agent_id).sanitized_text
    return (
        f"## IaC file: {target.iac_path} ({target.repository}@{target.base_branch})\n\n"
        f"```hcl\n{sanitized}\n```\n\n"
        f"Resources defined in this file: {addresses}\n\n"
        "Return \"terraform_address\": the address (type.name) of the ONE resource above that defines "
        "the affected resource, and \"corrected_block\": that resource's complete corrected block in "
        "HCL -- same type and name, every other attribute kept exactly as written, only what must change "
        "for the fix changed. Never JSON, never more than that one block, never other blocks or files. "
        "If no resource above is the affected one, set both to \"\"."
    )


def iac_pr_option(context: dict, call: str) -> list[OptionSpec]:
    """The PR option (opt_1) for agents 08 and 11 -- present only when diagnose
    has, or is about to compute, a one-block change to a real .tf file."""
    proposal = context.get("iac_proposal") or {}
    if not (proposal or context.get("iac_file_available")):
        return []
    where = (f"{proposal['address']} in {proposal['file_path']}" if proposal
             else "the resource's block in its .tf file")
    return [OptionSpec(
        "opt_1", f"Open a PR changing {where}",
        "Changes only that resource block -- the diff below is exactly what the PR contains. Before "
        "opening it, Cloud Decoded re-checks the block hasn't changed and runs terraform fmt and "
        "terraform validate on the branch; if either fails, no PR is opened. Nothing changes in the "
        "cloud until you merge and your pipeline applies it.",
        "low", (call,), proposal=True,
    )]


def attach_diff(options: list[dict], proposal: Optional[dict]) -> list[dict]:
    """Puts the exact PR diff on the PR option so the approver reviews what will be committed."""
    if proposal:
        for opt in options:
            if opt.get("id") == "opt_1":
                opt["diff"] = proposal["diff"]
    return options


async def read_iac_file(repo_tools, target: RepoTarget) -> str:
    if not target.iac_path.endswith(".tf"):
        raise HclEditError(f"{target.iac_path or '(no path)'} is not a .tf file")
    text = await repo_tools.read_file(target.owner, target.repo, target.iac_path, target.base_branch)
    if text is None:
        raise HclEditError(f"{target.iac_path} not found in {target.repository}@{target.base_branch}")
    return text


def prepare_proposal(target: RepoTarget, file_text: str, address: str, corrected_block: str) -> IacProposal:
    """Raises HclEditError (operator-facing reason) when the edit isn't safe.
    `file_text` is the real file from the repo, not the sanitized copy the LLM saw."""
    if _REDACTION.search(corrected_block or ""):
        raise HclEditError(f"the proposed block for {address} contains a redacted value; Cloud Decoded "
                           "never writes a redaction placeholder over your real configuration")
    after = replace_resource_block(file_text, address, corrected_block)
    if after == file_text:
        raise HclEditError(f"the proposed block for {address} is identical to the current one")
    return IacProposal(
        owner=target.owner, repo=target.repo, base_branch=target.base_branch, file_path=target.iac_path,
        address=address, original_block=resource_block_text(file_text, address),
        corrected_block=corrected_block, diff=unified_diff(target.iac_path, file_text, after),
    )


async def open_fix_pr(repo_tools, proposal: Optional[IacProposal], branch_name: str,
                      pr_title: str, pr_body: str, commit_message: str) -> dict:
    if proposal is None:
        return _failed("no reviewed IaC change for this incident -- nothing to open a PR with")

    current = await repo_tools.read_file(proposal.owner, proposal.repo, proposal.file_path, proposal.base_branch)
    if current is None:
        return _failed(f"{proposal.file_path} no longer exists on {proposal.base_branch}")
    if resource_block_text(current, proposal.address) != proposal.original_block:
        return _failed(f"{proposal.address} in {proposal.file_path} changed after this fix was reviewed; "
                       "re-run the analysis so the diff you approve matches the file")
    try:
        new_text = replace_resource_block(current, proposal.address, proposal.corrected_block)
    except HclEditError as exc:
        return _failed(f"could not apply the reviewed change: {exc}")

    workdir = posixpath.dirname(proposal.file_path) or "."
    files = await _module_files(repo_tools, proposal, workdir)
    files[proposal.file_path] = new_text
    gate = await check_terraform(files, workdir, proposal.file_path, original=current)
    if not gate.ok:
        return {**_failed(f"Terraform check failed, so no PR was opened -- {gate.reason}"),
                "gate": {"stage": gate.stage, "reason": gate.reason}}

    await repo_tools.create_branch(proposal.owner, proposal.repo, branch_name, proposal.base_branch)
    await repo_tools.push_commit(proposal.owner, proposal.repo, branch_name, {proposal.file_path: new_text},
                                 commit_message)
    pr = await repo_tools.create_pr(proposal.owner, proposal.repo, branch_name, pr_title,
                                    f"{pr_body}\n\n```diff\n{proposal.diff}```\n\n"
                                    "terraform fmt and terraform validate passed on this branch before it was opened.",
                                    base=proposal.base_branch)
    return {"status": "pr_created", "pr_url": pr.get("pr_url", ""), "pr_number": pr.get("pr_number"),
            "branch": branch_name, "file_path": proposal.file_path, "address": proposal.address,
            "gate": {"stage": gate.stage, "ok": True}}


async def _module_files(repo_tools, proposal: IacProposal, workdir: str) -> dict[str, str]:
    """Every .tf file in the edited file's directory (one Terraform module), so
    validate sees the variables, providers and resources it references."""
    files: dict[str, str] = {}
    listing = await repo_tools.list_files(proposal.owner, proposal.repo, "" if workdir == "." else workdir,
                                          proposal.base_branch)
    for path in listing:
        if path.endswith(".tf") or path.endswith(_MODULE_EXTRAS):
            content = await repo_tools.read_file(proposal.owner, proposal.repo, path, proposal.base_branch)
            if content is not None:
                files[path] = content
    return files


def _failed(reason: str) -> dict:
    return {"status": "failed", "reason": reason}
