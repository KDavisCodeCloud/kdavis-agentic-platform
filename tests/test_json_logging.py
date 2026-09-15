"""
tests/test_json_logging.py
Phase 10 (part 1), scale-readiness build.

core/json_logging.py replaces api/main.py's logging.basicConfig() with
structured JSON output -- one JSON object per log line, with any
extra={} fields a caller attaches promoted to top-level keys. This is
what turns "grep the logs for this workspace" into "query the logs for
this workspace" on Railway.
"""

import json
import logging

from core.json_logging import JSONFormatter, configure_logging


def _make_record(msg="hello", level=logging.INFO, extra=None):
    logger = logging.getLogger("test-json-logging")
    record = logger.makeRecord(
        logger.name, level, "test_file.py", 1, msg, (), None,
    )
    if extra:
        for key, value in extra.items():
            setattr(record, key, value)
    return record


class TestJSONFormatter:
    def test_basic_fields_present(self):
        formatter = JSONFormatter()
        record = _make_record(msg="incident created")
        parsed = json.loads(formatter.format(record))

        assert parsed["message"] == "incident created"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test-json-logging"
        assert "timestamp" in parsed

    def test_extra_fields_promoted_to_top_level(self):
        formatter = JSONFormatter()
        record = _make_record(
            msg="incident created",
            extra={"workspace_id": "ws-123", "agent_id": "agent_01_cicd_triage"},
        )
        parsed = json.loads(formatter.format(record))

        assert parsed["workspace_id"] == "ws-123"
        assert parsed["agent_id"] == "agent_01_cicd_triage"

    def test_output_is_single_line_valid_json(self):
        formatter = JSONFormatter()
        record = _make_record(msg="multi\nline\nmessage")
        output = formatter.format(record)

        assert "\n" not in output
        json.loads(output)  # does not raise

    def test_non_json_serializable_extra_falls_back_to_str(self):
        class Weird:
            def __str__(self):
                return "weird-repr"

        formatter = JSONFormatter()
        record = _make_record(msg="x", extra={"thing": Weird()})
        parsed = json.loads(formatter.format(record))

        assert parsed["thing"] == "weird-repr"

    def test_exception_info_included(self):
        formatter = JSONFormatter()
        logger = logging.getLogger("test-json-logging")
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logger.makeRecord(
                logger.name, logging.ERROR, "test_file.py", 1, "failed", (), sys.exc_info(),
            )
        parsed = json.loads(formatter.format(record))

        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
        assert "boom" in parsed["exception"]

    def test_standard_record_attrs_not_duplicated_as_extra(self):
        """pathname, lineno, etc. are standard LogRecord attrs -- they
        should not leak into the JSON body as if they were caller-supplied
        extra fields (message/level/logger already cover the useful ones)."""
        formatter = JSONFormatter()
        record = _make_record(msg="x")
        parsed = json.loads(formatter.format(record))

        assert "pathname" not in parsed
        assert "lineno" not in parsed
        assert "args" not in parsed


class TestConfigureLogging:
    def teardown_method(self):
        # Restore a clean root logger state so this test doesn't leak a
        # JSON/text handler into every other test file's log output.
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)

    def test_json_format_installs_json_formatter(self):
        configure_logging(level="INFO", fmt="json")
        root = logging.getLogger()

        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_text_format_installs_plain_formatter(self):
        configure_logging(level="INFO", fmt="text")
        root = logging.getLogger()

        assert len(root.handlers) == 1
        assert not isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_reconfiguring_does_not_stack_handlers(self):
        configure_logging(level="INFO", fmt="json")
        configure_logging(level="INFO", fmt="json")
        root = logging.getLogger()

        assert len(root.handlers) == 1
