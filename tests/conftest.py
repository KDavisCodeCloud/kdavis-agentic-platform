"""
Shared fixtures and import stubs for the Cloud Decoded test suite.

Module-level sys.modules stubs allow all agent/API modules to be imported
in a bare environment (before pip install -r requirements.txt), so tests
exist as runnable specification rather than deferred integration tests.

Stub order matters: register parent packages before sub-packages.
"""

import sys
import os
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ──────────────────────────────────────────────
# Dependency stubs — register before any project imports
# ──────────────────────────────────────────────

def _stub(name: str) -> MagicMock:
    m = MagicMock()
    sys.modules[name] = m
    return m


def _ensure_stub(name: str) -> MagicMock:
    """Register stub only if the real module is not importable."""
    try:
        __import__(name)
        return sys.modules[name]
    except ImportError:
        return _stub(name)


# LangGraph — not installed in CI; stub so workflow.py is importable
_lg       = _ensure_stub("langgraph")
_lg_graph = _ensure_stub("langgraph.graph")
_lg_types = _ensure_stub("langgraph.types")
_lg_chk   = _ensure_stub("langgraph.checkpoint")
_lg_pg    = _ensure_stub("langgraph.checkpoint.postgres")
_lg_pgaio = _ensure_stub("langgraph.checkpoint.postgres.aio")

# Expose the symbols workflow.py imports directly
_lg_graph.StateGraph    = MagicMock(return_value=MagicMock())
_lg_graph.START         = "START"
_lg_graph.END           = "END"
_lg_types.interrupt     = MagicMock(return_value=None)
_lg_types.Command       = MagicMock()
_lg_pgaio.AsyncPostgresSaver = MagicMock()

# slowapi — used in api/
_ensure_stub("slowapi")
_ensure_stub("slowapi.util")
_ensure_stub("slowapi.errors")

# asyncpg — not needed in tests (always mocked at DB layer)
_ensure_stub("asyncpg")

# stripe — not needed in security/agent tests
_ensure_stub("stripe")

# ──────────────────────────────────────────────
# Sample data constants
# ──────────────────────────────────────────────

TEST_WORKSPACE_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

SAMPLE_K8S_DIAGNOSIS = json.dumps({
    "parsed_error": (
        "The pod 'payment-service-7d9f8b-xkq2p' in namespace 'production' was killed by the "
        "Linux OOM killer (exit code 137) because it exceeded its 512Mi memory limit — it has "
        "restarted 4 times in the last 10 minutes. The payment-service deployment is currently "
        "degraded and serving reduced capacity."
    ),
    "options": [
        {
            "id": "opt_1",
            "title": "Increase memory limit to 1Gi",
            "description": (
                "Updates the payment-service Deployment manifest to set "
                "resources.limits.memory: 1Gi and requests.memory: 512Mi. "
                "Lowest-risk fix if the app legitimately needs more memory."
            ),
            "impact": "low",
            "docs_url": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",
        },
        {
            "id": "opt_2",
            "title": "Add horizontal pod autoscaler",
            "description": (
                "Configures an HPA to scale payment-service between 2–10 replicas based on "
                "memory utilization (target: 70%), distributing load instead of increasing "
                "per-pod limits."
            ),
            "impact": "medium",
            "docs_url": "https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/",
        },
        {
            "id": "hold",
            "title": "Hold for manual resolution",
            "description": "Pause this incident and handle it manually. No automated action will be taken.",
            "impact": "low",
            "docs_url": "https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/",
        },
    ],
    "estimated_duration_seconds": 30,
})

SAMPLE_LLM_DIAGNOSIS = json.dumps({
    "parsed_error": (
        "The CI pipeline failed because the npm install step could not resolve "
        "a peer dependency conflict between react@18 and @testing-library/react@12."
    ),
    "options": [
        {
            "id": "opt_1",
            "title": "Pin @testing-library/react to compatible version",
            "description": "Update package.json to use @testing-library/react@13 which supports React 18.",
            "impact": "low",
            "docs_url": "https://testing-library.com/docs/react-testing-library/intro/",
        },
        {
            "id": "opt_2",
            "title": "Use --legacy-peer-deps flag",
            "description": "Add --legacy-peer-deps to the npm install command to bypass strict peer checks.",
            "impact": "medium",
            "docs_url": "https://docs.npmjs.com/cli/v10/using-npm/config#legacy-peer-deps",
        },
        {
            "id": "hold",
            "title": "Stay broken / custom solution",
            "description": "Accept current state and provide a custom fix.",
            "impact": "low",
            "docs_url": "https://docs.github.com/en/actions",
        },
    ],
    "estimated_duration_seconds": 90,
})


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def workspace_id() -> str:
    return TEST_WORKSPACE_ID


@pytest.fixture
def mock_db():
    """
    Async mock that mirrors the asyncpg connection API used throughout the
    platform (fetchrow, fetch, execute, transaction context manager).
    """
    conn = AsyncMock()

    # Default fetchrow returns an incident UUID row
    _default_row = {"id": uuid4()}
    conn.fetchrow = AsyncMock(return_value=_default_row)
    conn.fetch    = AsyncMock(return_value=[])
    conn.execute  = AsyncMock(return_value=None)

    # transaction() must return an async context manager
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=tx_ctx)
    tx_ctx.__aexit__  = AsyncMock(return_value=False)
    conn.transaction  = MagicMock(return_value=tx_ctx)

    return conn


@pytest.fixture
def mock_router():
    """
    Mock of .llm/router.py's complete() function.
    Returns a valid JSON diagnosis string by default.
    """
    m = MagicMock()
    m.complete.return_value = SAMPLE_LLM_DIAGNOSIS
    return m


@pytest.fixture
def mock_checkpointer():
    """Mock LangGraph AsyncPostgresSaver."""
    return MagicMock()


@pytest.fixture
def github_failure_payload():
    return {
        "action": "completed",
        "workflow_run": {
            "id": 12345678,
            "name": "CI / test",
            "conclusion": "failure",
            "head_branch": "feature/add-auth",
            "html_url": "https://github.com/acme/backend/actions/runs/12345678",
            "head_commit": {"message": "feat: add JWT middleware"},
            "pull_requests": [{"number": 99}],
        },
        "repository": {"full_name": "acme/backend"},
    }


@pytest.fixture
def azure_failure_payload():
    return {
        "eventType": "build.complete",
        "resource": {
            "id": 555,
            "result": "failed",
            "definition": {"id": 7, "name": "Deploy to Staging"},
            "sourceBranch": "refs/heads/main",
            "repository": {"id": "repo-abc-123"},
        },
        "resourceContainers": {
            "account": {"id": "contoso"},
            "project": {"name": "BackendServices"},
        },
    }


@pytest.fixture
def github_pr_payload():
    return {
        "action": "opened",
        "number": 42,
        "pull_request": {
            "number": 42,
            "title": "feat: add JWT authentication middleware",
            "body": "Adds JWT token validation to all protected API routes.",
            "user": {"login": "dev-alice"},
            "base": {"ref": "main", "sha": "abc123"},
            "head": {"ref": "feature/add-auth", "sha": "def456abc789"},
            "html_url": "https://github.com/acme/backend/pull/42",
        },
        "repository": {"full_name": "acme/backend"},
    }


@pytest.fixture
def k8s_alertmanager_payload():
    from tests.mocks.azure_fixtures import MOCK_PROMETHEUS_ALERTMANAGER
    return MOCK_PROMETHEUS_ALERTMANAGER


@pytest.fixture
def k8s_azure_monitor_payload():
    from tests.mocks.azure_fixtures import MOCK_AZURE_MONITOR_AKS_ALERT
    return MOCK_AZURE_MONITOR_AKS_ALERT


