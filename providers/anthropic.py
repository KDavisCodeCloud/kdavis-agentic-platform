"""Anthropic provider — fallback + think tank: complex reasoning."""

from __future__ import annotations

import os
from typing import Any

from anthropic import AsyncAnthropic

from providers.base import (
    CompletionResult,
    LLMProvider,
    ProviderCallError,
    ProviderNotConfiguredError,
)

DEFAULT_MODEL = "claude-sonnet-4-6"

# Published per-token rates, USD per 1M tokens.
INPUT_COST_PER_1M = 3.00
OUTPUT_COST_PER_1M = 15.00


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> CompletionResult:
        if not self.is_configured():
            raise ProviderNotConfiguredError("ANTHROPIC_API_KEY is not set")

        client = AsyncAnthropic(api_key=self.api_key)

        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise ProviderCallError(f"Anthropic call failed: {exc}") from exc

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost_usd = (
            (input_tokens / 1_000_000) * INPUT_COST_PER_1M
            + (output_tokens / 1_000_000) * OUTPUT_COST_PER_1M
        )

        text = "".join(
            block.text for block in response.content if block.type == "text"
        )

        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            raw=response.model_dump(),
        )
