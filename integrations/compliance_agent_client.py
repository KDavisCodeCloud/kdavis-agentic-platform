"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Thin HTTP client for the separately-deployed kdavis-compliance-agent
Railway service. Mirrors integrations/finops_agent_client.py's shape
exactly, minus the HITL approve/dismiss calls (compliance reports have
no HITL queue).

Not named "compliance_client" alone -- this repo already has an
unrelated core/compliance.py (WorkspaceComplianceGuard, a billing-tier
gate). The "_agent_" marker throughout this file's callers keeps the
two visually distinct.
"""

import os

import httpx

_TIMEOUT = httpx.Timeout(30.0)


class AgentServiceError(Exception):
    """Raised when kdavis-compliance-agent can't be reached or returns an error.

    status_code carries the upstream HTTP status when there was one (e.g.
    404 "no scans yet"), so callers can pass through a meaningful status
    instead of collapsing every failure to a generic 502.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _base_url() -> str:
    url = os.environ.get("COMPLIANCE_AGENT_API_URL", "")
    if not url:
        raise EnvironmentError("COMPLIANCE_AGENT_API_URL not set")
    return url.rstrip("/")


async def _request(method: str, path: str, tenant_token: str | None = None, **kwargs) -> dict:
    headers = {"X-Tenant-Token": tenant_token} if tenant_token else {}
    try:
        async with httpx.AsyncClient(base_url=_base_url(), timeout=_TIMEOUT) as client:
            resp = await client.request(method, path, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("detail", exc.response.text) if exc.response.content else str(exc)
        raise AgentServiceError(
            f"kdavis-compliance-agent returned {exc.response.status_code}: {detail}",
            status_code=exc.response.status_code,
        ) from exc
    except httpx.RequestError as exc:
        raise AgentServiceError(f"Could not reach kdavis-compliance-agent: {exc}") from exc


async def create_tenant(company_name: str) -> dict:
    return await _request("POST", "/api/v1/tenants", json={"company_name": company_name})


async def verify_aws_role(tenant_id: str, tenant_token: str, role_arn: str) -> dict:
    return await _request(
        "PATCH", f"/api/v1/tenants/{tenant_id}/aws-role", tenant_token, json={"role_arn": role_arn}
    )


async def trigger_scan(tenant_id: str, tenant_token: str) -> dict:
    return await _request("POST", f"/api/v1/tenants/{tenant_id}/scan", tenant_token)


async def get_report(tenant_id: str, tenant_token: str) -> dict:
    return await _request("GET", f"/api/v1/tenants/{tenant_id}/report", tenant_token)
