from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app
from app.reporting import _query_data, previous_completed_week, record_report_run, render_markdown, report_digest

UTC = ZoneInfo("UTC")


class ScriptedCursor:
    def __init__(self, results):
        self.results = list(results)
        self.current = None

    def execute(self, _sql, _params=None):
        self.current = self.results.pop(0)

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.current

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ScriptedConnection:
    def __init__(self, results):
        self.cursor_value = ScriptedCursor(results)

    def cursor(self):
        return self.cursor_value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def scripted_data(empty=False):
    if empty:
        return [
            {"unique_documents": 0, "invoice_count": 0, "change_order_count": 0, "unclassified_invalid_count": 0}, [], {"count": 0}, [],
            {"total": Decimal("0")}, [], [], [], [], [], {"count": 0},
        ]
    return [
        {"unique_documents": 7, "invoice_count": 5, "change_order_count": 1, "unclassified_invalid_count": 1},
        [{"outcome": "accepted", "count": 3}, {"outcome": "needs_review", "count": 2}, {"outcome": "rejected_invalid", "count": 1}],
        {"count": 4},
        [{"review_status": "approved_exception", "count": 1}, {"review_status": "declined", "count": 2}],
        {"total": Decimal("1234.56")},
        [{"community": "Demo Alder Grove", "invoice_count": 2, "total": Decimal("1000.10")}],
        [{"vendor_name": "Demo Sitework Vendor 01", "invoice_count": 2, "total": Decimal("1000.10")}],
        [{"reason": "duplicate_invoice", "count": 2}, {"reason": "budget_exception", "count": 1}],
        [{"day": "2026-11-10", "documents": 6, "accepted": 3, "needs_review": 2, "rejected_invalid": 1}],
        [{"day": "2026-11-11", "approved_exception": 1, "declined": 2}],
        {"count": 2},
    ]


def test_previous_week_month_and_year_boundaries():
    start, end = previous_completed_week(datetime(2027, 1, 4, 17, tzinfo=UTC))
    assert start.isoformat() == "2026-12-28T00:00:00-08:00"
    assert end.isoformat() == "2027-01-04T00:00:00-08:00"
    start, end = previous_completed_week(datetime(2026, 3, 2, 17, tzinfo=UTC))
    assert start.date().isoformat() == "2026-02-23" and end.date().isoformat() == "2026-03-02"


def test_dst_week_boundaries_are_local_calendar_weeks():
    start, end = previous_completed_week(datetime(2026, 3, 9, 17, tzinfo=UTC))
    assert start.isoformat().endswith("-08:00") and end.isoformat().endswith("-07:00")
    assert (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() == 167 * 3600
    start, end = previous_completed_week(datetime(2026, 11, 2, 18, tzinfo=UTC))
    assert start.isoformat().endswith("-07:00") and end.isoformat().endswith("-08:00")
    assert (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() == 169 * 3600


def test_naive_generation_timestamp_rejected():
    try:
        previous_completed_week(datetime(2026, 11, 14, 12))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive datetime accepted")


def test_status_reviews_decimal_breakdowns_and_duplicates():
    data = _query_data(ScriptedCursor(scripted_data()), datetime.now(UTC), datetime.now(UTC))
    assert data["document_volume"] == {"unique_documents": 7, "invoice_count": 5, "change_order_count": 1, "unclassified_invalid_count": 1}
    assert data["validation_outcomes"] == {"accepted": 3, "needs_review": 2, "rejected_invalid": 1}
    assert data["pending_human_reviews_as_of_generation"] == 4
    assert data["review_decisions_in_period"] == {"approved_exception": 1, "declined": 2}
    assert data["total_valid_invoice_value"] == "1234.56"
    assert data["accepted_invoice_totals_by_community"][0]["total_valid_invoice_value"] == "1000.10"
    assert data["accepted_invoice_totals_by_vendor"][0]["vendor"] == "Demo Sitework Vendor 01"
    assert data["duplicate_invoice_documents"] == 2


def test_empty_database_results_are_zero_and_renderable():
    data = _query_data(ScriptedCursor(scripted_data(empty=True)), datetime.now(UTC), datetime.now(UTC))
    assert data["document_volume"]["unique_documents"] == 0
    assert data["validation_outcomes"] == {"accepted": 0, "needs_review": 0, "rejected_invalid": 0}
    assert data["total_valid_invoice_value"] == "0.00"
    assert data["accepted_invoice_totals_by_vendor"] == []
    report = {"period": {"start_inclusive": "a", "end_exclusive": "b"}, "generated_at": "c", **data,
              "limitations": ["No payment approval."]}
    assert "_No rows._" in render_markdown(report)


def test_report_digest_ignores_rendered_formats():
    report = {"generated_at": "x", "value": "1.00", "markdown": "one", "html": "two"}
    first = report_digest(report)
    report.update(markdown="changed", html="changed")
    assert report_digest(report) == first


def test_report_run_receipt_is_idempotent():
    payload = {
        "idempotency_key": "weekly:2026-11-02", "period_start": "2026-11-02T08:00:00+00:00",
        "period_end": "2026-11-09T08:00:00+00:00", "report_digest": "a" * 64,
        "generated_at": "2026-11-09T17:00:00+00:00", "source": "n8n",
    }
    connections = iter([
        ScriptedConnection([None, {"id": 7, "recorded_at": "now"}]),
        ScriptedConnection([None, None, {"id": 7, "period_start": payload["period_start"], "period_end": payload["period_end"],
                                   "report_digest": "a" * 64, "generated_at": payload["generated_at"], "recorded_at": "now", "source": "n8n"}]),
    ])
    factory = lambda: next(connections)
    assert record_report_run(payload, factory)["created"] is True
    retry = record_report_run(payload, factory)
    assert retry == {"report_run_id": 7, "recorded_at": "now", "created": False, "report_digest_matches": True}


def test_reporting_api_requires_dedicated_token(monkeypatch):
    monkeypatch.setenv("REPORT_API_TOKEN", "report-token-test")
    client = TestClient(app)
    assert client.get("/v1/reports/weekly").status_code == 401
    assert client.get("/v1/reports/weekly", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_reporting_api_error_and_recovery(monkeypatch):
    monkeypatch.setenv("REPORT_API_TOKEN", "report-token-test")
    from app import main
    client = TestClient(app, raise_server_exceptions=False)
    monkeypatch.setattr(main, "generate_weekly_report", lambda _: (_ for _ in ()).throw(RuntimeError("database unavailable")))
    assert client.get("/v1/reports/weekly", headers={"Authorization": "Bearer report-token-test"}).status_code == 500
    monkeypatch.setattr(main, "generate_weekly_report", lambda _: {"document_volume": {"unique_documents": 0}})
    response = client.get("/v1/reports/weekly", headers={"Authorization": "Bearer report-token-test"})
    assert response.status_code == 200 and response.json()["document_volume"]["unique_documents"] == 0
