"""Clone the live-tested Stage 3B flow and add nonblocking review routing."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
source = json.loads((ROOT / "gemini_validation_stage3b.json").read_text(encoding="utf-8"))
workflow = {
    "name": "Stage 4A - Validation and human review routing",
    "nodes": source["nodes"],
    "connections": source["connections"],
    "settings": source["settings"],
    "active": False,
    "pinData": {},
}
form = next(node for node in workflow["nodes"] if node["name"] == "PDF upload form")
form["parameters"]["path"] = "stage4a-pdf-intake"
form["webhookId"] = "stage4a-pdf-intake"
saved = next(node for node in workflow["nodes"] if node["name"] == "Saved JSON test webhook")
saved["parameters"]["path"] = "stage4a-saved-json"
saved["webhookId"] = "stage4a-saved-json"
final = next(node for node in workflow["nodes"] if node["name"] == "Show validation outcome")
code = final["parameters"]["jsCode"]
old = "  record_id: status === 200 ? (body.record_id ?? null) : null,"
new = old + "\n  review_status: status === 200 ? (body.review_status ?? null) : null,"
assert old in code
final["parameters"]["jsCode"] = code.replace(old, new)


def rule(label):
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
            "combinator": "and",
            "conditions": [{"leftValue": "={{ $json.outcome }}", "rightValue": label,
                            "operator": {"type": "string", "operation": "equals"}}],
        },
        "renameOutput": True, "outputKey": label,
    }


workflow["nodes"].append({
    "id": "270e11ca-802d-40ce-9b64-62b2687a9252", "name": "Route validation outcome",
    "type": "n8n-nodes-base.switch", "typeVersion": 3.2, "position": [1790, 380],
    "parameters": {"mode": "rules", "rules": {"values": [rule("accepted"), rule("needs_review"), rule("rejected_invalid")]},
                   "options": {"fallbackOutput": "extra", "renameFallbackOutput": "processing_error"}},
})


def route_node(name, route, message, y):
    return {
        "id": {"Validation accepted": "5d9a881a-947b-45a5-a404-57a16e033640",
               "Pending human review": "74b7a0ce-a383-43db-88b2-5c01e190a1b8",
               "Correct and resubmit": "b7e7286b-66e1-44d9-9237-24f4c3ebd71a",
               "Processing error": "231932d0-a412-496c-9e56-9514daed90ff"}[name],
        "name": name, "type": "n8n-nodes-base.code", "typeVersion": 2,
        "position": [2020, y],
        "parameters": {"jsCode": f"return $input.all().map(item => ({{json: {{...item.json, route: '{route}', message: '{message}', payment_authorized: false}}}}));"},
    }


workflow["nodes"].extend([
    route_node("Validation accepted", "validation_success", "Validation passed. No payment approval was given.", 80),
    route_node("Pending human review", "human_review_pending", "Review is pending in PostgreSQL. Open the local dashboard with the record ID.", 280),
    route_node("Correct and resubmit", "correction_required", "Correct the invalid document and submit it for validation again.", 480),
    route_node("Processing error", "processing_error", "Validation service failed or returned an unexpected response. No approval was given.", 680),
])
workflow["connections"]["Show validation outcome"] = {"main": [[{"node": "Route validation outcome", "type": "main", "index": 0}]]}
workflow["connections"]["Route validation outcome"] = {"main": [
    [{"node": "Validation accepted", "type": "main", "index": 0}],
    [{"node": "Pending human review", "type": "main", "index": 0}],
    [{"node": "Correct and resubmit", "type": "main", "index": 0}],
    [{"node": "Processing error", "type": "main", "index": 0}],
]}
(ROOT / "human_review_stage4a.json").write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
print("Wrote Stage 4A workflow")
