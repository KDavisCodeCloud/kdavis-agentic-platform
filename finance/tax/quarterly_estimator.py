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
quarterly_estimator — rough, safe-harbor-based quarterly estimated tax
calculation for a self-employed / pass-through entity owner.

This is intentionally a simplified approximation (flat effective rate for
income tax, standard self-employment tax formula). It exists to give a
directional number and a recommended payment — not a filing-ready figure.
Every IRS-figure constant below (wage base, thresholds) should be
confirmed against the current tax year before being trusted; pass
overrides explicitly rather than relying on the defaults for anything
but a rough check.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

# 2025 figures — verify against the current IRS tax year before use.
DEFAULT_SS_WAGE_BASE = 176_100.0
DEFAULT_ADDITIONAL_MEDICARE_THRESHOLD = 200_000.0  # single filer threshold
SE_TAX_NET_EARNINGS_FACTOR = 0.9235
SOCIAL_SECURITY_RATE = 0.124
MEDICARE_RATE = 0.029
ADDITIONAL_MEDICARE_RATE = 0.009

# IRS Direct Pay — verify link is current before surfacing to the user.
IRS_ESTIMATED_PAYMENT_URL = "https://www.irs.gov/payments/direct-pay"

# (month, day) each quarter's estimated payment is due. Q4 is due
# January 15 of the *following* calendar year.
_QUARTER_DUE_DATE: dict[int, tuple[int, int]] = {1: (4, 15), 2: (6, 15), 3: (9, 15), 4: (1, 15)}


@dataclass(frozen=True)
class SelfEmploymentTax:
    net_se_earnings: float
    social_security: float
    medicare: float
    additional_medicare: float
    total: float


@dataclass(frozen=True)
class QuarterlyEstimate:
    tax_year: int
    quarter: int
    ytd_net_income: float
    self_employment_tax: SelfEmploymentTax
    estimated_income_tax: float
    estimated_total_tax: float
    recommended_quarterly_payment: float
    due_date: date
    payment_url: str
    note: str = "Estimate only. Confirm with your CPA."


def calculate_self_employment_tax(
    net_profit: float,
    ss_wage_base: float = DEFAULT_SS_WAGE_BASE,
    additional_medicare_threshold: float = DEFAULT_ADDITIONAL_MEDICARE_THRESHOLD,
) -> SelfEmploymentTax:
    net_se_earnings = max(0.0, net_profit) * SE_TAX_NET_EARNINGS_FACTOR
    social_security = min(net_se_earnings, ss_wage_base) * SOCIAL_SECURITY_RATE
    medicare = net_se_earnings * MEDICARE_RATE
    additional_medicare = max(0.0, net_se_earnings - additional_medicare_threshold) * ADDITIONAL_MEDICARE_RATE
    total = social_security + medicare + additional_medicare
    return SelfEmploymentTax(
        net_se_earnings=round(net_se_earnings, 2),
        social_security=round(social_security, 2),
        medicare=round(medicare, 2),
        additional_medicare=round(additional_medicare, 2),
        total=round(total, 2),
    )


def safe_harbor_annual_target(
    current_year_estimated_tax: float,
    prior_year_tax: Optional[float] = None,
    prior_year_agi: Optional[float] = None,
) -> float:
    """Smaller of 90% of this year's estimated tax or 100%/110% of last
    year's tax (110% if prior AGI exceeded $150k) — the IRS safe harbor."""
    current_year_target = current_year_estimated_tax * 0.90
    if prior_year_tax is None:
        return current_year_target
    multiplier = 1.10 if (prior_year_agi or 0) > 150_000 else 1.00
    return min(current_year_target, prior_year_tax * multiplier)


def _due_date(tax_year: int, quarter: int) -> date:
    month, day = _QUARTER_DUE_DATE[quarter]
    due_year = tax_year + 1 if quarter == 4 else tax_year
    return date(due_year, month, day)


def estimate_quarter(
    tax_year: int,
    quarter: int,
    ytd_net_income: float,
    prior_year_tax: Optional[float] = None,
    prior_year_agi: Optional[float] = None,
    effective_income_tax_rate: float = 0.22,
    ss_wage_base: float = DEFAULT_SS_WAGE_BASE,
    additional_medicare_threshold: float = DEFAULT_ADDITIONAL_MEDICARE_THRESHOLD,
) -> QuarterlyEstimate:
    if quarter not in (1, 2, 3, 4):
        raise ValueError("quarter must be 1-4")

    se_tax = calculate_self_employment_tax(ytd_net_income, ss_wage_base, additional_medicare_threshold)
    se_deduction = se_tax.total * 0.5
    taxable_income_estimate = max(0.0, ytd_net_income - se_deduction)
    estimated_income_tax = round(taxable_income_estimate * effective_income_tax_rate, 2)
    estimated_total_tax = round(se_tax.total + estimated_income_tax, 2)

    annual_target = safe_harbor_annual_target(estimated_total_tax, prior_year_tax, prior_year_agi)
    recommended_quarterly_payment = round(annual_target / 4, 2)

    return QuarterlyEstimate(
        tax_year=tax_year,
        quarter=quarter,
        ytd_net_income=ytd_net_income,
        self_employment_tax=se_tax,
        estimated_income_tax=estimated_income_tax,
        estimated_total_tax=estimated_total_tax,
        recommended_quarterly_payment=recommended_quarterly_payment,
        due_date=_due_date(tax_year, quarter),
        payment_url=IRS_ESTIMATED_PAYMENT_URL,
    )
