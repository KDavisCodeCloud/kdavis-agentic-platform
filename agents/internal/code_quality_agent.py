"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
code_quality_agent — overseer of code quality across the platform, per
CLAUDE.md Phase 2 Step 26. Runs on every PR (code-quality-gate.yml, not
wired here), on-demand via chat ("review [module]"), and on a weekly
sweep. This module is the actual analyzer: ast-based, stdlib only, no
network/LLM calls — it reads .py files from disk and returns a
structured report. CI wiring, the PR comment poster, and the tech_debt
table writer are integration-session concerns; review() and
to_tech_debt_rows() give the caller everything needed for both.

Checks, in the priority order CLAUDE.md specifies:
  1. DRY violations       — identical function logic in 2+ files, found
                             by normalizing each function body's AST
                             (renaming identifiers/constants to generic
                             placeholders) and hashing the result. Two
                             functions that only differ in names/literals
                             are the same logic; functions that merely
                             look similar in raw text but differ
                             structurally are never flagged.
  2. Bloat                 — functions over 40 lines, files over 300
                             lines.
  3. Dead code              — module-private (_leading_underscore)
                             top-level functions never referenced
                             anywhere in their own file, and imports
                             never used in their own file. Public
                             function dead-code detection needs a
                             whole-repo import graph to avoid flagging
                             every function a partial PR diff doesn't
                             happen to call — out of scope here; see
                             check_dead_functions()'s docstring.
                             Decorated functions and test_* functions are
                             skipped (registered/invoked indirectly).
  4. Readability            — unclear names (x, tmp, data2, foo...),
                             missing docstrings on public functions and
                             classes, overlong lines.
  5. Dependency bloat        — imports with a stdlib-equivalent
                             replacement, from a known map.
  6. Inconsistency           — same operation done differently across
                             files. Currently checks one concrete case:
                             os.environ.get(...) vs os.getenv(...) mixed
                             across the reviewed set; flags the minority
                             style and recommends the majority.

What it does NOT do (per spec): auto-fix without approval, flag style
(tabs/spaces — that's the linter's job), rewrite working logic without a
clear DRY/bloat violation, or touch test files unless a test itself has
a dead assertion (not implemented — no reliable static signal for that).
"""

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

MAX_FUNCTION_LINES = 40
MAX_FILE_LINES = 300
MAX_LINE_LENGTH = 150
MIN_DUPLICATE_FUNCTION_LINES = 5  # ignore trivial 1-4 line duplicates (getters, etc.)

BAD_NAME_PATTERN = re.compile(r"^(x|y|z|tmp|temp|val|foo|bar|baz|data\d*)$", re.IGNORECASE)
ALLOWED_SHORT_NAMES = {"i", "j", "k", "n", "_", "id", "ok", "db", "fn"}

DEPENDENCY_STDLIB_REPLACEMENTS = {
    "six": "no longer needed — this codebase is Python 3 only",
    "simplejson": "json",
    "pathlib2": "pathlib",
    "mock": "unittest.mock (Python 3 has it built in)",
}

BLOCKING = "blocking"
NON_BLOCKING = "non_blocking"


@dataclass
class Issue:
    file: str
    line: int
    issue_type: str  # "dry" | "bloat" | "dead_code" | "readability" | "dependency_bloat" | "inconsistency"
    description: str
    severity: str  # BLOCKING | NON_BLOCKING
    suggested_fix: str = ""

    def to_row(self, product_id: str = "platform") -> dict:
        return {
            "product_id": product_id,
            "file": self.file,
            "line": self.line,
            "issue_type": self.issue_type,
            "description": self.description,
            "severity": self.severity,
        }


@dataclass
class ParsedFile:
    path: str
    source: str
    lines: list[str]
    tree: ast.Module


def _parse_file(path: Path) -> ParsedFile | None:
    try:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None
    return ParsedFile(path=str(path), source=source, lines=source.splitlines(), tree=tree)


def _function_span(node: ast.AST) -> int:
    end_line = getattr(node, "end_lineno", None) or node.lineno
    return end_line - node.lineno + 1


def _top_level_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def check_bloat(parsed: ParsedFile) -> list[Issue]:
    issues = []
    for func in _top_level_functions(parsed.tree):
        span = _function_span(func)
        if span > MAX_FUNCTION_LINES:
            issues.append(Issue(
                file=parsed.path, line=func.lineno, issue_type="bloat",
                description=f"{func.name} is {span} lines",
                severity=NON_BLOCKING, suggested_fix="split into smaller functions",
            ))
    if len(parsed.lines) > MAX_FILE_LINES:
        issues.append(Issue(
            file=parsed.path, line=1, issue_type="bloat",
            description=f"file is {len(parsed.lines)} lines",
            severity=NON_BLOCKING, suggested_fix="split into multiple modules",
        ))
    return issues


def _imported_names(tree: ast.Module) -> dict[str, int]:
    """import name -> line number, skipping __future__ imports."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for alias in node.names:
                if alias.name != "*":
                    names[alias.asname or alias.name] = node.lineno
    return names


def _used_names(tree: ast.Module, exclude_import_lines: set[int]) -> set[str]:
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.lineno not in exclude_import_lines:
            used.add(node.id)
        elif isinstance(node, ast.Attribute) and node.lineno not in exclude_import_lines:
            base = node.value
            if isinstance(base, ast.Name):
                used.add(base.id)
    return used


def check_unused_imports(parsed: ParsedFile) -> list[Issue]:
    imported = _imported_names(parsed.tree)
    import_lines = set(imported.values())
    used = _used_names(parsed.tree, exclude_import_lines=set())
    issues = []
    for name, line in imported.items():
        if name not in used:
            issues.append(Issue(
                file=parsed.path, line=line, issue_type="dead_code",
                description=f"import '{name}' is never used",
                severity=BLOCKING, suggested_fix="remove the unused import",
            ))
    return issues


def check_dead_functions(parsed_files: list[ParsedFile]) -> list[Issue]:
    """Module-PRIVATE (leading-underscore) top-level functions never
    referenced anywhere in their own file. Deliberately scoped to
    underscore-prefixed names only: a `_helper` is never meant to be
    called from another module by convention, so "unused in this file"
    is a sound signal regardless of how many files are in the reviewed
    set. Public (non-underscore) functions are NOT checked here — for
    those, "unused in the reviewed set" just as often means "used by a
    caller that isn't part of this diff," which would make this a
    BLOCKING false-positive machine on every partial-file PR review
    (the primary use case per CLAUDE.md's code-quality-gate.yml).
    Real public dead-code detection needs a whole-repo import graph,
    out of scope for this stub. Decorated and test_* functions are
    skipped — both are commonly invoked indirectly."""
    issues = []
    for pf in parsed_files:
        # FunctionDef.name is a plain string attribute, not an ast.Name
        # node — a function's own definition never appears in this set,
        # so no self-reference exclusion is needed.
        used_in_file: set[str] = {n.id for n in ast.walk(pf.tree) if isinstance(n, ast.Name)}

        for node in pf.tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("_") or node.name.startswith("__"):
                continue
            if node.decorator_list:
                continue
            if node.name not in used_in_file:
                issues.append(Issue(
                    file=pf.path, line=node.lineno, issue_type="dead_code",
                    description=f"{node.name} is defined but never referenced anywhere in {pf.path}",
                    severity=BLOCKING, suggested_fix="remove it",
                ))
    return issues


def check_readability(parsed: ParsedFile) -> list[Issue]:
    issues = []
    for node in ast.walk(parsed.tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id in ALLOWED_SHORT_NAMES or node.id.startswith("_"):
                continue
            if BAD_NAME_PATTERN.match(node.id):
                issues.append(Issue(
                    file=parsed.path, line=node.lineno, issue_type="readability",
                    description=f"variable '{node.id}' is not descriptive",
                    severity=NON_BLOCKING, suggested_fix="rename to describe what it holds",
                ))
        elif isinstance(node, ast.arg):
            if node.arg in ALLOWED_SHORT_NAMES or node.arg.startswith("_") or node.arg == "self":
                continue
            if BAD_NAME_PATTERN.match(node.arg):
                issues.append(Issue(
                    file=parsed.path, line=node.lineno, issue_type="readability",
                    description=f"parameter '{node.arg}' is not descriptive",
                    severity=NON_BLOCKING, suggested_fix="rename to describe what it holds",
                ))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_"):
                continue
            if ast.get_docstring(node) is None:
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                issues.append(Issue(
                    file=parsed.path, line=node.lineno, issue_type="readability",
                    description=f"public {kind} '{node.name}' has no docstring",
                    severity=NON_BLOCKING, suggested_fix="add a one-line docstring explaining the non-obvious part",
                ))

    for i, line in enumerate(parsed.lines, start=1):
        if len(line) > MAX_LINE_LENGTH:
            issues.append(Issue(
                file=parsed.path, line=i, issue_type="readability",
                description=f"line is {len(line)} characters",
                severity=NON_BLOCKING, suggested_fix="break into multiple statements",
            ))
    return issues


def check_dependency_bloat(parsed: ParsedFile) -> list[Issue]:
    issues = []
    for node in ast.walk(parsed.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in DEPENDENCY_STDLIB_REPLACEMENTS:
                    issues.append(Issue(
                        file=parsed.path, line=node.lineno, issue_type="dependency_bloat",
                        description=f"imports '{top}'",
                        severity=NON_BLOCKING,
                        suggested_fix=f"use {DEPENDENCY_STDLIB_REPLACEMENTS[top]} instead",
                    ))
    return issues


class _NormalizingVisitor(ast.NodeTransformer):
    """Renames identifiers and blanks literal values in-place so two
    functions that differ only in names/literals hash identically."""

    def __init__(self):
        self._counter = 0
        self._seen: dict[str, str] = {}

    def _alias(self, original: str) -> str:
        if original not in self._seen:
            self._counter += 1
            self._seen[original] = f"v{self._counter}"
        return self._seen[original]

    def visit_Name(self, node):
        node.id = self._alias(node.id)
        return node

    def visit_arg(self, node):
        node.arg = self._alias(node.arg)
        return self.generic_visit(node)

    def visit_Constant(self, node):
        node.value = f"<{type(node.value).__name__}>"
        return node

    def visit_FunctionDef(self, node):
        node.name = "_fn_"
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        node.name = "_fn_"
        return self.generic_visit(node)


def _normalized_hash(func: ast.AST) -> str:
    clone = ast.parse(ast.unparse(func))
    _NormalizingVisitor().visit(clone)
    dumped = ast.dump(clone, annotate_fields=False)
    return hashlib.sha256(dumped.encode()).hexdigest()


def check_dry_violations(parsed_files: list[ParsedFile]) -> list[Issue]:
    by_hash: dict[str, list[tuple[str, ast.AST]]] = {}
    for pf in parsed_files:
        for func in _top_level_functions(pf.tree):
            if _function_span(func) < MIN_DUPLICATE_FUNCTION_LINES:
                continue
            digest = _normalized_hash(func)
            by_hash.setdefault(digest, []).append((pf.path, func))

    issues = []
    for matches in by_hash.values():
        if len(matches) < 2:
            continue
        locations = [f"{path}:{func.lineno}" for path, func in matches]
        for path, func in matches:
            others = [loc for loc in locations if loc != f"{path}:{func.lineno}"]
            issues.append(Issue(
                file=path, line=func.lineno, issue_type="dry",
                description=f"{func.name} duplicates logic also found at {', '.join(others)}",
                severity=BLOCKING, suggested_fix="extract to a shared utility",
            ))
    return issues


def check_inconsistency(parsed_files: list[ParsedFile]) -> list[Issue]:
    """Concrete instance: os.environ.get(...) vs os.getenv(...) mixed
    across the reviewed set. Flags the minority style; majority wins."""
    environ_get_files: dict[str, int] = {}
    getenv_files: dict[str, int] = {}
    for pf in parsed_files:
        for node in ast.walk(pf.tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "get" and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "environ":
                environ_get_files[pf.path] = node.lineno
            elif node.func.attr == "getenv" and isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                getenv_files[pf.path] = node.lineno

    if not environ_get_files or not getenv_files:
        return []

    majority, minority, winner = (
        (getenv_files, environ_get_files, "os.getenv(...)")
        if len(getenv_files) >= len(environ_get_files)
        else (environ_get_files, getenv_files, "os.environ.get(...)")
    )
    return [
        Issue(
            file=path, line=line, issue_type="inconsistency",
            description=f"uses a different env-var read style than the rest of the reviewed set ({len(majority)} files use {winner})",
            severity=NON_BLOCKING, suggested_fix=f"switch to {winner} for consistency",
        )
        for path, line in minority.items()
    ]


@dataclass
class CodeQualityReport:
    files_reviewed: int
    issues: list[Issue]
    clean_files: list[str]

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == BLOCKING]

    @property
    def non_blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == NON_BLOCKING]

    def to_report_text(self, pr_number: str = "-") -> str:
        lines = [
            f"CODE QUALITY REPORT — PR #{pr_number}",
            f"Files reviewed: {self.files_reviewed}",
            f"Issues found: {len(self.issues)}",
            "",
            "BLOCKING (must fix before merge):",
        ]
        lines += [f"  - [{i.file}:{i.line}] {_issue_label(i)}: {i.description} → {i.suggested_fix}" for i in self.blocking] or ["  (none)"]
        lines += ["", "NON-BLOCKING (recommended):"]
        lines += [f"  - [{i.file}:{i.line}] {_issue_label(i)}: {i.description} → {i.suggested_fix}" for i in self.non_blocking] or ["  (none)"]
        lines += ["", f"CLEAN: {', '.join(self.clean_files) if self.clean_files else '(none)'}"]
        return "\n".join(lines)

    def to_tech_debt_rows(self, product_id: str = "platform") -> list[dict]:
        return [i.to_row(product_id) for i in self.non_blocking]


_ISSUE_LABELS = {
    "dry": "DRY violation", "bloat": "Bloat", "dead_code": "Dead code",
    "readability": "Readability", "dependency_bloat": "Dependency bloat",
    "inconsistency": "Inconsistency",
}


def _issue_label(issue: Issue) -> str:
    return _ISSUE_LABELS.get(issue.issue_type, issue.issue_type)


class CodeQualityAgent:
    def review(self, paths: list[Path]) -> CodeQualityReport:
        parsed_files = [pf for pf in (_parse_file(p) for p in paths) if pf is not None]

        issues: list[Issue] = []
        issues_by_file: dict[str, list[Issue]] = {pf.path: [] for pf in parsed_files}

        for pf in parsed_files:
            file_issues = (
                check_bloat(pf) + check_unused_imports(pf)
                + check_readability(pf) + check_dependency_bloat(pf)
            )
            issues += file_issues
            issues_by_file[pf.path] += file_issues

        cross_file_issues = check_dead_functions(parsed_files) + check_dry_violations(parsed_files) + check_inconsistency(parsed_files)
        issues += cross_file_issues
        for issue in cross_file_issues:
            issues_by_file.setdefault(issue.file, []).append(issue)

        clean_files = sorted(path for path, file_issues in issues_by_file.items() if not file_issues)

        return CodeQualityReport(files_reviewed=len(parsed_files), issues=issues, clean_files=clean_files)
