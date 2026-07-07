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
document_organizer — resolves the correct folder path for any financial
document and hands the bytes off to a storage backend to persist.

The storage backend only needs to satisfy DocumentStorage (structural
typing — no import of finance.integrations.document_store required here,
keeping this module storage-agnostic). Concrete backends (local disk,
Google Drive, S3) are implemented in finance/integrations/document_store.py.

Folder layout mirrors the IRS document folder structure defined in
CLAUDE.md's Finance section:

  KDavis Business Financials/
    [YEAR]/
      Revenue/{Stripe_Exports,Invoices_Sent,Other_Income}/
      Expenses/{<IRSCategory>}/
      Payroll/{Owner_Salary,Contractor_1099s}/
      Tax_Filings/{Quarterly_Estimates,Annual_Returns}/
      CPA_Handoff/[MONTH]_Package/
"""

from enum import Enum
from typing import Protocol

from finance.accounting.expense_categorizer import IRSCategory

ROOT_FOLDER = "KDavis Business Financials"


class DocumentStorage(Protocol):
    def save(self, relative_path: str, content: bytes) -> str:
        """Persist content at relative_path, return a retrievable URL/path."""
        ...


class RevenueDocKind(str, Enum):
    STRIPE_EXPORT = "Stripe_Exports"
    INVOICE_SENT = "Invoices_Sent"
    OTHER_INCOME = "Other_Income"


class PayrollDocKind(str, Enum):
    OWNER_SALARY = "Owner_Salary"
    CONTRACTOR_1099 = "Contractor_1099s"


class TaxFilingKind(str, Enum):
    QUARTERLY_ESTIMATE = "Quarterly_Estimates"
    ANNUAL_RETURN = "Annual_Returns"


def expense_folder(year: int, category: IRSCategory) -> str:
    return f"{ROOT_FOLDER}/{year}/Expenses/{category.value}"


def revenue_folder(year: int, kind: RevenueDocKind) -> str:
    return f"{ROOT_FOLDER}/{year}/Revenue/{kind.value}"


def payroll_folder(year: int, kind: PayrollDocKind) -> str:
    return f"{ROOT_FOLDER}/{year}/Payroll/{kind.value}"


def tax_filing_folder(year: int, kind: TaxFilingKind) -> str:
    return f"{ROOT_FOLDER}/{year}/Tax_Filings/{kind.value}"


def cpa_handoff_folder(year: int, month_label: str) -> str:
    return f"{ROOT_FOLDER}/{year}/CPA_Handoff/{month_label}_Package"


def cpa_handoff_year_complete_folder(year: int) -> str:
    return f"{ROOT_FOLDER}/{year}/CPA_Handoff/{year}_Complete"


class DocumentOrganizer:
    def __init__(self, storage: DocumentStorage):
        self._storage = storage

    def file_expense_receipt(self, year: int, category: IRSCategory, filename: str, content: bytes) -> str:
        return self._storage.save(f"{expense_folder(year, category)}/{filename}", content)

    def file_revenue_document(self, year: int, kind: RevenueDocKind, filename: str, content: bytes) -> str:
        return self._storage.save(f"{revenue_folder(year, kind)}/{filename}", content)

    def file_payroll_document(self, year: int, kind: PayrollDocKind, filename: str, content: bytes) -> str:
        return self._storage.save(f"{payroll_folder(year, kind)}/{filename}", content)

    def file_tax_filing(self, year: int, kind: TaxFilingKind, filename: str, content: bytes) -> str:
        return self._storage.save(f"{tax_filing_folder(year, kind)}/{filename}", content)

    def file_cpa_handoff_document(self, year: int, month_label: str, filename: str, content: bytes) -> str:
        return self._storage.save(f"{cpa_handoff_folder(year, month_label)}/{filename}", content)
