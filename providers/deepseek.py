"""DeepSeek provider — primary: cheap, fast, high volume."""

from __future__ import annotations

import os
from typing import Any

from openai import AsyncOpenAI

from providers.base import (
    CompletionResult,
    LLMProvider,
    ProviderCallError,
    ProviderNotConfiguredError,
)

BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

# Published per-token rates, USD per 1M tokens (cache-miss pricing).
INPUT_COST_PER_1M = 0.27
OUTPUT_COST_PER_1M = 1.10


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model or os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)

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
            raise ProviderNotConfiguredError("DEEPSEEK_API_KEY is not set")

        client = AsyncOpenAI(api_key=self.api_key, base_url=BASE_URL)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            raise ProviderCallError(f"DeepSeek call failed: {exc}") from exc

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cost_usd = (
            (input_tokens / 1_000_000) * INPUT_COST_PER_1M
            + (output_tokens / 1_000_000) * OUTPUT_COST_PER_1M
        )

        return CompletionResult(
            text=response.choices[0].message.content or "",
            provider=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            raw=response.model_dump(),
        )
