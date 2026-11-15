"""Replay a prior live PDF's exact saved request through n8n without Gemini."""
import json
import subprocess

import httpx

from tests.live_stage3b import WEBHOOK, audit_count


def main() -> None:
    sql = (
        "SELECT json_build_object('idempotency_key',idempotency_key,"
        "'source_filename',source_filename,'extracted',raw_extraction,"
        "'extraction_confidence',extraction_confidence,"
        "'extraction_uncertainty',extraction_uncertainty) "
        "FROM documents.records WHERE id=52"
    )
    command = ["docker", "exec", "homebuilder-ops-copilot-db-1", "psql", "-U", "homebuilder", "-d", "homebuilder_ops", "-Atqc", sql]
    output = subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()
    if not output:
        raise RuntimeError("Expected live PDF record 52 is unavailable")
    request = json.loads(output)
    before = audit_count(52)
    response = httpx.post(WEBHOOK, json=request, timeout=30)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["record_id"] == 52 and result["outcome"] == "accepted", result
    assert audit_count(52) == before == 1
    print(json.dumps({"passed": True, "record_id": 52, "outcome": result["outcome"], "audit_events_before": before, "audit_events_after": audit_count(52)}))


if __name__ == "__main__":
    main()
