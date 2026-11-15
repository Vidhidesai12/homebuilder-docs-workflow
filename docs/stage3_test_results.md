# Stage 3 test results — 2026-11-13

Final unit suite: **26 passed, 1 Starlette dependency deprecation warning in 1.67s**. This includes stricter ISO date and zero-value checks. The final Docker image was rebuilt and its live smoke test passed again.

The live integration smoke test passed against the existing Project 1 PostgreSQL container using the limited documents role. It created synthetic records and audit entries only in the `documents` schema. Observed outcomes:

| Case | Outcome | Actual reasons |
| --- | --- | --- |
| Normal synthetic invoice | accepted | none |
| `invoice_12` | needs_review | budget_category_mismatch, budget_exception, duplicate_invoice |
| `invoice_14` | needs_review | budget_category_mismatch, duplicate_invoice |
| `change_order_19` | needs_review | unknown_vendor |
| Invalid total | rejected_invalid | validation error |

The smoke test used a new shared synthetic invoice number for the normal and duplicate pair so it remains repeatable. `invoice_12` had already been submitted during an earlier failed smoke assertion, so the final run also correctly reported it as a duplicate. Read-only inspection found that the live November 2026 budget row for Demo Juniper Vista is `Permits`, while `invoice_12` says `Labor`; the live row for Demo Oakline Park is `Permits`, while `invoice_14` says `Sitework`. The service retained these extra reasons rather than hiding them. No public business row was changed.

The same request repeated with the same key returned the same response for each live case. Reusing a key with changed content returned HTTP 409. Two concurrent submissions of a new synthetic invoice number returned one `accepted` and one `needs_review` duplicate result. `http://localhost:8001/health` and `http://api:8001/health` from inside the n8n container both returned `{"status":"ok"}`. PostgreSQL privilege checks returned: budgets INSERT false, vendors SELECT true, documents.records INSERT true, public schema CREATE false.

No Gemini call, Slack action, payment approval, or Project 1 reseed was performed. A full live n8n Gemini-to-HTTP Request workflow execution was not performed; only API HTTP reachability from n8n and direct POST behavior were tested.
