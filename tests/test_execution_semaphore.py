"""
tests/test_execution_semaphore.py
Tests for core/execution_semaphore.py -- Phase 7, scale-readiness build.

Confirms:
  - the semaphore's capacity is derived from db_pool.get_max_size(), not
    a second, independently-drifting magic number
  - it's created once and cached on app.state, not recreated per call
  - concurrent executions beyond capacity actually queue (proven the
    same way core/checkpointer_lock.py's tests prove serialization --
    tracking max-concurrent-seen against a fake that yields control)
  - a wait past the backpressure threshold is reported via
    core.error_tracking.capture_message, a wait under it is not
  - the bounded_execution decorator preserves the wrapped function's
    call signature and return value
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.execution_semaphore import (
    _get_or_create_semaphore,
    bounded_agent_execution,
    bounded_execution,
)


def _fake_app(max_size: int = 3):
    pool = MagicMock()
    pool.get_max_size = MagicMock(return_value=max_size)
    return SimpleNamespace(state=SimpleNamespace(db_pool=pool))


class TestGetOrCreateSemaphore:
    def test_capacity_derived_from_pool_max_size(self):
        app = _fake_app(max_size=7)
        semaphore = _get_or_create_semaphore(app)
        assert semaphore._value == 7

    def test_cached_on_app_state_not_recreated(self):
        app = _fake_app(max_size=5)
        first = _get_or_create_semaphore(app)
        second = _get_or_create_semaphore(app)
        assert first is second


class TestBoundedAgentExecutionConcurrency:
    async def test_caps_concurrent_executions_at_pool_max_size(self):
        app = _fake_app(max_size=2)
        max_concurrent_seen = 0
        in_flight = 0

        async def simulated_job(i):
            nonlocal in_flight, max_concurrent_seen
            async with bounded_agent_execution(app, "agent_01_cicd_triage", f"ws-{i}"):
                in_flight += 1
                max_concurrent_seen = max(max_concurrent_seen, in_flight)
                await asyncio.sleep(0.01)
                in_flight -= 1

        await asyncio.gather(*[simulated_job(i) for i in range(5)])

        assert max_concurrent_seen == 2  # never more than the pool's max_size

    async def test_all_jobs_eventually_run(self):
        app = _fake_app(max_size=2)
        completed = []

        async def simulated_job(i):
            async with bounded_agent_execution(app, "agent_01_cicd_triage", f"ws-{i}"):
                await asyncio.sleep(0.001)
                completed.append(i)

        await asyncio.gather(*[simulated_job(i) for i in range(5)])
        assert sorted(completed) == [0, 1, 2, 3, 4]


class TestBackpressureReporting:
    async def test_short_wait_does_not_report(self):
        app = _fake_app(max_size=5)
        with patch("core.execution_semaphore.capture_message") as mock_capture:
            async with bounded_agent_execution(app, "agent_01_cicd_triage", "ws-1"):
                pass
        mock_capture.assert_not_called()

    async def test_long_wait_reports_backpressure(self):
        app = _fake_app(max_size=1)

        async def hold_the_only_slot():
            async with bounded_agent_execution(app, "agent_01_cicd_triage", "ws-holder"):
                await asyncio.sleep(1.2)  # forces the next waiter past the 1.0s threshold

        with patch("core.execution_semaphore.capture_message") as mock_capture, \
             patch("core.execution_semaphore._BACKPRESSURE_LOG_THRESHOLD_SECONDS", 0.05):
            holder_task = asyncio.create_task(hold_the_only_slot())
            await asyncio.sleep(0.01)  # let the holder acquire first

            async with bounded_agent_execution(app, "agent_02_k8s_alert", "ws-waiter"):
                pass

            await holder_task

        mock_capture.assert_called_once()
        args, kwargs = mock_capture.call_args
        assert "backpressure" in args[0].lower()
        assert kwargs["agent_id"] == "agent_02_k8s_alert"
        assert kwargs["workspace_id"] == "ws-waiter"


class TestBoundedExecutionDecorator:
    async def test_preserves_call_signature_and_return_value(self):
        app = _fake_app(max_size=3)

        @bounded_execution("agent_01_cicd_triage")
        async def _run_something(app, workspace, payload, cloud_provider, ingestion_log_id=None):
            return {"workspace": workspace["id"], "payload": payload, "log_id": ingestion_log_id}

        result = await _run_something(app, {"id": "ws-1"}, {"x": 1}, "github", ingestion_log_id="log-1")

        assert result == {"workspace": "ws-1", "payload": {"x": 1}, "log_id": "log-1"}

    async def test_handles_workspace_without_id_gracefully(self):
        """Some callers might pass a non-standard workspace shape --
        must not crash the semaphore/backpressure logging path."""
        app = _fake_app(max_size=3)

        @bounded_execution("agent_01_cicd_triage")
        async def _run_something(app, workspace):
            return "ok"

        result = await _run_something(app, {})
        assert result == "ok"

    async def test_caps_concurrency_through_the_decorator(self):
        app = _fake_app(max_size=2)
        max_concurrent_seen = 0
        in_flight = 0

        @bounded_execution("agent_01_cicd_triage")
        async def _run_something(app, workspace):
            nonlocal in_flight, max_concurrent_seen
            in_flight += 1
            max_concurrent_seen = max(max_concurrent_seen, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

        await asyncio.gather(*[_run_something(app, {"id": f"ws-{i}"}) for i in range(5)])

        assert max_concurrent_seen == 2
