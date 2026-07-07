"""Smoke test for providers/router.py — Session 1 HITL gate.

Confirms the router returns a real completion and logs which provider served
it. DeepSeek has no configured key in this environment, so this test proves
the fallback path: deepseek is skipped (unconfigured) and anthropic serves
the request.
"""

import pytest

from providers.router import complete


@pytest.mark.asyncio
async def test_router_returns_completion_and_falls_back_to_anthropic():
    result = await complete("Reply with exactly the word: pong", task_type="smoke_test")

    assert result.text.strip()
    assert result.provider == "anthropic"
    assert result.model
    assert result.input_tokens > 0
    assert result.output_tokens > 0
