"""Routes completions by task_type: DeepSeek primary, Anthropic fallback.

All LLM calls in this platform go through providers.router.complete(). Never
import a concrete provider (deepseek/openrouter/anthropic) from business logic.
"""

from __future__ import annotations

import logging
from typing import Any

from providers.anthropic import AnthropicProvider
from providers.base import CompletionResult, LLMProvider, ProviderCallError, ProviderNotConfiguredError
from providers.deepseek import DeepSeekProvider
from providers.openrouter import OpenRouterProvider

logger = logging.getLogger("providers.router")

DEFAULT_CHAIN = ["deepseek", "anthropic"]

_PROVIDERS: dict[str, LLMProvider] = {
    "deepseek": DeepSeekProvider(),
    "openrouter": OpenRouterProvider(),
    "anthropic": AnthropicProvider(),
}


async def complete(
    prompt: str,
    *,
    task_type: str = "default",
    chain: list[str] | None = None,
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    **kwargs: Any,
) -> CompletionResult:
    """Try each provider in `chain` in order until one returns a completion.

    Default chain is [deepseek, anthropic] per CLAUDE.md build sequence step 4.
    A provider is skipped (not retried) when it lacks its API key; a configured
    provider that raises is logged and the next provider in the chain is tried.
    """
    attempt_chain = chain or DEFAULT_CHAIN
    last_error: Exception | None = None

    for name in attempt_chain:
        provider = _PROVIDERS[name]

        if not provider.is_configured():
            logger.info(
                "router: skipping %s for task_type=%s (not configured)", name, task_type
            )
            continue

        try:
            result = await provider.complete(
                prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
        except (ProviderNotConfiguredError, ProviderCallError) as exc:
            logger.warning("router: %s failed for task_type=%s: %s", name, task_type, exc)
            last_error = exc
            continue

        logger.info(
            "router: task_type=%s served by %s (model=%s, cost=$%.6f)",
            task_type,
            result.provider,
            result.model,
            result.cost_usd,
        )
        return result

    raise ProviderCallError(
        f"All providers in chain {attempt_chain} failed or were unconfigured "
        f"for task_type={task_type}. Last error: {last_error}"
    )
