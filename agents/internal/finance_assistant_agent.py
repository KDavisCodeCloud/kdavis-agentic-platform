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
finance_assistant_agent — read-only retrieval and coordination layer.
Answers questions immediately by reading accounting_agent, tax_agent,
and the ledgers/trackers they hold. Never writes, updates, or modifies
any record — it only surfaces what other agents have already recorded.

Response shape always: direct answer first, then source, last-updated
timestamp, and a related action when one applies.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from finance import disclaim
from finance.accounting.expense_categorizer import IRSCategory
from finance.accounting.invoice_tracker import InvoiceStatus, InvoiceTracker
from finance.accounting.revenue_ledger import RevenueLedger
from finance.wealth.cash_flow_monitor import CashFlowMonitor

from agents.internal.accounting_agent import AccountingAgent
from agents.internal.tax_agent import TaxAgent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FinanceAssistantAgent:
    def __init__(
        self,
        accounting_agent: AccountingAgent,
        tax_agent: TaxAgent,
        invoice_tracker: InvoiceTracker,
        revenue_ledger: RevenueLedger,
    ):
        self._accounting_agent = accounting_agent
        self._tax_agent = tax_agent
        self._invoice_tracker = invoice_tracker
        self._revenue_ledger = revenue_ledger

    def revenue_ytd(self, year: int) -> dict:
        summary = self._revenue_ledger.ytd_summary(year)
        return disclaim({
            "answer": f"YTD revenue for {year}: ${summary['total']:,.2f}",
            "source": "revenue_ledger",
            "by_product": summary["by_product"],
            "last_updated": _now_iso(),
        })

    def software_spend(self, year: int) -> dict:
        expenses = [
            e for e in self._accounting_agent.expenses_snapshot()
            if e.get("tax_year") == year and e.get("irs_category") == IRSCategory.SOFTWARE_SUBSCRIPTIONS.value
        ]
        total = sum(e.get("amount") or 0.0 for e in expenses)
        by_vendor: dict[str, float] = defaultdict(float)
        for e in expenses:
            by_vendor[e["vendor"]] += e.get("amount") or 0.0
        return disclaim({
            "answer": f"${total:,.2f} spent on software subscriptions in {year}",
            "source": "accounting_agent expenses",
            "by_vendor": dict(by_vendor),
            "receipt_links": [e.get("receipt_url") for e in expenses if e.get("receipt_url")],
            "last_updated": _now_iso(),
        })

    def receipts_for_month(self, year: int, month: int) -> dict:
        expenses = [e for e in self._accounting_agent.expenses_snapshot() if (e.get("date") or "").startswith(f"{year}-{month:02d}")]
        gaps = [e for e in expenses if not e.get("amount") or not e.get("date")]
        answer = f"{len(expenses)} receipts recorded for {year}-{month:02d}"
        if gaps:
            answer += f" — {len(gaps)} incomplete and need review"
        return disclaim({
            "answer": answer,
            "source": "accounting_agent expenses",
            "expenses": expenses,
            "gaps": gaps,
            "last_updated": _now_iso(),
            "related_action": "Reconciling against bank statements requires the banking integration (not yet built).",
        })

    def invoice_status(self, vendor_or_client: str) -> dict:
        matches = [i for i in self._invoice_tracker.all() if i.vendor_or_client.lower() == vendor_or_client.lower()]
        if not matches:
            answer = f"No invoices found for {vendor_or_client}."
        else:
            latest = max(matches, key=lambda i: i.issued_date)
            paid = latest.status == InvoiceStatus.PAID
            answer = f"{vendor_or_client}: latest invoice #{latest.id} is {latest.status.value}" + (f" (paid {latest.paid_date.isoformat()})" if paid else "")
        return disclaim({
            "answer": answer,
            "source": "invoice_tracker",
            "invoices": [i.id for i in matches],
            "last_updated": _now_iso(),
        })

    def deductions_ytd(self, tax_year: int) -> dict:
        flags = self._tax_agent.deduction_flags_for_year(tax_year)
        total = sum(f.estimated_amount for f in flags)
        return disclaim({
            "answer": f"${total:,.2f} in deductions tracked for {tax_year} across {len(flags)} categories",
            "source": "tax_agent deduction_tracker",
            "deductions": [{"category": f.category.value, "amount": f.estimated_amount, "confidence": f.confidence} for f in flags],
            "last_updated": _now_iso(),
        })

    def cpa_handoff_readiness(self, tax_year: int) -> dict:
        expense_count = len([e for e in self._accounting_agent.expenses_snapshot() if e.get("tax_year") == tax_year])
        deduction_count = len(self._tax_agent.deduction_flags_for_year(tax_year))
        revenue_count = len(self._revenue_ledger.for_year(tax_year))
        missing = []
        if revenue_count == 0:
            missing.append("no revenue events recorded")
        if expense_count == 0:
            missing.append("no expenses recorded")
        if deduction_count == 0:
            missing.append("no deductions tracked")
        answer = "CPA handoff ready" if not missing else f"CPA handoff incomplete: {', '.join(missing)}"
        return disclaim({
            "answer": answer,
            "source": "accounting_agent + tax_agent",
            "revenue_count": revenue_count,
            "expense_count": expense_count,
            "deduction_count": deduction_count,
            "last_updated": _now_iso(),
            "related_action": "Run tax_agent.year_end_package once revenue, expenses, and deductions are all present." if missing else "Year-end package is ready to generate.",
        })

    def tax_reserve_status(self, year: int, month: int, revenue: float, expenses: float, annual_estimated_tax: float) -> dict:
        summary = CashFlowMonitor().monthly_summary(year, month, revenue, expenses, annual_estimated_tax)
        return disclaim({
            "answer": f"Recommended tax reserve for {year}-{month:02d}: ${summary.recommended_tax_reserve:,.2f}",
            "source": "cash_flow_monitor",
            "available_surplus": summary.available_surplus,
            "last_updated": _now_iso(),
        })
