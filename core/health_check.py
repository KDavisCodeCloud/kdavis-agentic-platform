"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

core/health_check.py — the "how healthy is the whole platform" sweep
Kelvin asked for (2026-09-16): a script he can fire on demand, and that
also runs itself weekly/monthly/quarterly, alerting him via Slack.

Deliberately does NOT re-implement checks that already exist:
- Backend/DB/frontend liveness: api/main.py's real GET /api/status
  already HEADs theclouddecoded.com and checks the DB pool -- this
  module calls that endpoint rather than duplicating its logic.
- Code quality / gap detection / portfolio digest: already covered by
  .github/workflows/weekly-sweep.yml calling code_quality_agent /
  gap_detector_agent / portfolio_monitor directly, and surfaced live in
  ceo-dashboard's SystemHealthPanel.tsx. Not duplicated here.

What this module adds that nothing else in the repo checks yet:
  - Each deployed service's own health endpoint, hit independently
    (main backend, kdavis-finops-agent, kdavis-compliance-agent) --
    weekly-sweep.yml's own header comment says real-time visibility
    "lives in ceo-dashboard's System Health panel", but that panel only
    ever fires code_quality/gap_detector, never actually pings any
    deployed service.
  - TLS certificate expiry (theclouddecoded.com) -- monthly.
  - Internal agent activity: last successful run + error rate per known
    agent_id from internal_agent_runs -- nothing today aggregates "which
    agents haven't run recently or are erroring."
  - GitHub Actions workflow health -- are the cron workflows (weekly-
    sweep, linkedin-dispatch) actually succeeding on schedule, not
    silently red for weeks (this exact failure mode already happened
    once with weekly-sweep.yml's missing DATABASE_URL env, per that
    file's own comment -- this check exists specifically so that class
    of silent failure gets caught automatically instead of by accident).
  - Stripe API connectivity -- monthly.
  - RLS coverage across every public table -- quarterly, extends
    migration 031's own concern (workspaces/incidents/audit_events/
    token_usage had zero RLS until that migration) into an ongoing
    check that a *future* table doesn't reintroduce the same gap.

Explicitly NOT built (real gaps, not oversights -- reported as
NOT_IMPLEMENTED results rather than skipped silently, so a health report
shows what's missing, not just what passed):
  - n8n workflow health: n8n is not deployed anywhere in this stack.
    "n8n self-hosted" appears only in planning docs (knowledge/,
    CLOUD_DECODED_AUDIT_*.md) -- grepped the whole repo for any n8n
    client/webhook/API call in actual code, found none. There is
    nothing running to health-check.
  - Inbound email receiving ("ability to receive emails from clients"):
    finance/accounting/receipt_processor.py only parses receipt text
    already handed to it (OCR is a pluggable callable, not wired to
    anything) -- there is no webhook endpoint, IMAP poller, or forwarding
    address handler anywhere in this codebase that actually receives an
    email. Nothing to health-check until that's built.
  - Cost/token-spend trend and dependency/CVE scanning: no time-series
    cost table or dependency-scan tooling exists yet to check against.

Cadence design:
  WEEKLY  (Monday): everything cheap and fast -- service health
          endpoints, agent activity/error-rate (7-day lookback), GitHub
          Actions workflow status. Minutes, not an audit.
  MONTHLY: weekly + TLS cert expiry warning, Stripe connectivity. Things
          that change slowly enough that daily/weekly checking would be
          noise, but matter before they become an outage (a cert expiring
          in 25 days is not a "drop everything" Monday alert).
  QUARTERLY: monthly + RLS coverage across every public table, and the
          explicit gap report (n8n / inbound email / cost-tracking still
          not built) -- surfaced quarterly rather than every week so it
          nags without becoming wallpaper Kelvin starts ignoring.
"""

import logging
import os
import ssl
import socket
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import asyncpg
import httpx

log = logging.getLogger(__name__)

Status = Literal["ok", "degraded", "error", "not_implemented"]
Tier = Literal["weekly", "monthly", "quarterly"]

MAIN_BACKEND_URL = os.getenv("MAIN_BACKEND_URL", "https://kdavis-agentic-platform-production.up.railway.app")
FRONTEND_URL = "https://theclouddecoded.com"
_HTTP_TIMEOUT = 10.0

# name -> health endpoint. Each of these is a real, separately-deployed
# Railway service per .env's own *_API_URL vars -- api/main.py's
# /api/status only ever checks the main backend + its own DB + the
# frontend, never these two satellites.
_SATELLITE_SERVICES = {
    "kdavis-finops-agent": os.getenv("FINOPS_AGENT_API_URL", "").rstrip("/") + "/health",
    "kdavis-compliance-agent": os.getenv("COMPLIANCE_AGENT_API_URL", "").rstrip("/") + "/health",
}

# Same roster api/routes/internal_agents.py's gap_detector branch derives
# its AgentRosterEntry list from (_KNOWN_INTERNAL_AGENTS) -- reused here
# rather than redefined, so this can't drift from what the dashboard
# already considers "a real agent" out from under it.
from api.routes.internal_agents import _KNOWN_INTERNAL_AGENTS, _WIRABLE_AGENTS  # noqa: E402

_MONITORED_WORKFLOWS = ("weekly-sweep.yml", "linkedin-dispatch.yml", "gitea-mirror.yml")
_GITHUB_REPO = "KDavisCodeCloud/kdavis-agentic-platform"

_CERT_EXPIRY_WARNING_DAYS = 30
_AGENT_ACTIVITY_LOOKBACK_DAYS = 30  # "recently run" window -- an agent that only fires monthly shouldn't false-alarm every week it happens not to have run


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str
    data: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail, "data": self.data}


@dataclass
class HealthReport:
    tier: Tier
    generated_at: datetime
    results: list[CheckResult]

    @property
    def overall_status(self) -> Status:
        statuses = {r.status for r in self.results}
        if "error" in statuses:
            return "error"
        if "degraded" in statuses:
            return "degraded"
        return "ok"

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "generated_at": self.generated_at.isoformat(),
            "overall_status": self.overall_status,
            "results": [r.to_row() for r in self.results],
        }


async def check_service_health(name: str, health_url: str) -> CheckResult:
    if not health_url or health_url == "/health":
        return CheckResult(name, "error", "no URL configured for this service (missing *_API_URL env var)")
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(health_url)
        if response.status_code == 200:
            return CheckResult(name, "ok", "responding", {"url": health_url})
        status = "degraded" if response.status_code < 500 else "error"
        return CheckResult(name, status, f"HTTP {response.status_code}", {"url": health_url})
    except httpx.RequestError as exc:
        return CheckResult(name, "error", str(exc), {"url": health_url})


async def check_main_backend_status() -> CheckResult:
    """Calls api/main.py's own real /api/status (backend + DB + frontend
    HEAD check) rather than re-implementing any of that here."""
    url = f"{MAIN_BACKEND_URL}/api/status"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(url)
        response.raise_for_status()
        body = response.json()
        overall = body.get("status", "error")
        status: Status = "ok" if overall == "ok" else ("degraded" if overall == "degraded" else "error")
        return CheckResult("main_backend (/api/status)", status, str(body.get("services", {})), body)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return CheckResult("main_backend (/api/status)", "error", str(exc), {"url": url})


def check_tls_cert_expiry(hostname: str, warn_days: int = _CERT_EXPIRY_WARNING_DAYS) -> CheckResult:
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=_HTTP_TIMEOUT) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
        expires_at = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days_left = (expires_at - datetime.now(timezone.utc)).days
        if days_left < 0:
            return CheckResult(f"tls_cert:{hostname}", "error", "certificate already expired", {"days_left": days_left})
        if days_left < warn_days:
            return CheckResult(f"tls_cert:{hostname}", "degraded", f"expires in {days_left} days", {"days_left": days_left})
        return CheckResult(f"tls_cert:{hostname}", "ok", f"expires in {days_left} days", {"days_left": days_left})
    except (socket.error, ssl.SSLError, OSError) as exc:
        return CheckResult(f"tls_cert:{hostname}", "error", str(exc))


async def check_agent_activity(conn: asyncpg.Connection, lookback_days: int = _AGENT_ACTIVITY_LOOKBACK_DAYS) -> list[CheckResult]:
    """Per known agent_id (same roster internal_agents.py's gap_detector
    branch already trusts): last run timestamp + error rate over the
    lookback window. An agent that has NEVER run at all (email_sequence_
    agent, as of 2026-09-15 -- 0 executions ever) reports 'error' with an
    explicit "never run" detail rather than being silently absent from
    the report, which is exactly the kind of gap Kelvin asked to see."""
    results = []
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    for agent_id in sorted(_KNOWN_INTERNAL_AGENTS):
        row = await conn.fetchrow(
            """
            SELECT
              count(*) FILTER (WHERE created_at >= $2) AS recent_runs,
              count(*) FILTER (WHERE created_at >= $2 AND status = 'failed') AS recent_failures,
              max(created_at) AS last_run_at
            FROM internal_agent_runs WHERE agent_id = $1
            """,
            agent_id, since,
        )
        last_run_at = row["last_run_at"]
        recent_runs = row["recent_runs"] or 0
        recent_failures = row["recent_failures"] or 0

        if last_run_at is None:
            status: Status = "error" if agent_id in _WIRABLE_AGENTS else "not_implemented"
            detail = "never run in production" if agent_id in _WIRABLE_AGENTS else "not yet wired to a dispatch branch (spec only)"
        elif recent_runs and recent_failures / recent_runs > 0.5:
            status, detail = "error", f"{recent_failures}/{recent_runs} runs failed in the last {lookback_days}d, last run {last_run_at.isoformat()}"
        elif recent_failures:
            status, detail = "degraded", f"{recent_failures}/{recent_runs} runs failed in the last {lookback_days}d, last run {last_run_at.isoformat()}"
        else:
            status, detail = "ok", f"last run {last_run_at.isoformat()}, {recent_runs} run(s) in the last {lookback_days}d"

        results.append(CheckResult(f"agent:{agent_id}", status, detail, {
            "recent_runs": recent_runs, "recent_failures": recent_failures,
            "last_run_at": last_run_at.isoformat() if last_run_at else None,
        }))
    return results


async def check_github_actions_workflows(github_token: Optional[str]) -> list[CheckResult]:
    if not github_token:
        return [CheckResult("github_actions", "error", "GITHUB_TOKEN not provided -- cannot check workflow run history")]

    results = []
    headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client:
        for workflow in _MONITORED_WORKFLOWS:
            url = f"https://api.github.com/repos/{_GITHUB_REPO}/actions/workflows/{workflow}/runs"
            try:
                response = await client.get(url, params={"per_page": 1})
                response.raise_for_status()
                runs = response.json().get("workflow_runs", [])
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                results.append(CheckResult(f"workflow:{workflow}", "error", str(exc)))
                continue

            if not runs:
                results.append(CheckResult(f"workflow:{workflow}", "degraded", "no runs found"))
                continue

            latest = runs[0]
            conclusion = latest.get("conclusion")
            status: Status = "ok" if conclusion == "success" else ("degraded" if conclusion is None else "error")
            results.append(CheckResult(
                f"workflow:{workflow}", status,
                f"last run {latest.get('status')}/{conclusion} at {latest.get('run_started_at')}",
                {"run_url": latest.get("html_url")},
            ))
    return results


async def check_stripe_connectivity(stripe_api_key: Optional[str]) -> CheckResult:
    if not stripe_api_key:
        return CheckResult("stripe", "error", "STRIPE_SECRET_KEY not set")
    try:
        import stripe as stripe_sdk

        stripe_sdk.api_key = stripe_api_key
        account = stripe_sdk.Account.retrieve()
        return CheckResult("stripe", "ok", f"connected as {account.get('id', 'unknown')}")
    except Exception as exc:  # noqa: BLE001 -- any stripe SDK/auth error is a real "not connected" signal
        return CheckResult("stripe", "error", str(exc))


async def check_rls_coverage(conn: asyncpg.Connection) -> CheckResult:
    """Extends migration 031's concern (workspaces/incidents/audit_events/
    token_usage had zero RLS until that migration) into an ongoing check:
    any public, non-system table with RLS still disabled today. Does not
    judge whether a given table *should* have RLS (some internal-only
    tables legitimately don't need it) -- just reports the raw list so a
    human decides, same "surface, don't auto-fix" rule as everywhere else
    in this platform."""
    rows = await conn.fetch(
        """
        SELECT relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
        ORDER BY relname
        """
    )
    unprotected = [r["relname"] for r in rows]
    if not unprotected:
        return CheckResult("rls_coverage", "ok", "every public table has row-level security enabled")
    return CheckResult(
        "rls_coverage", "degraded",
        f"{len(unprotected)} public table(s) without RLS enabled: {', '.join(unprotected[:20])}"
        + (" ..." if len(unprotected) > 20 else ""),
        {"unprotected_tables": unprotected},
    )


def gap_report() -> list[CheckResult]:
    """Explicit, permanent NOT_IMPLEMENTED entries for the things Kelvin
    asked about that genuinely don't exist yet -- see module docstring."""
    return [
        CheckResult("n8n_workflows", "not_implemented", "n8n is not deployed anywhere in this stack -- no client/webhook code found in the repo, only mentioned in planning docs"),
        CheckResult("inbound_email", "not_implemented", "no webhook, IMAP poller, or forwarding-address handler exists anywhere -- receipt_processor.py only parses text already handed to it"),
        CheckResult("cost_spend_trend", "not_implemented", "no time-series cost/token-spend table exists to check a trend against"),
        CheckResult("dependency_cve_scan", "not_implemented", "no dependency/CVE scanning tool is wired into this repo's CI"),
    ]


async def run_health_sweep(
    tier: Tier,
    database_url: str,
    github_token: Optional[str] = None,
    stripe_api_key: Optional[str] = None,
) -> HealthReport:
    results: list[CheckResult] = []

    results.append(await check_main_backend_status())
    for name, health_url in _SATELLITE_SERVICES.items():
        results.append(await check_service_health(name, health_url))

    conn = await asyncpg.connect(database_url, statement_cache_size=0)
    try:
        results.extend(await check_agent_activity(conn))
        if tier == "quarterly":
            results.append(await check_rls_coverage(conn))
    finally:
        await conn.close()

    results.extend(await check_github_actions_workflows(github_token))

    if tier in ("monthly", "quarterly"):
        results.append(check_tls_cert_expiry("theclouddecoded.com"))
        results.append(await check_stripe_connectivity(stripe_api_key))

    if tier == "quarterly":
        results.extend(gap_report())

    return HealthReport(tier=tier, generated_at=datetime.now(timezone.utc), results=results)


def format_slack_message(report: HealthReport) -> dict:
    icon = {"ok": "✅", "degraded": "⚠️", "error": "🔴", "not_implemented": "⬜"}
    lines = [f"*{report.tier.upper()} health sweep — {report.overall_status.upper()}* ({report.generated_at.strftime('%Y-%m-%d %H:%M UTC')})"]
    for r in report.results:
        if r.status == "ok":
            continue  # only surface what needs attention, plus the not_implemented gap list -- an all-green line-by-line report is noise
        lines.append(f"{icon[r.status]} `{r.name}` — {r.detail}")
    ok_count = sum(1 for r in report.results if r.status == "ok")
    lines.append(f"\n{ok_count}/{len(report.results)} checks passed clean.")
    return {"text": "\n".join(lines)}


async def send_slack_alert(webhook_url: str, report: HealthReport) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(webhook_url, json=format_slack_message(report))
        response.raise_for_status()


async def main(tier: Tier, report_out: Optional[str] = None) -> HealthReport:
    database_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    report = await run_health_sweep(
        tier=tier,
        database_url=database_url,
        github_token=os.getenv("GITHUB_TOKEN"),
        stripe_api_key=os.getenv("STRIPE_SECRET_KEY"),
    )

    webhook_url = os.getenv("SLACK_OPS_WEBHOOK_URL")
    if webhook_url:
        try:
            await send_slack_alert(webhook_url, report)
        except httpx.HTTPError as exc:  # noqa: BLE001 -- alert delivery failure must never crash the sweep itself
            log.warning("Failed to send Slack health alert: %s", exc)
    else:
        log.warning("SLACK_OPS_WEBHOOK_URL not set -- health report generated but not delivered anywhere")

    if report_out:
        import json

        with open(report_out, "w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)

    return report


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=["weekly", "monthly", "quarterly"], required=True)
    parser.add_argument("--report-out", default=None)
    args = parser.parse_args()

    result = asyncio.run(main(args.tier, args.report_out))
    print(f"{result.tier} health sweep: {result.overall_status}")
    for row in result.results:
        print(f"  [{row.status}] {row.name}: {row.detail}")
    if result.overall_status == "error":
        raise SystemExit(1)
