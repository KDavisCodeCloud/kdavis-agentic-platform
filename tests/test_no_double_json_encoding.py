"""
tests/test_no_double_json_encoding.py
2026-09-22 real bug, root-caused after "too many fixes" for the LinkedIn
posting pipeline: api/routes/internal_marketing.py's
_generate_and_gate_image_for_approved_row bound `json.dumps(image_brief)`
as a query parameter on a connection where api/main.py's db_pool already
has core.db.register_jsonb_codec applied (encoder=json.dumps) -- double-
encoding every auto-generated image_brief into a JSON string instead of a
JSON object, silently, for months. dispatch_scheduled_posts.py's cron
later choked on it with an opaque "'str' object has no attribute 'get'".

The reason 2000+ existing tests never caught this: tests/conftest.py
stubs asyncpg entirely ("not needed in tests -- always mocked at DB
layer"), so nothing in this suite ever exercises the real jsonb codec's
double-encoding behavior. Individual unit tests mocked conn.execute and
asserted whatever the code happened to produce (see the two tests this
same fix corrected in test_internal_marketing_publish.py and
test_internal_marketing_approval_image_gen.py) -- self-consistency, not
correctness against real Postgres.

Given standing up a real Postgres in CI is a bigger infra change than
this fix warrants, this is a cheap, deterministic static guard instead:
the LinkedIn/marketing publish pipeline may not call
conn.execute/fetchrow/fetchval/fetch with a json.dumps(...) call as one
of the positional arguments. Every jsonb column write in this codebase
goes through connections with this codec registered (core/db.py's
register_jsonb_codec, wired in api/main.py's pool init) -- passing a
native dict/list and letting the codec encode it once is always
correct; manually json.dumps()-ing first is never correct on these
connections.

Scope note: an earlier draft of this test scanned all of api/ and
core/, and found the identical json.dumps()-into-execute() pattern in
~10+ other files (core/hitl.py, core/notification_retry.py,
api/routes/incidents.py, api/routes/internal_agents.py, and more).
Deliberately NOT auditing or fixing those here -- confirming each one is
actually a bug (vs. a legitimate `text` column intentionally storing a
JSON string, which this same static pattern can't distinguish) needs
individual investigation per file, well beyond what "make the LinkedIn
posting loop robust" asked for, and misjudging one risks introducing a
new bug while chasing an unverified one. Flagged in GAPS.md as its own
item for a dedicated pass. This test's scope stays narrow and enforceable:
the one pipeline this session actually verified end-to-end.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCAN_PATHS = ("api/routes/internal_marketing.py",)
_EXECUTE_METHODS = {"execute", "executemany", "fetch", "fetchrow", "fetchval"}


def _find_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    violations = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_execute_call = (
            isinstance(func, ast.Attribute) and func.attr in _EXECUTE_METHODS
        )
        if not is_execute_call:
            continue

        for arg in node.args:
            if (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "dumps"
                and isinstance(arg.func.value, ast.Name)
                and arg.func.value.id == "json"
            ):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno} — "
                    f"json.dumps(...) passed directly to .{func.attr}(); "
                    "pass the native dict/list instead, the connection's "
                    "jsonb codec (core/db.py's register_jsonb_codec) "
                    "already encodes it -- double-encoding bug, see this "
                    "file's own module docstring"
                )
    return violations


def test_no_manual_json_dumps_passed_to_asyncpg_query_methods():
    violations: list[str] = []
    for rel_path in _SCAN_PATHS:
        violations.extend(_find_violations(REPO_ROOT / rel_path))

    assert not violations, "Double-JSON-encoding risk found:\n" + "\n".join(violations)
