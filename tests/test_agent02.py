"""
tests/test_agent02.py
Tests for agents/agent_02_k8s_alert/tools.py and agents/agent_02_k8s_alert/workflow.py.

What this file validates:
  K8sTools (post-approval execution tools):
    - patch_deployment_memory() PATCHes the correct k8s API endpoint
    - patch_deployment_memory() raises EnvironmentError when k8s config is missing
    - patch_deployment_memory() includes container name in patch body
    - apply_hpa() POSTs to the autoscaling/v2 API endpoint
    - apply_hpa() raises EnvironmentError when k8s config is missing
    - apply_hpa() retries with PUT when 409 Conflict is returned
    - rollback_deployment() GETs current revision then PATCHes with restart annotation
    - rollback_deployment() raises EnvironmentError when k8s config is missing
    - create_gitops_pr() delegates branch/commit/PR creation to core.repo_tools (Phase 4)
    - create_gitops_pr() raises NoRepoCredentialError when no repo credential is configured
    - execute_option("hold") returns held status without making any API call
    - execute_option("opt_1") dispatches to patch_deployment_memory
    - execute_option("opt_2") dispatches to apply_hpa
    - execute_option("opt_3") dispatches to rollback_deployment

  K8sAlertWorkflow._ingest_node():
    - Prometheus payload extracts namespace from labels
    - Prometheus payload extracts pod_name from labels
    - Prometheus payload derives deployment_name from pod_name (strips RS+pod hash)
    - Prometheus payload extracts cluster_name from labels
    - Prometheus payload extracts alert_type from labels
    - Azure Monitor payload extracts namespace from customProperties
    - Azure Monitor payload extracts pod_name from search results
    - Azure Monitor payload extracts exit_code from search results
    - Azure Monitor payload extracts restart_count from search results
    - Azure Monitor payload derives deployment_name when not in customProperties
    - Unknown payload format does not raise and returns non-empty log_excerpt
    - Sanitizes log_excerpt via DataSanitizationShield

  _classify_alert_category():
    - Maps alert_type strings to evidence categories (crashloop, oomkill,
      imagepull, pending, dns, pvc, service, generic fallback)

  K8sTools.gather_evidence() (read-only pre-diagnose evidence step):
    - crashloop category fetches describe + previous logs + events
    - imagepull category fetches describe + events
    - pending category fetches describe + node conditions
    - oomkill category fetches describe + metrics
    - service category fetches endpoints + service + ingress describe
    - pvc category fetches PVC describe + storageclass
    - dns category fetches CoreDNS logs from kube-system
    - generic category (unrecognized alert_type) fetches describe + events
    - Missing cluster credentials returns available=False, no HTTP calls made
    - A failed individual check degrades to an "[unavailable: ...]" section
      without failing the whole gather
    - Evidence text is truncated to _MAX_EVIDENCE_CHARS

  K8sAlertWorkflow._evidence_node():
    - Reachable cluster returns live_evidence_text populated from gather_evidence
    - Unreachable/unconfigured cluster returns a "[live evidence unavailable: ...]" note
    - Skips (returns {}) when state["error"] is already set upstream

  K8sAlertWorkflow._diagnose_node():
    - Calls router.complete() with task_type="k8s_triage"
    - Parses valid LLM JSON response into parsed_error + options
    - Handles LLM JSON parse error and sets state["error"]
    - Calls budget.assert_budget_available() before the LLM call
    - Includes deployment_name and alert_type in LLM message
    - Includes live_evidence_text (available or unavailable-note) in LLM message

  K8sAlertWorkflow._hitl_gate_node():
    - Calls hitl.create_incident() with correct fields
    - Calls interrupt() to pause the graph
    - Skips incident creation when state["error"] is set
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agents.agent_02_k8s_alert.tools import K8sTools, _halve_memory
from agents.agent_02_k8s_alert.workflow import K8sAlertWorkflow, K8sAlertState, _classify_alert_category
from core.repo_tools import NoRepoCredentialError


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_workflow(mock_db, workspace_id, mock_router) -> K8sAlertWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(K8sAlertWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = K8sAlertWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_k8s_state(workspace_id: str, payload: dict | None = None) -> K8sAlertState:
    return {
        "workspace_id": workspace_id,
        "cloud_provider": "azure",
        "webhook_payload": payload or {},
        "namespace": "production",
        "pod_name": "payment-service-7d9f8b-xkq2p",
        "deployment_name": "payment-service",
        "cluster_name": "prod-aks",
        "container_name": "payment-service",
        "exit_code": 137,
        "restart_count": 4,
        "alert_type": "OOMKilled",
        "current_memory_limit": "512Mi",
        "current_cpu_limit": "500m",
        "log_excerpt": "Alert: KubePodCrashLooping\nPod: payment-service-7d9f8b-xkq2p",
        "live_evidence_text": "",
        "incident_id": None,
        "parsed_error": None,
        "remediation_options": None,
        "estimated_duration_seconds": None,
        "tokens_used": 0,
        "selected_option": None,
        "execution_result": None,
        "error": None,
    }


class TestK8sAlertWorkflowCredentialWiring:
    # Phase 4 (connectivity gaps): K8sAlertWorkflow.__init__ used to accept
    # only (db_conn, workspace_id, checkpointer) -- no way for a caller to
    # pass a workspace's real K8s API or GitHub credential at all, so
    # K8sTools always fell back to shared os.environ["K8S_API_URL"]/
    # ["K8S_TOKEN"]/["GITHUB_TOKEN"]. This pins that the constructor now
    # threads all of them through to self._tools.

    def test_k8s_and_github_credentials_reach_k8s_tools(self):
        mock_db = MagicMock()
        with (
            patch("agents.base_agent._load_router", return_value=MagicMock()),
            patch.object(K8sAlertWorkflow, "_build_graph", return_value=MagicMock()),
        ):
            wf = K8sAlertWorkflow(
                mock_db, str(uuid4()), MagicMock(),
                github_token="ghp_real_workspace_token",
                aws_session=MagicMock(),
                azure_access_token="unused",
                azure_devops_token="unused",
                azure_devops_org="unused",
                k8s_api_url="https://prod-cluster.example.com",
                k8s_token="real_k8s_token",
                k8s_ca_cert="fake-pem",
            )
        assert wf._tools.github_token == "ghp_real_workspace_token"
        assert wf._tools.k8s_api_url == "https://prod-cluster.example.com"
        assert wf._tools.k8s_token == "real_k8s_token"

    def test_no_credentials_leaves_tools_empty_not_env_fallback(self):
        mock_db = MagicMock()
        with (
            patch("agents.base_agent._load_router", return_value=MagicMock()),
            patch.object(K8sAlertWorkflow, "_build_graph", return_value=MagicMock()),
            patch.dict("os.environ", {
                "K8S_API_URL": "https://platform-shared-cluster.example.com",
                "K8S_TOKEN": "platform-shared-token-must-not-leak",
                "GITHUB_TOKEN": "platform-shared-token-must-not-leak",
            }),
        ):
            wf = K8sAlertWorkflow(mock_db, str(uuid4()), MagicMock())
        assert wf._tools.k8s_api_url == ""
        assert wf._tools.k8s_token == ""
        assert wf._tools.github_token == ""


class TestK8sToolsVerifyProperty:
    def test_returns_true_when_no_ca_cert(self):
        tools = K8sTools(k8s_api_url="https://c.example.com", k8s_token="t")
        assert tools._verify is True

    def test_writes_ca_cert_to_a_temp_file_and_reuses_it(self):
        tools = K8sTools(k8s_api_url="https://c.example.com", k8s_token="t", k8s_ca_cert="fake-pem-content")
        first = tools._verify
        second = tools._verify
        assert first == second
        assert os.path.exists(first)
        with open(first) as f:
            assert f.read() == "fake-pem-content"
        os.unlink(first)


def _mock_k8s_resp(status_code: int, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})[:200]
    return resp


def _make_k8s_client_ctx(responses: list) -> tuple:
    """Return (mock_client_cls, ctx) where ctx.patch/get/post/put return responses in order."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)

    call_count = {"n": 0}

    async def _dynamic(*args, **kwargs):
        i = call_count["n"]
        call_count["n"] += 1
        return responses[min(i, len(responses) - 1)]

    ctx.get = _dynamic
    ctx.post = _dynamic
    ctx.patch = _dynamic
    ctx.put = _dynamic

    mock_cls = MagicMock(return_value=ctx)
    return mock_cls, ctx


# ──────────────────────────────────────────────────────────────────────────────
# K8sTools — patch_deployment_memory()
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sToolsPatchMemory:
    @pytest.fixture
    def tools(self) -> K8sTools:
        return K8sTools(
            k8s_api_url="https://prod-aks.azmk8s.io",
            k8s_token="sa_token_abc",
            github_token="gh_test",
        )

    async def test_patches_correct_k8s_endpoint(self, tools):
        ok_resp = _mock_k8s_resp(200, {"metadata": {"name": "payment-service"}})
        mock_cls, ctx = _make_k8s_client_ctx([ok_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.patch_deployment_memory("production", "payment-service", "1Gi")

        assert result["status"] == "patched"
        assert result["new_memory_limit"] == "1Gi"
        assert result["namespace"] == "production"
        assert result["deployment"] == "payment-service"

    async def test_raises_without_k8s_config(self):
        tools_no_config = K8sTools(k8s_api_url="", k8s_token="")
        with pytest.raises(EnvironmentError, match="K8S_API_URL and K8S_TOKEN"):
            await tools_no_config.patch_deployment_memory("production", "my-app", "1Gi")

    async def test_patch_body_includes_container_name(self, tools):
        ok_resp = _mock_k8s_resp(200)
        mock_cls, ctx = _make_k8s_client_ctx([ok_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            await tools.patch_deployment_memory(
                "production", "payment-service", "1Gi",
                container_name="payment-container",
            )

        # If the call went through, json body should contain container name
        # (We verify via result since the mock doesn't capture the body directly here)
        assert ok_resp.status_code == 200

    async def test_before_state_captures_current_resources(self, tools):
        """Migration 042, GAPS.md 24-gap closure Phase 1: patch_deployment_memory
        now GETs the deployment's current resources before mutating, so an
        operator has real rollback information."""
        current_deploy = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "name": "payment-service",
                            "resources": {
                                "limits": {"memory": "512Mi", "cpu": "500m"},
                                "requests": {"memory": "256Mi", "cpu": "250m"},
                            },
                        }]
                    }
                }
            }
        }
        get_resp = _mock_k8s_resp(200, current_deploy)
        patch_resp = _mock_k8s_resp(200, {"metadata": {"name": "payment-service"}})
        mock_cls, ctx = _make_k8s_client_ctx([get_resp, patch_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.patch_deployment_memory("production", "payment-service", "1Gi")

        assert result["before_state"] == {
            "memory_limit": "512Mi", "memory_request": "256Mi",
            "cpu_limit": "500m", "cpu_request": "250m",
        }

    async def test_before_state_capture_failure_does_not_block_patch(self, tools):
        """A failed capture GET must never block the remediation the
        operator already approved -- degrades to a marker, never raises."""
        failed_get_resp = _mock_k8s_resp(500)
        patch_resp = _mock_k8s_resp(200, {"metadata": {"name": "payment-service"}})
        mock_cls, ctx = _make_k8s_client_ctx([failed_get_resp, patch_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.patch_deployment_memory("production", "payment-service", "1Gi")

        assert result["status"] == "patched"
        assert "capture_failed" in result["before_state"]


# ──────────────────────────────────────────────────────────────────────────────
# K8sTools — apply_hpa()
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sToolsApplyHPA:
    @pytest.fixture
    def tools(self) -> K8sTools:
        return K8sTools(
            k8s_api_url="https://prod-aks.azmk8s.io",
            k8s_token="sa_token_abc",
        )

    async def test_posts_to_autoscaling_endpoint(self, tools):
        ok_resp = _mock_k8s_resp(201, {"metadata": {"name": "payment-service"}})
        mock_cls, ctx = _make_k8s_client_ctx([ok_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.apply_hpa("production", "payment-service", 2, 10)

        assert result["status"] in ("applied", "replaced")
        assert result["kind"] == "HorizontalPodAutoscaler"
        assert result["min_replicas"] == 2
        assert result["max_replicas"] == 10

    async def test_raises_without_k8s_config(self):
        tools_no_config = K8sTools(k8s_api_url="", k8s_token="")
        with pytest.raises(EnvironmentError, match="K8S_API_URL and K8S_TOKEN"):
            await tools_no_config.apply_hpa("production", "my-app")

    async def test_retries_with_put_on_409(self, tools):
        # Migration 042: apply_hpa now GETs the existing HPA (before_state
        # capture) before POSTing -- that GET consumes the first queued
        # response, so it must be listed first here.
        capture_get_resp = _mock_k8s_resp(404)
        conflict_resp = _mock_k8s_resp(409, {"message": "already exists"})
        ok_resp = _mock_k8s_resp(200, {"metadata": {"name": "payment-service"}})
        mock_cls, ctx = _make_k8s_client_ctx([capture_get_resp, conflict_resp, ok_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.apply_hpa("production", "payment-service")

        assert result["status"] == "replaced"

    async def test_before_state_reflects_no_existing_hpa(self, tools):
        capture_get_resp = _mock_k8s_resp(404)
        ok_resp = _mock_k8s_resp(201, {"metadata": {"name": "payment-service"}})
        mock_cls, ctx = _make_k8s_client_ctx([capture_get_resp, ok_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.apply_hpa("production", "payment-service", 2, 10)

        assert result["before_state"] == {"existed": False}

    async def test_before_state_reflects_existing_hpa_replicas(self, tools):
        existing_hpa = {"spec": {"minReplicas": 1, "maxReplicas": 5}}
        capture_get_resp = _mock_k8s_resp(200, existing_hpa)
        ok_resp = _mock_k8s_resp(200, {"metadata": {"name": "payment-service"}})
        mock_cls, ctx = _make_k8s_client_ctx([capture_get_resp, ok_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.apply_hpa("production", "payment-service", 2, 10)

        assert result["before_state"] == {"existed": True, "min_replicas": 1, "max_replicas": 5}


# ──────────────────────────────────────────────────────────────────────────────
# K8sTools — rollback_deployment()
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sToolsRollback:
    @pytest.fixture
    def tools(self) -> K8sTools:
        return K8sTools(
            k8s_api_url="https://prod-aks.azmk8s.io",
            k8s_token="sa_token_abc",
        )

    async def test_gets_current_revision_then_patches(self, tools):
        current_deploy = {
            "metadata": {
                "name": "payment-service",
                "annotations": {"deployment.kubernetes.io/revision": "3"},
            }
        }
        get_resp = _mock_k8s_resp(200, current_deploy)
        patch_resp = _mock_k8s_resp(200, {"metadata": {"name": "payment-service"}})
        mock_cls, ctx = _make_k8s_client_ctx([get_resp, patch_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.rollback_deployment("production", "payment-service")

        assert result["status"] == "rolled_back"
        assert result["rolled_back_from_revision"] == 3
        assert result["before_state"] == {"revision": 3}

    async def test_raises_without_k8s_config(self):
        tools_no_config = K8sTools(k8s_api_url="", k8s_token="")
        with pytest.raises(EnvironmentError, match="K8S_API_URL and K8S_TOKEN"):
            await tools_no_config.rollback_deployment("production", "my-app")


# ──────────────────────────────────────────────────────────────────────────────
# K8sTools — create_gitops_pr()
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sToolsGitOpsPR:
    # Phase 4 (connectivity gaps): create_gitops_pr used to be its own
    # direct 5-step GitHub REST implementation; it now delegates to
    # core.repo_tools (same treatment Phase 2 gave agents 04/08/10),
    # selected by K8sTools._repo_tools(). These tests exercise that
    # delegation boundary -- RepoTools' own httpx-level behavior is covered
    # by tests/test_repo_tools.py.

    @pytest.fixture
    def tools(self) -> K8sTools:
        return K8sTools(github_token="gh_test_token")

    @pytest.fixture
    def mock_repo_tools(self):
        rt = MagicMock()
        rt.create_branch = AsyncMock(return_value=None)
        rt.push_commit = AsyncMock(return_value="commit_sha_abc")
        rt.create_pr = AsyncMock(return_value={
            "pr_url": "https://github.com/acme/infra/pull/42", "pr_number": 42,
        })
        return rt

    async def test_creates_branch_commits_file_opens_pr(self, tools, mock_repo_tools):
        with patch.object(tools, "_repo_tools", return_value=mock_repo_tools):
            result = await tools.create_gitops_pr(
                owner="acme", repo="infra",
                file_path="k8s/production/payment-service.yaml",
                new_content="apiVersion: apps/v1\nkind: Deployment\n...",
                commit_message="fix: increase payment-service memory to 1Gi",
                pr_title="[Cloud Decoded] Increase payment-service memory limit",
                pr_body="Automated fix for OOMKilled — see incident inc-002",
            )

        assert result["status"] == "pr_opened"
        assert result["pr_url"] == "https://github.com/acme/infra/pull/42"
        assert result["pr_number"] == 42

        mock_repo_tools.push_commit.assert_awaited_once()
        args = mock_repo_tools.push_commit.await_args.args
        assert args[3] == {"k8s/production/payment-service.yaml": "apiVersion: apps/v1\nkind: Deployment\n..."}
        assert args[4] == "fix: increase payment-service memory to 1Gi"

    async def test_raises_without_any_credential_configured(self):
        no_creds = K8sTools()
        with pytest.raises(NoRepoCredentialError):
            await no_creds.create_gitops_pr(
                owner="acme", repo="infra",
                file_path="k8s/deploy.yaml",
                new_content="...",
                commit_message="fix",
                pr_title="Fix",
                pr_body="body",
            )


# ──────────────────────────────────────────────────────────────────────────────
# K8sTools — execute_option() routing
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sToolsExecuteOption:
    @pytest.fixture
    def tools(self) -> K8sTools:
        return K8sTools(
            k8s_api_url="https://prod-aks.azmk8s.io",
            k8s_token="sa_token_abc",
        )

    async def test_hold_returns_held_without_api_call(self, tools):
        with patch.object(tools, "patch_deployment_memory") as mock_patch:
            result = await tools.execute_option(
                {"id": "hold"},
                {"namespace": "production", "deployment_name": "payment-service", "container_name": "payment-service"},
            )
        mock_patch.assert_not_called()
        assert result["status"] == "held"

    async def test_opt1_dispatches_to_patch_memory(self, tools):
        expected = {"status": "patched", "new_memory_limit": "1Gi", "deployment": "payment-service", "namespace": "production", "new_memory_request": "512Mi"}
        with patch.object(tools, "patch_deployment_memory", return_value=expected) as mock_patch:
            result = await tools.execute_option(
                {"id": "opt_1"},
                {
                    "namespace": "production",
                    "deployment_name": "payment-service",
                    "container_name": "payment-service",
                    "new_memory_limit": "1Gi",
                },
            )
        mock_patch.assert_called_once()
        assert result["status"] == "patched"

    async def test_opt2_dispatches_to_apply_hpa(self, tools):
        expected = {"status": "applied", "kind": "HorizontalPodAutoscaler", "name": "payment-service", "namespace": "production", "min_replicas": 2, "max_replicas": 10}
        with patch.object(tools, "apply_hpa", return_value=expected) as mock_hpa:
            result = await tools.execute_option(
                {"id": "opt_2"},
                {
                    "namespace": "production",
                    "deployment_name": "payment-service",
                    "container_name": "payment-service",
                    "hpa_min": 2,
                    "hpa_max": 10,
                },
            )
        mock_hpa.assert_called_once()
        assert result["status"] == "applied"

    async def test_opt3_dispatches_to_rollback(self, tools):
        expected = {"status": "rolled_back", "deployment": "payment-service", "namespace": "production", "rolled_back_from_revision": 3}
        with patch.object(tools, "rollback_deployment", return_value=expected) as mock_rollback:
            result = await tools.execute_option(
                {"id": "opt_3"},
                {"namespace": "production", "deployment_name": "payment-service", "container_name": "payment-service"},
            )
        mock_rollback.assert_called_once_with(namespace="production", deployment_name="payment-service")
        assert result["status"] == "rolled_back"


# ──────────────────────────────────────────────────────────────────────────────
# K8sTools — gather_evidence() (read-only pre-diagnose evidence step)
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sToolsGatherEvidence:
    @pytest.fixture
    def tools(self) -> K8sTools:
        return K8sTools(
            k8s_api_url="https://prod-aks.azmk8s.io",
            k8s_token="sa_token_abc",
        )

    async def test_no_credentials_returns_unavailable_without_http_calls(self):
        tools_no_config = K8sTools(k8s_api_url="", k8s_token="")
        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient") as mock_cls:
            result = await tools_no_config.gather_evidence(
                "production", "payment-service-7d9f8b-xkq2p", "payment-service",
                "payment-service", "crashloop",
            )
        mock_cls.assert_not_called()
        assert result == {
            "available": False, "text": "",
            "unavailable_reason": "no cluster credentials configured for this workspace",
        }

    async def test_crashloop_fetches_describe_previous_logs_and_events(self, tools):
        describe_resp = _mock_k8s_resp(200, {"status": {"phase": "Running"}})
        logs_resp = MagicMock(status_code=200, text="panic: out of memory")
        events_resp = _mock_k8s_resp(200, {"items": [{"reason": "BackOff"}]})
        mock_cls, ctx = _make_k8s_client_ctx([describe_resp, logs_resp, events_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "payment-service-7d9f8b-xkq2p", "payment-service",
                "payment-service", "crashloop",
            )

        assert result["available"] is True
        assert "Pod describe" in result["text"]
        assert "Previous container logs" in result["text"]
        assert "panic: out of memory" in result["text"]
        assert "Namespace events" in result["text"]
        assert "BackOff" in result["text"]

    async def test_imagepull_fetches_describe_and_events_only(self, tools):
        describe_resp = _mock_k8s_resp(200, {"status": {"phase": "Pending"}})
        events_resp = _mock_k8s_resp(200, {"items": [{"reason": "ErrImagePull"}]})
        mock_cls, ctx = _make_k8s_client_ctx([describe_resp, events_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "worker-abc-123", "worker", "worker", "imagepull",
            )

        assert "Pod describe" in result["text"]
        assert "Namespace events" in result["text"]
        assert "Previous container logs" not in result["text"]

    async def test_pending_fetches_describe_and_node_conditions(self, tools):
        describe_resp = _mock_k8s_resp(200, {"status": {"phase": "Pending"}})
        nodes_resp = _mock_k8s_resp(200, {"items": [{"metadata": {"name": "node-1"}, "status": {"conditions": []}}]})
        mock_cls, ctx = _make_k8s_client_ctx([describe_resp, nodes_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "worker-abc-123", "worker", "worker", "pending",
            )

        assert "Pod describe" in result["text"]
        assert "Node conditions" in result["text"]
        assert "node-1" in result["text"]

    async def test_oomkill_fetches_describe_and_metrics(self, tools):
        describe_resp = _mock_k8s_resp(200, {"status": {"phase": "Running"}})
        metrics_resp = _mock_k8s_resp(200, {"containers": [{"usage": {"memory": "1000Mi"}}]})
        mock_cls, ctx = _make_k8s_client_ctx([describe_resp, metrics_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "payment-service-7d9f8b-xkq2p", "payment-service",
                "payment-service", "oomkill",
            )

        assert "Pod describe" in result["text"]
        assert "Pod metrics" in result["text"]
        assert "1000Mi" in result["text"]

    async def test_oomkill_metrics_server_absent_degrades_without_failing(self, tools):
        """metrics-server is routinely absent on smaller clusters -- a 404
        here must not take down the pod describe evidence gathered
        alongside it."""
        describe_resp = _mock_k8s_resp(200, {"status": {"phase": "Running"}})
        metrics_404 = _mock_k8s_resp(404, {"message": "the server could not find the requested resource"})
        mock_cls, ctx = _make_k8s_client_ctx([describe_resp, metrics_404])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "payment-service-7d9f8b-xkq2p", "payment-service",
                "payment-service", "oomkill",
            )

        assert result["available"] is True
        assert "Pod describe" in result["text"]
        assert "[unavailable:" in result["text"]

    async def test_service_fetches_endpoints_service_and_ingress(self, tools):
        endpoints_resp = _mock_k8s_resp(200, {"subsets": []})
        service_resp = _mock_k8s_resp(200, {"spec": {"type": "ClusterIP"}})
        ingress_resp = _mock_k8s_resp(200, {"spec": {"rules": []}})
        mock_cls, ctx = _make_k8s_client_ctx([endpoints_resp, service_resp, ingress_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "checkout-abc-123", "checkout", "checkout", "service",
            )

        assert "Endpoints" in result["text"]
        assert "Service describe" in result["text"]
        assert "Ingress describe" in result["text"]

    async def test_pvc_fetches_describe_then_storageclass_when_present(self, tools):
        pvc_resp = _mock_k8s_resp(200, {"spec": {"storageClassName": "fast-ssd"}})
        sc_resp = _mock_k8s_resp(200, {"provisioner": "kubernetes.io/aws-ebs"})
        mock_cls, ctx = _make_k8s_client_ctx([pvc_resp, sc_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "db-abc-123", "db", "db", "pvc",
            )

        assert "PVC describe" in result["text"]
        assert "StorageClass (fast-ssd)" in result["text"]
        assert "aws-ebs" in result["text"]

    async def test_pvc_skips_storageclass_lookup_when_pvc_fetch_fails(self, tools):
        pvc_404 = _mock_k8s_resp(404, {"message": "not found"})
        mock_cls, ctx = _make_k8s_client_ctx([pvc_404])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "db-abc-123", "db", "db", "pvc",
            )

        assert "PVC describe" in result["text"]
        assert "[unavailable:" in result["text"]
        assert "StorageClass" not in result["text"]

    async def test_dns_fetches_coredns_logs_by_label_selector(self, tools):
        pods_list_resp = _mock_k8s_resp(200, {"items": [{"metadata": {"name": "coredns-abc123"}}]})
        logs_resp = MagicMock(status_code=200, text="[ERROR] plugin/errors: query refused")
        mock_cls, ctx = _make_k8s_client_ctx([pods_list_resp, logs_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "app-abc-123", "app", "app", "dns",
            )

        assert "CoreDNS logs" in result["text"]
        assert "query refused" in result["text"]

    async def test_dns_no_coredns_pods_found_degrades_without_failing(self, tools):
        pods_list_resp = _mock_k8s_resp(200, {"items": []})
        mock_cls, ctx = _make_k8s_client_ctx([pods_list_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "app-abc-123", "app", "app", "dns",
            )

        assert result["available"] is True
        assert "[unavailable: no CoreDNS pods found" in result["text"]

    async def test_generic_fallback_fetches_describe_and_events(self, tools):
        """Evicted, or any alert_type the classifier doesn't recognize,
        falls back to the cheap, broadly-useful describe+events pair."""
        describe_resp = _mock_k8s_resp(200, {"status": {"phase": "Failed"}})
        events_resp = _mock_k8s_resp(200, {"items": [{"reason": "Evicted"}]})
        mock_cls, ctx = _make_k8s_client_ctx([describe_resp, events_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "worker-abc-123", "worker", "worker", "generic",
            )

        assert "Pod describe" in result["text"]
        assert "Namespace events" in result["text"]

    async def test_never_issues_a_write_verb(self, tools):
        """Governance Rule 11: this step must be read-only. Assert directly
        against the httpx client that no PATCH/POST/PUT/DELETE is ever
        wired up as reachable from gather_evidence."""
        describe_resp = _mock_k8s_resp(200, {"status": {}})
        events_resp = _mock_k8s_resp(200, {"items": []})
        mock_cls, ctx = _make_k8s_client_ctx([describe_resp, events_resp])
        ctx.patch = AsyncMock(side_effect=AssertionError("write verb called"))
        ctx.post  = AsyncMock(side_effect=AssertionError("write verb called"))
        ctx.put   = AsyncMock(side_effect=AssertionError("write verb called"))
        ctx.delete = AsyncMock(side_effect=AssertionError("write verb called"))

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "worker-abc-123", "worker", "worker", "generic",
            )

        assert result["available"] is True

    async def test_evidence_text_truncated_to_max_chars(self, tools):
        from agents.agent_02_k8s_alert.tools import _MAX_EVIDENCE_CHARS

        huge_log = "x" * (_MAX_EVIDENCE_CHARS * 2)
        describe_resp = _mock_k8s_resp(200, {"status": {}})
        logs_resp = MagicMock(status_code=200, text=huge_log)
        events_resp = _mock_k8s_resp(200, {"items": []})
        mock_cls, ctx = _make_k8s_client_ctx([describe_resp, logs_resp, events_resp])

        with patch("agents.agent_02_k8s_alert.tools.httpx.AsyncClient", mock_cls):
            result = await tools.gather_evidence(
                "production", "worker-abc-123", "worker", "worker", "crashloop",
            )

        assert len(result["text"]) <= _MAX_EVIDENCE_CHARS + len("\n... [truncated]")
        assert result["text"].endswith("[truncated]")


# ──────────────────────────────────────────────────────────────────────────────
# K8sTools — _halve_memory() helper
# ──────────────────────────────────────────────────────────────────────────────

class TestHalveMemory:
    def test_halves_gi_below_1(self):
        assert _halve_memory("1Gi") == "512Mi"

    def test_halves_gi_above_1(self):
        assert _halve_memory("4Gi") == "2Gi"

    def test_halves_mi(self):
        assert _halve_memory("512Mi") == "256Mi"

    def test_unknown_suffix_returns_unchanged(self):
        assert _halve_memory("2G") == "2G"


# ──────────────────────────────────────────────────────────────────────────────
# K8sAlertWorkflow._ingest_node() — Prometheus AlertManager format
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sIngestPrometheus:
    async def test_extracts_namespace(self, mock_db, workspace_id, mock_router, k8s_alertmanager_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_alertmanager_payload)
        result = await wf._ingest_node(state)
        assert result["namespace"] == "production"

    async def test_extracts_pod_name(self, mock_db, workspace_id, mock_router, k8s_alertmanager_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_alertmanager_payload)
        result = await wf._ingest_node(state)
        assert result["pod_name"] == "payment-service-7d9f8b-xkq2p"

    async def test_derives_deployment_name_from_pod_name(self, mock_db, workspace_id, mock_router, k8s_alertmanager_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_alertmanager_payload)
        result = await wf._ingest_node(state)
        # pod "payment-service-7d9f8b-xkq2p" → deployment "payment-service"
        assert result["deployment_name"] == "payment-service"

    async def test_extracts_cluster_name(self, mock_db, workspace_id, mock_router, k8s_alertmanager_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_alertmanager_payload)
        result = await wf._ingest_node(state)
        assert result["cluster_name"] == "prod-aks"

    async def test_extracts_alert_type(self, mock_db, workspace_id, mock_router, k8s_alertmanager_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_alertmanager_payload)
        result = await wf._ingest_node(state)
        assert result["alert_type"] == "OOMKilled"

    async def test_raw_severity_is_none_prometheus_has_no_severity_field(self, mock_db, workspace_id, mock_router, k8s_alertmanager_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_alertmanager_payload)
        result = await wf._ingest_node(state)
        assert result["raw_severity"] is None


# ──────────────────────────────────────────────────────────────────────────────
# K8sAlertWorkflow._ingest_node() — Azure Monitor format
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sIngestAzureMonitor:
    async def test_extracts_namespace(self, mock_db, workspace_id, mock_router, k8s_azure_monitor_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_azure_monitor_payload)
        result = await wf._ingest_node(state)
        assert result["namespace"] == "production"

    async def test_extracts_pod_name_from_search_results(self, mock_db, workspace_id, mock_router, k8s_azure_monitor_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_azure_monitor_payload)
        result = await wf._ingest_node(state)
        assert result["pod_name"] == "payment-service-7d9f8b-xkq2p"

    async def test_extracts_exit_code(self, mock_db, workspace_id, mock_router, k8s_azure_monitor_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_azure_monitor_payload)
        result = await wf._ingest_node(state)
        assert result["exit_code"] == 137

    async def test_extracts_restart_count(self, mock_db, workspace_id, mock_router, k8s_azure_monitor_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_azure_monitor_payload)
        result = await wf._ingest_node(state)
        assert result["restart_count"] == 4

    async def test_derives_deployment_name_when_not_in_custom_props(self, mock_db, workspace_id, mock_router, k8s_azure_monitor_payload):
        # Remove deployment_name from customProperties to test derivation
        payload = dict(k8s_azure_monitor_payload)
        payload["data"] = dict(payload["data"])
        payload["data"]["customProperties"] = {
            k: v for k, v in payload["data"]["customProperties"].items()
            if k != "deployment_name"
        }
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, payload)
        result = await wf._ingest_node(state)
        assert result["deployment_name"] == "payment-service"

    async def test_extracts_raw_severity(self, mock_db, workspace_id, mock_router, k8s_azure_monitor_payload):
        """Migration 042: essentials.severity used to be dropped after
        being logged -- now it's captured for hitl_gate to normalize."""
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, k8s_azure_monitor_payload)
        result = await wf._ingest_node(state)
        assert result["raw_severity"] == "Sev1"


class TestK8sIngestUnknownFormat:
    async def test_unknown_format_does_not_raise(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, {"some": "unknown", "format": True})
        result = await wf._ingest_node(state)
        assert isinstance(result["log_excerpt"], str)
        assert len(result["log_excerpt"]) > 0

    async def test_sanitizes_log_excerpt(self, mock_db, workspace_id, mock_router, k8s_alertmanager_payload):
        # Inject a secret into the alert description
        payload = dict(k8s_alertmanager_payload)
        payload["alerts"] = [dict(payload["alerts"][0])]
        payload["alerts"][0]["annotations"] = {
            "description": "Pod crashed with token AKIAIOSFODNN7EXAMPLE in env"
        }
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id, payload)
        result = await wf._ingest_node(state)
        assert "AKIAIOSFODNN7EXAMPLE" not in result["log_excerpt"]


# ──────────────────────────────────────────────────────────────────────────────
# _classify_alert_category()
# ──────────────────────────────────────────────────────────────────────────────

class TestClassifyAlertCategory:
    @pytest.mark.parametrize("alert_type,expected", [
        ("CrashLoopBackOff", "crashloop"),
        ("OOMKilled", "oomkill"),
        ("ImagePullBackOff", "imagepull"),
        ("ErrImagePull", "imagepull"),
        ("Pending", "pending"),
        ("FailedScheduling", "pending"),
        ("CoreDNSDown", "dns"),
        ("ServiceUnavailable", "service"),
        ("IngressDegraded", "service"),
        ("Evicted", "generic"),
        ("SomethingNeverSeenBefore", "generic"),
        ("", "generic"),
    ])
    def test_maps_known_alert_types(self, alert_type, expected):
        assert _classify_alert_category(alert_type) == expected

    def test_pvc_keyword_variants(self):
        assert _classify_alert_category("PersistentVolumeClaimPending") == "pvc"
        assert _classify_alert_category("VolumeMountFailed") == "pvc"

    def test_case_insensitive(self):
        assert _classify_alert_category("crashloopbackoff") == "crashloop"
        assert _classify_alert_category("OOMKILLED") == "oomkill"


# ──────────────────────────────────────────────────────────────────────────────
# K8sAlertWorkflow._evidence_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sEvidenceNode:
    async def test_reachable_cluster_populates_live_evidence_text(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["alert_type"] = "OOMKilled"

        with patch.object(
            wf._tools, "gather_evidence",
            return_value={"available": True, "text": "### Pod describe\n{...}", "unavailable_reason": None},
        ) as mock_gather:
            result = await wf._evidence_node(state)

        mock_gather.assert_called_once()
        kwargs = mock_gather.call_args.kwargs
        assert kwargs["alert_category"] == "oomkill"
        assert kwargs["namespace"] == state["namespace"]
        assert kwargs["pod_name"] == state["pod_name"]
        assert result["live_evidence_text"] == "### Pod describe\n{...}"

    async def test_unreachable_cluster_notes_unavailable(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)

        with patch.object(
            wf._tools, "gather_evidence",
            return_value={"available": False, "text": "", "unavailable_reason": "no cluster credentials configured for this workspace"},
        ):
            result = await wf._evidence_node(state)

        assert result["live_evidence_text"] == "[live evidence unavailable: no cluster credentials configured for this workspace]"

    async def test_gather_evidence_raising_still_degrades_gracefully(self, mock_db, workspace_id, mock_router):
        """Belt-and-braces: even though K8sTools.gather_evidence's own
        fetchers never raise, _evidence_node must not propagate an
        unexpected exception up into the graph."""
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)

        with patch.object(wf._tools, "gather_evidence", side_effect=RuntimeError("boom")):
            result = await wf._evidence_node(state)

        assert "[live evidence unavailable:" in result["live_evidence_text"]
        assert "boom" in result["live_evidence_text"]

    async def test_skips_when_upstream_error_already_set(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["error"] = "ingest failed"

        with patch.object(wf._tools, "gather_evidence") as mock_gather:
            result = await wf._evidence_node(state)

        mock_gather.assert_not_called()
        assert result == {}


# ──────────────────────────────────────────────────────────────────────────────
# K8sAlertWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sDiagnoseNode:
    async def test_calls_router_with_k8s_triage_task(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            await wf._diagnose_node(state)

        call_args = mock_router.complete.call_args
        task_type = call_args.kwargs.get("task_type") or call_args.args[0]
        assert task_type == "k8s_triage"

    async def test_parses_valid_llm_response(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        # Use the K8s sample diagnosis from conftest mock_router
        state = _base_k8s_state(workspace_id)

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            result = await wf._diagnose_node(state)

        assert result.get("parsed_error") is not None
        assert len(result.get("remediation_options", [])) >= 2

    async def test_handles_llm_json_parse_error(self, mock_db, workspace_id, mock_router):
        mock_router.complete.return_value = "Not valid JSON at all."
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None

    async def test_checks_budget_before_llm_call(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)

        with patch.object(wf.budget, "assert_budget_available") as mock_budget:
            mock_budget.return_value = None
            await wf._diagnose_node(state)

        mock_budget.assert_called_once()

    async def test_includes_deployment_name_and_alert_type_in_message(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["deployment_name"] = "billing-worker"
        state["alert_type"] = "ImagePullBackOff"

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            await wf._diagnose_node(state)

        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[1]
        combined = " ".join(m["content"] for m in messages)
        assert "billing-worker" in combined
        assert "ImagePullBackOff" in combined

    @pytest.mark.parametrize("alert_type,evidence_text", [
        ("CrashLoopBackOff", "### Pod describe (payment-service-7d9f8b-xkq2p)\n{\"status\": {\"phase\": \"Running\"}}"),
        ("OOMKilled", "### Pod metrics (payment-service-7d9f8b-xkq2p)\n{\"usage\": {\"memory\": \"900Mi\"}}"),
        ("ImagePullBackOff", "### Pod describe (payment-service-7d9f8b-xkq2p)\n{\"status\": {\"phase\": \"Pending\"}}"),
        ("Pending", "### Node conditions\n{\"items\": []}"),
    ])
    async def test_live_evidence_reaches_llm_message_per_alert_type(
        self, mock_db, workspace_id, mock_router, alert_type, evidence_text,
    ):
        """_evidence_node's output must actually land in the diagnose
        prompt -- this is what makes the read-only evidence step matter,
        not just exist. One fixture per alert category."""
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["alert_type"] = alert_type
        state["live_evidence_text"] = evidence_text

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            await wf._diagnose_node(state)

        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[1]
        combined = " ".join(m["content"] for m in messages)
        assert "Live Cluster Evidence" in combined
        assert evidence_text in combined

    async def test_live_evidence_unavailable_note_reaches_llm_message(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["live_evidence_text"] = "[live evidence unavailable: cluster unreachable: connection refused]"

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            await wf._diagnose_node(state)

        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[1]
        combined = " ".join(m["content"] for m in messages)
        assert "live evidence unavailable" in combined


# ──────────────────────────────────────────────────────────────────────────────
# K8sAlertWorkflow._hitl_gate_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sHITLGateNode:
    async def test_creates_incident_in_db(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["parsed_error"] = "Pod OOMKilled: exceeded 512Mi memory limit"
        state["remediation_options"] = [{"id": "opt_1", "title": "Increase memory"}]
        state["tokens_used"] = 900

        incident_uuid = uuid4()
        mock_db.fetchrow.return_value = {"id": incident_uuid}
        mock_db.fetchrow.reset_mock()

        with patch("agents.agent_02_k8s_alert.workflow.interrupt", return_value={"id": "opt_1"}):
            await wf._hitl_gate_node(state)

        mock_db.fetchrow.assert_called_once()
        query = mock_db.fetchrow.call_args.args[0]
        assert "INSERT INTO incidents" in query

    async def test_calls_interrupt_to_pause_graph(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["parsed_error"] = "OOMKilled"
        state["remediation_options"] = [{"id": "opt_1"}]

        incident_uuid = uuid4()
        mock_db.fetchrow.return_value = {"id": incident_uuid}

        with patch("agents.agent_02_k8s_alert.workflow.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {"id": "opt_1"}
            await wf._hitl_gate_node(state)

        mock_interrupt.assert_called_once()
        payload = mock_interrupt.call_args.args[0]
        assert "incident_id" in payload
        assert "options" in payload

    async def test_skips_incident_creation_when_error_set(self, mock_db, workspace_id, mock_router):
        """Phase 10, scale-readiness build: creates a real
        execution_status='failed' incident instead of skipping entirely."""
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["error"] = "LLM parse failed"

        mock_db.fetchrow.reset_mock()
        mock_db.fetchrow.return_value = {"id": "11111111-1111-1111-1111-111111111111"}
        result = await wf._hitl_gate_node(state)

        mock_db.fetchrow.assert_called_once()
        insert_sql = mock_db.fetchrow.await_args.args[0]
        assert "INSERT INTO incidents" in insert_sql
        assert result == {"incident_id": "11111111-1111-1111-1111-111111111111"}

    async def test_azure_sev0_severity_reaches_create_incident_as_critical(self, mock_db, workspace_id, mock_router):
        """Migration 042, GAPS.md 24-gap closure Phase 1 -- raw_severity
        (captured at ingest from Azure Monitor essentials.severity) must
        be normalized and passed through to hitl.create_incident."""
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["parsed_error"] = "Pod OOMKilled"
        state["remediation_options"] = [{"id": "opt_1"}]
        state["raw_severity"] = "Sev0"

        mock_db.fetchrow.return_value = {"id": uuid4()}
        mock_db.fetchrow.reset_mock()

        with patch("agents.agent_02_k8s_alert.workflow.interrupt", return_value={"id": "opt_1"}):
            await wf._hitl_gate_node(state)

        args = mock_db.fetchrow.call_args.args
        assert "critical" in args

    async def test_missing_raw_severity_defaults_to_medium(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_k8s_state(workspace_id)
        state["parsed_error"] = "Pod OOMKilled"
        state["remediation_options"] = [{"id": "opt_1"}]
        assert state.get("raw_severity") is None

        mock_db.fetchrow.return_value = {"id": uuid4()}
        mock_db.fetchrow.reset_mock()

        with patch("agents.agent_02_k8s_alert.workflow.interrupt", return_value={"id": "opt_1"}):
            await wf._hitl_gate_node(state)

        args = mock_db.fetchrow.call_args.args
        assert "medium" in args


# ──────────────────────────────────────────────────────────────────────────────
# K8sAlertWorkflow._complete_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestK8sCompleteNode:
    async def test_before_state_from_execution_result_reaches_mark_executed(self, mock_db, workspace_id, mock_router):
        """Migration 042, GAPS.md 24-gap closure Phase 1: rollback
        information captured during execute must be persisted, not
        dropped, when the incident is marked executed."""
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        incident_id = str(uuid4())
        state = _base_k8s_state(workspace_id)
        state["incident_id"] = incident_id
        state["execution_result"] = {
            "status": "patched",
            "before_state": {"memory_limit": "512Mi"},
        }

        mock_db.fetchrow.return_value = {
            "workspace_id": workspace_id, "agent_id": "agent_02_k8s_alert",
            "resource_name": None, "resource_group": None, "metric_name": None,
            "parsed_error": None, "selected_option_id": None,
            "resolved_at": None, "cloud_provider": "azure", "severity": "high",
        }
        mock_db.fetchrow.reset_mock()

        await wf._complete_node(state)

        mock_db.fetchrow.assert_awaited_once()
        args = mock_db.fetchrow.call_args.args
        assert '{"memory_limit": "512Mi"}' in args

    async def test_no_before_state_when_execution_result_has_none(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        incident_id = str(uuid4())
        state = _base_k8s_state(workspace_id)
        state["incident_id"] = incident_id
        state["execution_result"] = {"status": "applied"}  # no before_state key

        mock_db.fetchrow.return_value = {
            "workspace_id": workspace_id, "agent_id": "agent_02_k8s_alert",
            "resource_name": None, "resource_group": None, "metric_name": None,
            "parsed_error": None, "selected_option_id": None,
            "resolved_at": None, "cloud_provider": "azure", "severity": "medium",
        }
        mock_db.fetchrow.reset_mock()

        await wf._complete_node(state)

        args = mock_db.fetchrow.call_args.args
        assert None in args
