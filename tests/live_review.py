"""Opt-in Stage 4A integration test; uses saved synthetic extraction, no Gemini."""
import json
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8001"


def local_credentials() -> tuple[str, str]:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(("REVIEW_USERNAME=", "REVIEW_PASSWORD=")):
            key, value = line.split("=", 1)
            values[key] = value
    return values["REVIEW_USERNAME"], values["REVIEW_PASSWORD"]


def create_document(client: httpx.Client, run_id: str, suffix: str, invalid: bool = False) -> int:
    extracted = json.loads((ROOT / "evals" / "outputs" / "invoice_01.json").read_text(encoding="utf-8"))[0]
    if invalid:
        extracted["total_amount"] = "0.00"
    request = {
        "idempotency_key": f"stage4a-review-{run_id}-{suffix}",
        "source_filename": "invoice_01.pdf",
        "extracted": extracted,
        "extraction_confidence": None,
        "extraction_uncertainty": [],
    }
    response = client.post(API + "/v1/validate", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == ("rejected_invalid" if invalid else "needs_review"), body
    assert body["review_status"] == (None if invalid else "pending"), body
    return body["record_id"]


def main() -> None:
    username, password = local_credentials()
    run_id = uuid.uuid4().hex[:12]
    with httpx.Client(timeout=20) as client:
        assert client.get(API + "/v1/reviews/pending").status_code == 401
        assert client.post(API + "/v1/review/session", auth=(username, "wrong")).status_code == 401
        login = client.post(API + "/v1/review/session", auth=(username, password))
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        approved_id = create_document(client, run_id, "approve")
        declined_id = create_document(client, run_id, "decline")
        race_id = create_document(client, run_id, "race")
        invalid_id = create_document(client, run_id, "invalid", invalid=True)
        queue = client.get(API + "/v1/reviews/pending", headers=headers)
        assert queue.status_code == 200
        ids = {row["record_id"] for row in queue.json()["documents"]}
        assert {approved_id, declined_id, race_id} <= ids
        assert invalid_id not in ids
        assert client.post(API + f"/v1/reviews/{approved_id}/approve", json={}, headers=headers).status_code == 422
        assert client.post(API + f"/v1/reviews/{approved_id}/approve", json={"justification": "short"}, headers=headers).status_code == 422
        assert client.post(API + f"/v1/reviews/{approved_id}/approve", json={"justification": "Reviewed synthetic budget exception"}).status_code == 401

        approved = client.post(API + f"/v1/reviews/{approved_id}/approve", json={"justification": "Reviewed synthetic duplicate and accepted exception"}, headers=headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["review_status"] == "approved_exception"
        assert approved.json()["reviewer_identity"] == username
        assert approved.json()["payment_authorized"] is False
        declined = client.post(API + f"/v1/reviews/{declined_id}/decline", json={"justification": "Synthetic duplicate should not proceed"}, headers=headers)
        assert declined.status_code == 200 and declined.json()["review_status"] == "declined", declined.text

        repeat = client.post(API + f"/v1/reviews/{approved_id}/approve", json={"justification": "Reviewed synthetic duplicate and accepted exception"}, headers=headers)
        assert repeat.status_code == 409
        assert client.post(API + f"/v1/reviews/{invalid_id}/approve", json={"justification": "Attempt to approve invalid extraction"}, headers=headers).status_code == 409

        def decide_race(action):
            return httpx.post(API + f"/v1/reviews/{race_id}/{action}",
                              json={"justification": f"Concurrent synthetic {action} decision"}, headers=headers, timeout=20)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(decide_race, ("approve", "decline")))
        assert sorted(response.status_code for response in responses) == [200, 409], [r.text for r in responses]

        for record_id, expected in ((approved_id, "approved_exception"), (declined_id, "declined")):
            document = client.get(API + f"/v1/reviews/{record_id}", headers=headers)
            history = client.get(API + f"/v1/reviews/{record_id}/history", headers=headers)
            assert document.status_code == 200 and history.status_code == 200
            assert document.json()["outcome"] == "needs_review"
            assert document.json()["review_status"] == expected
            events = history.json()["events"]
            assert [event["event_type"] for event in events] == ["validated", "review_decision"]
            assert events[-1]["reviewer_identity"] == username
            assert events[-1]["original_validation_outcome"] == "needs_review"
        assert len(client.get(API + f"/v1/reviews/{race_id}/history", headers=headers).json()["events"]) == 2
        assert len(client.get(API + f"/v1/reviews/{invalid_id}/history", headers=headers).json()["events"]) == 1

        mutation_verified = False
        if os.environ.get("STAGE4A_SKIP_DB_MUTATION_CHECK") != "1":
            sql = f"UPDATE documents.audit_history SET event_type='tamper' WHERE record_id={int(approved_id)}"
            mutation = subprocess.run(["docker", "exec", "homebuilder-ops-copilot-db-1", "psql", "-v", "ON_ERROR_STOP=1", "-U", "homebuilder", "-d", "homebuilder_ops", "-c", sql], capture_output=True, text=True)
            assert mutation.returncode != 0 and "immutable" in mutation.stderr.lower(), mutation.stderr
            mutation_verified = True
        assert len(client.get(API + f"/v1/reviews/{approved_id}/history", headers=headers).json()["events"]) == 2
        print(json.dumps({
            "passed": True, "approved_record": approved_id, "declined_record": declined_id,
            "concurrent_record": race_id, "concurrent_http_statuses": sorted(r.status_code for r in responses),
            "invalid_record": invalid_id, "unauthenticated_status": 401,
            "repeated_decision_status": 409, "audit_immutable_mutation_check": mutation_verified,
        }, indent=2))


if __name__ == "__main__":
    main()
