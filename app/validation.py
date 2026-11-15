"""Deterministic document checks; no AI or database writes."""
from __future__ import annotations

from decimal import Decimal
from typing import Callable, Protocol

from pydantic import ValidationError

from evals.accuracy import ExtractedDocument, normalize

REVIEW_THRESHOLD = Decimal("25000.00")


class Catalog(Protocol):
    def vendor_id(self, name: str) -> int | None: ...
    def community_id(self, name: str) -> int | None: ...
    def lot_exists(self, community_id: int, lot_number: int) -> bool: ...
    def budget_category(self, community_id: int, month: str) -> str | None: ...


def reason(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def validate_extraction(extracted: dict, source_filename: str) -> tuple[ExtractedDocument | None, list[dict[str, str]]]:
    data = normalize(extracted)
    errors = []
    if "filename" in data and data["filename"] != source_filename:
        errors.append(reason("source_identity_mismatch", "Extracted filename differs from source_filename."))
    try:
        doc = ExtractedDocument.model_validate(data)
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(map(str, error["loc"])) or "document"
            errors.append(reason("invalid_extraction", f"{location}: {error['msg']}"))
        return None, errors
    if doc.total_amount <= 0:
        errors.append(reason("invalid_extraction", "total_amount must be greater than zero."))
    for index, item in enumerate(doc.line_items):
        if item.unit_price <= 0 or item.amount <= 0:
            errors.append(reason("invalid_extraction", f"line_items.{index}: unit_price and amount must be greater than zero."))
    return (None, errors) if errors else (doc, [])


def validate_business(doc: ExtractedDocument, catalog: Catalog) -> list[dict[str, str]]:
    reasons = []
    if catalog.vendor_id(doc.vendor_name) is None:
        reasons.append(reason("unknown_vendor", f"Vendor '{doc.vendor_name}' is absent from the vendor catalog."))
    community_id = catalog.community_id(doc.community)
    if community_id is None:
        reasons.append(reason("unknown_community", f"Community '{doc.community}' is absent from the community catalog."))
    else:
        if not catalog.lot_exists(community_id, doc.lot_number):
            reasons.append(reason("community_lot_mismatch", f"Lot {doc.lot_number} does not belong to '{doc.community}'."))
        month = doc.issue_date.replace(day=1).isoformat()
        category = catalog.budget_category(community_id, month)
        if category is None:
            reasons.append(reason("budget_record_missing", f"No budget row for '{doc.community}' in {month}."))
        elif category != doc.budget_category:
            reasons.append(reason("budget_category_mismatch", f"Community-month category is '{category}', document says '{doc.budget_category}'."))
    if doc.total_amount > REVIEW_THRESHOLD:
        reasons.append(reason("budget_exception", f"Document total {doc.total_amount:.2f} exceeds the {REVIEW_THRESHOLD:.2f} review threshold."))
    return reasons


def outcome(reasons: list[dict[str, str]], invalid: bool = False) -> str:
    return "rejected_invalid" if invalid else "needs_review" if reasons else "accepted"


def validate_document(extracted: dict, source_filename: str, catalog: Catalog, claim_invoice: Callable[[str, str], bool]) -> tuple[ExtractedDocument | None, str, list[dict[str, str]]]:
    """Return parsed document, outcome, reasons; claim returns false for duplicates."""
    doc, reasons = validate_extraction(extracted, source_filename)
    if doc is None:
        return None, "rejected_invalid", reasons
    reasons.extend(validate_business(doc, catalog))
    if doc.document_type == "invoice" and catalog.vendor_id(doc.vendor_name) is not None:
        if not claim_invoice(doc.vendor_name, doc.document_number):
            reasons.append(reason("duplicate_invoice", f"Invoice '{doc.document_number}' is already claimed for vendor '{doc.vendor_name}'."))
    return doc, outcome(reasons), reasons
