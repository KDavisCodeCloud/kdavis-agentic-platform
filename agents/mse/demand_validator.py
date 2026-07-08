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
demand_validator — MSE pipeline step 2. Scores an opportunity_finder
candidate and, if it clears the bar, upserts it into mse_opportunities for
CEO dashboard review.

`go` is recomputed deterministically from demand_score/build_complexity
rather than trusting the LLM's self-reported bool — same "deterministic
validation" spirit as core/assertion.py, guards against the model stating
a `go` that contradicts its own scores.

mse_opportunities has no unique constraint (see db/migrations — `id` is a
fresh gen_random_uuid() every row), so there is no real conflict target to
upsert against; this calls .insert() and documents why rather than calling
.upsert() in a way that wouldn't actually update anything.
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
REQUIRED_KEYS = {"demand_score", "build_complexity", "weeks_to_revenue", "go", "reason"}
GO_DEMAND_SCORE_MIN = 7
GO_BUILD_COMPLEXITY_MAX = 6

LLMCompleteFn = Callable[..., Awaitable[Any]]


class DemandValidator:
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

    async def validate(self, opportunity: dict) -> dict:
        sanitized_json, _redactions = sanitize(json.dumps(opportunity), product_id=self.product_id)
        sanitized_opportunity = json.loads(sanitized_json)

        prompt = (
            f"Evaluate this micro SaaS concept: {json.dumps(sanitized_opportunity)}\n"
            'Return JSON: {"demand_score": int 1-10, "build_complexity": int 1-10, '
            '"weeks_to_revenue": int, "go": bool, "reason": str}\n'
            f"Base go=true on: demand_score >= {GO_DEMAND_SCORE_MIN} AND "
            f"build_complexity <= {GO_BUILD_COMPLEXITY_MAX}"
        )

        outcome = "ok"
        try:
            result = await self._llm_complete(
                prompt,
                task_type="mse_demand_validation",
                chain=["anthropic"],
                model=ANALYSIS_MODEL,
                max_tokens=1024,
            )
            validation = self._parse_validation(result.text)

            if validation["go"]:
                # Captures the DB-generated id so product_spec_writer can set
                # mse_product_specs.opportunity_id — the only reliable link,
                # since mse_opportunities has no natural unique key.
                validation["opportunity_id"] = self._insert_opportunity(opportunity, validation)

            return {**opportunity, **validation}
        except Exception:
            outcome = "error"
            raise
        finally:
            self._audit_log.append(
                actor="mse_demand_validator",
                action="mse_demand_validation",
                resource=opportunity.get("name", "unknown"),
                outcome=outcome,
                product_id=self.product_id,
                tenant_id=self.tenant_id,
            )

    def _parse_validation(self, raw_text: str) -> dict:
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            validation = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"demand_validator LLM response was not valid JSON: {exc} — raw: {raw_text[:300]}"
            ) from exc

        if not isinstance(validation, dict):
            raise ValueError(f"demand_validator expected a JSON object, got {type(validation).__name__}")

        missing = REQUIRED_KEYS - validation.keys()
        if missing:
            raise ValueError(f"demand_validator response missing required keys: {sorted(missing)}")

        demand_score = int(validation["demand_score"])
        build_complexity = int(validation["build_complexity"])
        if not (1 <= demand_score <= 10):
            raise ValueError(f"demand_validator demand_score out of range 1-10: {demand_score}")
        if not (1 <= build_complexity <= 10):
            raise ValueError(f"demand_validator build_complexity out of range 1-10: {build_complexity}")

        return {
            "demand_score": demand_score,
            "build_complexity": build_complexity,
            "weeks_to_revenue": int(validation["weeks_to_revenue"]),
            "go": demand_score >= GO_DEMAND_SCORE_MIN and build_complexity <= GO_BUILD_COMPLEXITY_MAX,
            "reason": str(validation["reason"]),
        }

    def _insert_opportunity(self, opportunity: dict, validation: dict) -> str:
        row = {
            "product_id": self.product_id,
            "name": opportunity.get("name"),
            "problem": opportunity.get("problem"),
            "target_user": opportunity.get("target_user"),
            "estimated_arr": opportunity.get("estimated_arr"),
            "competition_level": opportunity.get("competition_level"),
            "demand_score": validation["demand_score"],
            "build_complexity": validation["build_complexity"],
            "weeks_to_revenue": validation["weeks_to_revenue"],
            "go": validation["go"],
            "reason": validation["reason"],
        }
        result = self._supabase_or_default().table("mse_opportunities").insert(row).execute()
        if not result.data:
            raise RuntimeError(f"Failed to insert mse_opportunities row: {row}")
        return result.data[0]["id"]
