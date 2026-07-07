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
tax_agent — tracks potential deductions, estimates quarterly liability,
packages year-end documents. Never files anything. Every output carries
the CPA/advisor disclaimer.

Orchestrates: deduction_tracker, quarterly_estimator, year_end_packager.
"""

from typing import Optional

from finance import disclaim
from finance.accounting.expense_categorizer import IRSCategory
from finance.accounting.invoice_tracker import InvoiceTracker
from finance.accounting.revenue_ledger import RevenueLedger
from finance.tax.deduction_tracker import DeductionFlag, DeductionTracker
from finance.tax.quarterly_estimator import QuarterlyEstimate, estimate_quarter
from finance.tax.year_end_packager import YearEndPackage, YearEndPackager


class TaxAgent:
    def __init__(self, deduction_tracker: Optional[DeductionTracker] = None, year_end_packager: Optional[YearEndPackager] = None):
        self._deduction_tracker = deduction_tracker or DeductionTracker()
        self._year_end_packager = year_end_packager or YearEndPackager()
        self._deduction_flags_by_year: dict[int, list[DeductionFlag]] = {}

    def track_deductions(
        self,
        tax_year: int,
        expenses: list[dict],
        has_dedicated_workspace: bool = False,
        office_sqft: Optional[float] = None,
        business_miles: float = 0.0,
        health_insurance_premiums: float = 0.0,
        retirement_contributions: float = 0.0,
        net_se_income: Optional[float] = None,
        home_internet_monthly_bill: float = 0.0,
        home_internet_business_use_percent: float = 0.0,
    ) -> dict:
        flags = self._deduction_tracker.scan_expenses(expenses, tax_year)
        flags.extend(f for f in [
            self._deduction_tracker.flag_home_office(tax_year, has_dedicated_workspace, office_sqft),
            self._deduction_tracker.flag_vehicle_mileage(tax_year, business_miles),
            self._deduction_tracker.flag_health_insurance(tax_year, health_insurance_premiums),
            self._deduction_tracker.flag_retirement_contributions(tax_year, retirement_contributions, net_se_income),
            self._deduction_tracker.flag_home_internet(tax_year, home_internet_monthly_bill, home_internet_business_use_percent),
            self._deduction_tracker.flag_equipment_depreciation(tax_year, expenses),
        ] if f is not None)

        self._deduction_flags_by_year[tax_year] = flags
        return disclaim({
            "tax_year": tax_year,
            "deductions": [
                {"category": f.category.value, "description": f.description, "estimated_amount": f.estimated_amount, "confidence": f.confidence}
                for f in flags
            ],
            "total_estimated": round(sum(f.estimated_amount for f in flags), 2),
        })

    def deduction_flags_for_year(self, tax_year: int) -> list[DeductionFlag]:
        return self._deduction_flags_by_year.get(tax_year, [])

    def under_utilized_categories(self, tax_year: int, prior_tax_year: int) -> dict:
        current = self.deduction_flags_for_year(tax_year)
        prior = self.deduction_flags_for_year(prior_tax_year)
        return disclaim({"messages": self._deduction_tracker.compare_to_prior_year(current, prior)})

    def quarterly_estimate_card(
        self, tax_year: int, quarter: int, ytd_net_income: float,
        prior_year_tax: Optional[float] = None, prior_year_agi: Optional[float] = None,
    ) -> dict:
        estimate: QuarterlyEstimate = estimate_quarter(tax_year, quarter, ytd_net_income, prior_year_tax, prior_year_agi)
        return disclaim({
            "tax_year": estimate.tax_year,
            "quarter": estimate.quarter,
            "ytd_net_income": estimate.ytd_net_income,
            "self_employment_tax": estimate.self_employment_tax.total,
            "estimated_income_tax": estimate.estimated_income_tax,
            "estimated_total_tax": estimate.estimated_total_tax,
            "recommended_quarterly_payment": estimate.recommended_quarterly_payment,
            "due_date": estimate.due_date.isoformat(),
            "payment_url": estimate.payment_url,
            "options": ["ive_paid_this", "need_to_adjust", "flag_for_cpa_review"],
        })

    def year_end_package(
        self,
        tax_year: int,
        revenue_ledger: RevenueLedger,
        invoice_tracker: InvoiceTracker,
        quarterly_estimates: list[QuarterlyEstimate],
        receipts_by_category: dict[IRSCategory, list[str]],
        contractor_payments: dict[str, float],
    ) -> dict:
        flags = self.deduction_flags_for_year(tax_year)
        package: YearEndPackage = self._year_end_packager.build(
            tax_year, revenue_ledger, invoice_tracker, flags, quarterly_estimates, receipts_by_category, contractor_payments,
        )
        return disclaim({
            "summary_message": package.summary_message,
            "folder": package.folder,
            "contractor_1099_candidates": [
                {"vendor": c.vendor, "total_paid": c.total_paid} for c in package.contractor_1099_candidates
            ],
            "package": package,
        })
