"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Single FastMCP instance — imported by tools/read.py and tools/write.py
to register their @mcp.tool() decorators.

Kept in its own module to avoid circular imports between server.py
and the tools modules.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="cloud-decoded",
    instructions=(
        "Cloud Decoded DevOps automation platform. "
        "Exposes HITL incident management and agent orchestration via MCP. "
        "Read-only tools are available to all tiers. "
        "Write tools (approve/reject/triage) require mcp:write scope and "
        "Growth or Enterprise tier."
    ),
)
