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
invoice_tracker — tracks every invoice issued and every invoice received
from vendors/contractors. Flags overdue invoices with actionable options.
Pure Python, in-memory store — the caller (accounting_agent) is responsible
for loading/persisting records from Supabase.
"""

import itertools
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class InvoiceType(str, Enum):
    SENT = "sent"          # you billed a client
    RECEIVED = "received"  # a vendor/contractor billed you


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    WRITTEN_OFF = "written_off"


_id_counter = itertools.count(1)


@dataclass
class Invoice:
    invoice_type: InvoiceType
    vendor_or_client: str
    amount: float
    due_date: date
    issued_date: date
    status: InvoiceStatus = InvoiceStatus.SENT
    paid_date: Optional[date] = None
    document_url: Optional[str] = None
    write_off_reason: Optional[str] = None
    id: int = field(default_factory=lambda: next(_id_counter))


@dataclass(frozen=True)
class OverdueFlag:
    invoice: Invoice
    days_overdue: int

    def to_decision_card(self) -> dict:
        return {
            "message": (
                f"Invoice #{self.invoice.id} to {self.invoice.vendor_or_client} "
                f"is {self.days_overdue} days past due — ${self.invoice.amount:,.2f}"
            ),
            "options": ["send_reminder", "mark_paid", "write_off"],
        }


class InvoiceTracker:
    def __init__(self):
        self._invoices: dict[int, Invoice] = {}

    def add_invoice(self, invoice: Invoice) -> Invoice:
        self._invoices[invoice.id] = invoice
        return invoice

    def get(self, invoice_id: int) -> Invoice:
        return self._invoices[invoice_id]

    def all(self) -> list[Invoice]:
        return list(self._invoices.values())

    def mark_paid(self, invoice_id: int, paid_date: date) -> Invoice:
        invoice = self._invoices[invoice_id]
        invoice.status = InvoiceStatus.PAID
        invoice.paid_date = paid_date
        return invoice

    def write_off(self, invoice_id: int, reason: str) -> Invoice:
        invoice = self._invoices[invoice_id]
        invoice.status = InvoiceStatus.WRITTEN_OFF
        invoice.write_off_reason = reason
        return invoice

    def overdue_invoices(self, as_of: Optional[date] = None) -> list[OverdueFlag]:
        as_of = as_of or date.today()
        flags: list[OverdueFlag] = []
        for invoice in self._invoices.values():
            if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.WRITTEN_OFF):
                continue
            if invoice.due_date >= as_of:
                continue
            invoice.status = InvoiceStatus.OVERDUE
            flags.append(OverdueFlag(invoice=invoice, days_overdue=(as_of - invoice.due_date).days))
        return sorted(flags, key=lambda f: f.days_overdue, reverse=True)

    def totals_by_type(self, status: Optional[InvoiceStatus] = None) -> dict[InvoiceType, float]:
        totals = {InvoiceType.SENT: 0.0, InvoiceType.RECEIVED: 0.0}
        for invoice in self._invoices.values():
            if status is not None and invoice.status != status:
                continue
            totals[invoice.invoice_type] += invoice.amount
        return totals
