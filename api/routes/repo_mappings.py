"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Settings → Repositories: where this workspace's IaC lives (G13, migration 063).

GET /workspace/repo-mappings  -- the default + per-prefix rules
PUT /workspace/repo-mappings  -- replace them all (admin only, audited)

Agents 08 and 11 resolve a resource's repo through core/repo_mapping.py; an
alert that names its own owner/repo still wins.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.middleware.auth import get_workspace_or_member
from api.routes.policies import _caller_is_policy_admin
from core.audit import write_audit_event
from core.repo_mapping import validate_mapping
from core.workspace_scope import workspace_scoped_connection

log = logging.getLogger(__name__)
router = APIRouter(tags=["repo-mappings"])

_MAX_RULES = 50


class RepoMapping(BaseModel):
    match_prefix: Optional[str] = Field(None, description="Resource-ID prefix; omit for the workspace default")
    repository: str = Field(..., description="owner/repo")
    base_branch: str = "main"
    iac_path: str = Field(..., description="Repo-relative .tf file")


class RepoMappingList(BaseModel):
    mappings: list[RepoMapping]


@router.get("/workspace/repo-mappings", response_model=RepoMappingList)
async def list_repo_mappings(request: Request, workspace: dict = Depends(get_workspace_or_member)) -> RepoMappingList:
    async with workspace_scoped_connection(request.app.state.db_pool, str(workspace["id"])) as conn:
        rows = await conn.fetch(
            "SELECT match_prefix, repository, base_branch, iac_path FROM workspace_repo_mappings "
            "WHERE workspace_id = $1 ORDER BY match_prefix NULLS FIRST",
            workspace["id"],
        )
    return RepoMappingList(mappings=[RepoMapping(**dict(r)) for r in rows])


@router.put("/workspace/repo-mappings", response_model=RepoMappingList)
async def replace_repo_mappings(
    body: RepoMappingList, request: Request, workspace: dict = Depends(get_workspace_or_member),
) -> RepoMappingList:
    if not _caller_is_policy_admin(workspace):
        raise HTTPException(status_code=403, detail="Only a workspace admin can change repository mappings")
    if len(body.mappings) > _MAX_RULES:
        raise HTTPException(status_code=400, detail=f"At most {_MAX_RULES} mappings")

    cleaned: list[RepoMapping] = []
    seen: set[Optional[str]] = set()
    for m in body.mappings:
        prefix = m.match_prefix.strip() if m.match_prefix is not None else None
        try:
            validate_mapping(m.repository.strip(), m.iac_path.strip(), m.base_branch.strip(), prefix)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        key = prefix.lower() if prefix else None
        if key in seen:
            raise HTTPException(status_code=400, detail="Only one default, and each prefix only once"
                                if key is None else f"Prefix listed twice: {prefix}")
        seen.add(key)
        cleaned.append(RepoMapping(match_prefix=prefix, repository=m.repository.strip(),
                                   base_branch=m.base_branch.strip(), iac_path=m.iac_path.strip()))

    async with workspace_scoped_connection(request.app.state.db_pool, str(workspace["id"])) as conn:
        await conn.execute("DELETE FROM workspace_repo_mappings WHERE workspace_id = $1", workspace["id"])
        for m in cleaned:
            await conn.execute(
                "INSERT INTO workspace_repo_mappings "
                "(workspace_id, match_prefix, repository, base_branch, iac_path, created_by) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                workspace["id"], m.match_prefix, m.repository, m.base_branch, m.iac_path,
                workspace.get("member_id"),
            )

    await write_audit_event(str(workspace["id"]), "repo_mappings_updated", "ok",
                            metadata={"count": len(cleaned)})
    log.info("[RepoMappings] workspace=%s now has %d mapping(s)", workspace["id"], len(cleaned))
    return RepoMappingList(mappings=cleaned)
