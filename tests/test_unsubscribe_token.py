"""
tests/test_unsubscribe_token.py
core/unsubscribe_token.py -- signed, stateless unsubscribe tokens.
"""

from unittest.mock import patch

import pytest

from core import unsubscribe_token as ut


@pytest.fixture(autouse=True)
def _secret_env():
    with patch.dict("os.environ", {"CD_UNSUBSCRIBE_SECRET": "test-secret-value"}):
        yield


class TestMakeAndVerifyToken:
    def test_round_trips_the_email(self):
        token = ut.make_token("Jane@Example.com")
        assert ut.verify_token(token) == "jane@example.com"

    def test_tampered_signature_rejected(self):
        token = ut.make_token("jane@example.com")
        payload, sig = token.split(".", 1)
        tampered = f"{payload}.{sig[:-1]}f"
        assert ut.verify_token(tampered) is None

    def test_malformed_token_rejected(self):
        assert ut.verify_token("not-a-real-token") is None

    def test_token_for_different_secret_rejected(self):
        token = ut.make_token("jane@example.com")
        with patch.dict("os.environ", {"CD_UNSUBSCRIBE_SECRET": "a-different-secret"}):
            assert ut.verify_token(token) is None


class TestMissingSecret:
    def test_make_token_raises_when_secret_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ut.UnsubscribeConfigError):
                ut.make_token("jane@example.com")
