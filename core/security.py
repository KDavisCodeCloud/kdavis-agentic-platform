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
_CREDENTIAL_PATTERNS = [
    (
        "aws_access_key",
        re.compile(r"(?<![A-Z0-9])(AKIA[A-Z0-9]{16})(?![A-Z0-9])"),
        "[REDACTED:AWS_ACCESS_KEY]",
    ),
    (
        "aws_secret_key",
        # 40-char base64-ish string following common env var names
        re.compile(
            r"(?i)(aws_secret_access_key|aws_secret_key)\s*[=:]\s*['\"]?([A-Za-z0-9/+]{40})['\"]?"
        ),
        r"\1=[REDACTED:AWS_SECRET_KEY]",
    ),
    (
        "azure_client_secret",
        # Azure client secrets: 34–40 chars, tilde-prefixed or following env var name
        re.compile(
            r"(?i)(azure_client_secret|client_secret)\s*[=:]\s*['\"]?([A-Za-z0-9~._\-]{34,40})['\"]?"
        ),
        r"\1=[REDACTED:AZURE_CLIENT_SECRET]",
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
            r"(?im)^([A-Z_]*(KEY|SECRET|TOKEN|PASSWORD|PASS|CREDENTIAL)[A-Z_]*)\s*=\s*['\"]?(.+?)['\"]?\s*$"
        ),
        r"\1=[REDACTED:ENV_SECRET]",
    ),
    (
        "generic_api_key_header",
        # x-api-key: <value> or api-key: <value> in headers
        re.compile(r"(?i)(x-api-key|api[-_]key)\s*[=:]\s*['\"]?([A-Za-z0-9\-._~]{20,})['\"]?"),
        r"\1=[REDACTED:API_KEY]",
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
        """Recursively sanitize string values in a dict (e.g., webhook payloads)."""
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, str):
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
