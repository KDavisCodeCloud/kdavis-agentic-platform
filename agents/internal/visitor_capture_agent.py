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
visitor_capture_agent — processes every inbound lead/trial signup,
optionally enriches it, scores intent, and either routes it to a
dashboard decision card (high intent) or lets the nurture sequence run
automatically (everything else). Per CLAUDE.md's Lead Capture section.

Triggered in production by leads/capture/signup_handler.py and
trial_handler.py on every new row — neither exists in this repo yet
(the `leads/` package is Session 10 PM, not this session), so
process_incoming_lead() takes an IncomingLead value directly rather than
a webhook payload.

Enrichment (company domain -> size estimate, LinkedIn lookup) and
Systeme.io tagging both require real external API calls this repo has no
client for yet (leads/integrations/systeme_io.py also doesn't exist).
Both are injected callables here, defaulting to no-ops, so scoring and
routing are fully testable today and real wiring later is additive.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

HIGH_INTENT_THRESHOLD = 70
MEDIUM_INTENT_THRESHOLD = 40

DIRECT_OR_ORGANIC_SOURCES = {"direct", "organic", "google_organic", "seo"}


@dataclass(frozen=True)
class IncomingLead:
    product_id: str
    email: str
    signup_type: str  # "trial" | "email_only"
    utm_source: str
    name: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    pages_viewed: int = 0


@dataclass(frozen=True)
class CompanySizeEstimate:
    domain: str
    employee_range: str  # "1-10" | "11-50" | "51-200" | "201-1000" | "1000+"
    confidence: float


@dataclass(frozen=True)
class LeadScore:
    score: int
    bucket: str  # "high_intent" | "medium_intent" | "low_intent"
    reasons: list[str]


def _email_domain(email: str) -> Optional[str]:
    if "@" not in email:
        return None
    return email.rsplit("@", 1)[-1].lower()


def score_lead(lead: IncomingLead, company_size: Optional[CompanySizeEstimate] = None) -> LeadScore:
    score = 0
    reasons = []

    if lead.signup_type == "trial":
        score += 50
        reasons.append("trial signup (+50)")
    else:
        score += 20
        reasons.append("email-only signup (+20)")

    if lead.utm_source.lower() in DIRECT_OR_ORGANIC_SOURCES:
        score += 20
        reasons.append(f"direct/organic source '{lead.utm_source}' (+20)")
    elif lead.utm_source.lower() not in ("paid", "cpc", "ads"):
        score += 10
        reasons.append(f"referral/other source '{lead.utm_source}' (+10)")

    if company_size is not None:
        if company_size.employee_range in ("51-200", "201-1000", "1000+"):
            score += 15
            reasons.append(f"company size {company_size.employee_range} (+15)")
        elif company_size.employee_range in ("1-10", "11-50"):
            score += 5
            reasons.append(f"company size {company_size.employee_range} (+5)")

    pages_bonus = min(lead.pages_viewed * 2, 20)
    if pages_bonus:
        score += pages_bonus
        reasons.append(f"{lead.pages_viewed} pages viewed (+{pages_bonus})")

    score = max(0, min(100, score))
    if score >= HIGH_INTENT_THRESHOLD:
        bucket = "high_intent"
    elif score >= MEDIUM_INTENT_THRESHOLD:
        bucket = "medium_intent"
    else:
        bucket = "low_intent"

    return LeadScore(score=score, bucket=bucket, reasons=reasons)


@dataclass
class HighIntentDecisionCard:
    email: str
    company: Optional[str]
    source: str
    message: str
    options: list[str] = field(default_factory=lambda: ["reach_out_personally", "let_nurture_run", "flag_for_follow_up"])

    def to_row(self) -> dict:
        return {"email": self.email, "company": self.company, "source": self.source, "message": self.message, "options": self.options}


class VisitorCaptureAgent:
    def process_incoming_lead(
        self,
        lead: IncomingLead,
        enrich_fn: Optional[Callable[[str], Optional[CompanySizeEstimate]]] = None,
        tag_fn: Optional[Callable[[str, str, list[str]], None]] = None,
    ) -> dict:
        domain = _email_domain(lead.email)
        company_size = enrich_fn(domain) if (enrich_fn is not None and domain) else None

        score = score_lead(lead, company_size)
        tags = [f"product_{lead.product_id}_interested" if lead.signup_type == "email_only" else f"product_{lead.product_id}_trial_active"]
        tags.append(score.bucket)

        if tag_fn is not None:
            tag_fn(lead.product_id, lead.email, tags)

        decision_card = None
        if score.bucket == "high_intent":
            decision_card = HighIntentDecisionCard(
                email=lead.email,
                company=lead.company,
                source=lead.utm_source,
                message=f"New high-intent trial: {lead.email}, {lead.company or 'unknown company'}, {lead.utm_source}",
            ).to_row()

        return {
            "product_id": lead.product_id,
            "email": lead.email,
            "score": score.score,
            "bucket": score.bucket,
            "reasons": score.reasons,
            "company_size": company_size.employee_range if company_size else None,
            "tags_applied": tags,
            "decision_card": decision_card,
            "nurture": "manual_review" if decision_card else "automatic",
        }
