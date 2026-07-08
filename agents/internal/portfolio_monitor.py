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
portfolio_monitor — daily 6am digest across the whole product portfolio.
Pulls per-product MRR, new subscriptions, cancellations, trial signups,
trial-to-paid conversion, agent run volume/error rate, and token cost;
derives gross margin, MoM growth, and churn rate. Flags any product still
under $500 MRR 60+ days after launch for a kill-switch review card.

Pure aggregation over ProductMetricsSnapshot records shaped like what a
caller would assemble from the `agent_runs` table and Stripe (via
finance/integrations/stripe_revenue.py, not called directly here — this
agent takes numbers, not API credentials, matching every other
agents/internal/* module's "no DB/API connection of its own" design).
Never fires the kill switch itself — every flag is a decision card with
options that always include "hold" (non-negotiable #9).
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

KILL_SWITCH_MRR_FLOOR = 500.0
KILL_SWITCH_MIN_DAYS_LIVE = 60


@dataclass(frozen=True)
class ProductMetricsSnapshot:
    product_id: str
    product_name: str
    as_of: date
    launched_at: date
    mrr: float
    new_subscriptions: int
    cancellations: int
    active_subscriptions_start_of_period: int
    trial_signups: int
    trial_to_paid_conversions: int
    agent_run_count: int
    agent_error_count: int
    token_cost_usd: float


def gross_margin(mrr: float, token_cost_usd: float) -> float:
    if mrr <= 0:
        return 0.0
    return round((mrr - token_cost_usd) / mrr, 4)


def mom_growth_rate(current_mrr: float, previous_mrr: float) -> Optional[float]:
    if previous_mrr <= 0:
        return None
    return round((current_mrr - previous_mrr) / previous_mrr, 4)


def churn_rate(cancellations: int, active_at_start: int) -> float:
    if active_at_start <= 0:
        return 0.0
    return round(cancellations / active_at_start, 4)


def trial_conversion_rate(trial_signups: int, conversions: int) -> float:
    if trial_signups <= 0:
        return 0.0
    return round(conversions / trial_signups, 4)


def agent_error_rate(run_count: int, error_count: int) -> float:
    if run_count <= 0:
        return 0.0
    return round(error_count / run_count, 4)


def days_since_launch(as_of: date, launched_at: date) -> int:
    return (as_of - launched_at).days


@dataclass
class ProductDigestRow:
    product_id: str
    product_name: str
    mrr: float
    mom_growth: Optional[float]
    churn_rate: float
    trial_conversion_rate: float
    gross_margin: float
    agent_run_count: int
    agent_error_rate: float

    def to_row(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "mrr": self.mrr,
            "mom_growth": self.mom_growth,
            "churn_rate": self.churn_rate,
            "trial_conversion_rate": self.trial_conversion_rate,
            "gross_margin": self.gross_margin,
            "agent_run_count": self.agent_run_count,
            "agent_error_rate": self.agent_error_rate,
        }


@dataclass
class KillSwitchReviewCard:
    product_id: str
    product_name: str
    mrr: float
    days_live: int
    message: str
    options: list[str] = field(default_factory=lambda: ["kill_switch_review", "give_more_runway", "hold"])

    def to_row(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "mrr": self.mrr,
            "days_live": self.days_live,
            "message": self.message,
            "options": self.options,
        }


class PortfolioMonitor:
    """Runs daily. daily_digest() is the single entry point — takes
    today's snapshots plus the prior period's (for MoM growth) and
    returns the digest rows plus any kill-switch review cards."""

    def daily_digest(
        self,
        snapshots: list[ProductMetricsSnapshot],
        previous_snapshots: Optional[list[ProductMetricsSnapshot]] = None,
        mrr_floor: float = KILL_SWITCH_MRR_FLOOR,
        min_days_live: int = KILL_SWITCH_MIN_DAYS_LIVE,
    ) -> dict:
        previous_by_product = {s.product_id: s.mrr for s in (previous_snapshots or [])}

        rows: list[ProductDigestRow] = []
        review_cards: list[KillSwitchReviewCard] = []

        for snap in snapshots:
            row = ProductDigestRow(
                product_id=snap.product_id,
                product_name=snap.product_name,
                mrr=snap.mrr,
                mom_growth=mom_growth_rate(snap.mrr, previous_by_product.get(snap.product_id, 0.0)),
                churn_rate=churn_rate(snap.cancellations, snap.active_subscriptions_start_of_period),
                trial_conversion_rate=trial_conversion_rate(snap.trial_signups, snap.trial_to_paid_conversions),
                gross_margin=gross_margin(snap.mrr, snap.token_cost_usd),
                agent_run_count=snap.agent_run_count,
                agent_error_rate=agent_error_rate(snap.agent_run_count, snap.agent_error_count),
            )
            rows.append(row)

            days_live = days_since_launch(snap.as_of, snap.launched_at)
            if snap.mrr < mrr_floor and days_live >= min_days_live:
                review_cards.append(KillSwitchReviewCard(
                    product_id=snap.product_id,
                    product_name=snap.product_name,
                    mrr=snap.mrr,
                    days_live=days_live,
                    message=(
                        f"{snap.product_name} is at ${snap.mrr:,.2f} MRR after {days_live} days live "
                        f"— under the ${mrr_floor:,.2f} floor for {days_live - min_days_live} extra days."
                    ),
                ))

        return {
            "as_of": snapshots[0].as_of.isoformat() if snapshots else None,
            "products": [r.to_row() for r in rows],
            "portfolio_mrr": round(sum(r.mrr for r in rows), 2),
            "kill_switch_reviews": [c.to_row() for c in review_cards],
        }
