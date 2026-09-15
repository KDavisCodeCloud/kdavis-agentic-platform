"""
core/json_logging.py
Phase 10 (part 1), scale-readiness build -- structured JSON logging.

api/main.py previously called logging.basicConfig() with a plain
"%(asctime)s [%(name)s] %(levelname)s %(message)s" format -- readable
in a terminal, but every log line was an opaque string on Railway.
Answering "show me every log line for workspace X" or "every failed
LLM call in the last hour" meant grepping message text, not querying a
field.

JSONFormatter renders every record as one JSON object per line and
auto-promotes any extra= fields a caller attaches (extra={"workspace_id":
..., "agent_id": ...}) into top-level JSON keys, so existing call sites
gain structured fields incrementally by adding extra=, without every
log.info() in the codebase needing to be rewritten at once.
"""

import json
import logging
import time

# Attributes every stdlib LogRecord carries regardless of extra= --
# anything NOT in this set on a record is a caller-supplied extra field.
_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JSONFormatter(logging.Formatter):
    """One JSON object per log line. Extra fields pass through as-is."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime_iso(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS:
                continue
            try:
                json.dumps(value)
            except TypeError:
                value = str(value)
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)

    @staticmethod
    def formatTime_iso(record: logging.LogRecord) -> str:
        return (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z"
        )


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """
    Replaces logging.basicConfig(). fmt="json" (default, used in
    production on Railway) emits structured JSON; fmt="text" keeps the
    original human-readable single-line format for local dev.
    """
    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
        )
    root.addHandler(handler)
