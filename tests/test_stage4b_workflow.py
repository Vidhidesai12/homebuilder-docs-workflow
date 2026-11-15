import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "workflows"


def load(name):
    value = json.loads((ROOT / name).read_text(encoding="utf-8"))
    return value[0] if isinstance(value, list) else value


def node(flow, name):
    return next(item for item in flow["nodes"] if item["name"] == name)


def test_stage4b_is_separate_and_earlier_exports_unchanged():
    ids = [load(name).get("id") for name in ("gemini_validation_stage3b.json", "human_review_stage4a.json", "weekly_reporting_stage4b.json")]
    assert len(set(ids)) == 3
    assert load("gemini_validation_stage3b.json")["name"] == "Stage 3B - Gemini extraction and validation"
    assert load("human_review_stage4a.json")["name"] == "Stage 4A - Validation and human review routing"


def test_schedule_timezone_manual_path_and_credential_reference():
    flow = load("weekly_reporting_stage4b.json")
    schedule = node(flow, "Every Monday 9 AM")["parameters"]["rule"]["interval"][0]
    assert schedule == {"field": "weeks", "triggerAtDay": [1], "triggerAtHour": 9, "triggerAtMinute": 0}
    assert flow["settings"]["timezone"] == "America/Los_Angeles"
    assert node(flow, "Run now")["type"] == "n8n-nodes-base.manualTrigger"
    assert node(flow, "Local manual test webhook")["parameters"]["path"] == "stage4b-weekly-report"
    for name in ("Request weekly report", "Record successful generation"):
        request = node(flow, name)
        assert request["credentials"]["httpHeaderAuth"]["name"] == "Stage 4B Reporting API"
        assert "Authorization" not in json.dumps(request["parameters"])
        assert request["retryOnFail"] and request["maxTries"] == 3


def test_report_format_and_success_receipt_are_safe():
    flow = load("weekly_reporting_stage4b.json")
    formatter = node(flow, "Format weekly report")["parameters"]["jsCode"]
    assert "payment_authorized: false" in formatter
    assert "report_digest" in formatter and "idempotency_key" in formatter
    complete = node(flow, "Report generation complete")["parameters"]["jsCode"]
    assert "payment_authorized: false" in complete
    assert flow["connections"]["Display generated report"]["main"][0][0]["node"] == "Record successful generation"
