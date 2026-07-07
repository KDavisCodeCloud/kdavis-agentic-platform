"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "products.yaml"

# ──────────────────────────────────────────────
# Built-in PII patterns
# ──────────────────────────────────────────────

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

# Candidate digit runs (13-19 digits, optionally grouped with spaces/dashes).
# Each candidate is validated with a Luhn check before being treated as a card.
_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")

# US (optional +1, optional parens) and generic international (leading +) formats.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)"
    r"|(?<!\d)\+\d{1,3}[-.\s]?\d{2,4}[-.\s]?\d{2,4}[-.\s]?\d{2,4}(?!\d)"
)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _redact_cards(text: str) -> tuple[str, int]:
    count = 0

    def _replace(match: re.Match) -> str:
        nonlocal count
        candidate = match.group(0)
        digits = re.sub(r"[ -]", "", candidate)
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            count += 1
            return "[REDACTED_CARD]"
        return candidate

    return _CARD_CANDIDATE_RE.sub(_replace, text), count


def _load_custom_patterns(product_id: Optional[str]) -> list[tuple[str, re.Pattern, str]]:
    """Load per-product custom PII patterns from config/products.yaml.

    Missing file, missing product entry, or malformed patterns are treated as
    "no custom patterns" rather than a hard failure — the built-in patterns
    still run.
    """
    if not product_id or not CONFIG_PATH.exists():
        return []

    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning(f"[SANITIZER] Could not load {CONFIG_PATH}: {exc}")
        return []

    product_cfg = (config.get("products") or {}).get(product_id) or {}
    entries = product_cfg.get("custom_pii_patterns") or []

    patterns = []
    for entry in entries:
        try:
            name = entry["name"]
            compiled = re.compile(entry["pattern"])
            replacement = entry.get("replacement", f"[REDACTED_{name.upper()}]")
            patterns.append((name, compiled, replacement))
        except (KeyError, re.error) as exc:
            log.warning(f"[SANITIZER] Skipping invalid custom pattern {entry!r}: {exc}")

    return patterns


class DataSanitizationShield:
    """
    Scrubs PII from text before it touches storage or an LLM.

    Built-in coverage: email addresses, SSNs, credit card numbers (Luhn-validated),
    and US/international phone numbers. Per-product custom patterns are loaded
    from config/products.yaml.
    """

    def sanitize(self, text: str, product_id: Optional[str] = None) -> tuple[str, list[dict]]:
        if not isinstance(text, str):
            text = str(text)

        redaction_log: list[dict] = []
        result = text

        result, card_count = _redact_cards(result)
        if card_count:
            redaction_log.append({"pattern": "credit_card", "count": card_count})

        result, ssn_count = _SSN_RE.subn("[REDACTED_SSN]", result)
        if ssn_count:
            redaction_log.append({"pattern": "ssn", "count": ssn_count})

        result, phone_count = _PHONE_RE.subn("[REDACTED_PHONE]", result)
        if phone_count:
            redaction_log.append({"pattern": "phone", "count": phone_count})

        result, email_count = _EMAIL_RE.subn("[REDACTED_EMAIL]", result)
        if email_count:
            redaction_log.append({"pattern": "email", "count": email_count})

        for name, pattern, replacement in _load_custom_patterns(product_id):
            result, count = pattern.subn(replacement, result)
            if count:
                redaction_log.append({"pattern": name, "count": count})

        return result, redaction_log


# Module-level singleton, mirroring core/security.py's convention.
shield = DataSanitizationShield()


def sanitize(text: str, product_id: Optional[str] = None) -> tuple[str, list[dict]]:
    """Convenience wrapper around the module-level `shield` singleton."""
    return shield.sanitize(text, product_id=product_id)
