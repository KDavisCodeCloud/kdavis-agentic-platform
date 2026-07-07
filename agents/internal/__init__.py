"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
Internal business OS agents (dashboard-facing, not customer-facing
products). These do not extend agents/base_agent.py — that base class is
built for the 10 commercial DevOps agents (LLM router, per-tenant DB
connection, subscription compliance). Internal finance agents are pure
orchestration over finance/* — no LLM calls, no DB connection of their
own. Wiring these into the live dashboard/HITL queue/Supabase happens in
a later integration session.
"""
