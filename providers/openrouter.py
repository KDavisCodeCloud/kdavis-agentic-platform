"""OpenRouter provider — secondary: model flexibility."""

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

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4"
HTTP_REFERER = "https://github.com/KDavisCodeCloud/kdavis-agentic-platform"
X_TITLE = "KDavis Agentic Platform"


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)

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
            raise ProviderNotConfiguredError("OPENROUTER_API_KEY is not set")

        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=BASE_URL,
            default_headers={
                "HTTP-Referer": HTTP_REFERER,
                "X-Title": X_TITLE,
            },
        )
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
            raise ProviderCallError(f"OpenRouter call failed: {exc}") from exc

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        # Cost varies per underlying model routed through OpenRouter; only
        # available when the account has usage accounting enabled.
        cost_usd = float(getattr(usage, "cost", 0.0) or 0.0)

        return CompletionResult(
            text=response.choices[0].message.content or "",
            provider=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            raw=response.model_dump(),
        )
