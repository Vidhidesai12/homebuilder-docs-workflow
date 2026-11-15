"""Validate saved extraction JSON and compare it with independent ground truth.

Usage: python -m evals.accuracy [evals/outputs/*.json ...]
No network calls, model calls, or database connections are made.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
TRUTH = ROOT / "data" / "ground_truth"
OUTPUTS = ROOT / "evals" / "outputs"
DOCUMENT_FIELDS = (
    "document_type", "document_number", "vendor_name", "issue_date",
    "community", "lot_number", "budget_category", "total_amount",
)
ITEM_FIELDS = ("description", "quantity", "unit_price", "amount")
META_FIELDS = {"extraction_status"}
MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")


def display_path(path: Path) -> str:
    """Use portable repository-relative evidence paths when possible."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def parse_money(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("money must be a decimal string or integer")
    if isinstance(value, str) and not MONEY_RE.fullmatch(value):
        raise ValueError("money must have exactly two decimal places")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal amount") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("money must be finite, nonnegative, and have at most two decimal places")
    return amount


def parse_quantity(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("quantity must be a positive decimal")
    try:
        quantity = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid quantity") from exc
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError("quantity must be positive and finite")
    return quantity


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1)
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal

    @field_validator("description")
    @classmethod
    def nonblank_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description cannot be blank")
        return value

    @field_validator("quantity", mode="before")
    @classmethod
    def valid_quantity(cls, value: object) -> Decimal:
        return parse_quantity(value)

    @field_validator("unit_price", "amount", mode="before")
    @classmethod
    def valid_money(cls, value: object) -> Decimal:
        return parse_money(value)

    @model_validator(mode="after")
    def correct_extension(self):
        if self.quantity * self.unit_price != self.amount:
            raise ValueError("line item amount does not equal quantity times unit price")
        return self


class ExtractedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: Literal["invoice", "change_order"]
    document_number: str = Field(min_length=1)
    vendor_name: str = Field(min_length=1)
    issue_date: date
    community: str = Field(min_length=1)
    lot_number: int = Field(gt=0)
    budget_category: str = Field(min_length=1)
    line_items: list[LineItem] = Field(min_length=1)
    total_amount: Decimal
    currency: str | None = None
    filename: str | None = None

    @field_validator("document_number", "vendor_name", "community", "budget_category")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field cannot be blank")
        return value

    @field_validator("lot_number", mode="before")
    @classmethod
    def valid_lot(cls, value: object) -> int:
        if isinstance(value, bool) or not re.fullmatch(r"[1-9]\d*", str(value)):
            raise ValueError("lot_number must be a positive integer")
        return int(value)

    @field_validator("issue_date", mode="before")
    @classmethod
    def valid_iso_date(cls, value: object) -> date:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("issue_date must be YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("issue_date is not a valid calendar date") from exc

    @field_validator("total_amount", mode="before")
    @classmethod
    def valid_total(cls, value: object) -> Decimal:
        return parse_money(value)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("currency must be a three-letter uppercase ISO code")
        return value

    @field_validator("filename")
    @classmethod
    def valid_filename(cls, value: str | None) -> str | None:
        if value is not None and ("/" in value or "\\" in value or not value.endswith(".pdf")):
            raise ValueError("filename must be a PDF basename")
        return value

    @model_validator(mode="after")
    def correct_total(self):
        if sum((item.amount for item in self.line_items), Decimal("0")) != self.total_amount:
            raise ValueError("total_amount does not equal line item amounts")
        return self


def normalize(raw: dict) -> dict:
    """Accept the observed Gemini date label and remove known transport metadata."""
    data = {k: v for k, v in raw.items() if k not in META_FIELDS}
    if "document_date" in data:
        if "issue_date" in data:
            # Both names are an ambiguous extraction, not a harmless alias.
            return data
        data["issue_date"] = data.pop("document_date")
    return data


def comparable(path: str, value: object) -> object:
    if path.endswith(("unit_price", "amount")) or path == "total_amount":
        return parse_money(value)
    if path.endswith("quantity"):
        return parse_quantity(value)
    if path == "lot_number":
        if isinstance(value, bool) or not re.fullmatch(r"[1-9]\d*", str(value)):
            raise ValueError("invalid lot number")
        return int(value)
    if path == "issue_date":
        if not isinstance(value, str):
            raise ValueError("invalid date")
        return date.fromisoformat(value)
    return value


def evaluate_file(output_path: Path, truth_dir: Path = TRUTH) -> dict:
    source_filename = output_path.stem + ".pdf"
    result = {
        "output_file": display_path(output_path), "source_filename": source_filename,
        "ground_truth_file": display_path(truth_dir / (output_path.stem + ".json")),
        "document_identity": None, "schema_valid": False, "validation_errors": [],
        "matched_fields": [], "missing_fields": [], "incorrect_fields": [],
        "unexpected_fields": [], "field_accuracy": None, "exact_document_accuracy": False,
    }
    truth_path = truth_dir / (output_path.stem + ".json")
    if not truth_path.is_file():
        result["validation_errors"].append("ground truth record not found")
        return result
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    if truth["filename"] != source_filename:
        result["validation_errors"].append("ground truth filename disagrees with output basename")
        return result
    try:
        raw = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["validation_errors"].append(f"malformed JSON: {exc}")
        return result
    if isinstance(raw, list):
        if len(raw) != 1:
            result["validation_errors"].append("output array must contain exactly one document")
            return result
        raw = raw[0]
    if not isinstance(raw, dict):
        result["validation_errors"].append("document output must be an object")
        return result
    data = normalize(raw)
    result["document_identity"] = data.get("document_number")
    if data.get("document_number") is not None and data["document_number"] != truth["document_number"]:
        result["validation_errors"].append("extracted document number does not match source identity")
    if data.get("document_type") is not None and data["document_type"] != truth["document_type"]:
        result["validation_errors"].append("extracted document type does not match source identity")
    if data.get("filename") is not None and data["filename"] != source_filename:
        result["validation_errors"].append("extracted filename does not match source filename")
    try:
        ExtractedDocument.model_validate(data)
        result["schema_valid"] = True
    except ValidationError as exc:
        result["validation_errors"].extend(
            f"{'.'.join(map(str, error['loc'])) or 'document'}: {error['msg']}"
            for error in exc.errors()
        )

    expected_paths: dict[str, object] = {field: truth[field] for field in DOCUMENT_FIELDS}
    if "currency" in truth:
        expected_paths["currency"] = truth["currency"]
    for index, item in enumerate(truth["line_items"]):
        for field in ITEM_FIELDS:
            expected_paths[f"line_items[{index}].{field}"] = item[field]

    actual_paths = {field: data[field] for field in DOCUMENT_FIELDS if field in data}
    if "currency" in data and "currency" in truth:
        actual_paths["currency"] = data["currency"]
    items = data.get("line_items")
    if isinstance(items, list):
        for index, item in enumerate(items):
            if isinstance(item, dict):
                for field in ITEM_FIELDS:
                    if field in item:
                        actual_paths[f"line_items[{index}].{field}"] = item[field]
                for extra in item.keys() - set(ITEM_FIELDS):
                    result["unexpected_fields"].append(f"line_items[{index}].{extra}")
            else:
                result["incorrect_fields"].append(f"line_items[{index}]")
    elif items is not None:
        result["incorrect_fields"].append("line_items")

    allowed = set(DOCUMENT_FIELDS) | {"line_items", "currency", "filename"}
    result["unexpected_fields"].extend(sorted(set(data) - allowed))
    if "currency" in data and "currency" not in truth:
        result["unexpected_fields"].append("currency (not present in ground truth)")
    for path, expected in expected_paths.items():
        if path not in actual_paths:
            result["missing_fields"].append(path)
            continue
        try:
            equal = comparable(path.split(".")[-1], actual_paths[path]) == comparable(path.split(".")[-1], expected)
        except (ValueError, TypeError):
            equal = False
        (result["matched_fields"] if equal else result["incorrect_fields"]).append(path)
    for path in actual_paths.keys() - expected_paths.keys():
        result["unexpected_fields"].append(path)
    denominator = len(expected_paths)
    result["field_accuracy"] = {"matched": len(result["matched_fields"]), "total": denominator, "rate": len(result["matched_fields"]) / denominator}
    result["exact_document_accuracy"] = (
        result["schema_valid"] and not result["validation_errors"]
        and not result["missing_fields"] and not result["incorrect_fields"]
        and not result["unexpected_fields"] and len(result["matched_fields"]) == denominator
    )
    return result


def evaluate_paths(paths: list[Path], truth_dir: Path = TRUTH) -> dict:
    documents = [evaluate_file(path, truth_dir) for path in paths]
    scored = [doc for doc in documents if doc["field_accuracy"] is not None]
    matched = sum(doc["field_accuracy"]["matched"] for doc in scored)
    total = sum(doc["field_accuracy"]["total"] for doc in scored)
    exact = sum(doc["exact_document_accuracy"] for doc in documents)
    return {
        "document_count": len(documents), "scored_document_count": len(scored),
        "field_accuracy": {"matched": matched, "total": total, "rate": matched / total if total else None},
        "exact_document_accuracy": {"matched": exact, "total": len(documents), "rate": exact / len(documents) if documents else None},
        "documents": documents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", nargs="*", type=Path, help="Saved Gemini JSON files; defaults to evals/outputs/*.json")
    parser.add_argument("--truth-dir", type=Path, default=TRUTH)
    parser.add_argument("--report", type=Path, help="Optional path to save the JSON report")
    args = parser.parse_args()
    paths = args.outputs or sorted(OUTPUTS.glob("*.json"))
    report = evaluate_paths(paths, args.truth_dir)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    if any(not doc["exact_document_accuracy"] for doc in report["documents"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
