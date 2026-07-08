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
product_spec_writer — MSE pipeline step 3. Writes a 1-page product spec
for a validated (go=True) opportunity and inserts it into
mse_product_specs, linked to its mse_opportunities row.
"""

import json
import logging
import os
from typing import Any, Awaitable, Callable, Optional

from providers.router import complete as router_complete
from security.audit_log import AuditLog
from security.sanitizer import sanitize

log = logging.getLogger(__name__)

ANALYSIS_MODEL = "claude-sonnet-4-6"
STACK = "Next.js 15, FastAPI, Supabase, Stripe"
REQUIRED_KEYS = {"product_name", "problem", "icp", "features", "price_monthly", "stack_notes", "milestones"}
FEATURES_COUNT = 5
MILESTONES_COUNT = 3

LLMCompleteFn = Callable[..., Awaitable[Any]]


class ProductSpecWriter:
    def __init__(
        self,
        product_id: str = "mse",
        tenant_id: str = "internal",
        audit_log: Optional[AuditLog] = None,
        llm_complete: Optional[LLMCompleteFn] = None,
        supabase_client: Optional[Any] = None,
    ):
        self.product_id = product_id
        self.tenant_id = tenant_id
        self._audit_log = audit_log or AuditLog()
        self._llm_complete = llm_complete or router_complete
        self._supabase = supabase_client

    def _supabase_or_default(self) -> Any:
        if self._supabase is None:
            from supabase import create_client

            self._supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        return self._supabase

    async def write_spec(self, validated_opportunity: dict) -> dict:
        if not validated_opportunity.get("go"):
            raise ValueError(
                "product_spec_writer.write_spec() called with go != True — "
                "only validated (go=True) opportunities get a spec"
            )

        sanitized_json, _redactions = sanitize(json.dumps(validated_opportunity), product_id=self.product_id)
        sanitized_opportunity = json.loads(sanitized_json)

        prompt = (
            f"Write a 1-page product spec for: {json.dumps(sanitized_opportunity)}\n"
            f"Stack must be: {STACK} (per CLAUDE.md)\n"
            'Return JSON: {"product_name": str, "problem": str, "icp": str, '
            '"features": [str x5], "price_monthly": int, "stack_notes": str, '
            '"milestones": [str x3]}'
        )

        outcome = "ok"
        try:
            result = await self._llm_complete(
                prompt,
                task_type="mse_product_spec",
                chain=["anthropic"],
                model=ANALYSIS_MODEL,
                max_tokens=2048,
            )
            spec = self._parse_spec(result.text)
            self._insert_spec(spec, opportunity_id=validated_opportunity.get("opportunity_id"))
            return spec
        except Exception:
            outcome = "error"
            raise
        finally:
            self._audit_log.append(
                actor="mse_product_spec_writer",
                action="mse_product_spec",
                resource=validated_opportunity.get("name", "unknown"),
                outcome=outcome,
                product_id=self.product_id,
                tenant_id=self.tenant_id,
            )

    def _parse_spec(self, raw_text: str) -> dict:
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            spec = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"product_spec_writer LLM response was not valid JSON: {exc} — raw: {raw_text[:300]}"
            ) from exc

        if not isinstance(spec, dict):
            raise ValueError(f"product_spec_writer expected a JSON object, got {type(spec).__name__}")

        missing = REQUIRED_KEYS - spec.keys()
        if missing:
            raise ValueError(f"product_spec_writer response missing required keys: {sorted(missing)}")

        features = spec["features"]
        if not isinstance(features, list) or len(features) != FEATURES_COUNT:
            raise ValueError(f"product_spec_writer expected {FEATURES_COUNT} features, got {features!r}")

        milestones = spec["milestones"]
        if not isinstance(milestones, list) or len(milestones) != MILESTONES_COUNT:
            raise ValueError(f"product_spec_writer expected {MILESTONES_COUNT} milestones, got {milestones!r}")

        return {
            "product_name": str(spec["product_name"]),
            "problem": str(spec["problem"]),
            "icp": str(spec["icp"]),
            "features": [str(f) for f in features],
            "price_monthly": int(spec["price_monthly"]),
            "stack_notes": str(spec["stack_notes"]),
            "milestones": [str(m) for m in milestones],
        }

    def _insert_spec(self, spec: dict, opportunity_id: Optional[str]) -> None:
        row = {
            "product_id": self.product_id,
            "opportunity_id": opportunity_id,
            "product_name": spec["product_name"],
            "problem": spec["problem"],
            "icp": spec["icp"],
            "features": spec["features"],
            "price_monthly": spec["price_monthly"],
            "stack_notes": spec["stack_notes"],
            "milestones": spec["milestones"],
        }
        result = self._supabase_or_default().table("mse_product_specs").insert(row).execute()
        if not result.data:
            raise RuntimeError(f"Failed to insert mse_product_specs row: {row}")
