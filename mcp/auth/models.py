"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
CallerIdentity — the resolved identity attached to every MCP request.

Built by the auth middleware from either an OAuth 2.1 JWT or an API key.
Passed through the request context via contextvars (see auth/context.py).
Written to the audit log on every tool call.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CallerIdentity:
    workspace_id:   str
    workspace_tier: str                      # starter | growth | enterprise
    auth_method:    Literal["oauth", "api_key"]
    scopes:         frozenset[str]           # {"mcp:read"} or {"mcp:read", "mcp:write"}
    subject:        str                      # OAuth: JWT sub / API key: key UUID

    # Optional — populated by auth method
    user_id:        str | None = None        # OAuth: Supabase user UUID / API key: None
    api_key_id:     str | None = None        # API key: DB row UUID / OAuth: None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def can_write(self) -> bool:
        return "mcp:write" in self.scopes

    def audit_dict(self) -> dict:
        """Returns fields safe for the audit log — no credential values."""
        return {
            "workspace_id":   self.workspace_id,
            "workspace_tier": self.workspace_tier,
            "auth_method":    self.auth_method,
            "scopes":         sorted(self.scopes),
            "subject":        self.subject,
            "user_id":        self.user_id,
        }


class AuthError(Exception):
    """Raised by oauth.py and apikey.py on auth failure."""
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code
