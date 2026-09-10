"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Shared Fernet encrypt/decrypt helper, keyed by the ENCRYPTION_KEY env var.

Same mechanism already used independently in api/routes/content.py,
api/routes/internal_marketing.py, and agents/base_agent.py's _decrypt_byok —
this module is a shared home for *new* callers (starting with
api/routes/workspaces.py's BYOK key storage). The existing call sites are
left as-is; ciphertext is interchangeable either way since all of them use
plain Fernet against the same env var.
"""

import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise EnvironmentError("ENCRYPTION_KEY not set — cannot encrypt/decrypt")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
