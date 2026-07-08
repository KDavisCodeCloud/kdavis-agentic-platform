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
opportunity_finder — MSE pipeline step 1. Scans a niche for underserved
micro-SaaS opportunities using a cheap, high-volume model.

Routes through providers/router.py (never imports a concrete provider —
CLAUDE.md CORE PRINCIPLE 1). NOTE: providers/router.py's chain-based
design picks a *provider*, not a specific model within it — AnthropicProvider
fixes its model at construction (ANTHROPIC_MODEL env var or a hardcoded
default in providers/anthropic.py), and complete()'s **kwargs never reach
the messages.create() call. So `model=SCAN_MODEL` below is passed through
per CLAUDE.md's instruction but is NOT currently honored — every call
actually served by the anthropic branch uses whatever model that provider
was constructed with. Flagged for follow-up; out of scope here (task scope
is agents/mse/ and db/migrations/ only, not providers/anthropic.py).
"""

import json
import logging
from typing import Any, Awaitable, Callable, Optional

from providers.router import complete as router_complete
from security.audit_log import AuditLog
from security.sanitizer import sanitize

log = logging.getLogger(__name__)

DEFAULT_NICHE = "productivity/workflow automation"
SCAN_MODEL = "claude-haiku-4-5-20251001"
REQUIRED_KEYS = {"name", "problem", "target_user", "estimated_arr", "competition_level"}

LLMCompleteFn = Callable[..., Awaitable[Any]]


class OpportunityFinder:
    def __init__(
        self,
        product_id: str = "mse",
        tenant_id: str = "internal",
        audit_log: Optional[AuditLog] = None,
        llm_complete: Optional[LLMCompleteFn] = None,
    ):
        self.product_id = product_id
        self.tenant_id = tenant_id
        self._audit_log = audit_log or AuditLog()
        self._llm_complete = llm_complete or router_complete

    async def find(self, niche_hint: str = "") -> list[dict]:
        niche = niche_hint or DEFAULT_NICHE
        sanitized_niche, _redactions = sanitize(niche, product_id=self.product_id)

        prompt = (
            f"Find 5 underserved micro SaaS opportunities in the {sanitized_niche} space. "
            'Return JSON array: [{"name": str, "problem": str, "target_user": str, '
            '"estimated_arr": str, "competition_level": str}]'
        )

        outcome = "ok"
        try:
            result = await self._llm_complete(
                prompt,
                task_type="mse_opportunity_scan",
                chain=["anthropic"],
                model=SCAN_MODEL,
                max_tokens=2048,
            )
            return self._parse_opportunities(result.text)
        except Exception:
            outcome = "error"
            raise
        finally:
            self._audit_log.append(
                actor="mse_opportunity_finder",
                action="mse_opportunity_scan",
                resource=sanitized_niche,
                outcome=outcome,
                product_id=self.product_id,
                tenant_id=self.tenant_id,
            )

    def _parse_opportunities(self, raw_text: str) -> list[dict]:
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            opportunities = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"opportunity_finder LLM response was not valid JSON: {exc} — raw: {raw_text[:300]}"
            ) from exc

        if not isinstance(opportunities, list):
            raise ValueError(
                f"opportunity_finder expected a JSON array, got {type(opportunities).__name__}"
            )

        for i, item in enumerate(opportunities):
            if not isinstance(item, dict):
                raise ValueError(f"opportunity_finder item {i} is not an object: {item!r}")
            missing = REQUIRED_KEYS - item.keys()
            if missing:
                raise ValueError(f"opportunity_finder item {i} missing required keys: {sorted(missing)}")

        return opportunities
