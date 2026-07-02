"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
guard() — the single entry point called at the top of every MCP tool.

Runs in this order:
  1. Kill switch — is this tool enabled?
  2. Scope check — does the caller have the required scope?
  3. Tier check  — does the caller's tier permit this tool?
  4. Rate limit  — is the caller within their per-minute budget?

If any check fails: writes an audit entry and raises an exception.
The tool function never runs.

On success: returns (CallerIdentity, start_time_float) so the tool
can write a completion audit entry with accurate latency.

Usage in every tool:

    @mcp.tool(description="...")
    async def my_tool(ctx: Context, some_arg: str) -> dict:
        arg_keys = ["some_arg"]
        caller, t0 = await guard("my_tool", arg_keys)
        try:
            result = await upstream.get("/...", caller.workspace_id)
            await write_audit("my_tool", caller, arg_keys, "ok",
                              int((time.monotonic()-t0)*1000), None)
            return result
        except Exception as exc:
            await write_audit("my_tool", caller, arg_keys, "error",
                              int((time.monotonic()-t0)*1000), type(exc).__name__)
            raise ValueError(str(exc)) from exc
"""

import time

from auth.context import get_caller
from auth.models import CallerIdentity
from config import TOOL_ENABLED, TOOL_REQUIRED_SCOPE, WRITE_TOOL_TIERS
from middleware.audit import write_audit
from middleware.ratelimit import enforce_rate_limit, RateLimitError


async def guard(tool_name: str, arg_keys: list[str]) -> tuple[CallerIdentity, float]:
    """
    Run all pre-execution checks for a tool call.

    Returns (caller, start_monotonic) on success.
    Raises ValueError or PermissionError with a user-readable message on failure.
    Each failure path writes its own audit entry before raising.
    """
    caller = get_caller()
    t0 = time.monotonic()

    # ── 1. Kill switch ────────────────────────────────────────────────────────
    if not TOOL_ENABLED.get(tool_name, True):
        await write_audit(tool_name, caller, arg_keys, "killed", 0, "kill_switch")
        raise ValueError(
            f"Tool '{tool_name}' is temporarily disabled. "
            f"Contact support@theclouddecoded.com if this is unexpected."
        )

    # ── 2. Scope check ────────────────────────────────────────────────────────
    required_scope = TOOL_REQUIRED_SCOPE.get(tool_name, "mcp:read")
    if not caller.has_scope(required_scope):
        await write_audit(tool_name, caller, arg_keys, "rejected", 0, "insufficient_scope")
        raise PermissionError(
            f"Tool '{tool_name}' requires scope '{required_scope}'. "
            f"Your token has: {sorted(caller.scopes)}. "
            f"Generate a new API key with write access in Dashboard → Integrations."
        )

    # ── 3. Tier check (write tools) ───────────────────────────────────────────
    if required_scope == "mcp:write" and caller.workspace_tier not in WRITE_TOOL_TIERS:
        await write_audit(tool_name, caller, arg_keys, "rejected", 0, "tier_not_authorized")
        raise PermissionError(
            f"Tool '{tool_name}' requires Growth or Enterprise tier "
            f"(current tier: {caller.workspace_tier}). "
            f"Upgrade at https://theclouddecoded.com/pricing"
        )

    # ── 4. Rate limit ─────────────────────────────────────────────────────────
    try:
        await enforce_rate_limit(tool_name, caller.workspace_id)
    except RateLimitError as exc:
        await write_audit(tool_name, caller, arg_keys, "rejected", 0, "rate_limited")
        raise ValueError(str(exc)) from exc

    return caller, t0
