"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
BaseAgent — shared base class for all 10 commercial agents.

Every agent MUST:
- Inherit this class
- Call super().__init__() with db_conn, workspace_id, agent_id
- Use self.call_llm() for ALL LLM calls — never import provider SDKs directly
- Use self.hitl for HITL gate operations
"""

import os
import sys
import json
import time
import logging
import threading
import contextlib
import importlib.util
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from core.security import shield
from core.hitl import HITLGate
from core.compliance import WorkspaceComplianceGuard, SubscriptionError
from core.token_budget import TokenBudgetGuard, BudgetExceededError

log = logging.getLogger(__name__)

# LLM router loaded once and cached
_ROUTER_LOCK = threading.Lock()
_ROUTER_MODULE = None

# Per-provider env var names for BYOK injection
_BYOK_ENV_VARS = {
    "anthropic":  "ANTHROPIC_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# Lock ensures BYOK env var overrides don't race in concurrent requests.
# For multi-tenant production scale this should be replaced with a
# context-var-based approach or a router that accepts key overrides.
_BYOK_LOCK = threading.Lock()


def _load_router():
    """Load .llm/router.py once and cache the module."""
    global _ROUTER_MODULE
    if _ROUTER_MODULE is not None:
        return _ROUTER_MODULE
    with _ROUTER_LOCK:
        if _ROUTER_MODULE is not None:
            return _ROUTER_MODULE
        router_path = Path(__file__).parent.parent / ".llm" / "router.py"
        spec = importlib.util.spec_from_file_location("llm_router", router_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _ROUTER_MODULE = module
        log.info("[BaseAgent] LLM router loaded from %s", router_path)
    return _ROUTER_MODULE


@contextlib.contextmanager
def _byok_env_override(provider: str, decrypted_key: str):
    """
    Thread-safe temporary env var injection for BYOK.
    Holds _BYOK_LOCK for the duration of the LLM call.
    """
    env_var = _BYOK_ENV_VARS.get(provider)
    if not env_var or not decrypted_key:
        yield
        return

    with _BYOK_LOCK:
        original = os.environ.get(env_var)
        os.environ[env_var] = decrypted_key
        try:
            yield
        finally:
            if original is not None:
                os.environ[env_var] = original
            elif env_var in os.environ:
                del os.environ[env_var]


class BaseAgent(ABC):
    """
    Shared base class for all Cloud Decoded commercial agents.

    Provides:
    - call_llm()       — routes through .llm/router.py, enforces sanitization + budget
    - hitl             — HITLGate instance for create/approve incident lifecycle
    - compliance       — WorkspaceComplianceGuard for subscription checks
    - budget           — TokenBudgetGuard for circuit breaking
    - _write_audit()   — appends to knowledge/operator/llm-audit.md
    """

    AGENT_ID: str = "base_agent"  # override in each subclass

    def __init__(self, db_conn, workspace_id: str):
        self.db = db_conn
        self.workspace_id = workspace_id
        self.agent_id = self.__class__.AGENT_ID
        self.hitl = HITLGate(db_conn)
        self.compliance = WorkspaceComplianceGuard(db_conn)
        self.budget = TokenBudgetGuard(db_conn)
        self._router = _load_router()

    # ──────────────────────────────────────────────
    # Core LLM call — the ONLY entry point to the router
    # ──────────────────────────────────────────────

    def call_llm(
        self,
        task_type: str,
        messages: list[dict],
        system_prompt: str = "",
        provider_override: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        byok_encrypted_key: Optional[str] = None,
    ) -> tuple[str, int]:
        """
        Sanitize inputs, inject BYOK key if present, call router.complete().
        Returns (response_text, estimated_token_count).

        Governance Rule 6: ALL LLM calls route through .llm/router.py.
        Governance Rule 9: Usage is logged here and via the router's own audit.
        """
        # Sanitize all message content before reaching the LLM
        sanitized_messages = []
        for msg in messages:
            content = msg.get("content", "")
            result = shield.sanitize(str(content), context=self.agent_id)
            if result.redaction_count > 0:
                log.info(
                    "[%s] Sanitized %d credential(s) from message before LLM call",
                    self.agent_id, result.redaction_count
                )
            sanitized_messages.append({**msg, "content": result.sanitized_text})

        # Also sanitize system prompt
        if system_prompt:
            sp_result = shield.sanitize(system_prompt, context=f"{self.agent_id}:system_prompt")
            system_prompt = sp_result.sanitized_text

        # Resolve BYOK key if present
        decrypted_key = None
        provider = provider_override or "anthropic"
        if byok_encrypted_key:
            decrypted_key = self._decrypt_byok(byok_encrypted_key)

        # Call router — optionally with BYOK env override
        start = time.time()
        with _byok_env_override(provider, decrypted_key):
            response = self._router.complete(
                task_type=task_type,
                messages=sanitized_messages,
                system_prompt=system_prompt,
                provider_override=provider_override,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        elapsed = round(time.time() - start, 2)

        # Rough token estimate: ~0.75 tokens per character for English text
        input_chars = sum(len(m.get("content", "")) for m in sanitized_messages)
        output_chars = len(response)
        estimated_tokens = int((input_chars + output_chars) / 3)

        log.info(
            "[%s] LLM call complete — task=%s elapsed=%.2fs ~tokens=%d",
            self.agent_id, task_type, elapsed, estimated_tokens
        )
        return response, estimated_tokens

    def parse_llm_json(self, response: str, context: str = "") -> dict:
        """Parse JSON from LLM response, stripping markdown fences."""
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError as exc:
            log.warning(
                "[%s] Failed to parse LLM JSON in %s: %s — raw: %s",
                self.agent_id, context, exc, response[:300]
            )
            raise ValueError(f"LLM did not return valid JSON: {exc}") from exc

    # ──────────────────────────────────────────────
    # HITL helpers
    # ──────────────────────────────────────────────

    async def create_incident(
        self,
        raw_log: str,
        parsed_error: str,
        remediation_options: list[dict],
        cloud_provider: Optional[str] = None,
        tokens_used: int = 0,
        estimated_duration_seconds: Optional[int] = None,
    ) -> str:
        """Create a HITL incident and return the incident_id."""
        incident_id = await self.hitl.create_incident(
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            raw_log=raw_log,
            parsed_error=parsed_error,
            remediation_options=remediation_options,
            cloud_provider=cloud_provider,
            tokens_used=tokens_used,
            estimated_duration_seconds=estimated_duration_seconds,
        )
        return incident_id

    # ──────────────────────────────────────────────
    # Budget helpers
    # ──────────────────────────────────────────────

    async def check_budget(self, estimated_tokens: int = 5000, model: str = "default") -> None:
        """Raise BudgetExceededError if workspace is over budget."""
        await self.budget.assert_budget_available(self.workspace_id, estimated_tokens, model)

    async def record_token_usage(
        self,
        tokens_used: int,
        model: str = "default",
        incident_id: Optional[str] = None,
    ) -> None:
        await self.budget.record_usage(
            workspace_id=self.workspace_id,
            tokens_used=tokens_used,
            model=model,
            incident_id=incident_id,
            agent_id=self.agent_id,
        )

    # ──────────────────────────────────────────────
    # Audit logging
    # ──────────────────────────────────────────────

    def _write_audit(
        self,
        action: str,
        status: str,
        tokens_used: int = 0,
        incident_id: Optional[str] = None,
    ) -> None:
        """
        Append an audit entry to knowledge/operator/llm-audit.md.
        Governance Rule 9: every agent action writes to audit log.
        Format: [TIMESTAMP] [AGENT] [WORKSPACE_ID] [ACTION] [STATUS] [TOKENS_USED]
        """
        log_path = Path(__file__).parent.parent / "knowledge" / "operator" / "llm-audit.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"| {timestamp} | {self.agent_id} | {self.workspace_id[:8]}... | "
            f"{action} | {status}"
            + (f" | incident:{incident_id}" if incident_id else "")
            + f" | {tokens_used} |\n"
        )
        if not log_path.exists():
            with open(log_path, "w") as f:
                f.write("# LLM Audit Log\n\n")
                f.write("| Timestamp | Agent | Workspace | Action | Status | Tokens |\n")
                f.write("|-----------|-------|-----------|--------|--------|--------|\n")
        with open(log_path, "a") as f:
            f.write(entry)

    # ──────────────────────────────────────────────
    # BYOK decryption
    # ──────────────────────────────────────────────

    def _decrypt_byok(self, encrypted_key: str) -> str:
        encryption_key = os.environ.get("ENCRYPTION_KEY")
        if not encryption_key:
            raise EnvironmentError("ENCRYPTION_KEY not set — cannot decrypt BYOK key")
        f = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        return f.decrypt(encrypted_key.encode()).decode()

    # ──────────────────────────────────────────────
    # Abstract interface — each agent implements this
    # ──────────────────────────────────────────────

    @abstractmethod
    async def run(self, payload: dict, byok_encrypted_key: Optional[str] = None) -> str:
        """
        Execute the agent workflow.
        Returns incident_id. The caller polls GET /incidents/{id} for status.
        """
        ...
