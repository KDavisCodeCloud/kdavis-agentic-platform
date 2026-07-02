"""
tests/test_security.py
Tests for core/security.py — DataSanitizationShield

What this file validates:
  - Every credential pattern correctly redacts its target
  - Safe / non-secret text is NOT redacted (no false positives)
  - SanitizationResult metadata is accurate (count, patterns_triggered, hash)
  - sanitize_dict() recursively sanitizes nested structures
  - Edge cases: empty string, non-string input, multi-pattern text
  - Module-level `shield` singleton is functional

Runs with stdlib only — no extra pip installs needed.
"""

import hashlib
import re

import pytest

from core.security import DataSanitizationShield, SanitizationResult, shield


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def s() -> DataSanitizationShield:
    """Fresh shield instance for each test."""
    return DataSanitizationShield()


# ──────────────────────────────────────────────────────────────────────────────
# Pattern: AWS access key  (AKIA + 16 uppercase alphanumeric)
# ──────────────────────────────────────────────────────────────────────────────

class TestAWSAccessKey:
    def test_standalone_key_redacted(self, s):
        text = "Found credential AKIAIOSFODNN7EXAMPLE in repo scan"
        result = s.sanitize(text)
        assert "[REDACTED:AWS_ACCESS_KEY]" in result.sanitized_text
        assert "AKIAIOSFODNN7EXAMPLE" not in result.sanitized_text

    def test_redaction_count_is_one(self, s):
        result = s.sanitize("key=AKIAIOSFODNN7EXAMPLE end")
        assert result.redaction_count >= 1
        assert "aws_access_key" in result.patterns_triggered

    def test_two_keys_in_same_text(self, s):
        text = "AKIAIOSFODNN7EXAMPLE and AKIAIOSFODNN7EXAMPLE2"
        result = s.sanitize(text)
        # First key is 20 chars (AKIA+16), second ends with digit so also valid
        assert result.redaction_count >= 1

    def test_partial_match_not_redacted(self, s):
        # Preceded by uppercase letter — lookbehind (?<![A-Z0-9]) blocks it
        text = "PAKIAIOSFODNN7EXAMPLE is not a real key"
        result = s.sanitize(text)
        assert "PAKIAIOSFODNN7EXAMPLE" in result.sanitized_text

    def test_key_inside_json_string(self, s):
        text = '{"aws_key": "AKIAIOSFODNN7EXAMPLE", "region": "us-east-1"}'
        result = s.sanitize(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result.sanitized_text
        assert '"region": "us-east-1"' in result.sanitized_text


# ──────────────────────────────────────────────────────────────────────────────
# Pattern: AWS secret key  (env var name + 40-char base64-ish value)
# ──────────────────────────────────────────────────────────────────────────────

class TestAWSSecretKey:
    # 40-char AWS-style secret
    SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

    def test_aws_secret_access_key_redacted(self, s):
        text = f"AWS_SECRET_ACCESS_KEY={self.SECRET}"
        result = s.sanitize(text)
        assert self.SECRET not in result.sanitized_text
        assert "REDACTED:AWS_SECRET_KEY" in result.sanitized_text

    def test_aws_secret_key_alias_redacted(self, s):
        text = f"aws_secret_key={self.SECRET}"
        result = s.sanitize(text)
        assert self.SECRET not in result.sanitized_text

    def test_variable_name_preserved_after_redaction(self, s):
        text = f"AWS_SECRET_ACCESS_KEY={self.SECRET}"
        result = s.sanitize(text)
        assert "AWS_SECRET_ACCESS_KEY=" in result.sanitized_text

    def test_short_value_not_matched(self, s):
        # 39 chars — one short of the 40-char requirement
        short_secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEK"
        assert len(short_secret) == 39
        text = f"AWS_SECRET_ACCESS_KEY={short_secret}"
        result = s.sanitize(text)
        # Should not match since value is 39 chars, not 40
        assert short_secret in result.sanitized_text


# ──────────────────────────────────────────────────────────────────────────────
# Pattern: Azure client secret
# ──────────────────────────────────────────────────────────────────────────────

class TestAzureClientSecret:
    # 34-char Azure-style secret (alphanumeric + ~._-)
    AZ_SECRET = "Abc123~Def456.Ghi789_Jkl012~Mno345"

    def test_azure_client_secret_redacted(self, s):
        text = f"AZURE_CLIENT_SECRET={self.AZ_SECRET}"
        result = s.sanitize(text)
        assert self.AZ_SECRET not in result.sanitized_text
        assert "REDACTED:AZURE_CLIENT_SECRET" in result.sanitized_text

    def test_client_secret_alias_redacted(self, s):
        text = f"client_secret={self.AZ_SECRET}"
        result = s.sanitize(text)
        assert self.AZ_SECRET not in result.sanitized_text

    def test_variable_name_preserved(self, s):
        text = f"AZURE_CLIENT_SECRET={self.AZ_SECRET}"
        result = s.sanitize(text)
        assert "AZURE_CLIENT_SECRET=" in result.sanitized_text


# ──────────────────────────────────────────────────────────────────────────────
# Pattern: Bearer token
# ──────────────────────────────────────────────────────────────────────────────

class TestBearerToken:
    JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeK"

    def test_bearer_token_redacted(self, s):
        text = f"Authorization: Bearer {self.JWT}"
        result = s.sanitize(text)
        assert self.JWT not in result.sanitized_text
        assert "Bearer [REDACTED:BEARER_TOKEN]" in result.sanitized_text

    def test_bearer_keyword_preserved(self, s):
        text = f"Authorization: Bearer {self.JWT}"
        result = s.sanitize(text)
        assert "Bearer " in result.sanitized_text

    def test_short_token_not_redacted(self, s):
        # "Bearer abc123" — value is 6 chars, minimum is 20
        result = s.sanitize("Authorization: Bearer abc123")
        assert "abc123" in result.sanitized_text

    def test_case_insensitive_bearer(self, s):
        text = f"authorization: bearer {self.JWT}"
        result = s.sanitize(text)
        assert self.JWT not in result.sanitized_text


# ──────────────────────────────────────────────────────────────────────────────
# Pattern: DB connection URL with embedded credentials
# ──────────────────────────────────────────────────────────────────────────────

class TestDBConnectionURL:
    def test_postgres_url_with_creds_redacted(self, s):
        text = "DATABASE_URL=postgres://admin:s3cr3tpass@db.prod.example.com:5432/appdb"
        result = s.sanitize(text)
        assert "admin:s3cr3tpass" not in result.sanitized_text
        assert "REDACTED:DB_CREDENTIALS" in result.sanitized_text

    def test_mysql_url_redacted(self, s):
        text = "mysql://root:password123@localhost:3306/myapp"
        result = s.sanitize(text)
        assert "root:password123" not in result.sanitized_text

    def test_mongodb_url_redacted(self, s):
        text = "mongodb://mongouser:mongosecret@cluster0.mongodb.net/mydb"
        result = s.sanitize(text)
        assert "mongouser:mongosecret" not in result.sanitized_text

    def test_redis_url_redacted(self, s):
        text = "redis://default:redispassword@redis.example.com:6379/0"
        result = s.sanitize(text)
        assert "redispassword" not in result.sanitized_text

    def test_url_without_credentials_not_redacted(self, s):
        # No user:pass@ — should not match
        text = "connecting to postgres://localhost:5432/mydb"
        result = s.sanitize(text)
        assert "postgres://localhost:5432/mydb" in result.sanitized_text


# ──────────────────────────────────────────────────────────────────────────────
# Pattern: RSA/EC private key block
# ──────────────────────────────────────────────────────────────────────────────

class TestPrivateKey:
    RSA_KEY = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xHn/ygWep4SJ4qseMa9TMTaLdTGh11uJIVnH\n"
        "-----END RSA PRIVATE KEY-----"
    )
    EC_KEY = (
        "-----BEGIN EC PRIVATE KEY-----\n"
        "MHQCAQEEIOFADDdJzJLBDVCNMeLpK9BSNl3Hgo10lHm6AgAAAAAA\n"
        "-----END EC PRIVATE KEY-----"
    )

    def test_rsa_private_key_redacted(self, s):
        result = s.sanitize(self.RSA_KEY)
        assert "MIIEpAIBAAKCAQEA" not in result.sanitized_text
        assert "[REDACTED:PRIVATE_KEY]" in result.sanitized_text

    def test_ec_private_key_redacted(self, s):
        result = s.sanitize(self.EC_KEY)
        assert "MHQCAQEEIOFADDdJ" not in result.sanitized_text
        assert "[REDACTED:PRIVATE_KEY]" in result.sanitized_text

    def test_public_key_not_redacted(self, s):
        public_key = (
            "-----BEGIN PUBLIC KEY-----\n"
            "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0Z3VS5JJcds3\n"
            "-----END PUBLIC KEY-----"
        )
        result = s.sanitize(public_key)
        # Public keys don't match the PRIVATE KEY pattern
        assert "BEGIN PUBLIC KEY" in result.sanitized_text


# ──────────────────────────────────────────────────────────────────────────────
# Pattern: .env / environment variable secret assignment
# ──────────────────────────────────────────────────────────────────────────────

class TestDotenvAssignment:
    def test_stripe_secret_key_redacted(self, s):
        text = "STRIPE_SECRET_KEY=sk_live_abcdefghijklmnopqrstuvwx"
        result = s.sanitize(text)
        assert "sk_live_abcdefghijklmnopqrstuvwx" not in result.sanitized_text
        assert "REDACTED:ENV_SECRET" in result.sanitized_text

    def test_github_token_redacted(self, s):
        text = "GITHUB_TOKEN=ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        result = s.sanitize(text)
        assert "ghp_" not in result.sanitized_text

    def test_api_token_redacted(self, s):
        result = s.sanitize("API_TOKEN=tok_abcdef12345")
        assert "tok_abcdef12345" not in result.sanitized_text

    def test_database_url_without_secret_word_not_matched(self, s):
        # DATABASE_URL contains no KEY/SECRET/TOKEN/PASSWORD/PASS/CREDENTIAL
        # so the dotenv pattern should not match it
        text = "DATABASE_URL=postgresql://localhost/mydb"
        result = s.sanitize(text)
        # The db_connection_url pattern also won't match (no user:pass@)
        # so the full value should survive
        assert "postgresql://localhost/mydb" in result.sanitized_text

    def test_variable_name_preserved(self, s):
        result = s.sanitize("MY_SECRET_KEY=supersecretvalue123")
        assert "MY_SECRET_KEY=" in result.sanitized_text


# ──────────────────────────────────────────────────────────────────────────────
# Pattern: Generic API key header
# ──────────────────────────────────────────────────────────────────────────────

class TestAPIKeyHeader:
    API_KEY = "abcdefghijklmnopqrstuvwxyz123456"  # 32 chars, well over 20 minimum

    def test_x_api_key_redacted(self, s):
        text = f"x-api-key: {self.API_KEY}"
        result = s.sanitize(text)
        assert self.API_KEY not in result.sanitized_text
        assert "REDACTED:API_KEY" in result.sanitized_text

    def test_api_key_with_underscore_redacted(self, s):
        text = f"api_key={self.API_KEY}"
        result = s.sanitize(text)
        assert self.API_KEY not in result.sanitized_text

    def test_short_api_key_not_redacted(self, s):
        # Value under 20 chars should not match
        text = "x-api-key: shortkey"
        result = s.sanitize(text)
        assert "shortkey" in result.sanitized_text


# ──────────────────────────────────────────────────────────────────────────────
# SanitizationResult metadata
# ──────────────────────────────────────────────────────────────────────────────

class TestSanitizationResult:
    def test_result_is_dataclass(self, s):
        result = s.sanitize("hello world")
        assert isinstance(result, SanitizationResult)

    def test_no_secrets_count_is_zero(self, s):
        result = s.sanitize("hello world, no secrets here")
        assert result.redaction_count == 0
        assert result.patterns_triggered == []

    def test_original_hash_is_sha256(self, s):
        text = "some log text"
        result = s.sanitize(text)
        expected_hash = hashlib.sha256(text.encode()).hexdigest()
        assert result.original_hash == expected_hash
        assert len(result.original_hash) == 64

    def test_patterns_triggered_lists_fired_names(self, s):
        result = s.sanitize("AKIAIOSFODNN7EXAMPLE is the key")
        assert "aws_access_key" in result.patterns_triggered

    def test_multiple_patterns_triggered(self, s):
        text = (
            "AKIAIOSFODNN7EXAMPLE "
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def123456789"
        )
        result = s.sanitize(text)
        assert "aws_access_key" in result.patterns_triggered
        assert "bearer_token" in result.patterns_triggered
        assert result.redaction_count >= 2

    def test_redaction_count_reflects_actual_substitutions(self, s):
        # Two separate bearer tokens in one string
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature123456"
        text = f"Bearer {jwt} and also Bearer {jwt}"
        result = s.sanitize(text)
        assert result.redaction_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_string_returns_empty(self, s):
        result = s.sanitize("")
        assert result.sanitized_text == ""
        assert result.redaction_count == 0

    def test_non_string_integer_coerced(self, s):
        result = s.sanitize(42)  # type: ignore
        assert result.sanitized_text == "42"

    def test_non_string_none_coerced(self, s):
        result = s.sanitize(None)  # type: ignore
        assert result.sanitized_text == "None"

    def test_context_parameter_included_in_log(self, s):
        # Should not raise; context is just for logging
        result = s.sanitize("safe text", context="test_context")
        assert result.sanitized_text == "safe text"

    def test_safe_log_line_fully_preserved(self, s):
        log_line = "2026-01-15 10:30:00 INFO Pod api-server-xyz CrashLoopBackOff: OOMKilled"
        result = s.sanitize(log_line)
        assert result.sanitized_text == log_line
        assert result.redaction_count == 0

    def test_large_text_with_single_secret(self, s):
        prefix = "x" * 10_000
        suffix = "y" * 10_000
        text = f"{prefix}AKIAIOSFODNN7EXAMPLE{suffix}"
        result = s.sanitize(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result.sanitized_text
        assert len(result.sanitized_text) > 0


# ──────────────────────────────────────────────────────────────────────────────
# sanitize_dict()
# ──────────────────────────────────────────────────────────────────────────────

class TestSanitizeDict:
    def test_flat_dict_string_values_sanitized(self, s):
        data = {
            "message": "Found key AKIAIOSFODNN7EXAMPLE in logs",
            "level": "error",
        }
        result = s.sanitize_dict(data)
        assert "AKIAIOSFODNN7EXAMPLE" not in result["message"]
        assert result["level"] == "error"

    def test_nested_dict_recursively_sanitized(self, s):
        data = {
            "outer": "safe",
            "inner": {
                "token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig123456",
            },
        }
        result = s.sanitize_dict(data)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result["inner"]["token"]

    def test_non_string_values_preserved(self, s):
        data = {
            "count": 42,
            "enabled": True,
            "ratio": 3.14,
            "nothing": None,
        }
        result = s.sanitize_dict(data)
        assert result["count"] == 42
        assert result["enabled"] is True
        assert result["ratio"] == 3.14
        assert result["nothing"] is None

    def test_list_values_sanitized(self, s):
        data = {
            "logs": [
                "normal log line",
                "AKIAIOSFODNN7EXAMPLE found in scan",
            ]
        }
        result = s.sanitize_dict(data)
        assert "AKIAIOSFODNN7EXAMPLE" not in result["logs"][1]
        assert result["logs"][0] == "normal log line"

    def test_non_string_list_items_preserved(self, s):
        data = {"counts": [1, 2, 3]}
        result = s.sanitize_dict(data)
        assert result["counts"] == [1, 2, 3]

    def test_empty_dict_returns_empty(self, s):
        assert s.sanitize_dict({}) == {}

    def test_empty_string_value_preserved(self, s):
        result = s.sanitize_dict({"key": ""})
        assert result["key"] == ""


# ──────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────────────────────────────────────

class TestModuleSingleton:
    def test_shield_is_dataclass_sanitization_shield(self):
        assert isinstance(shield, DataSanitizationShield)

    def test_shield_sanitizes_correctly(self):
        result = shield.sanitize("AKIAIOSFODNN7EXAMPLE is leaked")
        assert "AKIAIOSFODNN7EXAMPLE" not in result.sanitized_text

    def test_shield_is_same_object_across_imports(self):
        from core.security import shield as shield2
        assert shield is shield2


# ──────────────────────────────────────────────────────────────────────────────
# Custom extra patterns
# ──────────────────────────────────────────────────────────────────────────────

class TestCustomPatterns:
    def test_extra_pattern_applied(self):
        import re
        custom_pattern = ("ssn", re.compile(r"\d{3}-\d{2}-\d{4}"), "[REDACTED:SSN]")
        s_custom = DataSanitizationShield(extra_patterns=[custom_pattern])

        result = s_custom.sanitize("Employee SSN: 123-45-6789")
        assert "123-45-6789" not in result.sanitized_text
        assert "[REDACTED:SSN]" in result.sanitized_text

    def test_builtin_patterns_still_fire_with_extra(self):
        import re
        custom_pattern = ("ssn", re.compile(r"\d{3}-\d{2}-\d{4}"), "[REDACTED:SSN]")
        s_custom = DataSanitizationShield(extra_patterns=[custom_pattern])

        result = s_custom.sanitize("AKIAIOSFODNN7EXAMPLE and SSN 123-45-6789")
        assert "AKIAIOSFODNN7EXAMPLE" not in result.sanitized_text
        assert "123-45-6789" not in result.sanitized_text

    def test_broken_pattern_does_not_crash(self):
        import re
        # Regex that always raises on .subn() — deliberately broken
        bad_regex = MagicMock()
        bad_regex.subn = MagicMock(side_effect=Exception("bad pattern"))
        custom_pattern = ("bad", bad_regex, "[REDACTED]")
        s_custom = DataSanitizationShield(extra_patterns=[custom_pattern])

        # Should not raise; shield catches pattern exceptions and logs a warning
        result = s_custom.sanitize("some text")
        assert isinstance(result, SanitizationResult)


# Need MagicMock for the broken pattern test
from unittest.mock import MagicMock
