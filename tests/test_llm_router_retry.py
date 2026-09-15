"""
tests/test_llm_router_retry.py
Tests for .llm/router.py's retry-with-backoff (Phase 9, scale-readiness
build). Loaded via importlib (same mechanism agents/base_agent.py's
_load_router() uses) since .llm/ isn't a normal importable package.

Covers:
  _is_transient_error(): 429/5xx (via status_code) and known SDK
    exception-name patterns are retryable; everything else isn't
  _call_with_retry(): retries a transient error up to _MAX_RETRIES times
    with backoff, succeeds if a later attempt works, re-raises
    immediately on a non-transient error (no wasted retries), re-raises
    after exhausting all retries on a persistent transient error
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROUTER_PATH = Path(__file__).parent.parent / ".llm" / "router.py"
_spec = importlib.util.spec_from_file_location("llm_router_test", _ROUTER_PATH)
llm_router = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(llm_router)


class _RateLimitError(Exception):
    status_code = 429


class _ServerError(Exception):
    status_code = 503


class _BadRequestError(Exception):
    status_code = 400


class _SDKStyleRateLimitError(Exception):
    """No status_code attribute -- matched by class name instead, same
    as some SDKs' exception types."""


class TestIsTransientError:
    def test_429_is_transient(self):
        assert llm_router._is_transient_error(_RateLimitError("rate limited")) is True

    def test_5xx_is_transient(self):
        assert llm_router._is_transient_error(_ServerError("server error")) is True

    def test_4xx_non_429_is_not_transient(self):
        assert llm_router._is_transient_error(_BadRequestError("bad request")) is False

    def test_matches_by_exception_class_name_when_no_status_code(self):
        assert llm_router._is_transient_error(_SDKStyleRateLimitError("x")) is True

    def test_generic_exception_is_not_transient(self):
        assert llm_router._is_transient_error(ValueError("something else entirely")) is False


class TestCallWithRetry:
    def test_succeeds_first_try_no_retry_needed(self):
        dispatch = MagicMock(return_value="ok")

        result = llm_router._call_with_retry(dispatch, "model", [], "sys", 100, 0.2, "anthropic")

        assert result == "ok"
        assert dispatch.call_count == 1

    def test_retries_transient_error_then_succeeds(self):
        dispatch = MagicMock(side_effect=[_RateLimitError("x"), _RateLimitError("x"), "ok"])

        with patch("time.sleep") as mock_sleep:
            result = llm_router._call_with_retry(dispatch, "model", [], "sys", 100, 0.2, "anthropic")

        assert result == "ok"
        assert dispatch.call_count == 3
        assert mock_sleep.call_count == 2  # backoff before attempts 2 and 3

    def test_non_transient_error_raises_immediately_no_retry(self):
        dispatch = MagicMock(side_effect=_BadRequestError("bad request"))

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(_BadRequestError):
                llm_router._call_with_retry(dispatch, "model", [], "sys", 100, 0.2, "anthropic")

        assert dispatch.call_count == 1
        mock_sleep.assert_not_called()

    def test_exhausts_retries_on_persistent_transient_error(self):
        dispatch = MagicMock(side_effect=_RateLimitError("still limited"))

        with patch("time.sleep"):
            with pytest.raises(_RateLimitError):
                llm_router._call_with_retry(dispatch, "model", [], "sys", 100, 0.2, "anthropic")

        # Initial attempt + _MAX_RETRIES retries
        assert dispatch.call_count == llm_router._MAX_RETRIES + 1

    def test_backoff_grows_exponentially(self):
        dispatch = MagicMock(side_effect=[_RateLimitError("x"), _RateLimitError("x"), _RateLimitError("x"), "ok"])
        sleep_calls = []

        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            llm_router._call_with_retry(dispatch, "model", [], "sys", 100, 0.2, "anthropic")

        # Each backoff (minus jitter, which is in [0, 1)) must be >= the
        # previous attempt's base -- proves exponential growth, not a
        # fixed delay.
        bases = [llm_router._BASE_BACKOFF_SECONDS * (2**i) for i in range(3)]
        for sleep_call, base in zip(sleep_calls, bases):
            assert sleep_call >= base
            assert sleep_call < base + 1  # jitter is uniform(0, 1)
