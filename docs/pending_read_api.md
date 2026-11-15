# Pending invoice read API

`GET /v1/reports/pending-invoices` requires `Authorization: Bearer <DOCUMENT_READ_API_TOKEN>`. This token is distinct from the n8n `REPORT_API_TOKEN` and reviewer login/session credentials. The same read token also authorizes `GET /v1/reports/operations`; it cannot authorize report-run receipts or review decisions.

Query parameters:

| Parameter | Meaning |
|---|---|
| `page_size` | 1–50; default 25 |
| `search` | Up to 100 characters; case-insensitive literal text within invoice number, vendor, or community |
| `cursor` | Opaque next-page value from the preceding response. Keep the same search term. |

Response schema:

```json
{
  "as_of": "ISO 8601 UTC timestamp",
  "all_pending_count": 0,
  "total_count": 0,
  "page_size": 25,
  "search": "",
  "items": [
    {
      "document_id": 1,
      "invoice_number": "INV-EXAMPLE",
      "vendor_name": "Example Vendor",
      "community": "Example Community",
      "lot_number": 1,
      "issue_date": "YYYY-MM-DD",
      "total_amount": "123.45",
      "validation_outcome": "needs_review",
      "human_review_status": "pending",
      "validation_reasons": [{"code": "reason_code", "detail": "Reason detail"}]
    }
  ],
  "next_cursor": null
}
```

The numbers and names above illustrate field types; they are not application metrics. `total_amount` stays a decimal string. The endpoint reads only `documents.records` in a repeatable-read, read-only transaction. It counts and selects only pending `needs_review` invoices, so accepted, invalid, approved, and declined records are excluded. Existing idempotency keys keep retries from inserting duplicate records. Sorting by `(created_at, id)` and a cursor avoid offset shifts. Each page's count and rows share a transaction snapshot. A cursor fixes the creation cutoff across pages; review decisions between requests can still remove invoices and change counts. Fetch again to see the current queue.

The localhost demo exposes the main dashboard and both APIs on `127.0.0.1` host ports. The dashboard itself has no per-user login, so do not publish it or forward those ports to other machines. Human approval remains in the separate authenticated reviewer dashboard.
