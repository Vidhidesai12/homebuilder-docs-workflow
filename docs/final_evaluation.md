# Final evaluation and publication audit

Evaluation date: 2026-11-14. No Gemini request was made during this audit.

## Extraction evaluation

The inventory contains 20 text-selectable PDFs and 20 matching truth records: 15 invoices and 5 change orders. Exactly one actual saved Gemini output exists: [`invoice_01.json`](../evals/outputs/invoice_01.json).

`python -m evals.accuracy` reported:

- Evaluated: 1 of 20.
- Schema-valid: 1; malformed: 0.
- Missing saved outputs: 19 (14 invoices, 5 change orders).
- Field accuracy: 16/16 (100%) on the one observed invoice.
- Exact accuracy: 1/1 (100%) on the one observed invoice.
- Invoice sample: 1; change-order sample: 0, not measured.
- Missing, incorrect, or unexpected fields in the evaluated document: none.

This is an observed Gemini result, not 100% accuracy across the corpus. Ground-truth-derived validation fixtures are mocks and are excluded from model accuracy.

## Quota-conscious evaluation

Manually process one unevaluated file at a time in Stage 2. Save the parser result as `evals/outputs/<pdf-stem>.json`, preserve its source identity, and run:

```powershell
.\.venv\Scripts\python.exe -m evals.accuracy evals\outputs\*.json --report evals\reports\all_saved_outputs.json
```

The evaluator is offline. Review each output and stop at the desired quota; never fill missing results from truth.

## Complete-system verification

- Automated suite: 46 passed, 0 failed, 1 Starlette/anyio deprecation warning in 0.79 seconds.
- All five workflow exports parsed with names, nodes, and connections.
- Stage 3B documentation records two live PDF-to-Gemini-to-FastAPI-to-PostgreSQL runs (`invoice_09`, `invoice_11`).
- Stage 4A rerun passed authenticated decisions, 401, repeated 409, concurrent 200/409, invalid approval rejection, and immutable-audit rejection.
- Stage 4B rerun matched independent SQL and returned an idempotent receipt. Its fixed week contained 53 synthetic integration records at final verification.
- Live/static paths keep validation, review, and payment separate; outputs explicitly set payment authorization false.
- Duplicate detection and idempotency conflicts remain covered.

Stage 1, Stage 2, Stage 3B, Stage 4A, and Stage 4B were verified during their stages. This final audit reran Stage 4A and Stage 4B live without Gemini.

## GitHub security review

- `.gitignore` excludes environments, virtualenvs, caches, coverage, n8n data, SQLite/database files, and Streamlit secrets.
- `.env.example` contains placeholders only.
- Workflows contain credential references but no API key, bearer token, reviewer password, or session token.
- n8n ownership metadata containing personal email/project identity was removed.
- No n8n SQLite database is in the publishable tree.
- Screenshots show synthetic aggregate data or a blank local login; no secret is visible.
- Markdown links and PowerShell commands were checked locally.

## Remaining limitations

- Only 1 of 20 documents has observed Gemini output; change-order accuracy is unknown.
- No populated Streamlit or authenticated workflow-canvas screenshot was captured in the audit.
- Local auth and in-memory sessions are not production identity architecture.
- Public n8n webhooks need TLS, edge auth, rate limiting, upload limits, and monitoring.
- Raw transport failures and every attempt are not persisted historically.
- Full live operation depends on the fictional Project 1 PostgreSQL catalogs/network.

## Publication assessment

The source tree is suitable for publication after a final staged-diff and secret scan. Do not add `.env`, n8n volume data, browser profiles, or database files. This directory was not a Git repository during the audit, so there was no tracked index; the review covered the prospective publishable tree using `.gitignore` exclusions.
