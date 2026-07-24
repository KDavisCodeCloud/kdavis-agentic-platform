"""
Coverage for run_post_batch.py's process_batch() -- the dry-run test
harness that exercises asset_selector + post_formatter against
hand-written test posts. Does not test main()'s CLI/file-writing glue,
just the core per-item logic, plus the --dry-run refusal.
"""
import subprocess
import sys
from unittest.mock import patch

import run_post_batch as batch_runner

NO_MATCH = {"image_id": None, "image_path": None, "credit_line": None, "is_original": None, "selected_because": "no match found"}
MATCH = {
    "image_id": "img_001", "image_path": "assets_library/system_design/kubernetes.jpg",
    "credit_line": "Visual credit: @bytebytego", "is_original": False,
    "selected_because": "topic match on: kubernetes",
}


def test_process_batch_combines_hashtags_into_the_formatted_text():
    batch = [{
        "post_text": "Kubernetes is not the hard part.",
        "topic": "kubernetes", "pillar": "Cloud/DevOps", "hitl_tier": "T2",
        "suggested_hashtags": ["#Kubernetes", "#DevOps"],
    }]
    with patch("run_post_batch.select_asset", return_value=NO_MATCH):
        results = batch_runner.process_batch(batch)

    assert "#Kubernetes #DevOps" in results[0]["formatted_post"]
    assert results[0]["would_post_live"] is False


def test_process_batch_attaches_credit_line_when_image_matched():
    batch = [{
        "post_text": "Kubernetes is not the hard part.",
        "topic": "kubernetes", "pillar": "Cloud/DevOps", "hitl_tier": "T2",
        "suggested_hashtags": ["#Kubernetes"],
    }]
    with patch("run_post_batch.select_asset", return_value=MATCH):
        results = batch_runner.process_batch(batch)

    assert results[0]["formatted_post"].endswith("Visual credit: @bytebytego")
    assert results[0]["selected_image"] == MATCH


def test_process_batch_preserves_topic_pillar_and_tier_passthrough():
    batch = [{
        "post_text": "Text.", "topic": "RAG pipeline", "pillar": "AI Topics",
        "hitl_tier": "T2", "suggested_hashtags": [],
    }]
    with patch("run_post_batch.select_asset", return_value=NO_MATCH):
        results = batch_runner.process_batch(batch)

    assert results[0]["topic"] == "RAG pipeline"
    assert results[0]["pillar"] == "AI Topics"
    assert results[0]["hitl_tier"] == "T2"


def test_cli_refuses_to_run_without_dry_run_flag(tmp_path):
    batch_file = tmp_path / "batch.json"
    batch_file.write_text("[]")
    result = subprocess.run(
        [sys.executable, "run_post_batch.py", str(batch_file)],
        capture_output=True, text=True, cwd=str(batch_runner.REPO_ROOT),
    )
    assert result.returncode == 1
    assert "only supports --dry-run" in result.stderr
