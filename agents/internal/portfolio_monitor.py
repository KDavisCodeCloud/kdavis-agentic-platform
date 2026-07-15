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


# ──────────────────────────────────────────────
# CLI — backs the "Portfolio digest" step in .github/workflows/weekly-sweep.yml
#
# Real Stripe revenue data doesn't exist yet (pre-revenue - see the audit
# for the full reasoning) and config/products.yaml has no launched_at, so
# this deliberately does NOT fabricate MRR/subscription numbers. What it
# CAN report for real: agent_run_count/agent_error_count per product from
# internal_agent_runs, which is genuine signal now that agents actually run.
# MRR fields are always 0.0 here and the printed/summary output says so
# explicitly - never silently pass 0 off as "confirmed zero revenue."
# ──────────────────────────────────────────────

async def _fetch_agent_metrics_by_product(days_back: int) -> dict[str, tuple[int, int]]:
    """product_id -> (run_count, error_count) from real internal_agent_runs rows."""
    import asyncpg

    database_url = _os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise EnvironmentError("DATABASE_URL not set")
    asyncpg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(asyncpg_url, statement_cache_size=0)
    try:
        rows = await conn.fetch(
            "SELECT COALESCE(product_id, 'internal') AS product_id, status, count(*) AS n "
            "FROM internal_agent_runs WHERE created_at > now() - ($1 || ' days')::interval "
            "GROUP BY COALESCE(product_id, 'internal'), status",
            str(days_back),
        )
    finally:
        await conn.close()

    metrics: dict[str, tuple[int, int]] = {}
    for r in rows:
        run_count, error_count = metrics.get(r["product_id"], (0, 0))
        run_count += r["n"]
        if r["status"] == "failed":
            error_count += r["n"]
        metrics[r["product_id"]] = (run_count, error_count)
    return metrics


if __name__ == "__main__":
    import argparse
    import asyncio
    import json
    import os as _os
    import sys
    from datetime import date as _date
    from pathlib import Path

    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()

    parser = argparse.ArgumentParser(description="Run portfolio_monitor.daily_digest with real agent metrics")
    parser.add_argument("--digest", action="store_true", help="Run the digest (required)")
    parser.add_argument("--days-back", type=int, default=1, help="Lookback window for agent metrics (default 1)")
    parser.add_argument("--report-out", required=True, help="Path to write the JSON report")
    args = parser.parse_args()

    if not args.digest:
        parser.error("--digest is required")

    try:
        metrics_by_product = asyncio.run(_fetch_agent_metrics_by_product(args.days_back))
    except EnvironmentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    import yaml
    products_path = Path(__file__).resolve().parents[2] / "config" / "products.yaml"
    registered_products = yaml.safe_load(products_path.read_text())["products"]

    today = _date.today()
    snapshots = []
    for p in registered_products:
        run_count, error_count = metrics_by_product.get(p["id"], (0, 0))
        snapshots.append(ProductMetricsSnapshot(
            product_id=p["id"],
            product_name=p["name"],
            as_of=today,
            # No real launch-date tracking in products.yaml yet - today's
            # date means days_since_launch=0, which correctly never trips
            # the kill-switch review (min_days_live=60) for a placeholder.
            launched_at=today,
            mrr=0.0,
            new_subscriptions=0,
            cancellations=0,
            active_subscriptions_start_of_period=0,
            trial_signups=0,
            trial_to_paid_conversions=0,
            agent_run_count=run_count,
            agent_error_count=error_count,
            token_cost_usd=0.0,
        ))

    # Also surface product_ids with real agent activity but no products.yaml
    # entry (e.g. 'internal' for agents not yet product-scoped) - don't
    # silently drop that signal.
    registered_ids = {p["id"] for p in registered_products}
    for product_id, (run_count, error_count) in metrics_by_product.items():
        if product_id not in registered_ids:
            snapshots.append(ProductMetricsSnapshot(
                product_id=product_id, product_name=f"(unregistered: {product_id})",
                as_of=today, launched_at=today, mrr=0.0, new_subscriptions=0, cancellations=0,
                active_subscriptions_start_of_period=0, trial_signups=0, trial_to_paid_conversions=0,
                agent_run_count=run_count, agent_error_count=error_count, token_cost_usd=0.0,
            ))

    digest = PortfolioMonitor().daily_digest(snapshots)

    print(f"portfolio_monitor — {args.days_back}-day agent-activity digest")
    print("NOTE: MRR/subscription/trial fields are always 0 - no live Stripe revenue data exists yet (pre-revenue).")
    print("      Only agent_run_count/agent_error_rate below reflect real data.\n")
    for row in digest["products"]:
        if row["agent_run_count"] == 0:
            continue
        print(f"  {row['product_name']} ({row['product_id']}): "
              f"{row['agent_run_count']} runs, {row['agent_error_rate']*100:.1f}% error rate")
    if not any(r["agent_run_count"] for r in digest["products"]):
        print("  (no agent runs in this window)")

    digest["_note"] = "mrr/subscription/trial fields are placeholders (0.0/0) - no live Stripe data source wired yet, see audit"
    Path(args.report_out).write_text(json.dumps(digest, indent=2))
    print(f"\nReport written to {args.report_out}")

    summary_path = _os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write("## Portfolio Digest\n\n"
                     "_MRR/subscription fields are placeholders - no live Stripe data yet. "
                     "Only agent run counts/error rates below are real._\n\n")
            f.write("| Product | Agent Runs | Error Rate |\n|---|---|---|\n")
            for row in digest["products"]:
                if row["agent_run_count"] == 0:
                    continue
                f.write(f"| {row['product_name']} | {row['agent_run_count']} | {row['agent_error_rate']*100:.1f}% |\n")
            f.write("\n")
