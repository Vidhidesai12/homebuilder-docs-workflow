import json
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from data.generate_documents import CATEGORIES, COMMUNITIES, KNOWN_VENDORS, SAMPLES, TRUTH, make_records


def test_fixture_counts_and_exceptions():
    records = make_records()
    assert records == make_records()
    assert len(records) == 20
    assert [r["document_type"] for r in records].count("invoice") == 15
    assert [r["document_type"] for r in records].count("change_order") == 5
    exceptions = {r["filename"]: r["expected_exception_reasons"] for r in records if r["expected_exception_reasons"]}
    assert exceptions == {
        "invoice_12.pdf": ["budget_exception"],
        "invoice_14.pdf": ["duplicate_invoice"],
        "change_order_19.pdf": ["unknown_vendor"],
    }


def test_totals_and_catalog():
    for r in make_records():
        assert Decimal(r["total_amount"]) == sum(Decimal(x["quantity"]) * Decimal(x["unit_price"]) for x in r["line_items"])
        assert r["community"] in COMMUNITIES
        assert 1 <= r["lot_number"] <= 150
        community_id = COMMUNITIES.index(r["community"]) + 1
        assert r["budget_category"] == CATEGORIES[(22 + community_id) % 4]
        if r["filename"] != "change_order_19.pdf":
            assert r["vendor_name"] in KNOWN_VENDORS


def test_generated_files_and_pdf_text():
    records = make_records()
    assert len(list(SAMPLES.glob("*.pdf"))) == 20
    assert len(list(TRUTH.glob("*.json"))) == 20
    for r in records:
        assert (SAMPLES / r["filename"]).is_file()
        stored = json.loads((TRUTH / f"{Path(r['filename']).stem}.json").read_text(encoding="utf-8"))
        assert stored == r
    clean = records[0]
    extracted = "\n".join(page.extract_text() for page in PdfReader(SAMPLES / clean["filename"]).pages)
    for field in (clean["document_number"], clean["vendor_name"], clean["community"], clean["total_amount"]):
        assert field in extracted
