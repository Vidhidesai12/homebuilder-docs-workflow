from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import main
from app.reporting import current_week_start, generate_operations_summary
from tests.test_reporting import ScriptedConnection, scripted_data

UTC = ZoneInfo("UTC")


def test_current_week_starts_on_los_angeles_monday_across_dst():
    assert current_week_start(datetime(2026, 11, 14, 18, tzinfo=UTC)).isoformat() == "2026-11-09T00:00:00-08:00"
    assert current_week_start(datetime(2026, 3, 9, 18, tzinfo=UTC)).isoformat() == "2026-03-09T00:00:00-07:00"


def test_operations_summary_uses_current_period_and_snapshot_pending_count():
    connection = ScriptedConnection([None, None] + scripted_data() + [
        [{"community": "Demo Alpha", "count": 3}],
        [{"community_id": 1, "community": "Demo Alpha", "count": 2}],
        [{"community_id": 1, "reason": "budget_exception", "count": 2}],
        {"count": 1},
    ])
    queries = []
    original_execute = connection.cursor_value.execute
    def record_query(sql, params=None):
        queries.append(sql)
        return original_execute(sql, params)
    connection.cursor_value.execute = record_query
    report = generate_operations_summary(datetime(2026, 11, 14, 18, tzinfo=UTC), lambda: connection)
    assert report["period"]["start_inclusive"] == "2026-11-09T00:00:00-08:00"
    assert report["period"]["end_exclusive"] == "2026-11-14T18:00:00+00:00"
    assert report["pending_human_reviews_as_of_generation"] == 4
    assert report["total_valid_invoice_value"] == "1234.56"
    assert report["duplicate_invoice_documents"] == 2
    assert report["invoice_exceptions_by_community"] == [{"community": "Demo Alpha", "count": 3}]
    assert report["needs_review_invoices_by_community"] == [{
        "community_id": 1, "community": "Demo Alpha", "needs_review_invoices": 2,
        "common_exception_reasons": [{"reason": "budget_exception", "count": 2}],
    }]
    assert report["unmatched_needs_review_invoices"] == 1
    assert "REPEATABLE READ READ ONLY" in queries[0]
    assert any("JOIN public.communities c ON c.name = r.community" in sql
               and "c.id AS community_id" in sql for sql in queries)
    assert not any("ILIKE" in sql for sql in queries)
    queries = connection.cursor_value.results
    assert queries == []


def test_operations_endpoint_requires_document_read_token(monkeypatch):
    monkeypatch.setenv("DOCUMENT_READ_API_TOKEN", "test-token")
    monkeypatch.setenv("REPORT_API_TOKEN", "write-capable-token")
    monkeypatch.setattr(main, "generate_operations_summary", lambda: {"as_of": "2026-11-14T18:00:00+00:00"})
    client = TestClient(main.app)
    assert client.get("/v1/reports/operations").status_code == 401
    assert client.get("/v1/reports/operations", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/reports/operations", headers={"Authorization": "Bearer write-capable-token"}).status_code == 401
    response = client.get("/v1/reports/operations", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    assert response.json()["as_of"] == "2026-11-14T18:00:00+00:00"
