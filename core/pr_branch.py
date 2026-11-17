"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Branch names for the PRs Cloud Decoded opens (G17, Break-It Lab run 2).

Every fix PR's branch is `cloud-decoded/<kind>/<incident-uuid>`:
  - Unique per incident. Agent 08 used `drift-correction/<resource_id>`
    truncated to 100 chars; two Azure resources in the same resource group
    share that prefix, so lab Z4's commit hit Z2's branch and failed 409.
  - Parseable back to the incident. The GitHub App `pull_request` webhook
    reads the merged PR's head branch to find which incident it fixes.
"""

import re
from typing import Optional
from uuid import UUID

_PREFIX = "cloud-decoded"
_KIND = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_BRANCH = re.compile(
    r"^cloud-decoded/[a-z0-9-]+/"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def pr_branch_name(kind: str, incident_id: Optional[str]) -> str:
    """Raises ValueError without a real incident ID: a fix PR always belongs
    to an approved incident, and a random suffix would make the merge
    webhook unable to find it."""
    if not _KIND.match(kind or ""):
        raise ValueError(f"PR branch kind must be lowercase words joined by '-', got {kind!r}")
    try:
        normalized = str(UUID(str(incident_id)))
    except (ValueError, TypeError):
        raise ValueError(f"Cannot name a fix PR branch without the incident ID (got {incident_id!r})") from None
    return f"{_PREFIX}/{kind}/{normalized}"


def incident_id_from_branch(branch: Optional[str]) -> Optional[str]:
    """The incident a Cloud Decoded fix branch belongs to; None for any other branch."""
    match = _BRANCH.match(branch or "")
    return match.group(1) if match else None
