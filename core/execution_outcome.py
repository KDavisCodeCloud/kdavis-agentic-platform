"""
What an approved option's execution result means for the incident's status.

Why this exists (Break-It Lab G1, 2026-11-17): every agent's complete node
marked the incident 'executed' for any result that wasn't 'held'. A1 and Z1
returned `skipped` (nothing ran), and the incident said executed with no
failure_reason. A2 and Z2 opened a PR and nothing changed live, and the
incident also said executed.

Now one function decides, for all 11 agents:

  held                         -> 'held'
  nothing ran, or it errored   -> 'failed', failure_kind 'not_executed'
  part of it ran, part didn't  -> 'failed', failure_kind 'partial_execution'
  ran, and the option only
  proposes a fix (PR / issue /
  alert; OptionSpec.proposal)  -> 'proposed'  (nothing live changed yet)
  ran, and it is the change    -> 'executed'

'executed' means the approved action ran. It does not mean the live resource
was re-checked; that is G4 (post-fix verification), a separate fix.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

STATUS_EXECUTED = "executed"
STATUS_PROPOSED = "proposed"
STATUS_FAILED = "failed"
STATUS_HELD = "held"

FAILURE_NOT_EXECUTED = "not_executed"
FAILURE_PARTIAL = "partial_execution"

# Result statuses that mean the action did not happen.
NOT_RUN = frozenset({
    "skipped", "not_implemented", "not_available", "failed", "error", "no_change", "unknown",
})


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    reason: Optional[str] = None
    failure_kind: Optional[str] = None


def _why(result: Mapping[str, Any]) -> str:
    for key in ("reason", "error", "message", "detail"):
        val = result.get(key)
        if val:
            return str(val)
    return ""


def _parts(result: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """Sub-results of a multi-call option: dict values carrying their own status,
    directly or under a `results` dict (Agent 06 quick wins, Agent 10 opt_3)."""
    found: list[tuple[str, Mapping[str, Any]]] = []
    pools = [result]
    if isinstance(result.get("results"), Mapping):
        pools.append(result["results"])
    for pool in pools:
        for key, val in pool.items():
            if isinstance(val, Mapping) and "status" in val:
                found.append((str(key), val))
    return found


def classify_execution(result: Optional[Mapping[str, Any]],
                       selected_option: Optional[Mapping[str, Any]] = None) -> ExecutionOutcome:
    result = result or {}
    status = str(result.get("status") or "").lower()
    option_id = str((selected_option or {}).get("id", "")) or "the approved option"

    if status == "held":
        return ExecutionOutcome(STATUS_HELD)

    if not status and result.get("error"):
        status = "error"
    if not status:
        status = "unknown"

    if status in NOT_RUN:
        why = _why(result) or f"result status was '{status}'"
        return ExecutionOutcome(
            STATUS_FAILED,
            f"Not executed: {option_id} did nothing ({why}).",
            FAILURE_NOT_EXECUTED,
        )

    parts = _parts(result)
    bad = [(k, p) for k, p in parts if str(p.get("status", "")).lower() in NOT_RUN | {"partial"}]
    if status == "partial" or bad:
        detail = "; ".join(f"{k}: {p.get('status')}{' — ' + _why(p) if _why(p) else ''}" for k, p in bad)
        if parts and len(bad) == len(parts):
            return ExecutionOutcome(
                STATUS_FAILED, f"Not executed: every part of {option_id} failed ({detail}).", FAILURE_NOT_EXECUTED,
            )
        return ExecutionOutcome(
            STATUS_FAILED,
            f"Partly executed: some of {option_id} did not run ({detail or _why(result) or 'see audit log'}).",
            FAILURE_PARTIAL,
        )

    if (selected_option or {}).get("proposal"):
        return ExecutionOutcome(STATUS_PROPOSED)
    return ExecutionOutcome(STATUS_EXECUTED)
