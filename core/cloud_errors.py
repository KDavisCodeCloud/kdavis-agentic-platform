"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Graceful 403 handling (Settings → Policies build, Step 4).

Pre-build audit finding: agents 05/06/08's write methods (tools.py) raise
generic RuntimeError/ClientError on any non-2xx response — there was no
distinction anywhere between "the write failed because the workspace's
AWS role / Azure Service Principal lacks the permission" and any other
failure. Worse, api/routes/incidents.py's `_resume()` (the fire-and-forget
asyncio.create_task that actually runs an approved remediation) had NO
try/except at all — any exception raised inside _execute_node, permission
error or otherwise, was silently dropped by asyncio and the incident was
left stuck at execution_status='executing' forever, with the HITL card's
execution-log animation spinning indefinitely. Neither gap is specific to
read-only mode; both were found while tracing the execution path for
this build and are fixed by this module + its call site in incidents.py.

CloudPermissionError is raised by the write methods this module's helpers
are wired into (agents 05/06/08's tools.py) when the underlying provider
response is unambiguously an authorization failure — AWS AccessDenied-
class ClientErrors, Azure ARM 403/AuthorizationFailed responses. Every
other failure (network error, malformed request, a provider 5xx) is left
to raise its existing RuntimeError/ClientError unchanged; incidents.py's
_resume() catches both, but only CloudPermissionError gets the specific
"missing action" message and failure_kind='permission_denied'.
"""

import logging
import re
from typing import Optional

from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

# AWS error codes that unambiguously mean "the credential authenticated
# fine, but lacks this permission" -- as opposed to e.g. ValidationError,
# ThrottlingException, ResourceNotFoundException, which are not
# permission problems and must not be relabeled as one.
_AWS_PERMISSION_DENIED_CODES = frozenset({
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "AuthorizationError",
    "Forbidden",
})

_AZURE_AUTHORIZATION_FAILED_RE = re.compile(r'"code"\s*:\s*"AuthorizationFailed"')


class CloudPermissionError(Exception):
    """
    Raised in place of a generic RuntimeError/ClientError when a cloud
    write unambiguously failed due to insufficient permissions on the
    workspace's connected credential.

    provider: 'aws' | 'azure'
    action: the specific permission/action that was missing, in the
        provider's own naming (e.g. 'iam:CreatePolicyVersion',
        'Microsoft.Authorization/roleAssignments/write') -- always a
        real action name from docs/customer/permissions-guide.md's
        manifest, never a generic placeholder, so the operator can go
        grant exactly that.
    detail: the provider's own error message, truncated, for support/debug.
    """

    def __init__(self, provider: str, action: str, detail: str):
        self.provider = provider
        self.action = action
        self.detail = detail
        super().__init__(f"{provider} permission denied for '{action}': {detail}")

    def operator_message(self) -> str:
        return (
            f"Insufficient permissions — the connected {self.provider.upper()} "
            f"credential is missing '{self.action}'. See the permissions guide "
            f"(Settings → Connections, or docs/customer/permissions-guide.md) "
            f"to grant it, then retry."
        )


def classify_aws_client_error(exc: ClientError, action: str) -> Optional[CloudPermissionError]:
    """
    Returns a CloudPermissionError if exc is an AWS permission-denied
    response for `action`, else None (caller re-raises exc unchanged).
    """
    code = exc.response.get("Error", {}).get("Code", "")
    if code not in _AWS_PERMISSION_DENIED_CODES:
        return None
    message = exc.response.get("Error", {}).get("Message", str(exc))
    return CloudPermissionError("aws", action, message[:300])


def raise_if_azure_permission_error(status_code: int, response_text: str, action: str) -> None:
    """
    Call with an Azure ARM response's status_code and body text. Raises
    CloudPermissionError if it's unambiguously an authorization failure
    (403, or a 200-range-adjacent error body naming AuthorizationFailed);
    otherwise returns normally so the caller's existing status-code check
    proceeds unchanged.
    """
    if status_code == 403 or _AZURE_AUTHORIZATION_FAILED_RE.search(response_text or ""):
        raise CloudPermissionError("azure", action, (response_text or "")[:300])
