"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Per-request CallerIdentity via Python contextvars.

Each asyncio task (i.e., each HTTP request in ASGI) gets its own
ContextVar scope. The auth middleware sets the caller once per request;
tool functions and the audit logger read it from the same context.

No thread-local hacks, no global mutation.
"""

from contextvars import ContextVar

from auth.models import CallerIdentity

_caller_var: ContextVar[CallerIdentity | None] = ContextVar(
    "mcp_caller_identity", default=None
)


def set_caller(identity: CallerIdentity) -> None:
    _caller_var.set(identity)


def get_caller() -> CallerIdentity:
    identity = _caller_var.get()
    if identity is None:
        raise RuntimeError(
            "No CallerIdentity in context — MCPAuthMiddleware did not run or was bypassed"
        )
    return identity


def get_caller_or_none() -> CallerIdentity | None:
    return _caller_var.get()
