"""Opt-in n8n saved-JSON integration checks; no Gemini request is made."""
import json
import subprocess
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
WEBHOOK = "http://localhost:5678/webhook/stage3b-saved-json"


def payload(stem: str, run_id: str) -> dict:
    if stem == "invoice_01":
        extracted = json.loads((ROOT / "evals" / "outputs" / "invoice_01.json").read_text(encoding="utf-8"))[0]
    else:
        truth = json.loads((ROOT / "data" / "ground_truth" / f"{stem}.json").read_text(encoding="utf-8"))
        extracted = {key: value for key, value in truth.items() if not key.startswith("expected_")}
    return {
        "idempotency_key": f"stage3b-saved-{run_id}-{stem}",
        "source_filename": f"{stem}.pdf",
        "extracted": extracted,
        "extraction_confidence": None,
        "extraction_uncertainty": [],
    }


def audit_count(record_id: int) -> int:
    sql = f"SELECT count(*) FROM documents.audit_history WHERE record_id={int(record_id)}"
    result = subprocess.run(
        ["docker", "exec", "homebuilder-ops-copilot-db-1", "psql", "-U", "homebuilder", "-d", "homebuilder_ops", "-Atqc", sql],
        check=True, capture_output=True, text=True,
    )
    return int(result.stdout.strip())


def main() -> None:
    run_id = uuid.uuid4().hex[:12]
    results = []
    required = {
        "invoice_01": {"duplicate_invoice"},
        "invoice_12": {"budget_exception", "budget_category_mismatch"},
        "invoice_14": {"duplicate_invoice", "budget_category_mismatch"},
        "change_order_19": {"unknown_vendor"},
    }
    with httpx.Client(timeout=30) as client:
        for stem, codes in required.items():
            request = payload(stem, run_id)
            response = client.post(WEBHOOK, json=request)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["outcome"] == "needs_review", body
            assert body["approved_for_payment"] is False, body
            assert body["source_filename"] == request["source_filename"], body
            assert body["idempotency_key"] == request["idempotency_key"], body
            assert codes <= {item["code"] for item in body["reasons"]}, body
            assert audit_count(body["record_id"]) == 1
            retry = client.post(WEBHOOK, json=request)
            assert retry.status_code == 200 and retry.json() == body, retry.text
            assert audit_count(body["record_id"]) == 1
            results.append({"document": stem, "record_id": body["record_id"], "outcome": body["outcome"], "reasons": [item["code"] for item in body["reasons"]], "retry_idempotent": True})
        changed = payload("invoice_01", run_id)
        changed["extracted"]["total_amount"] = "1.00"
        conflict = client.post(WEBHOOK, json=changed)
        assert conflict.status_code == 200, conflict.text
        assert conflict.json()["outcome"] == "conflict", conflict.text
        assert conflict.json()["approved_for_payment"] is False
        invalid = payload("invoice_02", run_id)
        invalid["extracted"]["total_amount"] = "0.00"
        rejected = client.post(WEBHOOK, json=invalid)
        assert rejected.status_code == 200 and rejected.json()["outcome"] == "rejected_invalid", rejected.text
        assert rejected.json()["approved_for_payment"] is False
        assert audit_count(rejected.json()["record_id"]) == 1
        bad_envelope = payload("invoice_02", f"{run_id}-422")
        bad_envelope["extraction_confidence"] = "1.5"
        bad_request = client.post(WEBHOOK, json=bad_envelope)
        assert bad_request.status_code == 200 and bad_request.json()["outcome"] == "http_error", bad_request.text
        assert bad_request.json()["http_status"] == 422 and bad_request.json()["approved_for_payment"] is False
    print(json.dumps({"passed": True, "saved_cases": results, "conflict_handled": True, "rejected_invalid_handled": True, "http_422_handled": True}, indent=2))


if __name__ == "__main__":
    main()
