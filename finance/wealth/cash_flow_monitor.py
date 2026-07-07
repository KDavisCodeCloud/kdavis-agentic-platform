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
cash_flow_monitor — tracks monthly inflows vs outflows, sets aside a
recommended (not moved — informational only) tax reserve, and surfaces
the available surplus. Never moves money.
"""

from dataclasses import dataclass
from typing import Optional

DEFAULT_SURPLUS_OPPORTUNITY_THRESHOLD = 2_000.0
DEFAULT_EMERGENCY_FUND_TARGET_MONTHS = 6


@dataclass(frozen=True)
class CashFlowSummary:
    year: int
    month: int
    revenue: float
    expenses: float
    recommended_tax_reserve: float
    available_surplus: float


@dataclass(frozen=True)
class EmergencyFundStatus:
    target_amount: float
    current_amount: float
    percent_funded: float
    months_covered: float


class CashFlowMonitor:
    def monthly_summary(self, year: int, month: int, revenue: float, expenses: float, annual_estimated_tax: float) -> CashFlowSummary:
        """annual_estimated_tax: the current year's total estimated tax
        liability (e.g. sum of the four QuarterlyEstimate.estimated_total_tax
        values). Reserve is spread evenly across 12 months."""
        recommended_tax_reserve = round(annual_estimated_tax / 12, 2)
        available_surplus = round(revenue - expenses - recommended_tax_reserve, 2)
        return CashFlowSummary(
            year=year,
            month=month,
            revenue=revenue,
            expenses=expenses,
            recommended_tax_reserve=recommended_tax_reserve,
            available_surplus=available_surplus,
        )

    def emergency_fund_status(
        self, current_amount: float, avg_monthly_expenses: float,
        target_months: int = DEFAULT_EMERGENCY_FUND_TARGET_MONTHS,
    ) -> EmergencyFundStatus:
        target_amount = round(avg_monthly_expenses * target_months, 2)
        percent_funded = round(current_amount / target_amount, 4) if target_amount > 0 else 0.0
        months_covered = round(current_amount / avg_monthly_expenses, 1) if avg_monthly_expenses > 0 else 0.0
        return EmergencyFundStatus(
            target_amount=target_amount,
            current_amount=current_amount,
            percent_funded=percent_funded,
            months_covered=months_covered,
        )

    def surplus_opportunity_card(
        self, summary: CashFlowSummary, emergency_fund: Optional[EmergencyFundStatus] = None,
        threshold: float = DEFAULT_SURPLUS_OPPORTUNITY_THRESHOLD,
    ) -> Optional[dict]:
        """Fires when monthly surplus exceeds threshold — allocation
        priorities are informational context only, never a recommendation
        to act without a licensed advisor."""
        if summary.available_surplus <= threshold:
            return None

        allocation_priorities = ["Emergency fund", "SEP-IRA or Solo 401k contribution", "Taxable brokerage account", "Business reinvestment"]
        message = (
            f"You have an estimated ${summary.available_surplus:,.2f} available this month "
            "after expenses and tax reserve. Common allocation priorities at this stage: "
            f"{', '.join(allocation_priorities)}. Review with a licensed financial advisor before allocating."
        )
        if emergency_fund is not None:
            message += (
                f" Emergency fund: ${emergency_fund.current_amount:,.2f} of "
                f"${emergency_fund.target_amount:,.2f} target ({emergency_fund.percent_funded:.0%})."
            )
        return {
            "message": message,
            "allocation_priorities": allocation_priorities,
            "options": ["log_a_decision", "flag_for_advisor", "hold", "dismiss"],
        }
