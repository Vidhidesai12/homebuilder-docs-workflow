# Stage 2 offline extraction accuracy

The saved `evals/outputs/invoice_01.json` was compared with the independent `data/ground_truth/invoice_01.json`. The output is a one-document JSON array. `document_date` is explicitly mapped to ground truth's `issue_date`; string lot number `"8"` is parsed as integer 8. `extraction_status` is transport metadata and is not a document field. The PDF filename is derived from the saved output filename and preserved in the report; it is not credited as a Gemini-extracted field.

## Measured result

| Metric | Result |
| --- | --- |
| Schema validation | Passed |
| Field accuracy | 16/16 (100%) |
| Exact-document accuracy | 1/1 (100%) |
| Missing fields | None |
| Incorrect fields | None |
| Unexpected fields | None |
| Source identity | `invoice_01.pdf`, `INV-2026-001` |

The 16 scored fields are document type, number, vendor, date, community, lot, budget category, total, and description, quantity, unit price, and amount for each of two line items. The document has no currency field in either saved extraction or ground truth; currency accuracy therefore cannot be measured for this invoice. If a future output supplies currency, the checker validates its format and flags it as unverified when ground truth has no currency. A currency present in both records is compared exactly.

Strict validation requires complete document fields, a real ISO date, a supported document type, at least one line item, positive quantities, nonnegative finite monetary amounts at cent precision, correct line extensions, and a total equal to the sum of line amounts. Monetary calculations use `Decimal` throughout. Additional saved outputs can be passed to `python -m evals.accuracy` without network calls.

Verification: `python -m pytest -q` passed 10 tests. The measured JSON report is `evals/reports/invoice_01_accuracy.json`. Tests cover malformed JSON, missing fields, wrong total, wrong line extension, wrong document identity and filename, unexpected fields, and batch summary behavior.
