"""Unified LLM interface: prompt_in -> completion_out.

Every concrete provider (DeepSeek, OpenRouter, Anthropic) implements this
contract so providers/router.py can swap between them without any caller
knowing which vendor served the request.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderNotConfiguredError(RuntimeError):
    """Raised when a provider is invoked without its required API key set."""


class ProviderCallError(RuntimeError):
    """Raised when a configured provider's API call fails."""


@dataclass
class CompletionResult:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Base class every concrete provider extends."""

    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if this provider has the credentials it needs to run."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> CompletionResult:
        """Send prompt to the provider and return a normalized CompletionResult."""
