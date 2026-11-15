"""Opt-in outage recovery test: briefly stops only this project's API container."""
import json
import subprocess
import uuid

import httpx

from tests.live_stage3b import WEBHOOK, audit_count, payload


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], check=True, capture_output=True, text=True)


def main() -> None:
    request = payload("change_order_19", uuid.uuid4().hex[:12])
    try:
        compose("stop", "api")
        failed = httpx.post(WEBHOOK, json=request, timeout=30)
        assert failed.status_code == 200, failed.text
        body = failed.json()
        assert body["outcome"] == "transport_error", body
        assert body["record_id"] is None and body["approved_for_payment"] is False, body
    finally:
        compose("start", "api")
    recovered = httpx.post(WEBHOOK, json=request, timeout=30)
    assert recovered.status_code == 200, recovered.text
    body = recovered.json()
    assert body["outcome"] == "needs_review", body
    assert "unknown_vendor" in [item["code"] for item in body["reasons"]], body
    assert audit_count(body["record_id"]) == 1
    print(json.dumps({"passed": True, "outage_outcome": "transport_error", "recovery_outcome": body["outcome"], "record_id": body["record_id"], "audit_events": 1}))


if __name__ == "__main__":
    main()
