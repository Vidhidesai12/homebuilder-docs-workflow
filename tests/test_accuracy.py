import json
from pathlib import Path

from evals.accuracy import ROOT, evaluate_file, evaluate_paths


SOURCE = ROOT / "evals" / "outputs" / "invoice_01.json"


def candidate(tmp_path: Path, mutate):
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    mutate(data[0])
    path = tmp_path / "invoice_01.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return evaluate_file(path)


def test_first_invoice_exact():
    result = evaluate_file(SOURCE)
    assert result["schema_valid"]
    assert result["source_filename"] == "invoice_01.pdf"
    assert result["document_identity"] == "INV-2026-001"
    assert result["field_accuracy"] == {"matched": 16, "total": 16, "rate": 1.0}
    assert result["exact_document_accuracy"]
    assert not result["missing_fields"]
    assert not result["incorrect_fields"]
    assert not result["unexpected_fields"]


def test_malformed_json(tmp_path):
    path = tmp_path / "invoice_01.json"
    path.write_text("{broken", encoding="utf-8")
    result = evaluate_file(path)
    assert not result["exact_document_accuracy"]
    assert any("malformed JSON" in message for message in result["validation_errors"])


def test_missing_required_field(tmp_path):
    result = candidate(tmp_path, lambda doc: doc.pop("vendor_name"))
    assert not result["schema_valid"]
    assert "vendor_name" in result["missing_fields"]


def test_wrong_total_and_line_extension(tmp_path):
    result = candidate(tmp_path, lambda doc: doc.update(total_amount="2755.00"))
    assert not result["schema_valid"]
    assert "total_amount" in result["incorrect_fields"]
    assert any("total_amount does not equal" in message for message in result["validation_errors"])
    broken_item = candidate(tmp_path, lambda doc: doc["line_items"][0].update(amount="350.00"))
    assert not broken_item["schema_valid"]
    assert "line_items[0].amount" in broken_item["incorrect_fields"]


def test_wrong_document_identity_and_filename(tmp_path):
    result = candidate(tmp_path, lambda doc: doc.update(document_number="INV-2026-999", filename="invoice_02.pdf"))
    assert not result["exact_document_accuracy"]
    assert "document_number" in result["incorrect_fields"]
    assert any("document number does not match" in message for message in result["validation_errors"])
    assert any("filename does not match" in message for message in result["validation_errors"])


def test_line_item_detail_and_unexpected_field(tmp_path):
    result = candidate(tmp_path, lambda doc: (doc["line_items"][0].update(description="Different work"), doc.update(extra_field="surprise")))
    assert "line_items[0].description" in result["incorrect_fields"]
    assert "extra_field" in result["unexpected_fields"]
    assert not result["exact_document_accuracy"]


def test_batch_summary_is_offline_and_uses_saved_files():
    report = evaluate_paths([SOURCE])
    assert report["document_count"] == 1
    assert report["field_accuracy"]["matched"] == 16
    assert report["exact_document_accuracy"] == {"matched": 1, "total": 1, "rate": 1.0}
