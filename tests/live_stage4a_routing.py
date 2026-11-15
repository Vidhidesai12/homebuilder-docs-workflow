"""Opt-in n8n Switch routing checks using synthetic saved JSON; no Gemini calls."""
import json
import subprocess
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
URL = "http://localhost:5678/webhook/stage4a-saved-json"


def request(stem: str, suffix: str) -> dict:
    if stem == "invoice_01":
        extracted = json.loads((ROOT / "evals" / "outputs" / "invoice_01.json").read_text(encoding="utf-8"))[0]
    else:
        truth = json.loads((ROOT / "data" / "ground_truth" / f"{stem}.json").read_text(encoding="utf-8"))
        extracted = {key: value for key, value in truth.items() if not key.startswith("expected_")}
    return {
        "idempotency_key": f"stage4a-route-{suffix}",
        "source_filename": f"{stem}.pdf",
        "extracted": extracted,
        "extraction_confidence": None,
        "extraction_uncertainty": [],
    }


def post(client: httpx.Client, body: dict, outcome: str, route: str) -> dict:
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["outcome"] == outcome and result["route"] == route, result
    assert result["approved_for_payment"] is False and result["payment_authorized"] is False, result
    return result


def compose(*arguments: str) -> None:
    subprocess.run(["docker", "compose", *arguments], check=True, capture_output=True, text=True)


def main() -> None:
    run_id = uuid.uuid4().hex[:12]
    with httpx.Client(timeout=30) as client:
        accepted = post(client, request("change_order_17", f"{run_id}-accepted"), "accepted", "validation_success")
        assert accepted["review_status"] is None and accepted["record_id"] is not None
        review = post(client, request("invoice_12", f"{run_id}-review"), "needs_review", "human_review_pending")
        assert review["review_status"] == "pending" and review["record_id"] is not None
        assert "budget_category_mismatch" in [item["code"] for item in review["reasons"]]
        invalid = request("invoice_01", f"{run_id}-invalid")
        invalid["extracted"]["total_amount"] = "0.00"
        rejected = post(client, invalid, "rejected_invalid", "correction_required")
        assert rejected["review_status"] is None and rejected["record_id"] is not None
        bad = request("invoice_01", f"{run_id}-http-422")
        bad["extraction_confidence"] = "1.5"
        http_error = post(client, bad, "http_error", "processing_error")
        assert http_error["record_id"] is None and http_error["http_status"] == 422
        try:
            compose("stop", "api")
            failed = post(client, request("change_order_19", f"{run_id}-network"), "transport_error", "processing_error")
            assert failed["record_id"] is None
        finally:
            compose("start", "api")
    print(json.dumps({"passed": True, "accepted_record": accepted["record_id"],
                      "pending_record": review["record_id"], "rejected_record": rejected["record_id"],
                      "http_422_route": http_error["route"], "network_route": failed["route"]}))


if __name__ == "__main__":
    main()
