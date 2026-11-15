# Final evaluation and publication audit

Updated evaluation: 2026-11-15. No Gemini request was made during this audit.

## Extraction evaluation

The inventory contains 20 text-selectable PDFs and 20 matching ground-truth records: 15 invoices and 5 change orders. Six matching saved extraction JSON files are present in `evals/outputs/` (4 invoices, 2 change orders); 14 documents have no saved output (11 invoices, 3 change orders). The existing offline `python -m evals.accuracy` command exited 0 and reported **92/92 matched fields (100%)** and **6/6 exact documents (100%)**. All six outputs were schema-valid. No missing, incorrect, or unexpected fields or validation errors were reported.

| PDF | Type | Field accuracy | Exact document | Missing / incorrect / unexpected fields |
|---|---|---:|---|---|
| `invoice_01.pdf` | Invoice | 16/16 | Yes | None |
| `invoice_02.pdf` | Invoice | 16/16 | Yes | None |
| `invoice_12.pdf` | Invoice | 12/12 | Yes | None |
| `invoice_14.pdf` | Invoice | 16/16 | Yes | None |
| `change_order_16.pdf` | Change order | 16/16 | Yes | None |
| `change_order_19.pdf` | Change order | 16/16 | Yes | None |

Invoice subtotal: **60/60 fields, 4/4 exact documents**. Change-order subtotal: **32/32 fields, 2/2 exact documents**. Field accuracy is the sum of matched expected fields divided by the sum of expected fields; exact-document accuracy requires every expected field, valid schema, and no unexpected fields.

The evaluator normalizes the observed `document_date` label to `issue_date`, parses string lot numbers as integers, and excludes `extraction_status` transport metadata from field scoring. An independent `Decimal` check confirmed **11/11 line-item extensions** (`quantity × unit_price = amount`) and **6/6 document totals** (sum of line amounts). Ground-truth arithmetic also passed.

The six saved files are not byte-for-byte copies of ground truth: each is a one-document array with the `document_date` alias and `parsed_not_verified` transport status, whereas truth records contain `issue_date` and expected validation labels. **This does not independently prove Gemini provenance.** The saved files have no attached model response ID, immutable execution trace, or signed source record, so a manually transformed copy cannot be ruled out from repository evidence alone. The metrics therefore describe these six saved artifacts relative to ground truth, conditional on their claimed model origin; they do not establish accuracy for all 20 PDFs.

## Exception cases and validation boundary

| Saved extraction | Expected business exception | What extraction verified |
|---|---|---|
| `invoice_14.pdf` | `duplicate_invoice`: same vendor and invoice number as earlier `invoice_03.pdf` | 16/16 fields and arithmetic match truth; duplicate detection requires prior invoice state. |
| `change_order_19.pdf` | `unknown_vendor`: vendor absent from the fictional vendor catalog | 16/16 fields and arithmetic match truth; catalog membership is a validation rule. |
| `invoice_12.pdf` | `budget_exception`: $28,500 exceeds the fixture's $25,000 review threshold | 12/12 fields and arithmetic match truth; threshold evaluation is a validation rule. |

Extraction accuracy measures whether saved fields match the document ground truth. The offline evaluator does **not** test business-rule decisions, current database state, human review, or payment authorization. Existing validation tests cover these exception rules using fixtures; this audit did not submit the six saved outputs to a live validation API.

## Quota-conscious evaluation

Manually process one unevaluated file at a time in Stage 2. Save the parser result as `evals/outputs/<pdf-stem>.json`, preserve its source identity, and run:

```powershell
.\.venv\Scripts\python.exe -m evals.accuracy
```

The evaluator is offline. Review each output and stop at the desired quota; never fill missing results from truth.

## Complete-system verification

- Complete automated suite on 2026-11-15: **55 passed**, 0 failed, 1 Starlette/anyio deprecation warning in 0.86 seconds.
- All five workflow exports parsed with names, nodes, and connections.
- Stage 3B documentation records two live PDF-to-Gemini-to-FastAPI-to-PostgreSQL runs (`invoice_09`, `invoice_11`).
- Stage 4A rerun passed authenticated decisions, 401, repeated 409, concurrent 200/409, invalid approval rejection, and immutable-audit rejection.
- Stage 4B rerun matched independent SQL and returned an idempotent receipt. Its fixed week contained 53 synthetic integration records at final verification.
- Live/static paths keep validation, review, and payment separate; outputs explicitly set payment authorization false.
- Duplicate detection and idempotency conflicts remain covered.

Stage 1, Stage 2, Stage 3B, Stage 4A, and Stage 4B were verified during their stages. The earlier 2026-11-14 audit reran Stage 4A and Stage 4B live without Gemini; the 2026-11-15 update ran only the offline extraction evaluator and automated suite.

## GitHub security review

- `.gitignore` excludes environments, virtualenvs, caches, coverage, n8n data, SQLite/database files, and Streamlit secrets.
- `.env.example` contains placeholders only.
- Workflows contain credential references but no API key, bearer token, reviewer password, or session token.
- n8n ownership metadata containing personal email/project identity was removed.
- No n8n SQLite database is in the publishable tree.
- Screenshots show synthetic aggregate data or a blank local login; no secret is visible.
- Markdown links and PowerShell commands were checked locally.

## Remaining limitations

- Only 6 of 20 documents have saved extraction outputs; the sample is small and selected rather than a representative estimate of model performance.
- The six saved files lack attached model execution provenance, so their Gemini origin cannot be independently certified from repository files.
- Extraction matching does not measure live business-validation accuracy or payment decisions.
- No populated Streamlit or authenticated workflow-canvas screenshot was captured in the audit.
- Local auth and in-memory sessions are not production identity architecture.
- Public n8n webhooks need TLS, edge auth, rate limiting, upload limits, and monitoring.
- Raw transport failures and every attempt are not persisted historically.
- Full live operation depends on the fictional Project 1 PostgreSQL catalogs/network.

## Publication assessment

This extraction evaluation did not perform a publication or secret audit. The five newer saved outputs are currently untracked in Git. Review the final staged diff and secrets before any later publication. No commit or push was made during this evaluation.
