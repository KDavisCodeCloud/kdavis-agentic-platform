"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

import re
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# Each pattern: (name, compiled_regex, replacement_template)
# All patterns use raw strings with correct \s+ (not /s+)
#
# Hardened 2026-11-14 (GAPS #35). A probe of realistic cloud-log / CLI shapes
# found 13 of 18 leaking: every value-matching pattern only understood
# NAME=value, so JSON ("SecretAccessKey": "..."), `aws sts` output,
# `az ad sp create-for-rbac` output, k8s Secret data, connection strings and
# well-known token formats all passed through untouched. Two rules now:
#   - `_KV_PREFIX` patterns keep the key and any quote/colon formatting and
#     replace only the value, so JSON stays valid-looking and the operator can
#     still see WHICH credential was involved.
#   - `(?!\[REDACTED)` on every value means a later, more generic pattern
#     never re-labels a value an earlier, specific one already redacted.
_NOT_REDACTED = r"(?!\[REDACTED)"
# Optional quote, the key, optional quote, = or :, optional quote.
_KV_PREFIX = r"""(["']?{key}["']?\s*[=:]\s*["']?)""" + _NOT_REDACTED

# A key that ENDS in one of these words holds a secret: aws_secret_access_key,
# SecretAccessKey, SessionToken, client_secret, clientSecret, AccountKey,
# DB_PASSWORD, password. Ending, not containing: secretName / tokenUrl /
# passwordPolicy are names, not secrets, and are needed to diagnose
# "secret not found"-style incidents.
_SECRET_KEY_WORDS = (
    # Not "pwd": the shell's PWD=/current/dir is a path, not a password.
    r"password|passwd|secret|token|credentials?|private[_-]?key|"
    r"api[_-]?key|access[_-]?key|account[_-]?key|secret[_-]?key|auth[_-]?key"
)
_SECRET_KEY_NAME = r"[A-Za-z0-9_.\-]*(?:" + _SECRET_KEY_WORDS + r")"
SECRET_KEY_NAME_RE = re.compile(r"(?i)^" + _SECRET_KEY_NAME + r"$")

_CREDENTIAL_PATTERNS = [
    (
        "aws_access_key",
        # AKIA = long-term key id; ASIA = temporary (STS) key id.
        re.compile(r"(?<![A-Z0-9])((?:AKIA|ASIA)[A-Z0-9]{16})(?![A-Z0-9])"),
        "[REDACTED:AWS_ACCESS_KEY]",
    ),
    (
        "aws_secret_key",
        # 40-char base64-ish value after an AWS secret-key name, in env, YAML
        # or JSON form (aws_secret_access_key, SecretAccessKey, ...).
        re.compile(
            r"(?i)" + _KV_PREFIX.format(key=r"(?:aws_secret_access_key|aws_secret_key|secret_?access_?key)")
            + r"([A-Za-z0-9/+]{40})(?![A-Za-z0-9/+])"
        ),
        r"\1[REDACTED:AWS_SECRET_KEY]",
    ),
    (
        "aws_session_token",
        re.compile(
            r"(?i)" + _KV_PREFIX.format(key=r"(?:aws_session_token|aws_security_token|session_?token)")
            + r"([A-Za-z0-9/+=]{40,})"
        ),
        r"\1[REDACTED:AWS_SESSION_TOKEN]",
    ),
    (
        "azure_client_secret",
        # Azure client secrets, 30-64 chars (current ones are 40 with a '~'),
        # after AZURE_CLIENT_SECRET / client_secret / clientSecret.
        re.compile(
            r"(?i)" + _KV_PREFIX.format(key=r"(?:azure_client_secret|client[_-]?secret)")
            + r"([A-Za-z0-9~._\-]{30,64})(?![A-Za-z0-9~._\-])"
        ),
        r"\1[REDACTED:AZURE_CLIENT_SECRET]",
    ),
    (
        "github_token",
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{50,255})\b"),
        "[REDACTED:GITHUB_TOKEN]",
    ),
    (
        "slack_token",
        re.compile(r"\b(xox[abposr]-[A-Za-z0-9-]{10,})\b"),
        "[REDACTED:SLACK_TOKEN]",
    ),
    (
        "stripe_key",
        re.compile(r"\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,})\b"),
        "[REDACTED:STRIPE_KEY]",
    ),
    (
        "bearer_token",
        re.compile(r"(?i)(Bearer\s+)([A-Za-z0-9\-._~+/]{20,}={0,2})"),
        r"\1[REDACTED:BEARER_TOKEN]",
    ),
    (
        "db_connection_url",
        # postgres://, mysql://, mongodb://, redis:// with credentials embedded
        re.compile(
            r"(?i)(postgres|postgresql|mysql|mongodb|redis)://([^:@\s]+:[^@\s]+@[^\s'\"]+)"
        ),
        r"\1://[REDACTED:DB_CREDENTIALS]",
    ),
    (
        "rsa_private_key",
        re.compile(
            r"-----BEGIN\s+(RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----[\s\S]*?-----END\s+(RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----",
            re.MULTILINE,
        ),
        "[REDACTED:PRIVATE_KEY]",
    ),
    (
        "dotenv_assignment",
        # Matches KEY=value lines that look like secrets (contain key/secret/token/password/pass)
        re.compile(
            r"(?im)^([A-Z_]*(KEY|SECRET|TOKEN|PASSWORD|PASS|CREDENTIAL)[A-Z_]*)\s*=\s*['\"]?"
            + _NOT_REDACTED + r"(.+?)['\"]?\s*$"
        ),
        r"\1=[REDACTED:ENV_SECRET]",
    ),
    (
        "generic_api_key_header",
        # x-api-key: <value> or api-key: <value> in headers
        re.compile(r"(?i)(x-api-key|api[-_]key)\s*[=:]\s*['\"]?" + _NOT_REDACTED + r"([A-Za-z0-9\-._~]{20,})['\"]?"),
        r"\1=[REDACTED:API_KEY]",
    ),
    (
        "secret_key_value",
        # Last, catch-all: any key ENDING in a secret word, in env, YAML, JSON,
        # query-string or connection-string form (password=..., "password":
        # "...", AccountKey=...;, data:\n  password: <base64>). Value runs to
        # whitespace, quote, comma or semicolon; 6+ chars so "password: ''"
        # and "token: null"-style noise stays readable.
        re.compile(r"(?i)(?<![A-Za-z0-9_.\-])" + _KV_PREFIX.format(key=_SECRET_KEY_NAME) + r"([^\s\"',;]{6,})"),
        r"\1[REDACTED:SECRET_VALUE]",
    ),
]


@dataclass
class SanitizationResult:
    sanitized_text: str
    redaction_count: int
    patterns_triggered: list = field(default_factory=list)
    original_hash: str = ""


class DataSanitizationShield:
    """
    Scrubs PII and credentials from all text before it reaches the LLM router.
    Must be called on every log input, code snippet, or user-supplied text.

    Governance: Rule 9 (audit trail), Rule 6 (LLM-agnostic upstream safety).
    """

    def __init__(self, extra_patterns: Optional[list] = None):
        self._patterns = list(_CREDENTIAL_PATTERNS)
        if extra_patterns:
            self._patterns.extend(extra_patterns)

    def sanitize(self, text: str, context: str = "") -> SanitizationResult:
        """
        Run all credential patterns against text. Returns sanitized copy + metadata.
        Never raises — returns original text with a warning log on unexpected errors.
        """
        if not isinstance(text, str):
            text = str(text)

        original_hash = hashlib.sha256(text.encode()).hexdigest()
        result = text
        total_redactions = 0
        triggered = []

        for name, pattern, replacement in self._patterns:
            try:
                new_result, count = pattern.subn(replacement, result)
                if count:
                    total_redactions += count
                    triggered.append(name)
                    log.info(
                        f"[SHIELD] Redacted {count}x '{name}'"
                        + (f" in context={context}" if context else "")
                    )
                result = new_result
            except Exception as exc:
                log.warning(f"[SHIELD] Pattern '{name}' failed: {exc}")

        return SanitizationResult(
            sanitized_text=result,
            redaction_count=total_redactions,
            patterns_triggered=triggered,
            original_hash=original_hash,
        )

    def sanitize_dict(self, data: dict, context: str = "") -> dict:
        """Recursively sanitize string values in a dict (e.g., webhook payloads).

        A string under a secret-looking KEY ({"password": "x"},
        {"SecretAccessKey": "..."}) is redacted outright: scanned on its own,
        the value has no key next to it for any text pattern to recognise.
        """
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, str) and isinstance(k, str) and v and SECRET_KEY_NAME_RE.match(k):
                sanitized[k] = "[REDACTED:SECRET_VALUE]"
                log.info("[SHIELD] Redacted dict value under secret key" + (f" in context={context}" if context else ""))
            elif isinstance(v, str):
                sanitized[k] = self.sanitize(v, context=context).sanitized_text
            elif isinstance(v, dict):
                sanitized[k] = self.sanitize_dict(v, context=context)
            elif isinstance(v, list):
                sanitized[k] = [
                    self.sanitize(item, context=context).sanitized_text
                    if isinstance(item, str)
                    else item
                    for item in v
                ]
            else:
                sanitized[k] = v
        return sanitized


# Module-level singleton — import and call shield.sanitize() anywhere
shield = DataSanitizationShield()
