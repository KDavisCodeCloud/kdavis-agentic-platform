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
receipt_processor — turns a receipt (image bytes or already-extracted text)
into a structured, categorized record.

OCR is pluggable: pass an `ocr_fn(image_bytes) -> str` callable at
construction time. No OCR engine is imported here — wiring a real engine
(Tesseract, Textract, a vision LLM call, etc.) happens in the integration
session that wires this into accounting_agent's live pipeline.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Callable, Optional

from finance.accounting.expense_categorizer import IRSCategory, categorize_expense

OCRFunction = Callable[[bytes], str]

_DATE_PATTERNS = (
    "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y",
)
_DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}|"
    r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b"
)
_AMOUNT_RE = re.compile(r"\$?\s?(\d{1,3}(?:,\d{3})*\.\d{2})")
_TOTAL_LINE_RE = re.compile(r"\btotal\b", re.IGNORECASE)


class ReceiptSource(str, Enum):
    EMAIL_FORWARD = "email_forward"
    DASHBOARD_UPLOAD = "dashboard_upload"


@dataclass(frozen=True)
class ReceiptLineItem:
    description: str
    amount: Optional[float] = None


@dataclass
class ProcessedReceipt:
    vendor: str
    amount: Optional[float]
    receipt_date: Optional[date]
    line_items: list[ReceiptLineItem]
    irs_category: IRSCategory
    category_confidence: float
    needs_review: bool
    review_question: Optional[str]
    source: ReceiptSource
    raw_text: str

    def to_expense_record(self, tax_year: int | None = None) -> dict:
        """Shape matching the `expenses` table row this record will become."""
        return {
            "amount": self.amount,
            "vendor": self.vendor,
            "description": "; ".join(li.description for li in self.line_items) or self.vendor,
            "date": self.receipt_date.isoformat() if self.receipt_date else None,
            "irs_category": self.irs_category.value,
            "receipt_ocr_text": self.raw_text,
            "tax_year": tax_year or (self.receipt_date.year if self.receipt_date else None),
            "deductible": True,
            "approved_by_cpa": False,
        }


def _parse_date(text: str) -> Optional[date]:
    match = _DATE_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(raw, fmt.replace(",", "")).date()
        except ValueError:
            continue
    return None


def _parse_amount(text: str) -> Optional[float]:
    total_line_amounts: list[float] = []
    all_amounts: list[float] = []
    for line in text.splitlines():
        for match in _AMOUNT_RE.finditer(line):
            value = float(match.group(1).replace(",", ""))
            all_amounts.append(value)
            if _TOTAL_LINE_RE.search(line):
                total_line_amounts.append(value)
    if total_line_amounts:
        return max(total_line_amounts)
    if all_amounts:
        return max(all_amounts)
    return None


def _parse_vendor(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not _AMOUNT_RE.fullmatch(stripped) and not _DATE_RE.fullmatch(stripped):
            return stripped
    return "Unknown Vendor"


def _parse_line_items(text: str) -> list[ReceiptLineItem]:
    items: list[ReceiptLineItem] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _TOTAL_LINE_RE.search(stripped):
            continue
        match = _AMOUNT_RE.search(stripped)
        if not match:
            continue
        description = stripped[: match.start()].strip(" -:\t") or stripped
        items.append(ReceiptLineItem(description=description, amount=float(match.group(1).replace(",", ""))))
    return items


class ReceiptProcessor:
    """Processes receipts from either a dedicated OCR backend or plain text."""

    def __init__(self, ocr_fn: Optional[OCRFunction] = None):
        self._ocr_fn = ocr_fn

    def process_image(self, image_bytes: bytes, source: ReceiptSource = ReceiptSource.DASHBOARD_UPLOAD) -> ProcessedReceipt:
        if self._ocr_fn is None:
            raise RuntimeError(
                "No OCR backend configured. Pass ocr_fn=... to ReceiptProcessor, "
                "or call process_text() directly with already-extracted text."
            )
        text = self._ocr_fn(image_bytes)
        return self.process_text(text, source=source)

    def process_text(self, text: str, source: ReceiptSource = ReceiptSource.EMAIL_FORWARD) -> ProcessedReceipt:
        vendor = _parse_vendor(text)
        amount = _parse_amount(text)
        receipt_date = _parse_date(text)
        line_items = _parse_line_items(text)

        result = categorize_expense(vendor=vendor, description=text, amount=amount)

        return ProcessedReceipt(
            vendor=vendor,
            amount=amount,
            receipt_date=receipt_date,
            line_items=line_items,
            irs_category=result.category,
            category_confidence=result.confidence,
            needs_review=result.needs_review or amount is None,
            review_question=result.review_question,
            source=source,
            raw_text=text,
        )
