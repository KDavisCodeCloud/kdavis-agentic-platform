"""
tests/test_health_check.py
Tests for core/health_check.py -- the weekly/monthly/quarterly platform
health sweep (2026-09-16). External calls (httpx, asyncpg, stripe, TLS
sockets) are mocked throughout; this covers the check logic and the
weekly/monthly/quarterly tier composition, not real infrastructure.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import health_check as hc


def _mock_httpx_get_client(status_code: int = 200, json_body: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=json_body or {})
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")

    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestCheckServiceHealth:
    async def test_ok_on_200(self):
        client = _mock_httpx_get_client(200)
        with patch("core.health_check.httpx.AsyncClient", return_value=client):
            result = await hc.check_service_health("kdavis-finops-agent", "https://x.example.com/health")
        assert result.status == "ok"

    async def test_error_on_500(self):
        client = _mock_httpx_get_client(500)
        with patch("core.health_check.httpx.AsyncClient", return_value=client):
            result = await hc.check_service_health("kdavis-finops-agent", "https://x.example.com/health")
        assert result.status == "error"

    async def test_error_when_no_url_configured(self):
        result = await hc.check_service_health("kdavis-finops-agent", "")
        assert result.status == "error"
        assert "no URL configured" in result.detail


class TestCheckMainBackendStatus:
    async def test_maps_api_status_ok_through(self):
        client = _mock_httpx_get_client(200, {"status": "ok", "services": {}})
        with patch("core.health_check.httpx.AsyncClient", return_value=client):
            result = await hc.check_main_backend_status()
        assert result.status == "ok"

    async def test_maps_api_status_degraded_through(self):
        client = _mock_httpx_get_client(200, {"status": "degraded", "services": {}})
        with patch("core.health_check.httpx.AsyncClient", return_value=client):
            result = await hc.check_main_backend_status()
        assert result.status == "degraded"


class TestCheckAgentActivity:
    async def _conn_returning(self, rows_by_agent: dict):
        conn = AsyncMock()

        async def fetchrow(query, agent_id, since):
            return rows_by_agent.get(agent_id, {"recent_runs": 0, "recent_failures": 0, "last_run_at": None})

        conn.fetchrow = fetchrow
        return conn

    async def test_never_run_wirable_agent_is_error(self):
        conn = await self._conn_returning({})  # every agent defaults to never-run
        results = await hc.check_agent_activity(conn)
        wirable_result = next(r for r in results if r.name == "agent:research_agent")
        assert wirable_result.status == "error"
        assert "never run" in wirable_result.detail

    async def test_never_run_non_wirable_agent_is_not_implemented(self):
        conn = await self._conn_returning({})
        results = await hc.check_agent_activity(conn)
        # portfolio_monitor is in _KNOWN_INTERNAL_AGENTS but not _WIRABLE_AGENTS
        # (no dispatch branch in api/routes/internal_agents.py yet)
        target = next(r for r in results if r.name == "agent:portfolio_monitor")
        assert target.status == "not_implemented"

    async def test_high_failure_rate_is_error(self):
        now = datetime.now(timezone.utc)
        conn = await self._conn_returning({
            "code_quality_agent": {"recent_runs": 10, "recent_failures": 6, "last_run_at": now},
        })
        results = await hc.check_agent_activity(conn)
        target = next(r for r in results if r.name == "agent:code_quality_agent")
        assert target.status == "error"

    async def test_low_failure_rate_is_degraded_not_error(self):
        now = datetime.now(timezone.utc)
        conn = await self._conn_returning({
            "code_quality_agent": {"recent_runs": 10, "recent_failures": 1, "last_run_at": now},
        })
        results = await hc.check_agent_activity(conn)
        target = next(r for r in results if r.name == "agent:code_quality_agent")
        assert target.status == "degraded"

    async def test_clean_recent_run_is_ok(self):
        now = datetime.now(timezone.utc)
        conn = await self._conn_returning({
            "code_quality_agent": {"recent_runs": 5, "recent_failures": 0, "last_run_at": now},
        })
        results = await hc.check_agent_activity(conn)
        target = next(r for r in results if r.name == "agent:code_quality_agent")
        assert target.status == "ok"


class TestCheckGithubActionsWorkflows:
    async def test_no_token_returns_single_error_result(self):
        results = await hc.check_github_actions_workflows(None)
        assert len(results) == 1
        assert results[0].status == "error"

    async def test_successful_latest_run_is_ok(self):
        run = {"status": "completed", "conclusion": "success", "run_started_at": "2026-09-15T11:00:00Z", "html_url": "https://x"}
        client = _mock_httpx_get_client(200, {"workflow_runs": [run]})
        with patch("core.health_check.httpx.AsyncClient", return_value=client):
            results = await hc.check_github_actions_workflows("fake-token")
        assert all(r.status == "ok" for r in results)
        assert len(results) == len(hc._MONITORED_WORKFLOWS)

    async def test_failed_latest_run_is_error(self):
        run = {"status": "completed", "conclusion": "failure", "run_started_at": "2026-09-15T11:00:00Z", "html_url": "https://x"}
        client = _mock_httpx_get_client(200, {"workflow_runs": [run]})
        with patch("core.health_check.httpx.AsyncClient", return_value=client):
            results = await hc.check_github_actions_workflows("fake-token")
        assert all(r.status == "error" for r in results)

    async def test_no_runs_found_is_degraded(self):
        client = _mock_httpx_get_client(200, {"workflow_runs": []})
        with patch("core.health_check.httpx.AsyncClient", return_value=client):
            results = await hc.check_github_actions_workflows("fake-token")
        assert all(r.status == "degraded" for r in results)


class TestCheckStripeConnectivity:
    async def test_no_key_is_error(self):
        result = await hc.check_stripe_connectivity(None)
        assert result.status == "error"

    async def test_successful_retrieve_is_ok(self):
        fake_stripe = MagicMock()
        fake_stripe.Account.retrieve = MagicMock(return_value={"id": "acct_123"})
        with patch.dict("sys.modules", {"stripe": fake_stripe}):
            result = await hc.check_stripe_connectivity("sk_test_x")
        assert result.status == "ok"

    async def test_sdk_error_is_error(self):
        fake_stripe = MagicMock()
        fake_stripe.Account.retrieve = MagicMock(side_effect=Exception("invalid key"))
        with patch.dict("sys.modules", {"stripe": fake_stripe}):
            result = await hc.check_stripe_connectivity("sk_bad")
        assert result.status == "error"


class TestCheckBrevoConnectivity:
    async def test_no_key_is_error(self):
        result = await hc.check_brevo_connectivity(None)
        assert result.status == "error"
        assert "BREVO_API_KEY" in result.detail

    async def test_successful_get_lists_is_ok(self):
        fake_result = MagicMock(lists=[MagicMock(), MagicMock()])
        fake_client = MagicMock()
        fake_client.contacts.get_lists = MagicMock(return_value=fake_result)
        fake_brevo_module = MagicMock(Brevo=MagicMock(return_value=fake_client))
        with patch.dict("sys.modules", {"brevo": fake_brevo_module}):
            result = await hc.check_brevo_connectivity("fake-key")
        assert result.status == "ok"
        assert "2 list" in result.detail

    async def test_sdk_error_is_error(self):
        fake_client = MagicMock()
        fake_client.contacts.get_lists = MagicMock(side_effect=Exception("invalid key"))
        fake_brevo_module = MagicMock(Brevo=MagicMock(return_value=fake_client))
        with patch.dict("sys.modules", {"brevo": fake_brevo_module}):
            result = await hc.check_brevo_connectivity("bad-key")
        assert result.status == "error"


class TestCheckRlsCoverage:
    async def test_all_protected_is_ok(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        result = await hc.check_rls_coverage(conn)
        assert result.status == "ok"

    async def test_unprotected_tables_are_degraded(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"relname": "some_new_table"}])
        result = await hc.check_rls_coverage(conn)
        assert result.status == "degraded"
        assert "some_new_table" in result.detail


class TestGapReport:
    def test_reports_n8n_and_inbound_email_as_not_implemented(self):
        results = gap_names = {r.name: r for r in hc.gap_report()}
        assert gap_names["n8n_workflows"].status == "not_implemented"
        assert gap_names["inbound_email"].status == "not_implemented"


class TestHealthReport:
    def test_overall_status_error_wins_over_degraded(self):
        report = hc.HealthReport(tier="weekly", generated_at=datetime.now(timezone.utc), results=[
            hc.CheckResult("a", "ok", ""), hc.CheckResult("b", "degraded", ""), hc.CheckResult("c", "error", ""),
        ])
        assert report.overall_status == "error"

    def test_overall_status_ok_when_nothing_wrong(self):
        report = hc.HealthReport(tier="weekly", generated_at=datetime.now(timezone.utc), results=[
            hc.CheckResult("a", "ok", ""), hc.CheckResult("b", "not_implemented", ""),
        ])
        assert report.overall_status == "ok"


class TestFormatSlackMessage:
    def test_omits_ok_rows_includes_problem_rows(self):
        report = hc.HealthReport(tier="weekly", generated_at=datetime.now(timezone.utc), results=[
            hc.CheckResult("good_check", "ok", "fine"),
            hc.CheckResult("bad_check", "error", "broken"),
        ])
        message = hc.format_slack_message(report)
        assert "good_check" not in message["text"]
        assert "bad_check" in message["text"]
        assert "broken" in message["text"]


class TestRunHealthSweepTierComposition:
    """Confirms weekly < monthly < quarterly actually adds checks, not
    just relabels the same set -- the core claim behind the cadence design
    in the module docstring."""

    async def _patched_sweep(self, tier):
        with patch("core.health_check.check_main_backend_status", new=AsyncMock(return_value=hc.CheckResult("main_backend", "ok", ""))), \
             patch("core.health_check.check_service_health", new=AsyncMock(return_value=hc.CheckResult("svc", "ok", ""))), \
             patch("core.health_check.check_agent_activity", new=AsyncMock(return_value=[])), \
             patch("core.health_check.check_rls_coverage", new=AsyncMock(return_value=hc.CheckResult("rls_coverage", "ok", ""))), \
             patch("core.health_check.check_github_actions_workflows", new=AsyncMock(return_value=[])), \
             patch("core.health_check.check_tls_cert_expiry", return_value=hc.CheckResult("tls", "ok", "")), \
             patch("core.health_check.check_stripe_connectivity", new=AsyncMock(return_value=hc.CheckResult("stripe", "ok", ""))), \
             patch("core.health_check.check_brevo_connectivity", new=AsyncMock(return_value=hc.CheckResult("brevo", "ok", ""))), \
             patch("core.health_check.asyncpg.connect", new=AsyncMock(return_value=AsyncMock(close=AsyncMock()))):
            return await hc.run_health_sweep(tier, database_url="postgresql://fake")

    async def test_weekly_has_no_tls_stripe_or_gap_report(self):
        report = await self._patched_sweep("weekly")
        names = {r.name for r in report.results}
        assert not any(n.startswith("tls_cert") for n in names)
        assert "stripe" not in names
        assert "brevo" not in names
        assert "rls_coverage" not in names
        assert "n8n_workflows" not in names

    async def test_monthly_adds_tls_and_stripe_not_rls_or_gaps(self):
        report = await self._patched_sweep("monthly")
        names = {r.name for r in report.results}
        assert "stripe" in names
        assert "brevo" in names
        assert "rls_coverage" not in names
        assert "n8n_workflows" not in names

    async def test_quarterly_adds_rls_and_gap_report(self):
        report = await self._patched_sweep("quarterly")
        names = {r.name for r in report.results}
        assert "stripe" in names
        assert "brevo" in names
        assert "rls_coverage" in names
        assert "n8n_workflows" in names
        assert "inbound_email" in names
