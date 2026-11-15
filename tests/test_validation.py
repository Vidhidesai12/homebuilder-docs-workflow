import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import IdempotencyConflict, request_digest
from app.validation import validate_document

TRUTH = Path(__file__).resolve().parents[1] / "data" / "ground_truth"
COMMUNITIES = (
    "Demo Alder Grove", "Demo Birch Landing", "Demo Cedar Hollow", "Demo Juniper Vista",
    "Demo Maple Terrace", "Demo Oakline Park", "Demo Pinecrest Haven", "Demo Willow Crossing",
)
CATEGORIES = ("Sitework", "Materials", "Labor", "Permits")


class FakeCatalog:
    def vendor_id(self, name):
        import re
        return 1 if re.fullmatch(r"Demo (Sitework|Concrete|Framing|Mechanical|Inspection) Vendor 0[1-8]", name) else None

    def community_id(self, name):
        return COMMUNITIES.index(name) + 1 if name in COMMUNITIES else None

    def lot_exists(self, community_id, lot_number):
        return 1 <= lot_number <= 150

    def budget_category(self, community_id, month):
        return CATEGORIES[(22 + community_id) % 4] if month == "2026-11-01" else None


def record(name):
    data = json.loads((TRUTH / f"{name}.json").read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if not key.startswith("expected_")}


def test_normal_invoice_and_observed_gemini_alias():
    doc = record("invoice_01")
    doc["document_date"] = doc.pop("issue_date")
    doc["lot_number"] = "8"
    parsed, status, reasons = validate_document(doc, "invoice_01.pdf", FakeCatalog(), lambda *_: True)
    assert status == "accepted" and reasons == []
    assert parsed.total_amount == 2754


def test_three_deliberate_problem_cases():
    claims = set()

    def claim(vendor, number):
        key = vendor, number
        if key in claims:
            return False
        claims.add(key)
        return True

    validate_document(record("invoice_03"), "invoice_03.pdf", FakeCatalog(), claim)
    cases = {
        "invoice_12": "budget_exception",
        "invoice_14": "duplicate_invoice",
        "change_order_19": "unknown_vendor",
    }
    for name, expected in cases.items():
        _, status, reasons = validate_document(record(name), f"{name}.pdf", FakeCatalog(), claim)
        assert status == "needs_review"
        assert [item["code"] for item in reasons] == [expected]


@pytest.mark.parametrize("change,code", [
    (lambda d: d.update(community="Demo Absent"), "unknown_community"),
    (lambda d: d.update(lot_number=151), "community_lot_mismatch"),
    (lambda d: d.update(budget_category="Materials"), "budget_category_mismatch"),
    (lambda d: d.update(issue_date="2027-01-10"), "budget_record_missing"),
])
def test_catalog_mismatches(change, code):
    doc = record("invoice_01")
    change(doc)
    _, status, reasons = validate_document(doc, "invoice_01.pdf", FakeCatalog(), lambda *_: True)
    assert status == "needs_review"
    assert code in [item["code"] for item in reasons]


@pytest.mark.parametrize("change", [
    lambda d: d.pop("vendor_name"),
    lambda d: d["line_items"][0].update(quantity=0),
    lambda d: d["line_items"][0].update(unit_price="-1.00"),
    lambda d: d["line_items"][0].update(unit_price="0.00", amount="0.00"),
    lambda d: d.update(total_amount="0.00"),
    lambda d: d.update(issue_date="2026-02-30"),
    lambda d: d.update(issue_date=1794355200),
    lambda d: d.update(total_amount="2755.00"),
    lambda d: d.update(filename="invoice_02.pdf"),
])
def test_invalid_documents_rejected(change):
    doc = record("invoice_01")
    change(doc)
    _, status, reasons = validate_document(doc, "invoice_01.pdf", FakeCatalog(), lambda *_: True)
    assert status == "rejected_invalid"
    assert reasons


def test_digest_canonical_and_api_contract(monkeypatch):
    assert request_digest({"a": 1, "b": 2}) == request_digest({"b": 2, "a": 1})
    from app import main
    monkeypatch.setattr(main, "validate_and_store", lambda payload: {"outcome": "accepted", "source_filename": payload["source_filename"]})
    client = TestClient(app)
    payload = {"idempotency_key": "invoice01-run1", "source_filename": "invoice_01.pdf", "extracted": record("invoice_01")}
    response = client.post("/v1/validate", json=payload)
    assert response.status_code == 200 and response.json()["outcome"] == "accepted"
    assert client.post("/v1/validate", json={**payload, "source_filename": "../bad.pdf"}).status_code == 422
    def conflict(_):
        raise IdempotencyConflict("different content")
    monkeypatch.setattr(main, "validate_and_store", conflict)
    assert client.post("/v1/validate", json=payload).status_code == 409
