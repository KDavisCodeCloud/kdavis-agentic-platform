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
expense_categorizer — maps a vendor/description to an IRS Schedule C
category using keyword matching. Confidence-scored, never auto-final:
anything below LOW_CONFIDENCE_THRESHOLD is expected to be routed to a
human decision by the caller (accounting_agent).
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from finance import LOW_CONFIDENCE_THRESHOLD


class IRSCategory(str, Enum):
    ADVERTISING = "Advertising"
    SOFTWARE_SUBSCRIPTIONS = "Software_Subscriptions"
    HOME_OFFICE = "Home_Office"
    EDUCATION_TRAINING = "Education_Training"
    PROFESSIONAL_SERVICES = "Professional_Services"
    EQUIPMENT = "Equipment"
    TRAVEL_BUSINESS = "Travel_Business"
    CAR_AND_TRUCK = "Car_And_Truck"
    SUPPLIES = "Supplies"
    UTILITIES = "Utilities"
    INSURANCE = "Insurance"
    MEALS = "Meals"
    RENT_LEASE = "Rent_Or_Lease"
    CONTRACT_LABOR = "Contract_Labor"
    BANK_FEES = "Bank_Fees"
    OTHER_BUSINESS = "Other_Business"


# Ordered most-specific-first: first category whose keywords match wins.
_CATEGORY_KEYWORDS: dict[IRSCategory, tuple[str, ...]] = {
    IRSCategory.SOFTWARE_SUBSCRIPTIONS: (
        "supabase", "github", "vercel", "aws", "amazon web services", "anthropic",
        "openai", "stripe", "systeme.io", "systeme", "notion", "figma", "slack",
        "zoom", "adobe", "google workspace", "microsoft 365", "dropbox", "domain",
        "namecheap", "godaddy", "cloudflare", "hosting", "saas", "subscription",
        "api", "software",
    ),
    IRSCategory.ADVERTISING: (
        "google ads", "facebook ads", "meta ads", "linkedin ads", "reddit ads",
        "sponsored", "advertising", "ad spend", "marketing campaign", "adwords",
    ),
    IRSCategory.EDUCATION_TRAINING: (
        "course", "udemy", "coursera", "certification", "training", "bootcamp",
        "conference ticket", "textbook", "book", "workshop",
    ),
    IRSCategory.PROFESSIONAL_SERVICES: (
        "cpa", "accountant", "attorney", "lawyer", "legal", "bookkeeping",
        "consulting", "consultant", "notary", "registered agent",
    ),
    IRSCategory.CONTRACT_LABOR: (
        "contractor", "freelancer", "upwork", "fiverr", "1099",
    ),
    IRSCategory.EQUIPMENT: (
        "laptop", "monitor", "keyboard", "webcam", "microphone", "desk",
        "chair", "printer", "hardware", "computer",
    ),
    IRSCategory.CAR_AND_TRUCK: (
        "gas station", "shell", "chevron", "exxon", "mileage", "parking",
        "toll", "uber", "lyft", "car rental",
    ),
    IRSCategory.TRAVEL_BUSINESS: (
        "airline", "flight", "delta", "united", "southwest", "hotel", "airbnb",
        "marriott", "hilton", "travel",
    ),
    IRSCategory.MEALS: (
        "restaurant", "coffee", "starbucks", "lunch", "dinner", "doordash",
        "grubhub", "catering",
    ),
    IRSCategory.RENT_LEASE: (
        "office lease", "coworking", "wework", "rent",
    ),
    IRSCategory.UTILITIES: (
        "electric", "internet bill", "comcast", "at&t", "verizon", "t-mobile",
        "phone bill", "water bill",
    ),
    IRSCategory.INSURANCE: (
        "insurance", "liability policy", "e&o policy",
    ),
    IRSCategory.BANK_FEES: (
        "bank fee", "wire fee", "overdraft", "atm fee", "processing fee",
        "merchant fee",
    ),
    IRSCategory.HOME_OFFICE: (
        "home office", "standing desk",
    ),
}


@dataclass(frozen=True)
class CategorizationResult:
    category: IRSCategory
    confidence: float
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    needs_review: bool = False
    review_question: str | None = None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def categorize_expense(vendor: str, description: str = "", amount: float | None = None) -> CategorizationResult:
    """Categorize a single expense from vendor name + free-text description.

    Confidence reflects how many distinct keyword hits were found and
    whether the vendor name itself (not just the description) matched.
    """
    haystack = _normalize(f"{vendor} {description}")
    vendor_norm = _normalize(vendor)

    best_category: IRSCategory | None = None
    best_score = 0.0
    best_matches: list[str] = []

    for category, keywords in _CATEGORY_KEYWORDS.items():
        matches = [kw for kw in keywords if kw in haystack]
        if not matches:
            continue
        score = 0.55 + 0.15 * min(len(matches), 2)
        if any(kw in vendor_norm for kw in matches):
            score += 0.15
        score = min(score, 0.97)
        if score > best_score:
            best_category, best_score, best_matches = category, score, matches

    if best_category is None:
        return CategorizationResult(
            category=IRSCategory.OTHER_BUSINESS,
            confidence=0.3,
            matched_keywords=(),
            needs_review=True,
            review_question=(
                f"Received expense from {vendor or 'unknown vendor'}"
                f"{f' ${amount:.2f}' if amount is not None else ''} — "
                "category unclear. Which IRS category does this belong to?"
            ),
        )

    needs_review = best_score < LOW_CONFIDENCE_THRESHOLD
    review_question = None
    if needs_review:
        review_question = (
            f"Received expense from {vendor or 'unknown vendor'}"
            f"{f' ${amount:.2f}' if amount is not None else ''} — category unclear. "
            f"Is this {best_category.value} or {IRSCategory.OTHER_BUSINESS.value}?"
        )

    return CategorizationResult(
        category=best_category,
        confidence=round(best_score, 2),
        matched_keywords=tuple(best_matches),
        needs_review=needs_review,
        review_question=review_question,
    )
