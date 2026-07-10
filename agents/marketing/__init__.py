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
Wave 2 marketing agents (MKT-LI1, MKT-CN1, MKT-V1, MKT-N1). Plain
functions with injected collaborators (supabase_client, anthropic_client)
— no agents/base_agent.py dependency, same convention as agents/internal/*
(that base class is scoped to the 10 commercial DevOps agents: LLM router
loading, per-tenant DB, subscription compliance don't apply here).

Every agent: sanitizes external text before it reaches an LLM (DataSanitization
Shield), writes an audit_log entry, best-effort emits POST /events, and writes
its output to a HITL-gated queue table with status='pending_review'/'draft' —
nothing here ever auto-publishes. See agents/marketing/_shared.py.
"""
