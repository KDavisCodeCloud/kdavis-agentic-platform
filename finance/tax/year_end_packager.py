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
year_end_packager — compiles the full-year CPA handoff package: revenue
and expense summaries, receipt manifest, invoice export, deduction
export, quarterly estimate history, and 1099-NEC candidates.

Generates CSV + Markdown documents (no PDF rendering here — stdlib only;
PDF export is a presentation-layer concern for a later session).
"""

import csv
import io
from dataclasses import dataclass, field

from finance.accounting.document_organizer import cpa_handoff_year_complete_folder
from finance.accounting.expense_categorizer import IRSCategory
from finance.accounting.invoice_tracker import InvoiceTracker
from finance.accounting.revenue_ledger import RevenueLedger
from finance.tax.deduction_tracker import DeductionFlag
from finance.tax.quarterly_estimator import QuarterlyEstimate

CONTRACTOR_1099_THRESHOLD = 600.0


@dataclass
class Contractor1099Candidate:
    vendor: str
    total_paid: float


@dataclass
class YearEndPackage:
    tax_year: int
    folder: str
    revenue_csv: str
    revenue_by_month_md: str
    deductions_csv: str
    invoices_csv: str
    receipts_manifest: dict[str, list[str]]
    quarterly_estimates_summary_md: str
    contractor_1099_candidates: list[Contractor1099Candidate]
    summary_message: str


def _revenue_csv(ledger: RevenueLedger, tax_year: int) -> str:
    return ledger.export_csv(ledger.for_year(tax_year))


def _revenue_by_month_md(ledger: RevenueLedger, tax_year: int) -> str:
    lines = [f"# Revenue by month — {tax_year}", "", "| Month | Total |", "|---|---|"]
    for month in range(1, 13):
        summary = ledger.monthly_summary(tax_year, month)
        lines.append(f"| {month:02d} | ${summary['total']:,.2f} |")
    return "\n".join(lines)


def _deductions_csv(flags: list[DeductionFlag]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["tax_year", "category", "description", "estimated_amount", "confidence", "note"])
    for flag in flags:
        writer.writerow([flag.tax_year, flag.category.value, flag.description, f"{flag.estimated_amount:.2f}", flag.confidence, flag.note])
    return buffer.getvalue()


def _invoices_csv(tracker: InvoiceTracker) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "type", "vendor_or_client", "amount", "status", "due_date", "paid_date"])
    for invoice in tracker.all():
        writer.writerow([
            invoice.id, invoice.invoice_type.value, invoice.vendor_or_client,
            f"{invoice.amount:.2f}", invoice.status.value, invoice.due_date.isoformat(),
            invoice.paid_date.isoformat() if invoice.paid_date else "",
        ])
    return buffer.getvalue()


def _quarterly_estimates_md(estimates: list[QuarterlyEstimate]) -> str:
    lines = ["# Quarterly estimated tax payments", "", "| Quarter | Recommended payment | Due date |", "|---|---|---|"]
    for est in sorted(estimates, key=lambda e: e.quarter):
        lines.append(f"| Q{est.quarter} | ${est.recommended_quarterly_payment:,.2f} | {est.due_date.isoformat()} |")
    return "\n".join(lines)


def _contractor_1099_candidates(contractor_payments: dict[str, float]) -> list[Contractor1099Candidate]:
    return [
        Contractor1099Candidate(vendor=vendor, total_paid=round(total, 2))
        for vendor, total in contractor_payments.items()
        if total >= CONTRACTOR_1099_THRESHOLD
    ]


class YearEndPackager:
    def build(
        self,
        tax_year: int,
        revenue_ledger: RevenueLedger,
        invoice_tracker: InvoiceTracker,
        deduction_flags: list[DeductionFlag],
        quarterly_estimates: list[QuarterlyEstimate],
        receipts_by_category: dict[IRSCategory, list[str]],
        contractor_payments: dict[str, float],
    ) -> YearEndPackage:
        revenue_records = revenue_ledger.for_year(tax_year)
        receipts_manifest = {cat.value: urls for cat, urls in receipts_by_category.items()}
        receipt_count = sum(len(urls) for urls in receipts_manifest.values())

        summary_message = (
            f"Year-end package ready for CPA. {len(revenue_records)} revenue records, "
            f"{receipt_count} expense records, {len(deduction_flags)} deductions tracked. "
            f"Share {cpa_handoff_year_complete_folder(tax_year)} folder with your CPA."
        )

        return YearEndPackage(
            tax_year=tax_year,
            folder=cpa_handoff_year_complete_folder(tax_year),
            revenue_csv=_revenue_csv(revenue_ledger, tax_year),
            revenue_by_month_md=_revenue_by_month_md(revenue_ledger, tax_year),
            deductions_csv=_deductions_csv(deduction_flags),
            invoices_csv=_invoices_csv(invoice_tracker),
            receipts_manifest=receipts_manifest,
            quarterly_estimates_summary_md=_quarterly_estimates_md(quarterly_estimates),
            contractor_1099_candidates=_contractor_1099_candidates(contractor_payments),
            summary_message=summary_message,
        )
