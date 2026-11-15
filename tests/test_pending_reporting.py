from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app import main
from app.pending_reporting import InvalidPendingCursor, list_pending_summaries
from app.storage import request_digest, validate_and_store


STAMP = datetime(2026, 11, 14, 18, tzinfo=timezone.utc)


def invoice(record_id):
    return {
        "document_id": record_id, "invoice_number": f"INV-{record_id:03d}",
        "vendor_name": "Demo Vendor", "community": "Demo Alpha", "lot_number": 12,
        "issue_date": "2026-11-10", "total_amount": "1234.56",
        "validation_outcome": "needs_review", "human_review_status": "pending",
        "validation_reasons": [{"code": "budget_exception", "detail": "Over plan", "secret": "omit"}],
        "created_at": STAMP,
    }


class Cursor:
    def __init__(self, results):
        self.results = list(results)
        self.current = None
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self.current = self.results.pop(0)

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.current

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Connection:
    def __init__(self, results):
        self.cursor_value = Cursor(results)

    def cursor(self):
        return self.cursor_value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def scripted_page(all_count, matching_count, rows):
    return Connection([None, None, {"as_of": STAMP},
                       {"total_count": all_count}, {"total_count": matching_count}, rows])


def test_pending_page_count_rows_decimal_and_bounded_keyset_pagination():
    first = scripted_page(3, 3, [invoice(1), invoice(2), invoice(3)])
    page = list_pending_summaries(page_size=2, connection_factory=lambda: first)
    assert page["all_pending_count"] == page["total_count"] == 3
    assert [row["document_id"] for row in page["items"]] == [1, 2]
    assert page["items"][0]["total_amount"] == "1234.56"
    assert page["items"][0]["validation_reasons"] == [{"code": "budget_exception", "detail": "Over plan"}]
    assert "created_at" not in page["items"][0]
    assert page["next_cursor"]
    sql = first.cursor_value.calls[-1][0]
    assert "document_type='invoice'" in sql and "outcome='needs_review'" in sql
    assert "review_status='pending'" in sql and "ORDER BY created_at, id" in sql
    assert "JOIN" not in sql
    assert "REPEATABLE READ READ ONLY" in first.cursor_value.calls[0][0]

    second = scripted_page(3, 3, [invoice(3)])
    later = list_pending_summaries(page_size=2, cursor=page["next_cursor"], connection_factory=lambda: second)
    assert [row["document_id"] for row in later["items"]] == [3]
    assert later["next_cursor"] is None
    assert "(created_at, id) >" in second.cursor_value.calls[-1][0]
    assert second.cursor_value.calls[-1][1][-3:-1] == (STAMP, 2)


def test_search_and_review_status_changes_reflect_current_queue():
    searched = scripted_page(3, 1, [invoice(2)])
    result = list_pending_summaries(search="Demo Vendor", connection_factory=lambda: searched)
    assert result["all_pending_count"] == 3 and result["total_count"] == 1
    assert searched.cursor_value.calls[-1][1][1] == "Demo Vendor"

    # Once a reviewer changes the row status, a new read sees the updated queue.
    after_decision = scripted_page(2, 2, [invoice(1), invoice(3)])
    current = list_pending_summaries(connection_factory=lambda: after_decision)
    assert current["all_pending_count"] == 2
    assert 2 not in [item["document_id"] for item in current["items"]]


def test_cursor_search_mismatch_and_bounds_are_rejected():
    first = scripted_page(3, 3, [invoice(1), invoice(2)])
    page = list_pending_summaries(page_size=1, connection_factory=lambda: first)
    try:
        list_pending_summaries(page_size=1, search="different", cursor=page["next_cursor"])
    except InvalidPendingCursor:
        pass
    else:
        raise AssertionError("Cursor accepted with different search")


def test_read_only_service_token_required_for_pending_endpoint(monkeypatch):
    monkeypatch.setenv("DOCUMENT_READ_API_TOKEN", "read-only-test-token")
    monkeypatch.setenv("REPORT_API_TOKEN", "n8n-write-token")
    monkeypatch.setattr(main, "list_pending_summaries", lambda **kwargs: {"total_count": 0, "items": [], "as_of": STAMP.isoformat()})
    client = TestClient(main.app)
    path = "/v1/reports/pending-invoices"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer n8n-write-token"}).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer read-only-test-token"}).status_code == 200
    receipt = {"idempotency_key": "test-receipt", "period_start": "2026-11-02T08:00:00+00:00",
               "period_end": "2026-11-09T08:00:00+00:00", "report_digest": "a" * 64,
               "generated_at": "2026-11-09T09:00:00+00:00", "source": "test"}
    assert client.post("/v1/reports/weekly/runs", headers={"Authorization": "Bearer read-only-test-token"}, json=receipt).status_code == 401
    assert client.get("/v1/reviews/pending", headers={"Authorization": "Bearer read-only-test-token"}).status_code == 401
    assert client.get(path + "?page_size=51", headers={"Authorization": "Bearer read-only-test-token"}).status_code == 422
    assert client.get(path + "?page_size=0", headers={"Authorization": "Bearer read-only-test-token"}).status_code == 422


def test_endpoint_rejects_bad_cursor(monkeypatch):
    monkeypatch.setenv("DOCUMENT_READ_API_TOKEN", "read-token")
    client = TestClient(main.app)
    response = client.get("/v1/reports/pending-invoices?cursor=bad", headers={"Authorization": "Bearer read-token"})
    assert response.status_code == 422


def test_idempotent_retry_reuses_record_without_extra_pending_row():
    payload = {"idempotency_key": "same-invoice-upload", "source_filename": "invoice_01.pdf",
               "extracted": {"document_number": "INV-001"}}
    existing = {"request_digest": request_digest(payload),
                "response": {"record_id": 7, "outcome": "needs_review"},
                "review_status": "pending"}
    connection = Connection([None, None, None, existing])
    result = validate_and_store(payload, connection_factory=lambda: connection)
    assert result == {"record_id": 7, "outcome": "needs_review", "review_status": "pending"}
    assert len(connection.cursor_value.calls) == 4
    assert not any("UPDATE documents.records" in sql or "INSERT INTO documents.audit_history" in sql
                   for sql, _ in connection.cursor_value.calls)
