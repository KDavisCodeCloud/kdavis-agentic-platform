"""
tests/test_repo_tools.py
Tests for core/repo_tools.py's GitHubRepoTools -- the provider-agnostic
five-op interface (item 5's design), GitHub implementation lifted out of
agents/agent_08_drift_detection/tools.py's create_drift_pr. No live network.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.repo_tools import GitHubRepoTools


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
