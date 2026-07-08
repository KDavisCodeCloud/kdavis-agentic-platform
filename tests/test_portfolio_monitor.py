"""
tests/test_portfolio_monitor.py
Stub coverage for agents/internal/portfolio_monitor.py.

What this file validates:
  - gross_margin(), mom_growth_rate(), churn_rate() handle the zero
    denominator edge cases without raising
  - daily_digest() computes MoM growth against the previous snapshot
  - daily_digest() flags a kill-switch review card for a product under
    the MRR floor after the minimum days-live window, and not before
  - kill-switch review card options always include "hold"
"""

from datetime import date

from agents.internal.portfolio_monitor import (
    PortfolioMonitor,
    ProductMetricsSnapshot,
    churn_rate,
    gross_margin,
    mom_growth_rate,
)


def _snapshot(**overrides) -> ProductMetricsSnapshot:
    defaults = dict(
        product_id="p1", product_name="Product One", as_of=date(2026, 7, 7),
        launched_at=date(2026, 4, 1), mrr=400.0, new_subscriptions=2, cancellations=1,
        active_subscriptions_start_of_period=10, trial_signups=20,
        trial_to_paid_conversions=2, agent_run_count=50, agent_error_count=3,
        token_cost_usd=15.0,
    )
    defaults.update(overrides)
    return ProductMetricsSnapshot(**defaults)


def test_gross_margin_zero_mrr_is_zero():
    assert gross_margin(mrr=0, token_cost_usd=10) == 0.0


def test_mom_growth_rate_none_when_no_prior_mrr():
    assert mom_growth_rate(current_mrr=500, previous_mrr=0) is None


def test_mom_growth_rate_computed_correctly():
    assert mom_growth_rate(current_mrr=550, previous_mrr=500) == 0.1


def test_churn_rate_zero_active_at_start_is_zero():
    assert churn_rate(cancellations=2, active_at_start=0) == 0.0


def test_daily_digest_flags_kill_switch_for_underperforming_product():
    snap = _snapshot(mrr=400.0, launched_at=date(2026, 4, 1), as_of=date(2026, 7, 7))
    digest = PortfolioMonitor().daily_digest([snap], mrr_floor=500.0, min_days_live=60)

    assert len(digest["kill_switch_reviews"]) == 1
    card = digest["kill_switch_reviews"][0]
    assert card["product_id"] == "p1"
    assert "hold" in card["options"]


def test_daily_digest_does_not_flag_recently_launched_product():
    snap = _snapshot(mrr=100.0, launched_at=date(2026, 7, 1), as_of=date(2026, 7, 7))
    digest = PortfolioMonitor().daily_digest([snap], mrr_floor=500.0, min_days_live=60)

    assert digest["kill_switch_reviews"] == []


def test_daily_digest_computes_mom_growth_against_previous_period():
    current = _snapshot(mrr=550.0)
    previous = _snapshot(mrr=500.0)
    digest = PortfolioMonitor().daily_digest([current], previous_snapshots=[previous])

    assert digest["products"][0]["mom_growth"] == 0.1
