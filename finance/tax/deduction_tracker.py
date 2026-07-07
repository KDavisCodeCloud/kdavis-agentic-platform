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
deduction_tracker — surfaces potential deductions by category and year.
Never claims eligibility on its own behalf; every flag carries
"Confirm with CPA before claiming." IRS dollar limits below are cited
from the 2024/2025 tax years and must be re-verified for the current
tax year before being relied on.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from finance.accounting.expense_categorizer import IRSCategory

CONFIRM_WITH_CPA = "Confirm with CPA before claiming."

# 2024 SEP-IRA / Solo 401k employee+employer combined limit — verify current year.
DEFAULT_RETIREMENT_CONTRIBUTION_LIMIT = 69_000.0
DEFAULT_RETIREMENT_CONTRIBUTION_PCT_OF_NET_SE = 0.25

# IRS simplified home office method — verify current year.
HOME_OFFICE_SIMPLIFIED_RATE_PER_SQFT = 5.0
HOME_OFFICE_SIMPLIFIED_MAX_SQFT = 300

# Verify current-year IRS standard mileage rate before relying on this default.
DEFAULT_STANDARD_MILEAGE_RATE = 0.67


class DeductionCategory(str, Enum):
    HOME_OFFICE = "Home_Office"
    VEHICLE_MILEAGE = "Vehicle_Mileage"
    SOFTWARE_SUBSCRIPTIONS = "Software_Subscriptions"
    EDUCATION_TRAINING = "Education_Training"
    HEALTH_INSURANCE_PREMIUMS = "Health_Insurance_Premiums"
    RETIREMENT_CONTRIBUTIONS = "Retirement_Contributions"
    HOME_INTERNET = "Home_Internet"
    EQUIPMENT_DEPRECIATION = "Equipment_Depreciation"
    PROFESSIONAL_SERVICES = "Professional_Services"
    ADVERTISING = "Advertising"


# Straight pass-through expense categories that count toward a deduction
# 1:1 with high confidence — no special eligibility test required.
_DIRECT_EXPENSE_CATEGORIES: dict[IRSCategory, tuple[DeductionCategory, float]] = {
    IRSCategory.SOFTWARE_SUBSCRIPTIONS: (DeductionCategory.SOFTWARE_SUBSCRIPTIONS, 0.9),
    IRSCategory.EDUCATION_TRAINING: (DeductionCategory.EDUCATION_TRAINING, 0.85),
    IRSCategory.PROFESSIONAL_SERVICES: (DeductionCategory.PROFESSIONAL_SERVICES, 0.9),
    IRSCategory.ADVERTISING: (DeductionCategory.ADVERTISING, 0.9),
}


@dataclass(frozen=True)
class DeductionFlag:
    tax_year: int
    category: DeductionCategory
    description: str
    estimated_amount: float
    confidence: float
    note: str = CONFIRM_WITH_CPA


class DeductionTracker:
    def scan_expenses(self, expenses: list[dict], tax_year: int) -> list[DeductionFlag]:
        """expenses: dicts shaped like the `expenses` table row
        (irs_category, amount, tax_year, vendor)."""
        totals: dict[IRSCategory, float] = defaultdict(float)
        for exp in expenses:
            if exp.get("tax_year") != tax_year:
                continue
            try:
                category = IRSCategory(exp["irs_category"])
            except (KeyError, ValueError):
                continue
            totals[category] += exp.get("amount", 0.0)

        flags: list[DeductionFlag] = []
        for irs_category, (deduction_category, confidence) in _DIRECT_EXPENSE_CATEGORIES.items():
            amount = totals.get(irs_category, 0.0)
            if amount <= 0:
                continue
            flags.append(DeductionFlag(
                tax_year=tax_year,
                category=deduction_category,
                description=f"{deduction_category.value} tracked from recorded expenses",
                estimated_amount=round(amount, 2),
                confidence=confidence,
            ))
        return flags

    def flag_home_office(
        self, tax_year: int, has_dedicated_workspace: bool,
        office_sqft: Optional[float] = None,
    ) -> Optional[DeductionFlag]:
        if not has_dedicated_workspace:
            return None
        sqft = min(office_sqft or 0.0, HOME_OFFICE_SIMPLIFIED_MAX_SQFT)
        estimated_amount = sqft * HOME_OFFICE_SIMPLIFIED_RATE_PER_SQFT
        return DeductionFlag(
            tax_year=tax_year,
            category=DeductionCategory.HOME_OFFICE,
            description=(
                "Dedicated workspace reported. Simplified method estimate shown — "
                "CPA should compare against actual-expense method and confirm eligibility."
            ),
            estimated_amount=round(estimated_amount, 2),
            confidence=0.6,
        )

    def flag_vehicle_mileage(
        self, tax_year: int, business_miles: float,
        standard_mileage_rate: float = DEFAULT_STANDARD_MILEAGE_RATE,
    ) -> Optional[DeductionFlag]:
        if business_miles <= 0:
            return None
        estimated_amount = business_miles * standard_mileage_rate
        return DeductionFlag(
            tax_year=tax_year,
            category=DeductionCategory.VEHICLE_MILEAGE,
            description=(
                f"{business_miles:.0f} business miles logged. Standard mileage method shown — "
                "CPA should compare against actual vehicle cost method."
            ),
            estimated_amount=round(estimated_amount, 2),
            confidence=0.7,
        )

    def flag_health_insurance(self, tax_year: int, premiums_paid: float) -> Optional[DeductionFlag]:
        if premiums_paid <= 0:
            return None
        return DeductionFlag(
            tax_year=tax_year,
            category=DeductionCategory.HEALTH_INSURANCE_PREMIUMS,
            description="Self-employed health insurance premiums paid — eligibility depends on entity structure.",
            estimated_amount=round(premiums_paid, 2),
            confidence=0.75,
        )

    def flag_retirement_contributions(
        self, tax_year: int, contributions: float, net_se_income: Optional[float] = None,
    ) -> Optional[DeductionFlag]:
        if contributions <= 0:
            return None
        limit = DEFAULT_RETIREMENT_CONTRIBUTION_LIMIT
        if net_se_income is not None:
            limit = min(limit, net_se_income * DEFAULT_RETIREMENT_CONTRIBUTION_PCT_OF_NET_SE)
        capped_amount = min(contributions, limit)
        description = "SEP-IRA / Solo 401k contribution tracked."
        if contributions > limit:
            description += f" Contribution exceeds estimated limit (${limit:,.0f}) — flag for CPA immediately."
        return DeductionFlag(
            tax_year=tax_year,
            category=DeductionCategory.RETIREMENT_CONTRIBUTIONS,
            description=description,
            estimated_amount=round(capped_amount, 2),
            confidence=0.8,
        )

    def flag_home_internet(
        self, tax_year: int, monthly_bill: float, business_use_percent: float,
    ) -> Optional[DeductionFlag]:
        if monthly_bill <= 0 or business_use_percent <= 0:
            return None
        estimated_amount = monthly_bill * 12 * min(business_use_percent, 1.0)
        return DeductionFlag(
            tax_year=tax_year,
            category=DeductionCategory.HOME_INTERNET,
            description=f"Home internet at {business_use_percent:.0%} business use.",
            estimated_amount=round(estimated_amount, 2),
            confidence=0.65,
        )

    def flag_equipment_depreciation(self, tax_year: int, equipment_expenses: list[dict]) -> Optional[DeductionFlag]:
        total = sum(
            exp.get("amount", 0.0) for exp in equipment_expenses
            if exp.get("tax_year") == tax_year and exp.get("irs_category") == IRSCategory.EQUIPMENT.value
        )
        if total <= 0:
            return None
        return DeductionFlag(
            tax_year=tax_year,
            category=DeductionCategory.EQUIPMENT_DEPRECIATION,
            description="Equipment purchases tracked — may qualify for Section 179 or bonus depreciation.",
            estimated_amount=round(total, 2),
            confidence=0.6,
        )

    def compare_to_prior_year(
        self, current_flags: list[DeductionFlag], prior_flags: list[DeductionFlag],
    ) -> list[str]:
        """Surfaces categories claimed last year but missing or smaller this year."""
        prior_by_category = {f.category: f.estimated_amount for f in prior_flags}
        current_by_category = {f.category: f.estimated_amount for f in current_flags}
        messages: list[str] = []
        for category, prior_amount in prior_by_category.items():
            current_amount = current_by_category.get(category, 0.0)
            if prior_amount > 0 and current_amount == 0:
                messages.append(
                    f"{category.value} deduction not yet documented this year "
                    f"(tracked ${prior_amount:,.2f} last year) — confirm eligibility with your CPA."
                )
            elif prior_amount > 0 and current_amount < prior_amount * 0.5:
                messages.append(
                    f"{category.value} tracked at ${current_amount:,.2f} so far, "
                    f"well below last year's ${prior_amount:,.2f} — worth double-checking with your CPA."
                )
        return messages
