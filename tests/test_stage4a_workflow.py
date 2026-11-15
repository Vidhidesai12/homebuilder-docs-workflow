"""Review routing configuration and Stage 3B preservation checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "workflows"


def workflow(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def node(flow, name):
    return next(item for item in flow["nodes"] if item["name"] == name)


def test_stage4a_is_separate_and_keeps_gemini_path():
    stage3b = workflow("gemini_validation_stage3b.json")
    stage4a = workflow("human_review_stage4a.json")
    assert stage3b["id"] != stage4a["id"]
    assert "Show validation outcome" not in stage3b["connections"]
    for name in ("Extract PDF text", "Hash PDF text", "Message a model", "Code in JavaScript", "POST validation API"):
        assert node(stage4a, name)["parameters"] == node(stage3b, name)["parameters"]
    assert node(stage4a, "PDF upload form")["parameters"]["path"] != node(stage3b, "PDF upload form")["parameters"]["path"]
    assert node(stage4a, "Saved JSON test webhook")["parameters"]["path"] != node(stage3b, "Saved JSON test webhook")["parameters"]["path"]


def test_switch_routes_all_validation_states_and_fallback():
    flow = workflow("human_review_stage4a.json")
    switch = node(flow, "Route validation outcome")
    assert switch["type"] == "n8n-nodes-base.switch"
    assert [rule["conditions"]["conditions"][0]["rightValue"] for rule in switch["parameters"]["rules"]["values"]] == [
        "accepted", "needs_review", "rejected_invalid",
    ]
    assert switch["parameters"]["options"]["fallbackOutput"] == "extra"
    branches = flow["connections"]["Route validation outcome"]["main"]
    assert [branch[0]["node"] for branch in branches] == [
        "Validation accepted", "Pending human review", "Correct and resubmit", "Processing error",
    ]
    assert "review_status" in node(flow, "Show validation outcome")["parameters"]["jsCode"]
    for branch in branches:
        code = node(flow, branch[0]["node"])["parameters"]["jsCode"]
        assert "payment_authorized: false" in code
    assert "wait" not in [item["type"].split(".")[-1] for item in flow["nodes"]]
