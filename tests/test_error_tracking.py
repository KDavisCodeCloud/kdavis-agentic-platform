"""
tests/test_error_tracking.py
Tests for core/error_tracking.py -- Sentry error monitoring for Cloud
Decoded's own backend (GAPS.md #16), not customer infrastructure.

Covers:
  init_sentry():
    - No-ops (never calls sentry_sdk.init) when SENTRY_DSN isn't set --
      local dev and tests must work identically without a Sentry account
    - Calls sentry_sdk.init with the DSN, environment, and FastAPI/
      Starlette integrations when SENTRY_DSN is set
  capture_exception():
    - Tags the Sentry scope with workspace_id/agent_id when provided,
      so errors are traceable per tenant
    - Omits tags that weren't passed, rather than setting them to None
    - Never raises, even if called before Sentry was ever initialized
      (mirrors sentry_sdk's own safe-no-op behavior with no client set)
"""

from unittest.mock import MagicMock, patch

from core import error_tracking


class TestInitSentry:
    def test_noop_when_dsn_not_set(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        with patch("core.error_tracking.sentry_sdk.init") as mock_init:
            error_tracking.init_sentry()
        mock_init.assert_not_called()

    def test_noop_when_dsn_is_empty_string(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "")
        with patch("core.error_tracking.sentry_sdk.init") as mock_init:
            error_tracking.init_sentry()
        mock_init.assert_not_called()

    def test_initializes_with_dsn_and_environment(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")
        monkeypatch.setenv("ENVIRONMENT", "production")
        with patch("core.error_tracking.sentry_sdk.init") as mock_init:
            error_tracking.init_sentry()

        mock_init.assert_called_once()
        _, kwargs = mock_init.call_args
        assert kwargs["dsn"] == "https://examplePublicKey@o0.ingest.sentry.io/0"
        assert kwargs["environment"] == "production"
        assert kwargs["traces_sample_rate"] == 0.0
        assert kwargs["send_default_pii"] is False
        assert len(kwargs["integrations"]) == 2

    def test_defaults_environment_to_production_when_unset(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        with patch("core.error_tracking.sentry_sdk.init") as mock_init:
            error_tracking.init_sentry()

        assert mock_init.call_args.kwargs["environment"] == "production"


class TestCaptureException:
    def _mock_scope_cm(self):
        scope = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=scope)
        cm.__exit__ = MagicMock(return_value=False)
        return cm, scope

    def test_tags_workspace_id_and_agent_id(self):
        cm, scope = self._mock_scope_cm()
        exc = ValueError("boom")
        with patch("core.error_tracking.sentry_sdk.new_scope", return_value=cm), \
             patch("core.error_tracking.sentry_sdk.capture_exception") as mock_capture:
            error_tracking.capture_exception(exc, workspace_id="ws-123", agent_id="agent_01_cicd_triage")

        scope.set_tag.assert_any_call("workspace_id", "ws-123")
        scope.set_tag.assert_any_call("agent_id", "agent_01_cicd_triage")
        mock_capture.assert_called_once_with(exc)

    def test_no_tags_set_when_workspace_and_agent_omitted(self):
        cm, scope = self._mock_scope_cm()
        exc = RuntimeError("unhandled")
        with patch("core.error_tracking.sentry_sdk.new_scope", return_value=cm), \
             patch("core.error_tracking.sentry_sdk.capture_exception") as mock_capture:
            error_tracking.capture_exception(exc)

        scope.set_tag.assert_not_called()
        mock_capture.assert_called_once_with(exc)

    def test_extra_context_set_as_extras_not_tags(self):
        cm, scope = self._mock_scope_cm()
        exc = ValueError("boom")
        with patch("core.error_tracking.sentry_sdk.new_scope", return_value=cm), \
             patch("core.error_tracking.sentry_sdk.capture_exception"):
            error_tracking.capture_exception(exc, extra={"incident_id": "abc-123"})

        scope.set_extra.assert_called_once_with("incident_id", "abc-123")

    def test_does_not_raise_when_uninitialized(self):
        """Mirrors real sentry_sdk behavior: capture_exception/new_scope are
        safe no-ops without a configured client. No mocking here -- this
        exercises the real sentry_sdk with no DSN ever set in this process."""
        error_tracking.capture_exception(ValueError("no client configured"), workspace_id="ws-1")


class TestCaptureMessage:
    """capture_message -- for a real, non-exception event (e.g. sustained
    backpressure, core/execution_semaphore.py) that still deserves Sentry
    visibility, without fabricating an exception just to report it."""

    def _mock_scope_cm(self):
        scope = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=scope)
        cm.__exit__ = MagicMock(return_value=False)
        return cm, scope

    def test_tags_workspace_id_and_agent_id(self):
        cm, scope = self._mock_scope_cm()
        with patch("core.error_tracking.sentry_sdk.new_scope", return_value=cm), \
             patch("core.error_tracking.sentry_sdk.capture_message") as mock_capture:
            error_tracking.capture_message("backpressure", workspace_id="ws-123", agent_id="agent_01_cicd_triage")

        scope.set_tag.assert_any_call("workspace_id", "ws-123")
        scope.set_tag.assert_any_call("agent_id", "agent_01_cicd_triage")
        mock_capture.assert_called_once_with("backpressure", level="warning")

    def test_defaults_to_warning_level(self):
        cm, scope = self._mock_scope_cm()
        with patch("core.error_tracking.sentry_sdk.new_scope", return_value=cm), \
             patch("core.error_tracking.sentry_sdk.capture_message") as mock_capture:
            error_tracking.capture_message("something happened")

        mock_capture.assert_called_once_with("something happened", level="warning")

    def test_custom_level_passed_through(self):
        cm, scope = self._mock_scope_cm()
        with patch("core.error_tracking.sentry_sdk.new_scope", return_value=cm), \
             patch("core.error_tracking.sentry_sdk.capture_message") as mock_capture:
            error_tracking.capture_message("fyi", level="info")

        mock_capture.assert_called_once_with("fyi", level="info")

    def test_extra_context_set_as_extras(self):
        cm, scope = self._mock_scope_cm()
        with patch("core.error_tracking.sentry_sdk.new_scope", return_value=cm), \
             patch("core.error_tracking.sentry_sdk.capture_message"):
            error_tracking.capture_message("backpressure", extra={"wait_seconds": 2.5})

        scope.set_extra.assert_called_once_with("wait_seconds", 2.5)

    def test_does_not_raise_when_uninitialized(self):
        error_tracking.capture_message("no client configured", workspace_id="ws-1")
