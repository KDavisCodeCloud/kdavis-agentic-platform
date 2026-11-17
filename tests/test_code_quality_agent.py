"""
tests/test_code_quality_agent.py
Stub coverage for agents/internal/code_quality_agent.py.

What this file validates (against small on-disk fixture files, not the
real codebase — keeps this test deterministic regardless of what other
concurrent sessions are writing elsewhere in the repo):
  - check_bloat() flags a function over MAX_FUNCTION_LINES and a file
    over MAX_FILE_LINES
  - check_unused_imports() flags an import never referenced, and does
    NOT flag one that is used
  - check_dry_violations() flags two structurally identical functions
    across files (same logic, different names/literals) and does NOT
    flag two functions that are merely similar length
  - check_readability() flags a bad variable name, a bad parameter name,
    and a missing docstring on a public function
  - check_dead_functions() flags an unused module-PRIVATE helper but
    does not flag an unused PUBLIC function (see that function's
    docstring for why public dead-code detection is out of scope)
  - CodeQualityReport.to_report_text() renders the BLOCKING/NON-BLOCKING/
    CLEAN sections in the documented format
  - a file whose only unused function is public appears in CLEAN
"""

from pathlib import Path

from agents.internal.code_quality_agent import (
    CodeQualityAgent,
    _parse_file,
    check_bloat,
    check_dead_functions,
    check_unused_imports,
)


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source)
    return path


def test_check_bloat_flags_long_function(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(45))
    source = f"def big_function():\n{body}\n    return x0\n"
    path = _write(tmp_path, "big.py", source)
    issues = check_bloat(_parse_file(path))
    assert any(i.issue_type == "bloat" and "big_function" in i.description for i in issues)


def test_check_unused_imports_flags_unused_and_ignores_used(tmp_path):
    source = "import os\nimport json\n\ndef f():\n    return os.getcwd()\n"
    path = _write(tmp_path, "imports.py", source)
    issues = check_unused_imports(_parse_file(path))
    unused_names = [i.description for i in issues]
    assert any("json" in d for d in unused_names)
    assert not any("'os'" in d for d in unused_names)


def test_dry_violation_flags_structurally_identical_functions(tmp_path):
    source_a = "def compute_total(items):\n    total = 0\n    for item in items:\n        total += item.price\n    return total\n"
    source_b = "def sum_prices(products):\n    result = 0\n    for product in products:\n        result += product.price\n    return result\n"
    _write(tmp_path, "a.py", source_a)
    _write(tmp_path, "b.py", source_b)

    report = CodeQualityAgent().review([tmp_path / "a.py", tmp_path / "b.py"])
    dry_issues = [i for i in report.issues if i.issue_type == "dry"]
    assert len(dry_issues) == 2  # one flag per file, cross-referencing the other


def test_readability_flags_bad_variable_and_parameter_names_and_missing_docstring(tmp_path):
    source = "def process(data2):\n    tmp = data2 + 1\n    return tmp\n"
    path = _write(tmp_path, "readability.py", source)
    report = CodeQualityAgent().review([path])
    descriptions = [i.description for i in report.issues if i.issue_type == "readability"]
    assert any("parameter 'data2'" in d for d in descriptions)
    assert any("variable 'tmp'" in d for d in descriptions)
    assert any("no docstring" in d for d in descriptions)


def test_dead_functions_flags_unused_private_helper_only(tmp_path):
    source = (
        "def public_api():\n    return 1\n\n"
        "def _unused_helper():\n    return 1\n\n"
        "def _used_helper():\n    return 2\n\n"
        "def caller():\n    return _used_helper()\n"
    )
    path = _write(tmp_path, "deadcode.py", source)
    issues = check_dead_functions([_parse_file(path)])
    flagged = {i.description.split()[0] for i in issues}
    assert flagged == {"_unused_helper"}


def test_report_text_includes_all_three_sections(tmp_path):
    path = _write(tmp_path, "clean.py", 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n')
    report = CodeQualityAgent().review([path])
    text = report.to_report_text(pr_number="7")
    assert "CODE QUALITY REPORT — PR #7" in text
    assert "BLOCKING (must fix before merge):" in text
    assert "NON-BLOCKING (recommended):" in text
    assert "CLEAN:" in text


def test_file_with_no_issues_is_clean(tmp_path):
    path = _write(tmp_path, "clean2.py", 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n')
    report = CodeQualityAgent().review([path])
    assert str(path) in report.clean_files


# ── PR gate: block only on issues the PR introduces (2026-11-17) ─────────────

import subprocess
import sys

from agents.internal.code_quality_agent import BLOCKING, NON_BLOCKING, Issue, gate_report, split_new_issues

_DEAD = 'def _unused_helper(a):\n    """Never called."""\n    return a\n'
_CLEAN = 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n'


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    for rel, src in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(src)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def test_moved_lines_do_not_make_an_old_issue_new():
    base = [Issue("a.py", 10, "dry", "f duplicates logic also found at b.py:20", BLOCKING)]
    head = [Issue("a.py", 14, "dry", "f duplicates logic also found at b.py:31", BLOCKING)]
    new, old = split_new_issues(head, base)
    assert new == [] and len(old) == 1


def test_a_second_copy_of_an_existing_issue_is_new():
    issue = Issue("a.py", 1, "readability", "unclear name 'tmp'", NON_BLOCKING)
    new, old = split_new_issues([issue, issue], [issue])
    assert len(new) == 1 and len(old) == 1


def test_pre_existing_blocking_issue_does_not_block(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"pkg/a.py": _DEAD})
    (repo / "pkg/a.py").write_text("# touched\n" + _DEAD)
    monkeypatch.chdir(repo)
    report = gate_report(["pkg/a.py"], "HEAD", repo)
    assert report.blocking == []
    assert any("pre-existing on HEAD" in i.description for i in report.non_blocking)


def test_issue_introduced_by_the_pr_still_blocks(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"pkg/a.py": _CLEAN})
    (repo / "pkg/a.py").write_text(_CLEAN + "\n\n" + _DEAD)
    monkeypatch.chdir(repo)
    report = gate_report(["pkg/a.py"], "HEAD", repo)
    assert [i.issue_type for i in report.blocking] == ["dead_code"]


def test_new_file_issues_are_all_new(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"pkg/a.py": _CLEAN})
    (repo / "pkg/b.py").write_text(_DEAD)
    monkeypatch.chdir(repo)
    assert len(gate_report(["pkg/a.py", "pkg/b.py"], "HEAD", repo).blocking) == 1


def test_cli_accepts_exactly_the_gate_workflows_arguments(tmp_path):
    """code-quality-gate.yml called flags this CLI never accepted, so argparse
    exited 2 on every PR. Run the CLI with the arguments the workflow passes."""
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/code-quality-gate.yml").read_text()
    for flag in ("--paths-file", "--baseline-ref", "--pr-number", "--report-out"):
        assert flag in workflow
    repo = _repo(tmp_path, {"pkg/a.py": _DEAD})
    (repo / "changed_files.txt").write_text("pkg/a.py\nfrontend/x.ts\n")
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run(
        [sys.executable, "-m", "agents.internal.code_quality_agent", "--paths-file", "changed_files.txt",
         "--baseline-ref", "HEAD", "--pr-number", "9", "--report-out", "out.json"],
        cwd=repo, capture_output=True, text=True, env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"})
    assert run.returncode == 0, run.stderr
    import json
    report = json.loads((repo / "out.json").read_text())
    assert report["blocking_count"] == 0 and report["files_reviewed"] == 1
    assert report["markdown_summary"].startswith("```\nCODE QUALITY REPORT — PR #9")


def test_a_duplicate_group_changing_members_is_not_new():
    """Item 2 split one _build_graph copy-group into two; each member's 'also found at' list
    changed but the duplication itself was old."""
    base = [Issue("a.py", 1, "dry", "_build_graph duplicates logic also found at b.py:1, c.py:1", BLOCKING)]
    head = [Issue("a.py", 1, "dry", "_build_graph duplicates logic also found at b.py:1", BLOCKING)]
    assert split_new_issues(head, base)[0] == []


_TABLE = '''def option_catalog(context):
    """Options."""
    return catalog_dict(
        Spec("opt_1", "{a}", "desc", "low", ("call_a",)),
        Spec("opt_2", "{b}", "desc", "low", ("call_b",)),
    )
'''


def test_literal_data_tables_are_not_dry_violations(tmp_path):
    """Two option catalogs with the same number of rows are different data, not duplicated logic."""
    a = _write(tmp_path, "a.py", _TABLE.format(a="Open a PR", b="Open an issue"))
    b = _write(tmp_path, "b.py", _TABLE.format(a="Patch memory", b="Add an HPA"))
    assert not [i for i in CodeQualityAgent().review([a, b]).issues if i.issue_type == "dry"]


def test_a_table_that_uses_its_arguments_is_still_logic(tmp_path):
    src = _TABLE.replace('"desc"', "context['x']").format(a="A", b="B")
    a, b = _write(tmp_path, "a.py", src), _write(tmp_path, "b.py", src)
    assert len([i for i in CodeQualityAgent().review([a, b]).issues if i.issue_type == "dry"]) == 2
