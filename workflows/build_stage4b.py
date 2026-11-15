"""Create the separate Stage 4B scheduled and manual reporting workflow."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CREDENTIAL = {"id": "stage4b-reporting-api", "name": "Stage 4B Reporting API"}

workflow = {
    "name": "Stage 4B - Weekly document reporting",
    "active": False,
    "settings": {"executionOrder": "v1", "timezone": "America/Los_Angeles"},
    "pinData": {},
    "nodes": [
        {
            "id": "28cf2211-29f0-4f28-a305-e27e7e3c407d", "name": "Every Monday 9 AM",
            "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [220, 180],
            "parameters": {"rule": {"interval": [{"field": "weeks", "triggerAtDay": [1], "triggerAtHour": 9, "triggerAtMinute": 0}]}},
        },
        {
            "id": "31c371b9-d5fb-4185-b5c0-1602305b9b51", "name": "Run now",
            "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [220, 360], "parameters": {},
        },
        {
            "id": "3af8d3e5-18e7-4704-b90a-b21bfd08af9d", "name": "Local manual test webhook",
            "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [220, 540],
            "webhookId": "stage4b-weekly-report", "parameters": {"httpMethod": "POST", "path": "stage4b-weekly-report", "responseMode": "lastNode", "options": {}},
        },
        {
            "id": "4b20b248-bb80-4642-981d-12ec37e81c50", "name": "Request weekly report",
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [490, 360],
            "parameters": {
                "method": "GET", "url": "http://host.docker.internal:8001/v1/reports/weekly",
                "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                "options": {"timeout": 15000, "response": {"response": {"responseFormat": "json"}}},
            },
            "credentials": {"httpHeaderAuth": CREDENTIAL},
            "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000,
        },
        {
            "id": "71fe70e4-5d75-4b93-b3d2-f8eea3c802fa", "name": "Format weekly report",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [730, 360],
            "parameters": {"jsCode": r'''
const report = $input.first().json;
if (!report.period?.start_utc || !report.period?.end_utc || !report.report_digest) {
  throw new Error('Reporting API returned an incomplete report');
}
return [{json: {
  report_json: report,
  markdown_report: report.markdown,
  html_report: report.html,
  summary: {
    period: report.period,
    generated_at: report.generated_at,
    unique_documents: report.document_volume.unique_documents,
    accepted: report.validation_outcomes.accepted,
    needs_review: report.validation_outcomes.needs_review,
    rejected_invalid: report.validation_outcomes.rejected_invalid,
    pending_reviews_as_of_generation: report.pending_human_reviews_as_of_generation,
    total_valid_invoice_value: report.total_valid_invoice_value,
    payment_authorized: false
  },
  receipt: {
    idempotency_key: `weekly:${report.period.start_utc}:${report.period.end_utc}`,
    period_start: report.period.start_utc,
    period_end: report.period.end_utc,
    report_digest: report.report_digest,
    generated_at: report.generated_at,
    source: 'n8n'
  }
}}];
'''},
        },
        {
            "id": "412d071a-f6b1-4750-bd12-c98485487065", "name": "Display generated report",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [960, 360],
            "parameters": {"jsCode": "return $input.all();"},
        },
        {
            "id": "7304a605-5b47-48b4-aa8d-c9a659461868", "name": "Record successful generation",
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [1190, 360],
            "parameters": {
                "method": "POST", "url": "http://host.docker.internal:8001/v1/reports/weekly/runs",
                "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                "sendBody": True, "contentType": "json", "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json.receipt) }}",
                "options": {"timeout": 15000, "response": {"response": {"responseFormat": "json"}}},
            },
            "credentials": {"httpHeaderAuth": CREDENTIAL},
            "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000,
        },
        {
            "id": "4f62bf7b-b524-4a73-a17f-7baa943c660f", "name": "Report generation complete",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1420, 360],
            "parameters": {"jsCode": r'''
const receipt = $input.first().json;
const formatted = $('Format weekly report').first().json;
return [{json: {
  status: 'report_generated',
  report_run_id: receipt.report_run_id,
  report_record_created: receipt.created,
  report_digest_matches_existing: receipt.report_digest_matches ?? true,
  summary: formatted.summary,
  markdown_report: formatted.markdown_report,
  html_report: formatted.html_report,
  payment_authorized: false
}}];
'''},
        },
    ],
    "connections": {},
}
for trigger in ("Every Monday 9 AM", "Run now", "Local manual test webhook"):
    workflow["connections"][trigger] = {"main": [[{"node": "Request weekly report", "type": "main", "index": 0}]]}
workflow["connections"].update({
    "Request weekly report": {"main": [[{"node": "Format weekly report", "type": "main", "index": 0}]]},
    "Format weekly report": {"main": [[{"node": "Display generated report", "type": "main", "index": 0}]]},
    "Display generated report": {"main": [[{"node": "Record successful generation", "type": "main", "index": 0}]]},
    "Record successful generation": {"main": [[{"node": "Report generation complete", "type": "main", "index": 0}]]},
})
(ROOT / "weekly_reporting_stage4b.json").write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
print("Wrote Stage 4B workflow")
