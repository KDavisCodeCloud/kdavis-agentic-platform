"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Execution policy — Settings → Policies (migration 048).

Pre-build audit finding (see the Step 0 report delivered with this
build): no code path in any of the 11 agents' workflow.py files executes
a repo write or cloud API call without the incident first passing
through api/routes/incidents.py's POST /{incident_id}/approve. Every
agent's LangGraph graph is strictly linear
(ingest -> diagnose -> hitl_gate[interrupt()] -> execute -> complete),
and interrupt()/Command(resume=...) is the only mechanism that ever
supplies _execute_node a selected_option. There is no tiered-autonomy,
confidence-based-skip, or "previously-approved pattern" branch anywhere
in this codebase.

workspaces.auto_execution_enabled (default FALSE on every workspace) is
therefore not closing an existing bypass — there isn't one — it exists
so that guarantee is a structural, DB-backed, auditable setting instead
of only a fact you'd have to re-verify by reading code. This module is
the enforcement point: assert_auto_execution_allowed() raises unless the
flag is explicitly TRUE, and MUST be the first thing any future feature
that wants to execute a remediation without going through the human
POST /incidents/{id}/approve endpoint calls. It has no call site today
because nothing bypasses that endpoint today — see core/hitl.py's
approve_incident()/HITLGate, which remains the sole, unconditional path
to execution regardless of this flag's value.

Do not call this from approve_incident() or any human-approval path —
that path IS the explicit approval this flag is not a substitute for.
"""

import logging

log = logging.getLogger(__name__)


class AutoExecutionDisabledError(Exception):
    """Raised by assert_auto_execution_allowed() when a workspace has not
    explicitly enabled auto_execution_enabled. Any code path that wants
    to execute a remediation without a human POST /incidents/{id}/approve
    call must catch this the same way it would any other authorization
    failure — fail closed, never silently skip the check."""


def assert_auto_execution_allowed(workspace_row: dict) -> None:
    """
    Raises AutoExecutionDisabledError unless workspace_row explicitly has
    auto_execution_enabled = True.

    Default-closed: a missing key, None, or False all raise. There is
    deliberately no "unless severity is low" / "unless previously
    approved" escape hatch here — Kelvin's instruction was explicit that
    none of that ships in this build; this function enforces exactly one
    binary condition.
    """
    if not workspace_row.get("auto_execution_enabled"):
        raise AutoExecutionDisabledError(
            "auto_execution_enabled is False (or unset) for this workspace — "
            "every execution requires an explicit POST /incidents/{id}/approve "
            "call. Enable it in Settings → Policies only if a feature that "
            "legitimately needs to execute without that call has been built "
            "and reviewed."
        )
