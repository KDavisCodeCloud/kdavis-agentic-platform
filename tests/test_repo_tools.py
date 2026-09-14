"""
tests/test_repo_tools.py
Tests for core/repo_tools.py's GitHubRepoTools and AzureDevOpsRepoTools --
the provider-agnostic five-op interface (item 5's design). GitHub's
implementation was lifted out of agents/agent_08_drift_detection/tools.py's
create_drift_pr; Azure DevOps's is item 5's own new implementation against
the Azure DevOps Git REST API. No live network.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.repo_tools import AzureDevOpsRepoTools, GitHubRepoTools, NoRepoCredentialError, get_repo_tools


def _resp(status_code: int, json_body=None, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body or {}
    r.text = text
    return r


def _client_ctx(mock_client: AsyncMock) -> AsyncMock:
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestGitHubRepoToolsInit:
    def test_raises_without_token(self):
        with pytest.raises(ValueError):
            GitHubRepoTools(token="")


class TestReadFile:
    async def test_returns_decoded_content_on_success(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        content_b64 = base64.b64encode(b"resource {}").decode()
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, {"content": content_b64}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.read_file("acme", "infra", "main.tf", "main")
        assert result == "resource {}"

    async def test_returns_none_on_404(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(404))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.read_file("acme", "infra", "missing.tf", "main")
        assert result is None

    async def test_raises_when_path_is_a_directory(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, [{"name": "a"}]))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.read_file("acme", "infra", "terraform/", "main")


class TestListFiles:
    async def test_returns_file_paths_only(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, [
            {"path": "terraform/main.tf", "type": "file"},
            {"path": "terraform/modules", "type": "dir"},
        ]))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.list_files("acme", "infra", "terraform", "main")
        assert result == ["terraform/main.tf"]

    async def test_returns_empty_list_on_404(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(404))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.list_files("acme", "infra", "nope", "main")
        assert result == []


class TestCreateBranch:
    async def test_creates_branch_from_head_sha(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, {"object": {"sha": "abc123"}}))
        client.post = AsyncMock(return_value=_resp(201))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            await tools.create_branch("acme", "infra", "drift-fix", "main")
        client.post.assert_awaited_once()
        _, kwargs = client.post.await_args
        assert kwargs["json"] == {"ref": "refs/heads/drift-fix", "sha": "abc123"}

    async def test_treats_422_already_exists_as_success(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, {"object": {"sha": "abc123"}}))
        client.post = AsyncMock(return_value=_resp(422))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            await tools.create_branch("acme", "infra", "drift-fix", "main")  # does not raise

    async def test_raises_when_base_ref_not_found(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(404))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.create_branch("acme", "infra", "drift-fix", "does-not-exist")


class TestPushCommit:
    async def test_commits_new_file_without_sha(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(404))  # file doesn't exist yet
        client.put = AsyncMock(return_value=_resp(201, {"commit": {"sha": "deadbeef"}}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            sha = await tools.push_commit("acme", "infra", "drift-fix", {"main.tf": "content"}, "fix drift")
        assert sha == "deadbeef"
        _, kwargs = client.put.await_args
        assert "sha" not in kwargs["json"]

    async def test_commits_existing_file_with_sha(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, {"sha": "old-sha"}))
        client.put = AsyncMock(return_value=_resp(200, {"commit": {"sha": "newsha"}}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            await tools.push_commit("acme", "infra", "drift-fix", {"main.tf": "content"}, "fix drift")
        _, kwargs = client.put.await_args
        assert kwargs["json"]["sha"] == "old-sha"

    async def test_raises_on_commit_failure(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(404))
        client.put = AsyncMock(return_value=_resp(422))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.push_commit("acme", "infra", "drift-fix", {"main.tf": "x"}, "msg")


class TestCreatePR:
    async def test_returns_pr_url_and_number(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(201, {"html_url": "https://github.com/acme/infra/pull/7", "number": 7}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.create_pr("acme", "infra", "drift-fix", "Fix drift", "body")
        assert result == {"pr_url": "https://github.com/acme/infra/pull/7", "pr_number": 7}

    async def test_requests_reviewers_when_given(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(201, {"html_url": "url", "number": 7}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            await tools.create_pr("acme", "infra", "drift-fix", "Fix drift", "body", reviewers=["octocat"])
        assert client.post.await_count == 2

    async def test_raises_on_pr_creation_failure(self):
        tools = GitHubRepoTools(token="ghs_installtok")
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(422, text="validation failed"))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.create_pr("acme", "infra", "drift-fix", "Fix drift", "body")


# ── AzureDevOpsRepoTools ─────────────────────────────────────────────────
# `owner` in every call below is read as the Azure DevOps *project* name
# (see core/repo_tools.py's module docstring); org is bound at construction.

class TestAzureDevOpsRepoToolsInit:
    def test_raises_without_org(self):
        with pytest.raises(ValueError):
            AzureDevOpsRepoTools(org="", pat="pat123")

    def test_raises_without_pat(self):
        with pytest.raises(ValueError):
            AzureDevOpsRepoTools(org="acme-org", pat="")


class TestAzureDevOpsReadFile:
    async def test_returns_content_on_success(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, {"content": "resource {}", "isFolder": False}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.read_file("infra-project", "infra", "main.tf", "main")
        assert result == "resource {}"

    async def test_returns_none_on_404(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(404))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.read_file("infra-project", "infra", "missing.tf", "main")
        assert result is None

    async def test_raises_when_path_is_a_folder(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, {"isFolder": True}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.read_file("infra-project", "infra", "terraform/", "main")


class TestAzureDevOpsListFiles:
    async def test_returns_blob_paths_only(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, {"value": [
            {"path": "/terraform", "gitObjectType": "tree"},
            {"path": "/terraform/main.tf", "gitObjectType": "blob"},
            {"path": "/terraform/modules", "gitObjectType": "tree"},
        ]}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.list_files("infra-project", "infra", "/terraform", "main")
        assert result == ["/terraform/main.tf"]

    async def test_returns_empty_list_on_404(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(404))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.list_files("infra-project", "infra", "/nope", "main")
        assert result == []


class TestAzureDevOpsCreateBranch:
    async def test_creates_branch_from_head_object_id(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, {"value": []}),                                 # name doesn't exist yet
            _resp(200, {"value": [{"objectId": "abc123"}]}),            # from_ref head
        ])
        client.post = AsyncMock(return_value=_resp(200, {"value": [{"success": True}]}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            await tools.create_branch("infra-project", "infra", "drift-fix", "main")
        _, kwargs = client.post.await_args
        assert kwargs["json"][0]["name"] == "refs/heads/drift-fix"
        assert kwargs["json"][0]["newObjectId"] == "abc123"

    async def test_idempotent_when_branch_already_exists(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, {"value": [{"objectId": "existing"}]}))
        client.post = AsyncMock()
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            await tools.create_branch("infra-project", "infra", "drift-fix", "main")  # does not raise
        client.post.assert_not_awaited()

    async def test_raises_when_base_ref_not_found(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, {"value": []}),  # name doesn't exist
            _resp(200, {"value": []}),  # from_ref also doesn't exist
        ])
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.create_branch("infra-project", "infra", "drift-fix", "does-not-exist")

    async def test_raises_when_push_rejected(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, {"value": []}),
            _resp(200, {"value": [{"objectId": "abc123"}]}),
        ])
        client.post = AsyncMock(return_value=_resp(200, {"value": [{"success": False, "customMessage": "stale"}]}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.create_branch("infra-project", "infra", "drift-fix", "main")


class TestAzureDevOpsPushCommit:
    async def test_commits_new_file_as_add(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, {"value": [{"objectId": "branch-head"}]}),  # ref lookup for push
            _resp(404),                                             # file doesn't exist yet
        ])
        client.post = AsyncMock(return_value=_resp(201, {"commits": [{"commitId": "deadbeef"}]}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            sha = await tools.push_commit("infra-project", "infra", "drift-fix", {"main.tf": "content"}, "fix drift")
        assert sha == "deadbeef"
        _, kwargs = client.post.await_args
        assert kwargs["json"]["commits"][0]["changes"][0]["changeType"] == "add"

    async def test_commits_existing_file_as_edit(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, {"value": [{"objectId": "branch-head"}]}),
            _resp(200, {"content": "old content", "isFolder": False}),
        ])
        client.post = AsyncMock(return_value=_resp(201, {"commits": [{"commitId": "newsha"}]}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            await tools.push_commit("infra-project", "infra", "drift-fix", {"main.tf": "content"}, "fix drift")
        _, kwargs = client.post.await_args
        assert kwargs["json"]["commits"][0]["changes"][0]["changeType"] == "edit"

    async def test_raises_when_branch_not_found(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, {"value": []}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.push_commit("infra-project", "infra", "drift-fix", {"main.tf": "x"}, "msg")

    async def test_raises_on_push_failure(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, {"value": [{"objectId": "branch-head"}]}),
            _resp(404),
        ])
        client.post = AsyncMock(return_value=_resp(422, text="validation failed"))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.push_commit("infra-project", "infra", "drift-fix", {"main.tf": "x"}, "msg")


class TestAzureDevOpsCreatePR:
    async def test_returns_pr_url_and_number(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(201, {"pullRequestId": 42}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.create_pr("infra-project", "infra", "drift-fix", "Fix drift", "body")
        assert result["pr_number"] == 42
        assert result["pr_url"].endswith("/pullrequest/42")

    async def test_degrades_gracefully_when_reviewers_given(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(201, {"pullRequestId": 42}))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            result = await tools.create_pr(
                "infra-project", "infra", "drift-fix", "Fix drift", "body", reviewers=["someone@acme.com"]
            )
        assert result["pr_number"] == 42  # PR still opens -- reviewers just can't be set without identity resolution
        assert client.post.await_count == 1  # no second call attempted for reviewers

    async def test_raises_on_pr_creation_failure(self):
        tools = AzureDevOpsRepoTools(org="acme-org", pat="pat123")
        client = AsyncMock()
        client.post = AsyncMock(return_value=_resp(422, text="validation failed"))
        with patch("core.repo_tools.httpx.AsyncClient", return_value=_client_ctx(client)):
            with pytest.raises(RuntimeError):
                await tools.create_pr("infra-project", "infra", "drift-fix", "Fix drift", "body")


# ── get_repo_tools() provider-selection factory (Phase 2) ──────────────────

class TestGetRepoTools:
    def test_returns_github_repo_tools_when_github_token_given(self):
        tools = get_repo_tools(github_token="ghs_installtok")
        assert isinstance(tools, GitHubRepoTools)

    def test_returns_azure_devops_repo_tools_when_ado_creds_given(self):
        tools = get_repo_tools(azure_devops_token="pat123", azure_devops_org="acme-org")
        assert isinstance(tools, AzureDevOpsRepoTools)

    def test_github_takes_priority_when_both_configured(self):
        tools = get_repo_tools(
            github_token="ghs_installtok", azure_devops_token="pat123", azure_devops_org="acme-org",
        )
        assert isinstance(tools, GitHubRepoTools)

    def test_raises_when_neither_configured(self):
        with pytest.raises(NoRepoCredentialError):
            get_repo_tools()

    def test_raises_when_azure_devops_token_given_without_org(self):
        with pytest.raises(NoRepoCredentialError):
            get_repo_tools(azure_devops_token="pat123")
