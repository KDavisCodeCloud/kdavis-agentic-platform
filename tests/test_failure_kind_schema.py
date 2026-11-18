"""Lab run 3: every failure_kind core/execution_outcome.py can write must be
allowed by the incidents CHECK constraint (latest migration that defines it).
Mocked-DB tests never caught that 'not_executed' violated migration 050's."""

import re
from pathlib import Path

from core import execution_outcome

_MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations"


def _allowed_failure_kinds() -> set[str]:
    latest = None
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        m = re.search(r"incidents_failure_kind_check\s+CHECK\s*\((.*?)\);", path.read_text(), re.S)
        if m:
            latest = m.group(1)
    assert latest, "no migration defines incidents_failure_kind_check"
    return set(re.findall(r"'(\w+)'", latest))


def test_every_failure_kind_the_code_writes_is_allowed():
    written = {v for k, v in vars(execution_outcome).items() if k.startswith("FAILURE_") and isinstance(v, str)}
    assert written, "execution_outcome defines no FAILURE_* kinds"
    assert written | {"permission_denied", "execution_error"} <= _allowed_failure_kinds()
