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
Deterministic output validation layer — CLAUDE.md Phase 1, step 7.

Confidence scores and LLM judgment stop mattering here. Every check in this
file is a plain, inspectable rule: type/schema conformance against
config/schema_validations/{agent_name}.json, and a hard blocklist of tool
call name prefixes that must never execute without HITL approval no matter
how confident the model was.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "config" / "schema_validations"

# Any tool call whose name starts with one of these requires HITL approval
# regardless of confidence score. Governance: no autonomous destructive or
# outbound action (global CLAUDE.md non-negotiables).
BLOCKLIST_PREFIXES = ["delete_", "drop_", "truncate_", "send_", "publish_"]

_JSON_SCHEMA_TYPES = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _load_schema(agent_name: str) -> Optional[dict]:
    """Load config/schema_validations/{agent_name}.json, or None if it doesn't exist.

    Schema coverage is opt-in per agent — agents are added continuously and
    a missing schema file is not itself a validation failure.
    """
    path = SCHEMA_DIR / f"{agent_name}.json"
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.load(f)


def _check_type(value: Any, expected_type: str) -> bool:
    py_type = _JSON_SCHEMA_TYPES.get(expected_type)
    if py_type is None:
        log.warning("[ASSERTION] Unknown schema type '%s' — skipping type check", expected_type)
        return True
    return isinstance(value, py_type)


def validate_output(
    output: dict,
    schema: Optional[dict] = None,
    agent_name: Optional[str] = None,
) -> bool:
    """
    Validate `output` against a JSON schema (required fields + property types).

    `schema` takes precedence when passed directly; otherwise it's loaded from
    config/schema_validations/{agent_name}.json. Returns True when no schema
    is available — schema coverage is opt-in, not mandatory.
    """
    if schema is None and agent_name:
        schema = _load_schema(agent_name)
    if schema is None:
        return True

    if not isinstance(output, dict):
        log.warning("[ASSERTION] Output is not a dict: %s", type(output).__name__)
        return False

    for field in schema.get("required", []):
        if field not in output:
            log.warning("[ASSERTION] Missing required field '%s' in output", field)
            return False

    for field, field_schema in schema.get("properties", {}).items():
        if field not in output:
            continue
        expected_type = field_schema.get("type")
        if expected_type and not _check_type(output[field], expected_type):
            log.warning(
                "[ASSERTION] Field '%s' expected type '%s', got %s",
                field, expected_type, type(output[field]).__name__,
            )
            return False

    return True


def requires_hitl_for_tool_calls(tool_calls: list[str]) -> list[str]:
    """
    Return the subset of `tool_calls` matching a blocklist prefix.

    A non-empty result means HITL is mandatory for this run regardless of
    confidence score — the caller (core/engine.py) must route to the HITL
    gate rather than auto-completing.
    """
    flagged = [
        call for call in tool_calls
        if any(call.startswith(prefix) for prefix in BLOCKLIST_PREFIXES)
    ]
    if flagged:
        log.info("[ASSERTION] Blocklisted tool calls flagged for HITL: %s", flagged)
    return flagged
