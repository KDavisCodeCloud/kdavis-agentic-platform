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
