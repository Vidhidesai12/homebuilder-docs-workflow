# Stage 4A human invoice review

Stage 4A adds a human decision beside the existing deterministic validation outcome. Validation remains `accepted`, `needs_review`, or `rejected_invalid`. Only an invoice with validation outcome `needs_review` and review status `pending` can become `approved_exception` or `declined`. An approved exception is not payment authorization; no payment action exists in this project.

## Launch

Set `REVIEW_USERNAME` and a strong `REVIEW_PASSWORD` in the ignored `.env`. The checked-in `.env.example` contains placeholders. Start the existing services from this project:

```powershell
docker compose up -d --build api review-ui n8n
```

The reviewer dashboard is available only on the local machine at <http://localhost:8502>. The review API is bound to <http://localhost:8001>. Sign in to the dashboard with the local reviewer credentials from `.env`; the dashboard exchanges them for a one-hour, in-memory bearer session. It never receives a database password or Gemini credential.

## Submit and review a fictional invoice

Open the published `Stage 4A - Validation and human review routing` workflow in n8n at <http://localhost:5678>. Its production form is <http://localhost:5678/form/stage4a-pdf-intake>. Upload a synthetic invoice such as `data/samples/invoice_12.pdf`. This performs a Gemini request, so use the saved-JSON route below when extraction is already available.

For a no-Gemini test, POST an API-shaped request to <http://localhost:5678/webhook/stage4a-saved-json>. Use a stable idempotency key, a PDF basename, and one extracted object. `python -m tests.live_stage4a_routing` demonstrates all routes with saved synthetic data.

For `needs_review`, n8n returns the record ID and `pending` review status, then ends. PostgreSQL owns the state; no n8n execution remains open. In the dashboard, select the pending invoice, inspect its vendor, community, lot, line items, total, exception reasons, and audit history. Enter at least 10 nonblank characters of justification and choose **Approve exception** or **Decline**. The API derives reviewer identity from the authenticated bearer session. It rejects reviewer names supplied in request bodies.

`rejected_invalid` records never enter the queue. Correct the source or extraction and submit it for validation again. `accepted` records require no exception decision and still have no payment approval.

## Storage and state enforcement

The additive migration is in `docs/review_migration.sql`. It preserves existing records and audit events. Human state is stored in `documents.records.review_status`; the immutable decision evidence is stored once in `documents.review_decisions`. The decision row includes record ID, decision, justification, authenticated reviewer identity, timestamp, copied exception reasons, and original `needs_review` outcome.

Database triggers enforce invoice eligibility, the `pending → approved_exception|declined` transition, copied exception reasons, and immutable decision and audit rows. Inserting a decision automatically changes the record state and appends a `review_decision` audit event in the same transaction. A unique constraint on decision record ID and a locked record read ensure repeated or concurrent attempts cannot create two decisions.

Review history is available in the dashboard and through authenticated `GET /v1/reviews/{record_id}/history`. Other authenticated endpoints are:

- `POST /v1/review/session` with HTTP Basic credentials to create a bearer session.
- `DELETE /v1/review/session` to end the session.
- `GET /v1/reviews/pending` to list pending invoices.
- `GET /v1/reviews/{record_id}` to inspect a document and exception reasons.
- `POST /v1/reviews/{record_id}/approve` with `{"justification":"..."}`.
- `POST /v1/reviews/{record_id}/decline` with `{"justification":"..."}`.

## n8n routing

The exported workflow is `workflows/human_review_stage4a.json`. It preserves the Stage 3B extraction and validation path, then uses a Switch node:

- `accepted` → validation success, explicitly no payment approval.
- `needs_review` → pending human review with record ID and review status.
- `rejected_invalid` → correction and resubmission required.
- HTTP conflict, other HTTP errors, timeouts, and network errors → processing error.

All terminal nodes set `payment_authorized` to false. The original Stage 3B workflow remains separately published and was verified after the Stage 4A changes.

## Verified results

Final automated suite: **34 passed, 1 Starlette dependency deprecation warning in 0.70 seconds**, using `--basetemp .test_tmp/pytest-final -p no:cacheprovider` because the managed environment denied pytest access to its default Windows temp and cache directories.

The final live review integration passed against the database-triggered atomic path: approved record 70, declined record 71, concurrent record 72 with HTTP statuses 200 and 409, and invalid record 73 rejected from approval. An unauthenticated decision returned 401, a repeated decision returned 409, required justification returned 422 in API tests, and a deliberate audit UPDATE was rejected as immutable. Each decided record retained its original `needs_review` validation outcome and had exactly one review decision event.

The live n8n saved-data routing test passed: accepted record 58, pending record 59, rejected-invalid record 60, HTTP 422 routed to processing error, and a simulated network outage routed to processing error. The API was restarted afterward. No Gemini request was made for these Stage 4A tests.

## Local MVP security limits

The API and dashboard bind to localhost in Compose. Authentication uses one reviewer account configured through environment variables, in-memory bearer sessions, and HTTP on the local machine. Sessions disappear on API restart and cannot be centrally revoked across multiple API processes. There is no per-user role model, MFA, TLS termination, CSRF token beyond Streamlit's normal session flow, rate limiting, or durable identity provider. The database role remains limited, but this is a portfolio-grade local control rather than a production identity system. Production deployment would require TLS, a real identity provider, role-based authorization, secret management, rate limits, session revocation, and protected network ingress.
