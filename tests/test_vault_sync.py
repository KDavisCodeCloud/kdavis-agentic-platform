"""
tests/test_vault_sync.py
Tests for obsidian/vault_sync.py — push_sop()

What this file validates:
  - Missing OBSIDIAN_VAULT_PATH raises rather than silently writing nowhere
  - push_sop() writes to {vault}/KDavis Platform/SOPs/{agent_name}/{date}-{task}.md
  - task_summary is slugified into the filename
"""

from datetime import datetime, timezone

import pytest

from obsidian.vault_sync import push_sop


class TestMissingVaultPath:
    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        with pytest.raises(EnvironmentError):
            push_sop("content", "research_agent", "some task")


class TestPushSop:
    def test_writes_expected_path_and_content(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))

        result_path = push_sop("# SOP content", "research_agent", "Freight Invoice Research!")

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        expected = tmp_path / "KDavis Platform" / "SOPs" / "research_agent" / f"{today}-freight-invoice-research.md"

        assert result_path == str(expected)
        assert expected.read_text() == "# SOP content"

    def test_creates_nested_folders(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
        push_sop("content", "sop_agent", "task")
        assert (tmp_path / "KDavis Platform" / "SOPs" / "sop_agent").is_dir()
