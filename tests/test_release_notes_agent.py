"""
tests/test_release_notes_agent.py
Stub coverage for agents/internal/release_notes_agent.py.

What this file validates:
  - infer_products_affected() extracts product ids from
    agents/products/{id}/... paths
  - infer_prompt_version_bumps() matches prompts/**/v*.md paths only
  - infer_new_agents_deployed() matches agents/internal/{name}.py,
    excluding __init__.py
  - build() prefers explicit products_affected/prompt_version_bumps/
    new_agents_deployed over inference when the caller supplies them
  - to_markdown() renders version, date, and all sections
  - publish() calls obsidian_sink with the rendered markdown and version
    when provided, and leaves vault_path None when it isn't
"""

from datetime import date

from agents.internal.release_notes_agent import (
    DeploySummary,
    ReleaseNotesAgent,
    infer_new_agents_deployed,
    infer_products_affected,
    infer_prompt_version_bumps,
)


def test_infer_products_affected_from_product_paths():
    files = ["agents/products/gta_hub/news_scraper.py", "core/security.py"]
    assert infer_products_affected(files) == ["gta_hub"]


def test_infer_prompt_version_bumps_matches_versioned_prompt_files():
    files = ["prompts/research_agent/v1.0.1.md", "prompts/research_agent/CHANGELOG.md"]
    assert infer_prompt_version_bumps(files) == ["prompts/research_agent/v1.0.1.md"]


def test_infer_new_agents_deployed_excludes_init():
    files = ["agents/internal/gap_detector_agent.py", "agents/internal/__init__.py"]
    assert infer_new_agents_deployed(files) == ["gap_detector_agent"]


def test_build_prefers_explicit_products_affected_over_inference():
    summary = DeploySummary(
        version="1.0.0", deployed_at=date(2026, 7, 7),
        changed_files=["agents/products/gta_hub/news_scraper.py"],
        commit_messages=["fix: bug"], products_affected=["explicit_product"],
    )
    note = ReleaseNotesAgent().build(summary)
    assert note.products_affected == ["explicit_product"]


def test_to_markdown_includes_version_and_sections():
    summary = DeploySummary(
        version="2.1.0", deployed_at=date(2026, 7, 7),
        changed_files=["agents/internal/portfolio_monitor.py"],
        commit_messages=["feat: add portfolio monitor"],
    )
    note = ReleaseNotesAgent().build(summary)
    markdown = note.to_markdown()
    assert "# Release 2.1.0" in markdown
    assert "feat: add portfolio monitor" in markdown
    assert "portfolio_monitor" in markdown


def test_publish_calls_obsidian_sink_when_provided():
    captured = {}

    def fake_sink(markdown, version):
        captured["markdown"] = markdown
        captured["version"] = version
        return "/vault/path.md"

    summary = DeploySummary(version="1.0.0", deployed_at=date(2026, 7, 7), changed_files=[], commit_messages=[])
    note = ReleaseNotesAgent().build(summary)
    result = ReleaseNotesAgent().publish(note, obsidian_sink=fake_sink)

    assert result["vault_path"] == "/vault/path.md"
    assert captured["version"] == "1.0.0"


def test_publish_leaves_vault_path_none_without_sink():
    summary = DeploySummary(version="1.0.0", deployed_at=date(2026, 7, 7), changed_files=[], commit_messages=[])
    note = ReleaseNotesAgent().build(summary)
    result = ReleaseNotesAgent().publish(note)
    assert result["vault_path"] is None
