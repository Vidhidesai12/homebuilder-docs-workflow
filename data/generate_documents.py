"""Generate deterministic, wholly fictional PDF fixtures and ground truth.

No Project 1 import, environment variable, or database connection is used.
The catalog constants below mirror its documented seed-42 generator.
"""
from __future__ import annotations

import json
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
TRUTH = ROOT / "ground_truth"
COMMUNITIES = (
    "Demo Alder Grove", "Demo Birch Landing", "Demo Cedar Hollow",
    "Demo Juniper Vista", "Demo Maple Terrace", "Demo Oakline Park",
    "Demo Pinecrest Haven", "Demo Willow Crossing",
)
TRADES = ("Sitework", "Concrete", "Framing", "Mechanical", "Inspection")
CATEGORIES = ("Sitework", "Materials", "Labor", "Permits")
KNOWN_VENDORS = {f"Demo {trade} Vendor {n:02d}" for trade in TRADES for n in range(1, 9)}
ISSUE_DATE = date(2026, 11, 10)
REVIEW_THRESHOLD = Decimal("25000.00")


def money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def validate_record(record: dict, seen: set[tuple[str, str]]) -> list[str]:
    reasons = []
    vendor = record["vendor_name"]
    if vendor not in KNOWN_VENDORS:
        reasons.append("unknown_vendor")
    key = (vendor, record["document_number"])
    if record["document_type"] == "invoice" and key in seen:
        reasons.append("duplicate_invoice")
    if record["document_type"] == "invoice":
        seen.add(key)
    if Decimal(record["total_amount"]) > REVIEW_THRESHOLD:
        reasons.append("budget_exception")
    return reasons


def make_records(seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    records = []
    seen: set[tuple[str, str]] = set()
    for i in range(1, 21):
        kind = "invoice" if i <= 15 else "change_order"
        community_id = (i - 1) % len(COMMUNITIES) + 1
        # Project 1 makes one category per community/month, with month_offset 22.
        category = CATEGORIES[(22 + community_id) % 4]
        vendor = f"Demo {TRADES[(i - 1) % 5]} Vendor {(i - 1) // 5 + 1:02d}"
        if i == 19:
            vendor = "Demo Unknown Trade Vendor 99"
        number = f"INV-2026-{i:03d}" if kind == "invoice" else f"CO-2026-{i-15:03d}"
        if i == 14:
            vendor, number = records[2]["vendor_name"], records[2]["document_number"]
        if i == 12:
            items = [
                {"description": "Synthetic material package", "quantity": 2, "unit_price": "14250.00", "amount": "28500.00"}
            ]
        else:
            items = []
            for j in range(2):
                quantity = rng.randint(1, 4)
                price = Decimal(rng.randint(300, 1800))
                items.append({
                    "description": f"{category} demo work item {j+1}",
                    "quantity": quantity,
                    "unit_price": money(price),
                    "amount": money(quantity * price),
                })
        total = sum((Decimal(item["amount"]) for item in items), Decimal("0"))
        record = {
            "filename": f"{kind}_{i:02d}.pdf",
            "document_type": kind,
            "document_number": number,
            "vendor_name": vendor,
            "issue_date": ISSUE_DATE.isoformat(),
            "community": COMMUNITIES[community_id - 1],
            "lot_number": (i * 7) % 150 + 1,
            "budget_category": category,
            "line_items": items,
            "total_amount": money(total),
        }
        reasons = validate_record(record, seen)
        record["expected_validation_status"] = "exception" if reasons else "valid"
        record["expected_exception_reasons"] = reasons
        records.append(record)
    return records


def render_pdf(record: dict, path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    pdf.setTitle(record["document_number"])
    pdf.setAuthor("Synthetic Homebuilder Portfolio")
    y = 750
    lines = [
        "SYNTHETIC HOME BUILDER DOCUMENT",
        "Vendor Invoice" if record["document_type"] == "invoice" else "Construction Change Order",
        f"Document Number: {record['document_number']}",
        f"Vendor: {record['vendor_name']}",
        f"Issue Date: {record['issue_date']}",
        f"Community: {record['community']}",
        f"Lot Number: {record['lot_number']}",
        f"Budget Category: {record['budget_category']}",
        "Line Items:",
    ]
    for item in record["line_items"]:
        lines.append(f"{item['description']} | Qty {item['quantity']} | Unit ${item['unit_price']} | Amount ${item['amount']}")
    lines.append(f"Total Amount: ${record['total_amount']}")
    for line in lines:
        pdf.drawString(50, y, line)
        y -= 24
    pdf.save()


def generate(seed: int = 42) -> list[dict]:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    TRUTH.mkdir(parents=True, exist_ok=True)
    records = make_records(seed)
    for record in records:
        render_pdf(record, SAMPLES / record["filename"])
        (TRUTH / f"{Path(record['filename']).stem}.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
    return records


if __name__ == "__main__":
    generated = generate()
    print(f"Generated {len(generated)} PDFs and ground-truth records")
