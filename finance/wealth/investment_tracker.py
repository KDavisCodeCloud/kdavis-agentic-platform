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
investment_tracker — records brokerage/retirement allocations you tell it
about (manual input only — no brokerage API integration) and reports the
wealth-building ratio (invested vs gross revenue). No buy/sell
recommendations, ever. Tracking and context only.
"""

import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

_id_counter = itertools.count(1)


class AccountType(str, Enum):
    EMERGENCY_FUND = "emergency_fund"
    SEP_IRA = "sep_ira"
    SOLO_401K = "solo_401k"
    ROTH_IRA = "roth_ira"
    TAXABLE_BROKERAGE = "taxable_brokerage"
    OTHER = "other"


@dataclass(frozen=True)
class InvestmentAllocation:
    account_type: AccountType
    institution: str
    amount: float
    allocation_date: date
    purpose: str = ""
    advisor_reviewed: bool = False
    id: int = field(default_factory=lambda: next(_id_counter))


@dataclass(frozen=True)
class WealthBuildingRatio:
    tax_year: int
    total_invested: float
    gross_revenue: float
    percent_invested: float
    message: str


_RATIO_CONTEXT = (
    (0.05, "Still early — most business owners increase this ratio as revenue stabilizes."),
    (0.15, "Solid — you're building alongside the business at a healthy pace."),
    (1.01, "Strong — a high share of revenue is going toward long-term wealth building."),
)


class InvestmentTracker:
    def __init__(self):
        self._allocations: list[InvestmentAllocation] = []

    def add_allocation(self, allocation: InvestmentAllocation) -> InvestmentAllocation:
        self._allocations.append(allocation)
        return allocation

    def all(self) -> list[InvestmentAllocation]:
        return list(self._allocations)

    def for_year(self, year: int) -> list[InvestmentAllocation]:
        return [a for a in self._allocations if a.allocation_date.year == year]

    def total_invested(self, year: int | None = None) -> float:
        allocations = self.for_year(year) if year is not None else self._allocations
        return round(sum(a.amount for a in allocations), 2)

    def by_account_type(self, year: int | None = None) -> dict[AccountType, float]:
        allocations = self.for_year(year) if year is not None else self._allocations
        totals: dict[AccountType, float] = defaultdict(float)
        for a in allocations:
            totals[a.account_type] += a.amount
        return dict(totals)

    def wealth_building_ratio(self, tax_year: int, gross_revenue: float) -> WealthBuildingRatio:
        total_invested = self.total_invested(tax_year)
        percent_invested = round(total_invested / gross_revenue, 4) if gross_revenue > 0 else 0.0
        context = next(text for threshold, text in _RATIO_CONTEXT if percent_invested < threshold)
        message = f"You invested {percent_invested:.1%} of gross revenue this year. {context}"
        return WealthBuildingRatio(
            tax_year=tax_year,
            total_invested=total_invested,
            gross_revenue=gross_revenue,
            percent_invested=percent_invested,
            message=message,
        )
