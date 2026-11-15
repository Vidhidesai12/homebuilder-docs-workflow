# Stage 3 validation API

`POST http://api:8001/v1/validate` is reachable from n8n in this Compose project. The published Stage 3B workflow uses the separately verified Docker Desktop route `http://host.docker.internal:8001/v1/validate`. From Windows, use `http://localhost:8001/v1/validate`. The endpoint validates and records a document; **`accepted` means deterministic checks passed, not authorization to pay**. No approval or payment action exists.

## Request

```json
{
  "idempotency_key": "pdf-sha256-or-stable-n8n-event-id",
  "source_filename": "invoice_01.pdf",
  "extracted": {
    "document_type": "invoice",
    "document_number": "INV-2026-001",
    "vendor_name": "Demo Sitework Vendor 01",
    "document_date": "2026-11-10",
    "community": "Demo Alder Grove",
    "lot_number": "8",
    "budget_category": "Permits",
    "line_items": [
      {"description": "Permits demo work item 1", "quantity": 1, "unit_price": "351.00", "amount": "351.00"},
      {"description": "Permits demo work item 2", "quantity": 3, "unit_price": "801.00", "amount": "2403.00"}
    ],
    "total_amount": "2754.00"
  },
  "extraction_confidence": "0.94",
  "extraction_uncertainty": []
}
```

`idempotency_key` must be stable across retries for the same source and extraction. It may be a source PDF SHA-256 or a persistent n8n event identifier; a random key per retry defeats idempotency. A key reused with different request content returns HTTP 409. The source filename is mandatory and must be a PDF basename. The `extracted` object accepts `issue_date` or the observed Gemini `document_date` alias, but not both. Optional `filename` inside `extracted` must equal `source_filename`. Optional `currency` must be three uppercase letters. `extraction_status` from the Stage 2 Gemini result is treated as transport metadata.

## Response

HTTP 200 returns `record_id`, `source_filename`, `document_type`, `document_number`, `outcome`, `reasons`, `extraction_confidence`, and `extraction_uncertainty`. Outcomes are `accepted`, `needs_review`, and `rejected_invalid`. Every reason has a stable `code` and a concrete `detail`. Confidence and uncertainty are copied separately; they never change deterministic validation. Invalid JSON or a malformed request envelope returns HTTP 422. A database error returns HTTP 500 and does not commit a partial transaction.

## Policy

Unknown vendors, absent communities, lots outside the named community, missing monthly budget rows, category differences from that one monthly row, duplicate invoice numbers for the same vendor, and totals above $25,000 produce `needs_review`. The threshold is a document review policy; it does not assert remaining funds. Missing or invalid required fields, nonpositive quantities/prices/totals, incorrect line extensions or document totals, and a source filename mismatch produce `rejected_invalid`. The service never updates `public.budgets.actual_amount`, so document ingestion cannot double-count historical costs.

Vendor, community, lot, and monthly category are read from Project 1's existing synthetic tables at validation time. Consequently, live outcomes can include additional review reasons when the database differs from the checked-in fixture generator. The `documents` schema stores the raw extraction, normalized fields, outcome, reasons, confidence, uncertainty, and one audit event per new submission. A unique idempotency key plus a unique `(vendor_name, invoice_number)` claim enforce retry and concurrent duplicate behavior in one transaction. Rejected invalid documents do not reserve an invoice number.

## Setup and n8n call

The requested `documents` schema and limited `homebuilder_docs` role have been created in the existing Project 1 PostgreSQL container for this workspace. SQL is in `docs/documents_schema.sql` and `docs/documents_role.psql`; the role's generated password is stored only in this project's ignored `.env`. The role has SELECT on four business catalog tables, write permissions in `documents`, and no INSERT on `public.budgets` or CREATE on `public`.

Run `docker compose up -d --build api n8n`. The published Stage 3B n8n workflow already includes the **HTTP Request** node after Gemini parsing and request preparation. Its method is `POST`, URL is `http://host.docker.internal:8001/v1/validate`, and body type is JSON. It maps a stable source identifier and filename from the upload event and the parsed Gemini document object to `extracted`. If using saved Gemini output from a one-element array, select its first element before sending it to the saved-JSON webhook. Inspect the returned `outcome` and `reasons`; this stage adds no approval workflow.

The API uses Project 1's already-running Docker network `homebuilder-ops-copilot_default` and its existing `db` container. It starts no second PostgreSQL instance. If the Project 1 network is absent, Compose cannot start this API; start the existing Project 1 database without reseeding it. `docker compose exec -T api python -m tests.smoke_live` runs an opt-in synthetic integration check and writes only documents-schema test records.
