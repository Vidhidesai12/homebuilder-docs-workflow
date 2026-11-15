# Stage 3B: n8n → FastAPI integration

The running n8n instance now contains three separate workflows: `Stage 1 - PDF text ingestion`, `Gemini invoice extraction` (Stage 2), and `Stage 3B - Gemini extraction and validation`. The first two were preserved. The Stage 3B workflow is published and exported to `workflows/gemini_validation_stage3b.json`. It contains a reference to the existing Gemini credential, not a credential value.

## Live route

`PDF upload form → Extract PDF text → Hash PDF text (SHA-256) → Message a model → Code in JavaScript (JSON parser) → Prepare validation request → POST validation API → Show validation outcome`.

The validation request uses exactly the fields in `docs/stage3_api.md`: `idempotency_key`, `source_filename`, `extracted`, `extraction_confidence`, and `extraction_uncertainty`. The form route derives a stable key from the uploaded filename and SHA-256 hash of extracted PDF text. This remains stable when the same PDF is retried, even if the Gemini parsing changes; a changed extraction for the same key yields HTTP 409 for inspection. The source filename and extracted document number remain visible through the final node. The HTTP Request node calls `http://host.docker.internal:8001/v1/validate` from n8n's Docker container with a 15-second timeout, includes HTTP status, and does not throw on non-2xx responses. Network failures continue to the result node.

The result node distinguishes `accepted`, `needs_review`, `rejected_invalid`, HTTP 409 `conflict`, other `http_error`, and `transport_error`. It displays detailed reason codes and text, source filename, document number, idempotency key, and PostgreSQL record ID when one exists. `approved_for_payment` is always `false`. A failed HTTP call or validation never becomes a passed validation.

## Manual test in n8n

1. Run `docker compose up -d --build api n8n` from this project. Ensure Project 1's existing PostgreSQL container is running; do not reseed it.
2. Open <http://localhost:5678> and select **Stage 3B - Gemini extraction and validation**. It is already published in this local n8n instance. Confirm the existing Gemini credential is selected if importing the export into a different instance.
3. Open the form's **Production URL** or <http://localhost:5678/form/stage3b-pdf-intake>. Upload a synthetic PDF such as `data/samples/invoice_05.pdf`. It was unclaimed when these instructions were written; its actual outcome depends on current catalog rows and extraction quality.
4. Open that workflow's **Executions** view, select the new execution, and inspect **Show validation outcome**. The form itself returns a generic submission response. Inspect `outcome`, `reasons`, `record_id`, `source_filename`, `document_number`, and `idempotency_key` in the node output. `accepted` is only a validation outcome, never payment approval.
5. To replay a saved extraction without a Gemini request, POST the API-shaped JSON body to <http://localhost:5678/webhook/stage3b-saved-json>. The `extracted` value must be one object. Use a stable `idempotency_key` for retries. The webhook returns the result node's JSON directly. The opt-in script `python -m tests.live_stage3b` demonstrates the format using synthetic fixtures.

## Measured results

The published workflow was tested with a live upload of `invoice_09.pdf`; form POST returned HTTP 200, and PostgreSQL record **31** contains `INV-2026-009`, `parsed_not_verified`, `accepted`, zero reasons, and one audit event. After adding the hash node, a second live upload of `invoice_11.pdf` returned HTTP 200; record **52** contains a `pdftext:invoice_11.pdf:<SHA-256>` key, `INV-2026-011`, `parsed_not_verified`, `accepted`, zero reasons, and one audit event. These are evidence of the PDF → Gemini parser → validation API → PostgreSQL path. No Gemini credential or API response secret was displayed or saved in this repository.

The saved-JSON integration script passed for the actual saved Gemini output `invoice_01.json` and synthetic extracted fixtures for `invoice_12`, `invoice_14`, and `change_order_19`, without making Gemini requests. Each returned `needs_review` with relevant reasons and one audit event; exact retries reused the same record and did not add audit events. A changed request under the same key returned a displayed `conflict`; invalid extraction returned `rejected_invalid`; an invalid API envelope returned displayed `http_error` with HTTP 422. When the API container was briefly stopped, n8n displayed `transport_error`, no record ID, and `approved_for_payment: false`; restarting the API and retrying the same request produced `needs_review` and one audit event. The API container was restored.

The exact stored request from live PDF record **52** was also replayed through n8n's saved route without Gemini. It returned the same `accepted` record ID; its audit event count stayed **1 → 1**. This checks the final hash-based retry key on the actual live document.

Live Project 1 budget rows for November 2026 say `Permits` for Demo Juniper Vista and Demo Oakline Park. Therefore `invoice_12` also receives `budget_category_mismatch` beside `budget_exception`, and `invoice_14` receives `budget_category_mismatch` beside `duplicate_invoice`. `invoice_12` also now receives `duplicate_invoice` because earlier synthetic smoke tests claimed that vendor and invoice number. These reasons were preserved; Project 1 budget rows were not changed.

Final automated test suite: **29 passed, 1 dependency deprecation warning in 2.66s**. It includes static checks on the exported workflow graph and HTTP error settings. A live 15-second timeout was not induced; the node's timeout setting and connection-failure path were verified. n8n's internal execution database was not copied for node-by-node inspection: automatic approval review rejected that action because the database may contain credentials and execution payloads. The live form submissions, parser marker in document records, API results, and audit rows provided the verification above.
