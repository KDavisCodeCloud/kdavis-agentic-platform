"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Post-fix verification (G4, item 4).

Break-It Lab: A3 said "executed" while the IAM policy was still `*:*`;
A1/Z1 while CPU stayed pegged; A2/Z2 never learned whether anything
changed. "The action ran" is not "the problem is gone".

How it works:
  1. When an agent acts (status `executed`) or proposes a fix (`proposed`),
     it records a verification spec on the incident: which live reader to
     call and what "fixed" looks like. Deterministic, no LLM.
  2. A live action is scheduled at once (first check after LIVE_DELAY,
     deadline LIVE_WINDOW). A proposal is scheduled only when its PR merges
     (`fix_merged`; first check after MERGED_DELAY, deadline MERGED_WINDOW),
     because nothing changes until the customer's pipeline applies it.
  3. run_verification_pass() -- the API's background loop -- claims due
     incidents (FOR UPDATE SKIP LOCKED: every uvicorn worker runs the loop)
     and re-reads live state:
       fixed      -> 'verified' (verified_at; resolved_at if not set)
       not fixed  -> retry until the deadline, then 'verification_failed'
       can't tell -> retry until the deadline, then stop with
                     outcome 'unverifiable'; the status is left alone.
                     Can't-check is never reported as fixed or as failed.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from core.live_state import (
    AWS_STOPPED, AZURE_DEALLOCATED, LiveStateError, aws_alarm_state, aws_instance_states,
    aws_policy_default_document, azure_alert_condition, azure_vm_power_states, normalize_policy,
)

log = logging.getLogger(__name__)

STATUS_VERIFIED = "verified"
STATUS_VERIFICATION_FAILED = "verification_failed"
_VERIFIABLE_STATUSES = ("executed", "fix_merged")

LIVE_DELAY, LIVE_WINDOW, LIVE_RETRY = timedelta(minutes=2), timedelta(minutes=30), timedelta(minutes=5)
MERGED_DELAY, MERGED_WINDOW, MERGED_RETRY = timedelta(minutes=10), timedelta(hours=24), timedelta(minutes=15)
_CLAIM_LEASE = timedelta(minutes=10)
_BATCH = 20

FIXED, NOT_FIXED, UNKNOWN = "fixed", "not_fixed", "unknown"


@dataclass
class Outcome:
    result: str   # FIXED | NOT_FIXED | UNKNOWN
    detail: str


# ── recording and scheduling ─────────────────────────────────────────────────

async def record_spec(db, incident_id: str, spec: dict, schedule_now: bool) -> None:
    """Store what to re-check. A live action is scheduled immediately; a
    proposal waits for its PR to merge (schedule_after_merge)."""
    if schedule_now:
        await db.execute(
            "UPDATE incidents SET verification_spec = $1, verification_next_at = NOW() + $2, "
            "verification_deadline = NOW() + $3, verification_attempts = 0 WHERE id = $4",
            json.dumps(spec), LIVE_DELAY, LIVE_WINDOW, _uuid(incident_id),
        )
    else:
        await db.execute("UPDATE incidents SET verification_spec = $1 WHERE id = $2",
                         json.dumps(spec), _uuid(incident_id))


async def schedule_after_merge(conn, incident_id) -> bool:
    """Called when a fix PR merges. False if the incident has no live check."""
    row = await conn.fetchrow(
        "UPDATE incidents SET verification_next_at = NOW() + $1, verification_deadline = NOW() + $2, "
        "verification_attempts = 0 WHERE id = $3 AND verification_spec IS NOT NULL RETURNING id",
        MERGED_DELAY, MERGED_WINDOW, _uuid(incident_id),
    )
    return row is not None


# ── checks: one per kind of fix, each a deterministic live read ──────────────

async def _check_aws_policy(spec: dict, creds: dict) -> Outcome:
    live = await aws_policy_default_document(creds.get("aws_session"), spec["policy_arn"])
    if normalize_policy(live) == normalize_policy(spec["expected"]):
        return Outcome(FIXED, f"{spec['policy_arn']} default version now matches the minimized policy")
    return Outcome(NOT_FIXED, f"{spec['policy_arn']} default version still differs from the minimized policy")


async def _check_azure_assignments_removed(spec: dict, creds: dict) -> Outcome:
    from agents.agent_05_iam_minimizer.tools import IAMMinimizeTools
    tools = IAMMinimizeTools(azure_access_token=creds.get("azure_access_token"))
    if not tools.azure_access_token:
        raise LiveStateError("Azure service principal not connected for this workspace")
    try:
        assignments = await tools.get_azure_role_assignments(spec["subscription_id"], spec["principal_id"])
    except Exception as exc:
        raise LiveStateError(f"Could not read role assignments: {exc}") from exc
    present = {a.get("id") for a in assignments}
    still = [i for i in spec["removed_ids"] if i in present]
    if still:
        return Outcome(NOT_FIXED, f"{len(still)} over-privileged assignment(s) still present: {', '.join(still)}")
    return Outcome(FIXED, f"all {len(spec['removed_ids'])} over-privileged assignment(s) are gone")


async def _check_compute_stopped(spec: dict, creds: dict) -> Outcome:
    if spec["cloud"] == "aws":
        states = await aws_instance_states(creds.get("aws_session"), spec["instance_ids"])
        running = [i for i, s in states.items() if s not in AWS_STOPPED and s != "not-found"]
        noun = "instance(s) still running"
    else:
        states = await azure_vm_power_states(creds.get("azure_access_token"), spec["subscription_id"],
                                             spec["resource_group"], spec["vm_names"])
        running = [n for n, s in states.items() if s not in AZURE_DEALLOCATED and s != "not-found"]
        noun = "VM(s) not deallocated"
    if running:
        return Outcome(NOT_FIXED, f"{len(running)} {noun}: {', '.join(running)}")
    return Outcome(FIXED, f"all {len(states)} resource(s) stopped: " + ", ".join(f"{k}={v}" for k, v in states.items()))


async def _check_drift_findings(spec: dict, creds: dict) -> Outcome:
    from agents.agent_08_drift_detection.tools import DriftTools
    tools = DriftTools(aws_session=creds.get("aws_session"), azure_access_token=creds.get("azure_access_token"))
    live = await tools.fetch_live(spec["live_fetch"])
    if live is None or "error" in live:
        raise LiveStateError((live or {}).get("error", "no live reader for this resource"))
    remaining = sorted(set(spec["baseline_findings"]) & set(live.get("findings", [])))
    if remaining:
        return Outcome(NOT_FIXED, "still present: " + "; ".join(remaining))
    return Outcome(FIXED, f"none of the {len(spec['baseline_findings'])} finding(s) remain on the live resource")


async def _check_alarm(spec: dict, creds: dict) -> Outcome:
    if spec["cloud"] == "aws":
        state = await aws_alarm_state(creds.get("aws_session"), spec["alarm_arn"])
        if state == "OK":
            return Outcome(FIXED, "CloudWatch alarm is back to OK")
        if state == "ALARM":
            return Outcome(NOT_FIXED, "CloudWatch alarm is still in ALARM")
        return Outcome(UNKNOWN, f"CloudWatch alarm state is {state}")
    condition = await azure_alert_condition(creds.get("azure_access_token"), spec["alert_id"])
    if condition == "Resolved":
        return Outcome(FIXED, "Azure Monitor alert is Resolved")
    if condition == "Fired":
        return Outcome(NOT_FIXED, "Azure Monitor alert is still Fired")
    return Outcome(UNKNOWN, f"Azure Monitor alert condition is {condition}")


CHECKS: dict[str, Callable[[dict, dict], Awaitable[Outcome]]] = {
    "aws_policy": _check_aws_policy,
    "azure_assignments_removed": _check_azure_assignments_removed,
    "compute_stopped": _check_compute_stopped,
    "drift_findings": _check_drift_findings,
    "alarm": _check_alarm,
}


async def run_check(spec: dict, creds: dict) -> Outcome:
    check = CHECKS.get((spec or {}).get("check"))
    if check is None:
        return Outcome(UNKNOWN, f"no live check named {(spec or {}).get('check')!r}")
    try:
        return await check(spec, creds)
    except LiveStateError as exc:
        return Outcome(UNKNOWN, str(exc))
    except KeyError as exc:
        return Outcome(UNKNOWN, f"verification spec is missing {exc}")


# ── the background pass ──────────────────────────────────────────────────────

async def run_verification_pass(pool, credentials_for=None) -> int:
    """Check every due incident once. Returns how many were checked."""
    if credentials_for is None:
        from core.workspace_credentials import build_agent_credentials as credentials_for
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                "SELECT id, workspace_id, agent_id, execution_status, verification_spec, verification_deadline, "
                "verification_attempts FROM incidents WHERE verification_next_at <= NOW() "
                "ORDER BY verification_next_at LIMIT $1 FOR UPDATE SKIP LOCKED",
                _BATCH,
            )
            for row in rows:  # claim: another worker won't pick these up until the lease ends
                await conn.execute("UPDATE incidents SET verification_next_at = NOW() + $1 WHERE id = $2",
                                   _CLAIM_LEASE, row["id"])

    for row in rows:
        async with pool.acquire() as conn:
            await _verify_one(conn, dict(row), credentials_for)
    return len(rows)


async def _verify_one(conn, row: dict, credentials_for) -> None:
    status = row["execution_status"]
    if status not in _VERIFIABLE_STATUSES:  # resolved by hand, or similar, meanwhile
        await conn.execute("UPDATE incidents SET verification_next_at = NULL WHERE id = $1", row["id"])
        return

    spec = row["verification_spec"]
    spec = json.loads(spec) if isinstance(spec, str) else spec
    try:
        creds = await credentials_for(conn, str(row["workspace_id"]))
    except Exception as exc:  # expired role, revoked app -- can't check, not "not fixed"
        log.warning("[Verification] credentials unavailable for incident %s: %s", row["id"], exc)
        creds = {}
    outcome = await run_check(spec, creds) if creds else Outcome(UNKNOWN, "workspace cloud credentials unavailable")

    now = datetime.now(timezone.utc)
    past_deadline = row["verification_deadline"] is None or now >= row["verification_deadline"]
    retry = MERGED_RETRY if status == "fix_merged" else LIVE_RETRY
    result = {"outcome": outcome.result, "detail": outcome.detail, "checked_at": now.isoformat(),
              "attempt": row["verification_attempts"] + 1}

    if outcome.result == FIXED:
        await _close(conn, row, STATUS_VERIFIED, result,
                     extra="verified_at = NOW(), resolved_at = COALESCE(resolved_at, NOW()), ")
        if status == "fix_merged":
            await _notify_resolved(conn, row)
    elif outcome.result == NOT_FIXED and past_deadline:
        await _close(conn, row, STATUS_VERIFICATION_FAILED, result)
        await _notify_failed(conn, row, result)
    elif outcome.result == UNKNOWN and past_deadline:
        result["outcome"] = "unverifiable"
        await conn.execute(
            "UPDATE incidents SET verification_next_at = NULL, verification_attempts = verification_attempts + 1, "
            "verification_result = $1 WHERE id = $2", json.dumps(result), row["id"])
        await _audit(conn, row, "verification_unverifiable", status, result)
    else:
        await conn.execute(
            "UPDATE incidents SET verification_next_at = NOW() + $1, verification_attempts = verification_attempts + 1, "
            "verification_result = $2 WHERE id = $3", retry, json.dumps(result), row["id"])
    log.info("[Verification] incident %s: %s (%s)", row["id"], outcome.result, outcome.detail)


async def _close(conn, row: dict, new_status: str, result: dict, extra: str = "") -> None:
    await conn.execute(
        f"UPDATE incidents SET execution_status = $1, {extra}verification_next_at = NULL, "
        "verification_attempts = verification_attempts + 1, verification_result = $2 "
        "WHERE id = $3 AND execution_status = $4",
        new_status, json.dumps(result), row["id"], row["execution_status"],
    )
    await _audit(conn, row, new_status, new_status, result)


async def _audit(conn, row: dict, action: str, status: str, result: dict) -> None:
    await conn.execute(
        "INSERT INTO audit_events (workspace_id, agent_id, incident_id, action, status, metadata) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        row["workspace_id"], row["agent_id"], row["id"], action, status, json.dumps(result),
    )


async def _notify_resolved(conn, row: dict) -> None:
    """A merged fix confirmed live is the resolution: tickets / PagerDuty close now
    (an executed action already notified when it ran)."""
    from core.ticketing import schedule_resolution_notification
    full = await conn.fetchrow(
        "SELECT resource_name, resource_group, metric_name, parsed_error, selected_option_id, resolved_at, "
        "cloud_provider, severity FROM incidents WHERE id = $1", row["id"])
    full = dict(full) if full else {}
    schedule_resolution_notification(str(row["workspace_id"]), {
        "incident_id": str(row["id"]), "agent_id": row["agent_id"], "execution_status": STATUS_VERIFIED,
        **{k: v for k, v in full.items() if k != "resolved_at"},
        "resolved_at": full["resolved_at"].isoformat() if full.get("resolved_at") else None,
    })


async def _notify_failed(conn, row: dict, result: dict) -> None:
    """"Your fix didn't work" -- the most important alert this product sends.
    Fans out to every notification channel (Slack / PagerDuty / email) and
    reopens the resolution ticket if one was filed. Both are fire-and-forget
    and never raise. Sent as severity 'critical' so no channel's severity floor
    filters it out (the incident's own severity is unchanged)."""
    import asyncio
    from core.notifications import notify_incident_channels
    from core.ticketing import reopen_resolution_ticket
    full = await conn.fetchrow(
        "SELECT parsed_error, resource_name, alert_name, severity FROM incidents WHERE id = $1", row["id"])
    full = dict(full) if full else {}
    workspace_id = str(row["workspace_id"])
    summary = {
        "incident_id": str(row["id"]), "agent_id": row["agent_id"], "execution_status": STATUS_VERIFICATION_FAILED,
        "summary": f"The fix ran but the problem is still there: {result['detail']}. "
                   f"Original issue: {(full.get('parsed_error') or '')[:300]}",
        "detail": result["detail"], "severity": "critical", "incident_severity": full.get("severity"),
        "resource_name": full.get("resource_name"), "alert_name": full.get("alert_name"),
    }
    for coro in (notify_incident_channels(workspace_id, summary), reopen_resolution_ticket(workspace_id, summary)):
        try:
            asyncio.create_task(coro)
        except Exception as exc:  # no running loop: never let this block closing the incident
            coro.close()
            log.warning("[Verification] could not schedule fix-failed alert for %s: %s", row["id"], exc)


def _uuid(value):
    from uuid import UUID
    return value if isinstance(value, UUID) else UUID(str(value))
