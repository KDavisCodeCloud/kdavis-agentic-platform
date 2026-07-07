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
wealth_agent — monitors cash flow surplus, surfaces salary and
investment benchmarks for CPA/advisor review. Never moves money, never
gives financial advice. Every output carries the disclaimer.

Orchestrates: cash_flow_monitor, salary_advisor, investment_tracker,
and reuses deduction_tracker's comparison logic for the tax writeoff
surface (item 5 of the wealth_agent spec).
"""

from collections import defaultdict
from typing import Optional

from finance import disclaim
from finance.tax.deduction_tracker import DeductionFlag, DeductionTracker
from finance.wealth.cash_flow_monitor import (
    DEFAULT_SURPLUS_OPPORTUNITY_THRESHOLD,
    CashFlowMonitor,
)
from finance.wealth.investment_tracker import InvestmentAllocation, InvestmentTracker
from finance.wealth.salary_advisor import DEFAULT_MARKET_RATE_RANGE, EntityType, recommend_salary


class WealthAgent:
    def __init__(self, cash_flow_monitor: Optional[CashFlowMonitor] = None, investment_tracker: Optional[InvestmentTracker] = None):
        self._cash_flow_monitor = cash_flow_monitor or CashFlowMonitor()
        self._investment_tracker = investment_tracker or InvestmentTracker()
        self._deduction_tracker = DeductionTracker()

    def monthly_cash_flow(self, year: int, month: int, revenue: float, expenses: float, annual_estimated_tax: float) -> dict:
        summary = self._cash_flow_monitor.monthly_summary(year, month, revenue, expenses, annual_estimated_tax)
        return disclaim({
            "year": summary.year, "month": summary.month, "revenue": summary.revenue,
            "expenses": summary.expenses, "recommended_tax_reserve": summary.recommended_tax_reserve,
            "available_surplus": summary.available_surplus,
        })

    def surplus_opportunity_card(
        self, year: int, month: int, revenue: float, expenses: float, annual_estimated_tax: float,
        emergency_fund_current: Optional[float] = None, emergency_fund_avg_monthly_expenses: Optional[float] = None,
        threshold: float = DEFAULT_SURPLUS_OPPORTUNITY_THRESHOLD,
    ) -> Optional[dict]:
        summary = self._cash_flow_monitor.monthly_summary(year, month, revenue, expenses, annual_estimated_tax)
        emergency_fund_status = None
        if emergency_fund_current is not None and emergency_fund_avg_monthly_expenses:
            emergency_fund_status = self._cash_flow_monitor.emergency_fund_status(
                emergency_fund_current, emergency_fund_avg_monthly_expenses,
            )
        card = self._cash_flow_monitor.surplus_opportunity_card(summary, emergency_fund_status, threshold)
        return disclaim(card) if card else None

    def salary_recommendation(
        self, entity_type: EntityType, business_net_income: float,
        prior_salary: Optional[float] = None, market_rate_range: tuple[float, float] = DEFAULT_MARKET_RATE_RANGE,
    ) -> dict:
        recommendation = recommend_salary(entity_type, business_net_income, prior_salary, market_rate_range)
        return disclaim({
            "applies": recommendation.applies,
            "recommended_low": recommendation.recommended_low,
            "recommended_high": recommendation.recommended_high,
            "current_salary": recommendation.current_salary,
            "message": recommendation.message,
            "options": list(recommendation.options),
        })

    def record_allocation(self, allocation: InvestmentAllocation) -> dict:
        self._investment_tracker.add_allocation(allocation)
        return disclaim({"allocation_id": allocation.id})

    def wealth_building_ratio(self, tax_year: int, gross_revenue: float) -> dict:
        ratio = self._investment_tracker.wealth_building_ratio(tax_year, gross_revenue)
        return disclaim({
            "tax_year": ratio.tax_year, "total_invested": ratio.total_invested,
            "gross_revenue": ratio.gross_revenue, "percent_invested": ratio.percent_invested,
            "message": ratio.message,
        })

    def tax_writeoff_surface(self, current_flags: list[DeductionFlag], prior_flags: Optional[list[DeductionFlag]] = None) -> dict:
        by_category: dict[str, float] = defaultdict(float)
        for flag in current_flags:
            by_category[flag.category.value] += flag.estimated_amount
        messages = self._deduction_tracker.compare_to_prior_year(current_flags, prior_flags or [])
        return disclaim({
            "by_category": dict(by_category),
            "total": round(sum(by_category.values()), 2),
            "under_utilized_messages": messages,
        })
