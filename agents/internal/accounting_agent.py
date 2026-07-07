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
accounting_agent — keeps receipts, invoices, and revenue organized,
categorized, and retrievable. Never files anything with a taxing
authority. Every output carries the CPA/advisor disclaimer.

Orchestrates: receipt_processor, invoice_tracker, revenue_ledger,
document_organizer, stripe_revenue. Holds its own in-memory expense list
(populated as receipts are processed) — persistence to Supabase's
`expenses` table is the caller's responsibility in the integration
session that wires this into the live dashboard.
"""

from collections import defaultdict
from datetime import date
from typing import Optional

from finance import disclaim
from finance.accounting.document_organizer import DocumentOrganizer, RevenueDocKind
from finance.accounting.invoice_tracker import Invoice, InvoiceTracker
from finance.accounting.receipt_processor import ProcessedReceipt, ReceiptProcessor, ReceiptSource
from finance.accounting.revenue_ledger import RevenueLedger
from finance.integrations.stripe_revenue import sync_to_ledger


class AccountingAgent:
    def __init__(
        self,
        receipt_processor: ReceiptProcessor,
        invoice_tracker: InvoiceTracker,
        revenue_ledger: RevenueLedger,
        document_organizer: DocumentOrganizer,
    ):
        self._receipt_processor = receipt_processor
        self._invoice_tracker = invoice_tracker
        self._revenue_ledger = revenue_ledger
        self._document_organizer = document_organizer
        self._expenses: list[dict] = []

    def process_receipt(self, text: str, source: ReceiptSource = ReceiptSource.EMAIL_FORWARD) -> dict:
        processed: ProcessedReceipt = self._receipt_processor.process_text(text, source=source)
        year = processed.receipt_date.year if processed.receipt_date else date.today().year

        filename = f"{processed.vendor.replace(' ', '_')}_{processed.amount or 0:.2f}_{len(self._expenses) + 1}.txt"
        receipt_url = self._document_organizer.file_expense_receipt(
            year=year, category=processed.irs_category, filename=filename, content=processed.raw_text.encode(),
        )

        expense_record = processed.to_expense_record(tax_year=year)
        expense_record["receipt_url"] = receipt_url
        self._expenses.append(expense_record)

        result = {"expense_record": expense_record, "confidence": processed.category_confidence}
        if processed.needs_review:
            result["hitl_card"] = {
                "message": processed.review_question,
                "options": ["categorize_as_shown", "recategorize", "hold"],
            }
        return disclaim(result)

    def track_invoice(self, invoice: Invoice) -> dict:
        self._invoice_tracker.add_invoice(invoice)
        return disclaim({"invoice_id": invoice.id, "status": invoice.status.value})

    def overdue_invoice_cards(self, as_of: Optional[date] = None) -> list[dict]:
        return [disclaim(flag.to_decision_card()) for flag in self._invoice_tracker.overdue_invoices(as_of)]

    def sync_stripe_revenue(self, since: date, product_id: Optional[str] = None) -> dict:
        synced_count = sync_to_ledger(self._revenue_ledger, since, product_id=product_id)
        return disclaim({"synced_events": synced_count})

    def export_monthly_stripe_csv(self, year: int, month: int) -> dict:
        events = self._revenue_ledger.for_month(year, month)
        csv_content = self._revenue_ledger.export_csv(events)
        url = self._document_organizer.file_revenue_document(
            year=year, kind=RevenueDocKind.STRIPE_EXPORT, filename=f"{year}-{month:02d}.csv",
            content=csv_content.encode(),
        )
        return disclaim({"csv_url": url, "event_count": len(events)})

    def _expenses_for(self, year: int, month: Optional[int] = None) -> list[dict]:
        return [
            e for e in self._expenses
            if e.get("tax_year") == year and (month is None or (e.get("date") or "").startswith(f"{year}-{month:02d}"))
        ]

    def _expense_breakdown_by_category(self, expenses: list[dict]) -> dict[str, float]:
        breakdown: dict[str, float] = defaultdict(float)
        for e in expenses:
            breakdown[e["irs_category"]] += e.get("amount") or 0.0
        return dict(breakdown)

    def monthly_summary(self, year: int, month: int) -> dict:
        month_expenses = self._expenses_for(year, month)
        ytd_expenses = self._expenses_for(year)

        month_revenue = self._revenue_ledger.monthly_summary(year, month)
        ytd_revenue = self._revenue_ledger.ytd_summary(year)

        month_expense_total = sum(e.get("amount") or 0.0 for e in month_expenses)
        ytd_expense_total = sum(e.get("amount") or 0.0 for e in ytd_expenses)
        by_category = self._expense_breakdown_by_category(month_expenses)
        largest_categories = sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)[:5]

        return disclaim({
            "year": year,
            "month": month,
            "revenue_this_month": month_revenue["total"],
            "expenses_this_month": round(month_expense_total, 2),
            "net_this_month": round(month_revenue["total"] - month_expense_total, 2),
            "ytd_revenue": ytd_revenue["total"],
            "ytd_expenses": round(ytd_expense_total, 2),
            "ytd_net": round(ytd_revenue["total"] - ytd_expense_total, 2),
            "largest_expense_categories": [{"category": cat, "amount": round(amt, 2)} for cat, amt in largest_categories],
        })

    def expenses_snapshot(self) -> list[dict]:
        """Read-only snapshot used by finance_assistant_agent and tax_agent."""
        return list(self._expenses)
