"""Build a new Stage 3B workflow from an exported Stage 2 workflow.

The original workflow is left untouched. The generated JSON has no credential secret.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
source = json.loads((ROOT / "gemini_invoice_extraction_stage2.json").read_text(encoding="utf-8"))
workflow = {
    "name": "Stage 3B - Gemini extraction and validation",
    "nodes": source["nodes"],
    "connections": source["connections"],
    "settings": source.get("settings", {"executionOrder": "v1"}),
    "active": False,
    "pinData": {},
}
form = next(node for node in workflow["nodes"] if node["name"] == "PDF upload form")
form["parameters"]["path"] = "stage3b-pdf-intake"
form["webhookId"] = "stage3b-pdf-intake"

workflow["nodes"].extend([
    {
        "id": "e95e5580-a236-4a6b-95de-e9f04c5b19ce",
        "name": "Hash PDF text", "type": "n8n-nodes-base.crypto", "typeVersion": 1,
        "position": [670, 180],
        "parameters": {
            "action": "hash", "binaryData": False, "type": "SHA256",
            "value": "={{ $json.text }}", "dataPropertyName": "pdf_text_sha256", "encoding": "hex",
        },
    },
    {
        "id": "d47f49e8-f1a0-4b1c-ad49-61cd005d3147",
        "name": "Saved JSON test webhook",
        "type": "n8n-nodes-base.webhook", "typeVersion": 2,
        "position": [280, 680], "webhookId": "stage3b-saved-json",
        "parameters": {"httpMethod": "POST", "path": "stage3b-saved-json", "responseMode": "lastNode", "options": {}},
    },
    {
        "id": "0853f932-b388-4309-9db1-0e9af6c7f6c8",
        "name": "Prepare validation request", "type": "n8n-nodes-base.code", "typeVersion": 2,
        "position": [1120, 380],
        "parameters": {"jsCode": r'''
const input = $input.first().json;
let request;
if (input.body && typeof input.body === 'object' && input.body.extracted) {
  // Saved-output test route. The caller supplies the exact API request object.
  request = input.body;
} else {
  // Gemini parser output from the form route. The upload node is the source of truth
  // for filename; extracted document identity is preserved separately.
  const extracted = { ...input };
  const sourceFilename = $('PDF upload form').first().binary.document.fileName;
  const pdfTextHash = $('Hash PDF text').first().json.pdf_text_sha256;
  if (typeof sourceFilename !== 'string' || !sourceFilename ||
      typeof pdfTextHash !== 'string' || !/^[a-f0-9]{64}$/.test(pdfTextHash)) {
    throw new Error('Cannot create stable idempotency key from source filename and PDF text');
  }
  const key = `pdftext:${sourceFilename}:${pdfTextHash}`;
  if (key.length > 200) throw new Error('Document identity exceeds idempotency key limit');
  request = {
    idempotency_key: key,
    source_filename: sourceFilename,
    extracted,
    extraction_confidence: null,
    extraction_uncertainty: []
  };
}
if (typeof request.idempotency_key !== 'string' || !request.idempotency_key) {
  throw new Error('Missing idempotency_key');
}
if (typeof request.source_filename !== 'string' || !request.source_filename) {
  throw new Error('Missing source_filename');
}
if (!request.extracted || typeof request.extracted !== 'object' || Array.isArray(request.extracted)) {
  throw new Error('Expected one parsed document object');
}
return [{json: {
  request,
  source_filename: request.source_filename,
  document_number: request.extracted.document_number ?? null,
  idempotency_key: request.idempotency_key
}}];
'''},
    },
    {
        "id": "988ed027-71d6-43ec-85a7-a562bf2e6f3b",
        "name": "POST validation API", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
        "position": [1350, 380], "onError": "continueRegularOutput",
        "parameters": {
            "method": "POST", "url": "http://host.docker.internal:8001/v1/validate",
            "sendBody": True, "contentType": "json", "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json.request) }}",
            "options": {"timeout": 15000, "response": {"response": {"fullResponse": True, "neverError": True, "responseFormat": "json"}}},
        },
    },
    {
        "id": "e5c9ef2b-7853-4e08-a08d-146551346402",
        "name": "Show validation outcome", "type": "n8n-nodes-base.code", "typeVersion": 2,
        "position": [1570, 380],
        "parameters": {"jsCode": r'''
const response = $input.first().json;
const original = $('Prepare validation request').first().json;
const status = Number(response.statusCode ?? 0);
const body = response.body ?? {};
const validOutcomes = ['accepted', 'needs_review', 'rejected_invalid'];
let outcome = 'transport_error';
let reasons = [];
if (status === 200 && validOutcomes.includes(body.outcome)) {
  outcome = body.outcome;
  reasons = Array.isArray(body.reasons) ? body.reasons : [];
} else if (status === 409) {
  outcome = 'conflict';
  reasons = [{code: 'idempotency_conflict', detail: String(body.detail ?? 'Key was reused with different content')}];
} else if (status > 0) {
  outcome = 'http_error';
  reasons = [{code: 'http_error', detail: `Validation API returned HTTP ${status}: ${JSON.stringify(body)}`}];
} else {
  reasons = [{code: 'transport_error', detail: String(response.error?.message ?? response.error ?? 'Network error or timeout')}];
}
return [{json: {
  source_filename: original.source_filename,
  document_number: original.document_number,
  idempotency_key: original.idempotency_key,
  http_status: status || null,
  outcome,
  reasons,
  record_id: status === 200 ? (body.record_id ?? null) : null,
  extraction_confidence: status === 200 ? (body.extraction_confidence ?? null) : null,
  extraction_uncertainty: status === 200 ? (body.extraction_uncertainty ?? []) : [],
  validation_passed: outcome === 'accepted',
  approved_for_payment: false
}}];
'''},
    },
])
workflow["connections"]["Code in JavaScript"] = {"main": [[{"node": "Prepare validation request", "type": "main", "index": 0}]]}
workflow["connections"]["Extract PDF text"] = {"main": [[{"node": "Hash PDF text", "type": "main", "index": 0}]]}
workflow["connections"]["Hash PDF text"] = {"main": [[{"node": "Message a model", "type": "main", "index": 0}]]}
workflow["connections"]["Saved JSON test webhook"] = {"main": [[{"node": "Prepare validation request", "type": "main", "index": 0}]]}
workflow["connections"]["Prepare validation request"] = {"main": [[{"node": "POST validation API", "type": "main", "index": 0}]]}
workflow["connections"]["POST validation API"] = {"main": [[{"node": "Show validation outcome", "type": "main", "index": 0}]]}
workflow["connections"].pop("Show text and metadata", None)
workflow["nodes"] = [node for node in workflow["nodes"] if node["name"] != "Show text and metadata"]
(ROOT / "gemini_validation_stage3b.json").write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
print("Wrote Stage 3B workflow")
