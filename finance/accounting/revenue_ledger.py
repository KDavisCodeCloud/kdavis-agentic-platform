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
revenue_ledger — append-only record of every revenue event, whether it
came from Stripe or was entered manually. Provides the monthly/YTD
aggregation the accounting_agent monthly summary and tax_agent quarterly
estimator both read from.
"""

import csv
import io
import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

_id_counter = itertools.count(1)


@dataclass(frozen=True)
class RevenueEvent:
    source: str                      # "stripe" | "manual" | other integration name
    amount: float
    event_date: date
    product_id: Optional[str] = None
    stripe_event_id: Optional[str] = None
    customer_email: Optional[str] = None
    description: str = ""
    tax_year: int = field(init=False)
    id: int = field(default_factory=lambda: next(_id_counter))

    def __post_init__(self):
        object.__setattr__(self, "tax_year", self.event_date.year)


class RevenueLedger:
    """Append-only in-memory ledger. Persistence is the caller's job."""

    def __init__(self):
        self._events: list[RevenueEvent] = []

    def record(self, event: RevenueEvent) -> RevenueEvent:
        if event.stripe_event_id and any(
            e.stripe_event_id == event.stripe_event_id for e in self._events
        ):
            return event  # idempotent: never double-count a replayed Stripe event
        self._events.append(event)
        return event

    def all(self) -> list[RevenueEvent]:
        return list(self._events)

    def for_month(self, year: int, month: int) -> list[RevenueEvent]:
        return [e for e in self._events if e.event_date.year == year and e.event_date.month == month]

    def for_year(self, year: int) -> list[RevenueEvent]:
        return [e for e in self._events if e.event_date.year == year]

    def total(self, events: Optional[list[RevenueEvent]] = None) -> float:
        return sum(e.amount for e in (events if events is not None else self._events))

    def by_product(self, events: Optional[list[RevenueEvent]] = None) -> dict[str, float]:
        breakdown: dict[str, float] = defaultdict(float)
        for e in (events if events is not None else self._events):
            breakdown[e.product_id or "unassigned"] += e.amount
        return dict(breakdown)

    def monthly_summary(self, year: int, month: int) -> dict:
        events = self.for_month(year, month)
        return {
            "year": year,
            "month": month,
            "total": self.total(events),
            "by_product": self.by_product(events),
            "event_count": len(events),
        }

    def ytd_summary(self, year: int) -> dict:
        events = self.for_year(year)
        return {
            "year": year,
            "total": self.total(events),
            "by_product": self.by_product(events),
            "event_count": len(events),
        }

    def export_csv(self, events: Optional[list[RevenueEvent]] = None) -> str:
        """Exports events matching Stripe's payout CSV column convention."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "created", "amount", "currency", "customer_email", "description", "product_id"])
        for e in (events if events is not None else self._events):
            writer.writerow([
                e.stripe_event_id or e.id,
                e.event_date.isoformat(),
                f"{e.amount:.2f}",
                "usd",
                e.customer_email or "",
                e.description,
                e.product_id or "",
            ])
        return buffer.getvalue()
