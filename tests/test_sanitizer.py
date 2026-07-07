"""
tests/test_sanitizer.py
Tests for security/sanitizer.py — DataSanitizationShield (PII redaction)

What this file validates:
  - Email, SSN, credit card (Luhn-validated), and phone patterns redact correctly
  - Non-Luhn digit runs are left alone (no false-positive card redaction)
  - redaction_log accurately reports what fired and how many times
  - Custom per-product patterns load from config/products.yaml when present
  - Missing/malformed config is handled gracefully, not raised
"""

import re
from unittest.mock import mock_open, patch

import pytest

from security.sanitizer import DataSanitizationShield, shield, sanitize


@pytest.fixture
def s() -> DataSanitizationShield:
    return DataSanitizationShield()


# ──────────────────────────────────────────────────────────────────────────────
# Email
# ──────────────────────────────────────────────────────────────────────────────

class TestEmail:
    def test_email_redacted(self, s):
        text = "Contact john.doe@example.com for details."
        out, log = s.sanitize(text)
        assert "john.doe@example.com" not in out
        assert "[REDACTED_EMAIL]" in out
        assert {"pattern": "email", "count": 1} in log

    def test_multiple_emails_counted(self, s):
        out, log = s.sanitize("a@b.com and c@d.org")
        assert out == "[REDACTED_EMAIL] and [REDACTED_EMAIL]"
        assert {"pattern": "email", "count": 2} in log

    def test_no_email_no_log_entry(self, s):
        out, log = s.sanitize("no contact info here")
        assert out == "no contact info here"
        assert log == []


# ──────────────────────────────────────────────────────────────────────────────
# Phone (US + international)
# ──────────────────────────────────────────────────────────────────────────────

class TestPhone:
    def test_us_dashed_phone_redacted(self, s):
        out, log = s.sanitize("Call 555-123-4567 now")
        assert "555-123-4567" not in out
        assert "[REDACTED_PHONE]" in out
        assert {"pattern": "phone", "count": 1} in log

    def test_us_phone_with_country_code(self, s):
        out, log = s.sanitize("Reach me at +1 555-123-4567")
        assert "555-123-4567" not in out
        assert "[REDACTED_PHONE]" in out

    def test_us_phone_with_parens(self, s):
        out, log = s.sanitize("Office: (555) 123-4567")
        assert "[REDACTED_PHONE]" in out
        assert "123-4567" not in out

    def test_international_phone_redacted(self, s):
        out, log = s.sanitize("Call +44 20 7946 0958 now")
        assert "20 7946 0958" not in out
        assert "[REDACTED_PHONE]" in out

    def test_short_digit_run_not_redacted(self, s):
        out, log = s.sanitize("Only 42 items left")
        assert out == "Only 42 items left"
        assert log == []


# ──────────────────────────────────────────────────────────────────────────────
# Email + phone together (explicit combined scenario from the build spec)
# ──────────────────────────────────────────────────────────────────────────────

class TestEmailAndPhoneCombined:
    def test_both_redacted_and_logged(self, s):
        text = "Contact John at john.doe@example.com or 555-123-4567 for details."
        out, log = s.sanitize(text)
        assert "john.doe@example.com" not in out
        assert "555-123-4567" not in out
        assert "[REDACTED_EMAIL]" in out
        assert "[REDACTED_PHONE]" in out
        assert {"pattern": "email", "count": 1} in log
        assert {"pattern": "phone", "count": 1} in log
        assert len(log) == 2


# ──────────────────────────────────────────────────────────────────────────────
# SSN
# ──────────────────────────────────────────────────────────────────────────────

class TestSSN:
    def test_ssn_redacted(self, s):
        out, log = s.sanitize("Employee SSN: 123-45-6789")
        assert "123-45-6789" not in out
        assert "[REDACTED_SSN]" in out
        assert {"pattern": "ssn", "count": 1} in log

    def test_ssn_like_but_wrong_grouping_not_redacted(self, s):
        # 4-4-4 grouping, not the 3-2-4 SSN shape
        out, log = s.sanitize("Reference code: 1234-5678-9012")
        assert "1234-5678-9012" in out


# ──────────────────────────────────────────────────────────────────────────────
# Credit card (Luhn-validated)
# ──────────────────────────────────────────────────────────────────────────────

class TestCreditCard:
    VALID_VISA = "4111 1111 1111 1111"  # Luhn-valid test number

    def test_valid_card_redacted(self, s):
        out, log = s.sanitize(f"Card on file: {self.VALID_VISA}")
        assert "4111" not in out
        assert "[REDACTED_CARD]" in out
        assert {"pattern": "credit_card", "count": 1} in log

    def test_dashed_valid_card_redacted(self, s):
        out, log = s.sanitize("Card on file: 4111-1111-1111-1111")
        assert "[REDACTED_CARD]" in out

    def test_non_luhn_digit_run_not_redacted(self, s):
        # Same length as a card number but fails the Luhn check
        text = "Tracking number: 1234 5678 9012 3456"
        out, log = s.sanitize(text)
        assert "1234 5678 9012 3456" in out
        assert log == []


# ──────────────────────────────────────────────────────────────────────────────
# Custom per-product patterns (config/products.yaml)
# ──────────────────────────────────────────────────────────────────────────────

class TestCustomPatterns:
    def test_custom_pattern_applied_when_config_present(self, s):
        fake_yaml = """
products:
  cloud_decoded:
    custom_pii_patterns:
      - name: employee_id
        pattern: 'EMP-\\d{6}'
        replacement: '[REDACTED_EMPLOYEE_ID]'
"""
        with patch("security.sanitizer.CONFIG_PATH") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data=fake_yaml)):
                out, log = s.sanitize("Employee EMP-482910 flagged", product_id="cloud_decoded")

        assert "EMP-482910" not in out
        assert "[REDACTED_EMPLOYEE_ID]" in out
        assert {"pattern": "employee_id", "count": 1} in log

    def test_no_product_id_skips_custom_patterns(self, s):
        out, log = s.sanitize("Employee EMP-482910 flagged")
        assert "EMP-482910" in out

    def test_missing_config_file_does_not_raise(self, s):
        out, log = s.sanitize("hello world", product_id="cloud_decoded")
        assert out == "hello world"
        assert log == []

    def test_malformed_pattern_is_skipped_not_raised(self, s):
        fake_yaml = """
products:
  cloud_decoded:
    custom_pii_patterns:
      - name: broken
        pattern: '('
"""
        with patch("security.sanitizer.CONFIG_PATH") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data=fake_yaml)):
                out, log = s.sanitize("some text", product_id="cloud_decoded")

        assert out == "some text"
        assert log == []


# ──────────────────────────────────────────────────────────────────────────────
# Module singleton + convenience function
# ──────────────────────────────────────────────────────────────────────────────

class TestModuleSingleton:
    def test_shield_is_a_shield(self):
        assert isinstance(shield, DataSanitizationShield)

    def test_sanitize_function_matches_shield(self):
        out1, log1 = sanitize("a@b.com")
        out2, log2 = shield.sanitize("a@b.com")
        assert out1 == out2
        assert log1 == log2


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_string(self, s):
        out, log = s.sanitize("")
        assert out == ""
        assert log == []

    def test_non_string_coerced(self, s):
        out, log = s.sanitize(42)  # type: ignore
        assert out == "42"
        assert log == []

    def test_safe_text_untouched(self, s):
        text = "Deploy succeeded, no PII in this log line."
        out, log = s.sanitize(text)
        assert out == text
        assert log == []
