"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Client for the isolated terraform runner (services/terraform_runner, G16).

terraform fmt + validate must pass before Cloud Decoded opens an IaC fix
PR. The check runs in a separate service with no database and no customer
credentials, because `terraform init` executes provider binaries the
customer's code declares.

Fails closed: if TERRAFORM_RUNNER_URL / TERRAFORM_RUNNER_TOKEN aren't set,
or the runner can't be reached, the gate fails and no PR is opened.
"""

import logging
import os
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 420  # init can download providers on a cold cache


@dataclass
class GateResult:
    ok: bool
    reason: str = ""
    stage: str = ""
    details: dict = field(default_factory=dict)


async def check_terraform(files: dict[str, str], workdir: str, edited_path: str, original: str) -> GateResult:
    url = os.getenv("TERRAFORM_RUNNER_URL", "").rstrip("/")
    token = os.getenv("TERRAFORM_RUNNER_TOKEN", "")
    if not url or not token:
        return GateResult(False, "Terraform validation isn't available on this server "
                                 "(TERRAFORM_RUNNER_URL/TERRAFORM_RUNNER_TOKEN not set)", "unavailable")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{url}/check",
                headers={"Authorization": f"Bearer {token}"},
                json={"files": files, "workdir": workdir, "edited_path": edited_path, "original": original},
            )
    except httpx.HTTPError as exc:
        log.warning("[TerraformGate] runner unreachable: %s", exc)
        return GateResult(False, f"Terraform validation service unreachable: {exc}", "unavailable")

    if resp.status_code != 200:
        return GateResult(False, f"Terraform validation service error {resp.status_code}: {resp.text[:300]}",
                          "unavailable")
    body = resp.json()
    return GateResult(bool(body.get("ok")), body.get("reason", ""), body.get("stage", ""), body)
