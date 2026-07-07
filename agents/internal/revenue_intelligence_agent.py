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
revenue_intelligence_agent — finds money already within reach that the
platform isn't capturing. Not forecasting, not general advice: specific,
ranked, actionable opportunities with an estimated MRR impact behind
each one. Never moves money, never triggers campaigns — every finding is
a decision card the operator acts on or holds.

Reads pure-Python records shaped like the platform's leads,
visitor_sessions, and revenue_events tables (Lead, VisitorSession,
RevenueEvent — the latter reused from finance.accounting.revenue_ledger,
the two former defined here since no earlier session produced a pure
Python equivalent). Building last in this session, on top of every
other finance module, matches the CLAUDE.md build order: this agent
reads what everything else recorded.
"""

import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from finance.accounting.revenue_ledger import RevenueEvent

_id_counter = itertools.count(1)


@dataclass(frozen=True)
class Lead:
    product_id: str
    email: str
    signup_type: str  # "trial" | "email_only"
    source: str       # utm_source, e.g. "linkedin", "google_organic", "direct"
    signup_date: date
    role: Optional[str] = None
    company_size: Optional[str] = None
    trial_expired: bool = False
    trial_end_date: Optional[date] = None
    last_login: Optional[date] = None
    converted_to_paid: bool = False
    cancelled: bool = False
    months_active: Optional[int] = None
    hit_usage_limit: bool = False


@dataclass(frozen=True)
class VisitorSession:
    product_id: str
    utm_source: str
    session_date: date
    converted_to_lead: bool = False
    is_mobile: bool = False


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    price: float


@dataclass
class RevenueOpportunity:
    opportunity_type: str
    product_id: str
    description: str
    estimated_impact_mrr: float
    confidence: float
    options: list[str]
    status: str = "new"
    id: int = field(default_factory=lambda: next(_id_counter))

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "product_id": self.product_id,
            "opportunity_type": self.opportunity_type,
            "description": self.description,
            "estimated_impact_mrr": self.estimated_impact_mrr,
            "confidence": self.confidence,
            "status": self.status,
        }


def _days_between(a: date, b: date) -> int:
    return abs((a - b).days)


def _conversion_rate(trials: int, conversions: int) -> float:
    return round(conversions / trials, 4) if trials > 0 else 0.0


def _leads_for_product(leads: list[Lead], product_id: str) -> list[Lead]:
    return [l for l in leads if l.product_id == product_id]


def detect_expired_trials_reengaging(leads: list[Lead], products: dict[str, Product], as_of: date, reengagement_window_days: int = 14) -> list[RevenueOpportunity]:
    opportunities = []
    by_product: dict[str, list[Lead]] = defaultdict(list)
    for lead in leads:
        if (lead.signup_type == "trial" and lead.trial_expired and lead.last_login
                and lead.trial_end_date and _days_between(as_of, lead.last_login) <= reengagement_window_days):
            by_product[lead.product_id].append(lead)

    for product_id, matched in by_product.items():
        product = products.get(product_id)
        if not product:
            continue
        avg_days_since = sum(_days_between(as_of, l.trial_end_date) for l in matched) / len(matched)
        estimated_conversions = max(1, round(len(matched) * 0.3))
        estimated_mrr = round(estimated_conversions * product.price * 0.7, 2)
        opportunities.append(RevenueOpportunity(
            opportunity_type="expired_trial_reengaging",
            product_id=product_id,
            description=(
                f"{product.name}: {len(matched)} expired trial users logged in this week. "
                f"Avg days since trial ended: {avg_days_since:.0f}. They haven't left. "
                f"Estimated conversion if offered 30% discount: {estimated_conversions} users = ${estimated_mrr:,.2f}"
            ),
            estimated_impact_mrr=estimated_mrr,
            confidence=0.5,
            options=["trigger_winback_with_discount", "trigger_winback_no_discount", "flag_for_personal_outreach", "hold"],
        ))
    return opportunities


def detect_low_conversion_gap(leads: list[Lead], products: dict[str, Product], window_start: date, window_end: date, min_trials: int = 15, max_conversion_rate: float = 0.03) -> list[RevenueOpportunity]:
    opportunities = []
    stats: dict[str, tuple[int, int]] = {}
    for product_id, product in products.items():
        window_leads = [l for l in _leads_for_product(leads, product_id) if window_start <= l.signup_date <= window_end and l.signup_type == "trial"]
        trials = len(window_leads)
        conversions = sum(1 for l in window_leads if l.converted_to_paid)
        stats[product_id] = (trials, conversions)

    total_trials = sum(t for t, _ in stats.values())
    total_conversions = sum(c for _, c in stats.values())
    portfolio_avg = _conversion_rate(total_trials, total_conversions)

    for product_id, (trials, conversions) in stats.items():
        rate = _conversion_rate(trials, conversions)
        if trials > min_trials and rate < max_conversion_rate:
            product = products[product_id]
            lost_mrr = round(max(0.0, portfolio_avg - rate) * trials * product.price, 2)
            opportunities.append(RevenueOpportunity(
                opportunity_type="low_conversion_gap",
                product_id=product_id,
                description=(
                    f"{product.name}: {trials} trials started this period, {conversions} converted ({rate:.1%}). "
                    f"Portfolio avg conversion: {portfolio_avg:.1%}. Gap = ~${lost_mrr:,.2f}/mo estimated lost MRR."
                ),
                estimated_impact_mrr=lost_mrr,
                confidence=0.55,
                options=["rewrite_day3_nurture_email", "review_and_update_demo", "adjust_pricing_page", "ask_claude_to_diagnose", "hold"],
            ))
    return opportunities


def detect_underpriced_products(leads: list[Lead], products: dict[str, Product], as_of: date, min_days_observed: int = 60, churn_ceiling: float = 0.05, reprice_multiplier: float = 1.5) -> list[RevenueOpportunity]:
    opportunities = []
    for product_id, product in products.items():
        product_leads = [l for l in _leads_for_product(leads, product_id) if l.converted_to_paid]
        if not product_leads:
            continue
        earliest = min(l.signup_date for l in product_leads)
        if _days_between(as_of, earliest) < min_days_observed:
            continue
        churned = sum(1 for l in product_leads if l.cancelled)
        churn_rate = _conversion_rate(len(product_leads), churned)
        if churn_rate < churn_ceiling:
            new_price = round(product.price * reprice_multiplier, 2)
            active_paying = len(product_leads) - churned
            delta_mrr = round(active_paying * (new_price - product.price), 2)
            opportunities.append(RevenueOpportunity(
                opportunity_type="underpriced_signal",
                product_id=product_id,
                description=(
                    f"{product.name}: {churn_rate:.1%} monthly churn over {_days_between(as_of, earliest)} days "
                    f"at ${product.price:,.2f}/mo. Customers are keeping this. "
                    f"If repriced to ${new_price:,.2f} for new signups: estimated +${delta_mrr:,.2f} MRR without touching existing customers."
                ),
                estimated_impact_mrr=delta_mrr,
                confidence=0.5,
                options=["test_new_price_new_signups_only", "raise_price_for_all", "add_higher_tier", "hold_want_more_data", "ask_claude_for_pricing_strategy"],
            ))
    return opportunities


def detect_ad_readiness(
    leads: list[Lead], products: dict[str, Product], as_of: date,
    aeo_cited: dict[str, bool], conversion_gate: float = 0.04, churn_gate: float = 0.06,
) -> list[RevenueOpportunity]:
    opportunities = []
    for product_id, product in products.items():
        product_leads = [l for l in _leads_for_product(leads, product_id) if l.signup_type == "trial"]
        trials = len(product_leads)
        conversions = sum(1 for l in product_leads if l.converted_to_paid)
        conversion_rate = _conversion_rate(trials, conversions)
        paying = [l for l in product_leads if l.converted_to_paid]
        churn_rate = _conversion_rate(len(paying), sum(1 for l in paying if l.cancelled)) if paying else 1.0

        gates = {
            "conversion": conversion_rate > conversion_gate,
            "aeo": aeo_cited.get(product_id, False),
            "retention": churn_rate < churn_gate,
        }
        source_counts: dict[str, int] = defaultdict(int)
        for l in product_leads:
            if l.converted_to_paid:
                source_counts[l.source] += 1
        best_channel = max(source_counts, key=source_counts.get) if source_counts else "organic"

        if all(gates.values()):
            cac = 50 / conversion_rate if conversion_rate > 0 else 0.0
            payback_months = round(cac / product.price, 1) if product.price > 0 else 0.0
            description = (
                f"{product.name} is ad-ready. Conversion: {conversion_rate:.1%} (gate: >{conversion_gate:.0%}) OK. "
                f"AEO: cited OK. Churn: {churn_rate:.1%} (gate: <{churn_gate:.0%}) OK. "
                f"Estimated CAC at $50 CPL: ${cac:,.2f}. Estimated CAC payback period: {payback_months} months at ${product.price:,.2f}/mo. "
                f"Suggested starting budget: $500/mo. Suggested channel: {best_channel}."
            )
            options = ["start_500_test_campaign", "start_200_smaller_test", "ask_claude_for_channel_strategy", "hold_not_ready_to_spend"]
        else:
            blocking = [gate for gate, passed in gates.items() if not passed]
            description = f"{product.name} is not yet ad-ready. Blocking gate(s): {', '.join(blocking)}."
            options = ["view_roadmap_to_ad_ready", "hold"]

        opportunities.append(RevenueOpportunity(
            opportunity_type="ad_readiness",
            product_id=product_id,
            description=description,
            estimated_impact_mrr=0.0,
            confidence=0.6 if all(gates.values()) else 0.3,
            options=options,
        ))
    return opportunities


def detect_traffic_trial_mismatch(
    visitor_sessions: list[VisitorSession], leads: list[Lead], products: dict[str, Product],
    min_visits: int = 50, max_conversion_rate: float = 0.01,
) -> list[RevenueOpportunity]:
    opportunities = []
    for product_id, product in products.items():
        visits_by_source: dict[str, int] = defaultdict(int)
        mobile_by_source: dict[str, int] = defaultdict(int)
        for session in visitor_sessions:
            if session.product_id != product_id:
                continue
            visits_by_source[session.utm_source] += 1
            if session.is_mobile:
                mobile_by_source[session.utm_source] += 1

        trials_by_source: dict[str, int] = defaultdict(int)
        for lead in _leads_for_product(leads, product_id):
            if lead.signup_type == "trial":
                trials_by_source[lead.source] += 1

        for source, visits in visits_by_source.items():
            if visits < min_visits:
                continue
            rate = _conversion_rate(visits, trials_by_source.get(source, 0))
            if rate < max_conversion_rate:
                mobile_pct = _conversion_rate(visits, mobile_by_source.get(source, 0))
                opportunities.append(RevenueOpportunity(
                    opportunity_type="traffic_trial_mismatch",
                    product_id=product_id,
                    description=(
                        f"{product.name}: {source} sending {visits} visits/period, {rate:.1%} trial conversion. "
                        f"{mobile_pct:.0%} of that traffic is mobile."
                    ),
                    estimated_impact_mrr=0.0,
                    confidence=0.4,
                    options=["review_landing_page_for_source", "audit_content_icp_targeting", "add_mobile_layout_test", "redirect_cta_to_different_product", "hold"],
                ))
    return opportunities


def detect_cross_sell_opportunities(
    leads: list[Lead], products: dict[str, Product], source_product_id: str, target_product_id: str,
    icp_roles: list[str], min_matches: int = 10, conversion_low: float = 0.20, conversion_high: float = 0.30,
) -> Optional[RevenueOpportunity]:
    source_customers = [l for l in _leads_for_product(leads, source_product_id) if l.converted_to_paid]
    matches = [l for l in source_customers if l.role in icp_roles]
    if len(matches) < min_matches:
        return None

    target_product = products.get(target_product_id)
    if not target_product:
        return None
    mid_conversion = (conversion_low + conversion_high) / 2
    estimated_customers = round(len(matches) * mid_conversion)
    estimated_mrr = round(estimated_customers * target_product.price, 2)

    return RevenueOpportunity(
        opportunity_type="cross_sell",
        product_id=target_product_id,
        description=(
            f"{len(matches)} {products[source_product_id].name} customers match the ICP for {target_product.name}. "
            f"Estimated cross-sell conversion based on ICP overlap: {conversion_low:.0%}-{conversion_high:.0%}. "
            f"If {estimated_customers} convert at ${target_product.price:,.2f}: +${estimated_mrr:,.2f} from existing customer base."
        ),
        estimated_impact_mrr=estimated_mrr,
        confidence=0.45,
        options=["trigger_cross_sell_sequence", "add_in_product_recommendation", "hold_until_more_traction", "ask_claude_for_cross_sell_angle"],
    )


def detect_seasonal_patterns(leads: list[Lead], product_id: str, min_days_observed: int = 120) -> Optional[RevenueOpportunity]:
    product_leads = _leads_for_product(leads, product_id)
    if len(product_leads) < 10:
        return None
    span_days = (max(l.signup_date for l in product_leads) - min(l.signup_date for l in product_leads)).days
    if span_days < min_days_observed:
        return None

    conversions = [l for l in product_leads if l.converted_to_paid]
    weekday_counts: dict[int, int] = defaultdict(int)
    for l in conversions:
        weekday_counts[l.signup_date.weekday()] += 1
    total_conversions = sum(weekday_counts.values())
    tue_thu = sum(weekday_counts.get(d, 0) for d in (1, 2, 3))
    tue_thu_pct = _conversion_rate(total_conversions, tue_thu)

    return RevenueOpportunity(
        opportunity_type="seasonal_pattern",
        product_id=product_id,
        description=f"{tue_thu_pct:.0%} of paid conversions happen Tuesday-Thursday over the observed {span_days}-day window.",
        estimated_impact_mrr=0.0,
        confidence=0.35,
        options=["update_nurture_sequence_timing", "hold_want_more_data", "noted_no_action_needed"],
    )


def detect_mrr_concentration(revenue_events: list[RevenueEvent], products: dict[str, Product], leads_by_email: dict[str, Lead], concentration_threshold: float = 0.30) -> list[RevenueOpportunity]:
    opportunities = []
    for product_id, product in products.items():
        product_events = [e for e in revenue_events if e.product_id == product_id and e.customer_email]
        total = sum(e.amount for e in product_events)
        if total <= 0:
            continue
        by_customer: dict[str, float] = defaultdict(float)
        for e in product_events:
            by_customer[e.customer_email] += e.amount

        top_email, top_amount = max(by_customer.items(), key=lambda kv: kv[1])
        share = top_amount / total
        if share <= concentration_threshold:
            continue

        lead = leads_by_email.get(top_email)
        expansion_signals = []
        if lead:
            if lead.months_active and lead.months_active >= 3:
                expansion_signals.append(f"used the product for {lead.months_active} months")
            if not lead.hit_usage_limit:
                expansion_signals.append("hasn't hit any usage limits")

        description = f"{product.name}: customer {top_email} represents {share:.0%} of product MRR (${top_amount:,.2f})."
        if expansion_signals:
            description += " Also a candidate for expansion: " + "; ".join(expansion_signals) + "."

        opportunities.append(RevenueOpportunity(
            opportunity_type="mrr_concentration",
            product_id=product_id,
            description=description,
            estimated_impact_mrr=0.0,
            confidence=0.5,
            options=["flag_for_expansion_outreach", "build_enterprise_tier", "generate_case_study_request", "document_as_churn_risk", "hold"],
        ))
    return opportunities


class RevenueIntelligenceAgent:
    """Runs all eight opportunity detectors and ranks the results.
    Never persists on its own — the caller writes results to the
    revenue_opportunities table."""

    def scan(
        self,
        as_of: date,
        leads: list[Lead],
        visitor_sessions: list[VisitorSession],
        revenue_events: list[RevenueEvent],
        products: dict[str, Product],
        aeo_cited: dict[str, bool],
        window_days: int = 30,
    ) -> list[RevenueOpportunity]:
        window_start = date.fromordinal(as_of.toordinal() - window_days)
        leads_by_email = {l.email: l for l in leads}

        opportunities: list[RevenueOpportunity] = []
        opportunities += detect_expired_trials_reengaging(leads, products, as_of)
        opportunities += detect_low_conversion_gap(leads, products, window_start, as_of)
        opportunities += detect_underpriced_products(leads, products, as_of)
        opportunities += detect_ad_readiness(leads, products, as_of, aeo_cited)
        opportunities += detect_traffic_trial_mismatch(visitor_sessions, leads, products)
        opportunities += detect_mrr_concentration(revenue_events, products, leads_by_email)
        for product_id in products:
            seasonal = detect_seasonal_patterns(leads, product_id)
            if seasonal:
                opportunities.append(seasonal)

        return sorted(opportunities, key=lambda o: o.estimated_impact_mrr, reverse=True)

    def weekly_digest(self, opportunities: list[RevenueOpportunity]) -> dict:
        total_mrr = round(sum(o.estimated_impact_mrr for o in opportunities), 2)
        highest = max(opportunities, key=lambda o: o.estimated_impact_mrr, default=None)
        return {
            "total_estimated_mrr": total_mrr,
            "highest_impact": highest.description if highest else None,
            "ad_ready_count": sum(1 for o in opportunities if o.opportunity_type == "ad_readiness" and "is ad-ready" in o.description),
            "expired_trials_reengaging_count": sum(1 for o in opportunities if o.opportunity_type == "expired_trial_reengaging"),
            "cross_sell_count": sum(1 for o in opportunities if o.opportunity_type == "cross_sell"),
        }
