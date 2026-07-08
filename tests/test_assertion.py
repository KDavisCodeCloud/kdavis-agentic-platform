"""
tests/test_assertion.py
Tests for core/assertion.py — deterministic output validation + HITL blocklist.

What this file validates:
  - Blocklisted tool call prefixes (delete_/drop_/truncate_/send_/publish_) are
    always flagged, regardless of confidence
  - validate_output() checks required fields + property types against an
    inline schema or one loaded from config/schema_validations/{agent}.json
  - Missing schema coverage for an agent is not itself a validation failure
"""

import json

import pytest

from core.assertion import (
    BLOCKLIST_PREFIXES,
    requires_hitl_for_tool_calls,
    validate_output,
)


class TestBlocklist:
    def test_flags_delete_prefixed_call(self):
        assert requires_hitl_for_tool_calls(["delete_user"]) == ["delete_user"]

    def test_flags_multiple_blocklisted_calls(self):
        calls = ["read_data", "drop_table", "send_email"]
        assert requires_hitl_for_tool_calls(calls) == ["drop_table", "send_email"]

    def test_safe_calls_not_flagged(self):
        assert requires_hitl_for_tool_calls(["read_data", "list_items"]) == []

    def test_empty_list_not_flagged(self):
        assert requires_hitl_for_tool_calls([]) == []

    @pytest.mark.parametrize("prefix", BLOCKLIST_PREFIXES)
    def test_every_blocklist_prefix_flags(self, prefix):
        call = f"{prefix}anything"
        assert requires_hitl_for_tool_calls([call]) == [call]

    def test_prefix_must_be_at_start(self):
        # "resend_invite" contains "send_" but doesn't start with it — not flagged.
        assert requires_hitl_for_tool_calls(["resend_invite"]) == []


class TestValidateOutputNoSchema:
    def test_no_schema_no_agent_passes(self):
        assert validate_output({"anything": "goes"}) is True

    def test_unknown_agent_name_passes(self):
        assert validate_output({"anything": "goes"}, agent_name="no_such_agent_xyz") is True


class TestValidateOutputWithInlineSchema:
    SCHEMA = {
        "required": ["niche", "confidence"],
        "properties": {
            "niche": {"type": "string"},
            "confidence": {"type": "number"},
            "tags": {"type": "array"},
        },
    }

    def test_valid_output_passes(self):
        output = {"niche": "b2b saas", "confidence": 0.9, "tags": ["a", "b"]}
        assert validate_output(output, schema=self.SCHEMA) is True

    def test_missing_required_field_fails(self):
        assert validate_output({"niche": "b2b saas"}, schema=self.SCHEMA) is False

    def test_wrong_type_fails(self):
        output = {"niche": "b2b saas", "confidence": "high"}
        assert validate_output(output, schema=self.SCHEMA) is False

    def test_non_dict_output_fails(self):
        assert validate_output("not a dict", schema=self.SCHEMA) is False

    def test_extra_fields_are_ignored(self):
        output = {"niche": "x", "confidence": 0.5, "unexpected": "field"}
        assert validate_output(output, schema=self.SCHEMA) is True


class TestValidateOutputFromSchemaFile:
    def test_loads_schema_from_config_schema_validations(self, tmp_path, monkeypatch):
        schema_dir = tmp_path / "schema_validations"
        schema_dir.mkdir()
        (schema_dir / "demo_agent.json").write_text(json.dumps({
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        }))

        monkeypatch.setattr("core.assertion.SCHEMA_DIR", schema_dir)

        assert validate_output({"status": "ok"}, agent_name="demo_agent") is True
        assert validate_output({}, agent_name="demo_agent") is False

    def test_missing_schema_file_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.assertion.SCHEMA_DIR", tmp_path / "does_not_exist")
        assert validate_output({"anything": True}, agent_name="no_schema_agent") is True
