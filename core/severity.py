"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Severity normalization — 24-gap-closure build, Phase 1 (migration 042).

Every agent's ingest/diagnose node already speaks a different severity-
shaped dialect, confirmed by reading each one directly before writing this:
  - agent_02 (K8s alerts) and agent_11 (resource health) both parse Azure
    Monitor Common Alert Schema, whose `essentials.severity` is
    "Sev0".."Sev4" (Sev0 = highest). agent_11 additionally handles AWS
    CloudWatch alarms, whose only comparable field is `NewStateValue`
    ("ALARM"/"OK"/"INSUFFICIENT_DATA") -- not a severity at all, just
    alarm state, but it's the only signal CloudWatch itself provides.
  - agent_05 (IAM minimizer) computes a real `risk_score`:
    CRITICAL|HIGH|MEDIUM|LOW.
  - agent_08 (drift detection) computes a real `drift_severity`:
    CRITICAL|HIGH|MEDIUM|LOW.
  - agent_10 (dependency patch) computes real per-scan `critical_count`/
    `high_count` from OSV vulnerability data -- no single label, so its
    call site derives one from the counts before calling normalize_severity.
  - agents 01/03/04/06/07/09 have no severity-shaped signal at ingest at
    all (confirmed by grepping each workflow.py for risk/priority/
    critical/severity) -- they get the same 'medium' default as every
    backfilled pre-existing row, not a fabricated signal.

One shared normalizer instead of a per-agent-id dispatch table: every
caller already has its own real signal in hand by the time it reaches
the hitl_gate node, so the call site chooses what to pass rather than
this module trying to guess it from agent_id.
"""

VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low"})

_AZURE_SEV_MAP = {
    "sev0": "critical",
    "sev1": "high",
    "sev2": "medium",
    "sev3": "low",
    "sev4": "low",
}

# AWS CloudWatch alarm state is not a severity -- ALARM (a real threshold
# breach) is treated as high; OK/INSUFFICIENT_DATA (no real incident
# firing) as low, rather than inventing a severity CloudWatch never sends.
_AWS_STATE_MAP = {
    "alarm": "high",
    "ok": "low",
    "insufficient_data": "low",
}


def normalize_severity(raw: "str | None") -> str:
    """
    Maps a wide variety of upstream severity/priority/risk signals onto
    the incidents.severity enum (critical/high/medium/low). Defaults to
    'medium' for anything missing or unrecognized -- the same
    conservative default this migration's own backfill uses, and the
    only honest default when a caller genuinely has no severity-shaped
    signal.
    """
    if not raw:
        return "medium"
    r = raw.strip().lower()
    if r in VALID_SEVERITIES:
        return r
    if r in _AZURE_SEV_MAP:
        return _AZURE_SEV_MAP[r]
    if r in _AWS_STATE_MAP:
        return _AWS_STATE_MAP[r]
    return "medium"


def severity_from_counts(critical_count: int, high_count: int) -> str:
    """
    For agents that compute vulnerability/finding COUNTS by level rather
    than one overall label (agent_10's OSV scan: critical_count/
    high_count). Any critical finding makes the whole incident critical;
    any high finding (with no critical) makes it high; otherwise medium
    -- an incident with zero criticals/highs is still a real dependency
    patch worth reviewing, not downgraded to 'low'.
    """
    if critical_count > 0:
        return "critical"
    if high_count > 0:
        return "high"
    return "medium"


# Sort rank for the HITL queue (lower = shown first). Keep in sync with
# api/routes/incidents.py's list_incidents ORDER BY, which relies on this
# exact mapping via a SQL CASE expression (not this dict directly --
# see that file for why).
SEVERITY_SORT_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
