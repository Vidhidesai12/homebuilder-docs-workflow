"""Opt-in database and HTTP stack smoke test; writes only documents schema rows."""
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

TRUTH = Path(__file__).resolve().parents[1] / "data" / "ground_truth"


def payload(stem: str, run_id: str) -> dict:
    document = json.loads((TRUTH / f"{stem}.json").read_text(encoding="utf-8"))
    return {
        "idempotency_key": f"stage3-smoke-{run_id}-{stem}",
        "source_filename": document["filename"],
        "extracted": {k: v for k, v in document.items() if not k.startswith("expected_")},
        "extraction_confidence": "0.94",
        "extraction_uncertainty": [],
    }


def main() -> None:
    if not os.environ.get("DOCUMENTS_DATABASE_URL"):
        raise RuntimeError("Set DOCUMENTS_DATABASE_URL for the limited documents role")
    client = TestClient(app)
    run_id = uuid.uuid4().hex[:12]
    cases = [
        ("invoice_03", "accepted", []),
        ("invoice_12", "needs_review", ["budget_exception"]),
        ("invoice_14", "needs_review", ["duplicate_invoice"]),
        ("change_order_19", "needs_review", ["unknown_vendor"]),
    ]
    results = []
    for stem, expected, codes in cases:
        request = payload(stem, run_id)
        if stem in {"invoice_03", "invoice_14"}:
            # Same synthetic vendor+number, new on every smoke run.
            request["extracted"]["document_number"] = f"INV-SMOKE-{run_id}"
        response = client.post("/v1/validate", json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["outcome"] == expected, body
        assert set(codes) <= {item["code"] for item in body["reasons"]}, body
        repeat = client.post("/v1/validate", json=request)
        assert repeat.status_code == 200 and repeat.json() == body, repeat.text
        results.append({"document": stem, "outcome": body["outcome"], "reasons": [item["code"] for item in body["reasons"]], "idempotent": True})
    bad = payload("invoice_02", run_id)
    bad["extracted"]["total_amount"] = "0.00"
    response = client.post("/v1/validate", json=bad)
    assert response.status_code == 200 and response.json()["outcome"] == "rejected_invalid", response.text
    changed = payload("invoice_03", run_id)
    changed["extracted"]["total_amount"] = "1.00"
    assert client.post("/v1/validate", json=changed).status_code == 409
    simultaneous = [payload("invoice_01", f"{run_id}-race-{i}") for i in range(2)]
    for request in simultaneous:
        request["extracted"]["document_number"] = f"INV-RACE-{run_id}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda item: client.post("/v1/validate", json=item), simultaneous))
    assert all(response.status_code == 200 for response in responses), responses
    outcomes = sorted(response.json()["outcome"] for response in responses)
    assert outcomes == ["accepted", "needs_review"], outcomes
    print(json.dumps({"passed": True, "cases": results, "invalid_rejected": True, "idempotency_conflict": True, "concurrent_outcomes": outcomes}, indent=2))


if __name__ == "__main__":
    main()
