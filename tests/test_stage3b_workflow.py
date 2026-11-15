"""Static checks on the exported, live-tested n8n graph."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / "workflows" / name).read_text(encoding="utf-8"))


def node(workflow, name):
    return next(item for item in workflow["nodes"] if item["name"] == name)


def successor(workflow, name):
    return workflow["connections"][name]["main"][0][0]["node"]


def test_stage1_and_stage2_exports_remain_separate():
    stage1 = load("pdf_ingestion.json")
    stage2 = load("gemini_invoice_extraction_stage2.json")
    stage3b = load("gemini_validation_stage3b.json")
    assert len(stage1["nodes"]) == 3
    assert successor(stage2, "Code in JavaScript") == "Show text and metadata"
    assert stage3b["id"] not in {stage1.get("id"), stage2.get("id")}
    assert successor(stage3b, "Code in JavaScript") == "Prepare validation request"
    assert node(stage3b, "Message a model")["parameters"] == node(stage2, "Message a model")["parameters"]


def test_hash_and_request_path():
    workflow = load("gemini_validation_stage3b.json")
    assert successor(workflow, "PDF upload form") == "Extract PDF text"
    assert successor(workflow, "Extract PDF text") == "Hash PDF text"
    assert successor(workflow, "Hash PDF text") == "Message a model"
    assert successor(workflow, "Prepare validation request") == "POST validation API"
    assert successor(workflow, "POST validation API") == "Show validation outcome"
    hash_node = node(workflow, "Hash PDF text")["parameters"]
    assert hash_node["type"] == "SHA256" and hash_node["dataPropertyName"] == "pdf_text_sha256"
    code = node(workflow, "Prepare validation request")["parameters"]["jsCode"]
    for field in ("source_filename", "idempotency_key", "extracted", "extraction_confidence", "extraction_uncertainty", "pdf_text_sha256"):
        assert field in code


def test_http_errors_are_not_treated_as_approval():
    workflow = load("gemini_validation_stage3b.json")
    http = node(workflow, "POST validation API")
    assert http["parameters"]["method"] == "POST"
    assert http["parameters"]["url"] == "http://host.docker.internal:8001/v1/validate"
    assert http["parameters"]["options"]["timeout"] == 15000
    response = http["parameters"]["options"]["response"]["response"]
    assert response["fullResponse"] and response["neverError"]
    assert http["onError"] == "continueRegularOutput"
    final = node(workflow, "Show validation outcome")["parameters"]["jsCode"]
    for case in ("accepted", "needs_review", "rejected_invalid", "conflict", "transport_error", "http_error"):
        assert case in final
    assert "approved_for_payment: false" in final
