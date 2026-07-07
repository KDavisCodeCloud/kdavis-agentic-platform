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
salary_advisor — surfaces a reasonable-compensation benchmark for
S-Corp/C-Corp owners (an IRS requirement for those entity types) using a
caller-supplied market rate range. This module has no salary survey data
of its own — pass in a market_rate_range sourced from an actual
benchmark (BLS, Glassdoor, Levels.fyi, etc.) rather than relying on the
default, which exists only so the function is callable without one.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# Placeholder only — replace with a sourced benchmark before relying on this.
DEFAULT_MARKET_RATE_RANGE = (110_000.0, 160_000.0)


class EntityType(str, Enum):
    SOLE_PROPRIETORSHIP = "sole_proprietorship"
    LLC_DISREGARDED = "llc_disregarded"
    S_CORP = "s_corp"
    C_CORP = "c_corp"


_REASONABLE_COMP_APPLIES = {
    EntityType.SOLE_PROPRIETORSHIP: False,
    EntityType.LLC_DISREGARDED: False,
    EntityType.S_CORP: True,
    EntityType.C_CORP: True,
}


@dataclass(frozen=True)
class SalaryRecommendation:
    entity_type: EntityType
    applies: bool
    recommended_low: Optional[float]
    recommended_high: Optional[float]
    current_salary: Optional[float]
    message: str
    options: tuple[str, ...] = ("flag_for_cpa", "already_reviewed", "hold_for_next_quarter")


def recommend_salary(
    entity_type: EntityType,
    business_net_income: float,
    prior_salary: Optional[float] = None,
    market_rate_range: tuple[float, float] = DEFAULT_MARKET_RATE_RANGE,
) -> SalaryRecommendation:
    if not _REASONABLE_COMP_APPLIES[entity_type]:
        return SalaryRecommendation(
            entity_type=entity_type,
            applies=False,
            recommended_low=None,
            recommended_high=None,
            current_salary=prior_salary,
            message=(
                "Reasonable compensation requirements generally apply to S-Corp/C-Corp payroll, "
                "not sole proprietorships or disregarded LLCs. Confirm entity classification with your CPA."
            ),
        )

    market_low, market_high = market_rate_range
    recommended_low = min(market_low, business_net_income) if business_net_income > 0 else 0.0
    recommended_high = min(market_high, business_net_income) if business_net_income > 0 else 0.0

    current_salary_clause = f"${prior_salary:,.0f}." if prior_salary is not None else "not on file."
    message = (
        f"Reasonable compensation benchmark for your role and revenue level: "
        f"${recommended_low:,.0f}-${recommended_high:,.0f}. "
        f"Current salary: {current_salary_clause} "
        "Discuss adjustment with your CPA before changing payroll."
    )

    if business_net_income < market_low:
        message += (
            f" Business net income (${business_net_income:,.0f}) is below the typical market range — "
            "discuss a minimum defensible reasonable-comp figure with your CPA."
        )

    return SalaryRecommendation(
        entity_type=entity_type,
        applies=True,
        recommended_low=round(recommended_low, 2),
        recommended_high=round(recommended_high, 2),
        current_salary=prior_salary,
        message=message,
    )
