# Stage 4B weekly document reporting

Stage 4B generates deterministic operational reports from the `documents` PostgreSQL schema. It does not call Gemini, change Project 1 business data, authorize payment, or make human-review decisions.

## Reporting contract

`GET /v1/reports/weekly` returns JSON plus rendered Markdown and HTML. The endpoint requires a dedicated bearer token from `REPORT_API_TOKEN`; it does not accept reviewer credentials. An optional timezone-aware `as_of` query value supports reproducible local tests.

The report covers the previous completed calendar week in `America/Los_Angeles`: Monday 00:00 inclusive through the following Monday 00:00 exclusive. Boundaries are converted to UTC for PostgreSQL queries, so daylight-saving transitions are handled correctly. `pending_human_reviews_as_of_generation` is a current snapshot when the report is generated, not a count of reviews created during the report week.

The report includes unique stored documents, document types, validation outcomes, review decisions, pending reviews, accepted invoice value, community and vendor breakdowns, validation reasons, and daily processing/review trends. These definitions are intentionally separate:

- `accepted`, `needs_review`, and `rejected_invalid` are validation outcomes.
- `pending`, `approved_exception`, and `declined` are human-review states.
- `approved_exception` is not payment approval.
- Financial totals contain only validation-accepted invoices. Change orders and flagged/invalid invoice amounts are excluded.
- Report queries never update Project 1 budget actuals.

Exact transport failures and submission-attempt counts are reported as unavailable because historical attempts were not reliably persisted. Documents flagged with `duplicate_invoice` are counted separately, while idempotent retries do not create another document or report-run row.

`POST /v1/reports/weekly/runs` records only a successful report-generation receipt in `documents.report_runs`. Its unique idempotency key and period/source constraint make retries safe. The table has an immutable update/delete trigger. The GET report transaction is read-only; the receipt endpoint can insert only this audit receipt.

## Setup and launch

Copy `.env.example` to `.env` if needed and configure strong, distinct values for the database URL, n8n encryption key, reviewer settings, and `REPORT_API_TOKEN`. Never place the report token in workflow JSON.

```powershell
docker compose up -d --build api n8n
```

Open <http://localhost:5678>. Import [weekly_reporting_stage4b.json](../workflows/weekly_reporting_stage4b.json) if it is not already present. Create an n8n **Header Auth** credential named `Stage 4B Reporting API` with header name `Authorization` and value `Bearer <your REPORT_API_TOKEN>`, then select it on both HTTP Request nodes.

The local workflow calls `http://host.docker.internal:8001`, because n8n runs in Docker while FastAPI is exposed on the Windows host. Both ports remain localhost-only.

## Manual report generation

In n8n, open **Stage 4B - Weekly document reporting** and choose **Execute workflow** to use the Manual Trigger. For a local automated check, POST to the workflow webhook while the workflow is published:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:5678/webhook/stage4b-weekly-report
```

The completion output contains the report period, KPI summary, Markdown, HTML, report-run receipt, and `payment_authorized: false`. A database/API outage causes the HTTP Request node to fail after its bounded retries; it cannot reach the success-receipt node and must not be interpreted as approval.

## Monday schedule

The Schedule Trigger is configured for Monday at 9:00 AM and the workflow timezone is `America/Los_Angeles`. Publish/activate the workflow and keep n8n running through the scheduled time. Importing a workflow does not automatically prove a future execution; no real Monday scheduled execution was observed during implementation.

## Verification performed on 2026-11-14

The complete automated suite passed: **46 passed, 0 failed, 1 dependency deprecation warning in 0.83 seconds**. Coverage includes calendar/month/year boundaries, both DST changes, status and review counts, duplicate/retry behavior, Decimal totals, breakdowns, empty periods, authentication, API failure/recovery behavior, idempotency, and workflow safety.

An authenticated live report was generated with `as_of=2026-11-17T17:00:00Z` so the existing synthetic records fell inside the completed period `2026-11-09T00:00:00-08:00` through `2026-11-16T00:00:00-08:00`. Independent SQL queries matched every checked figure:

- 49 unique documents: 35 invoices, 6 change orders, and 8 unclassified invalid documents.
- Validation: 9 accepted, 32 needs review, 8 rejected invalid.
- 15 pending reviews as of report generation.
- Review decisions in period: 5 approved exceptions and 7 declined.
- Validation-accepted invoice value: `$26,392.00`.
- Community totals: Demo Alder Grove `$10,729.00`; Demo Cedar Hollow `$15,663.00`.
- Exception reasons: duplicate invoice 26, budget category mismatch 10, invalid extraction 8, budget exception 6, unknown vendor 5.
- Reposting the identical receipt returned the same report-run ID and did not create a second record.

This was a reproducible authenticated `as_of` test, not an observed Monday schedule. At the actual implementation time, the naturally selected prior week was 2026-11-02 through 2026-11-09 and contained zero submitted documents; the service handled that empty period. The pending-review snapshot still reflected the current queue by design.

## Remaining limitations

- This is a localhost portfolio deployment with a shared bearer credential, not enterprise identity, token rotation, TLS termination, or a secrets manager.
- n8n and FastAPI must remain running for scheduled execution.
- Transport failures and every raw duplicate attempt cannot be reported historically until an attempt ledger is added.
- HTML is returned as report data; Stage 4B does not email, publish, or send it to Slack.
- A newly generated snapshot can have a different digest because its generation timestamp changes, even when its business figures do not; the period/source constraint still prevents duplicate report-run records.
