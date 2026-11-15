"""Deterministic weekly document reporting from PostgreSQL."""
from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.storage import connect

REPORT_TZ = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")


def previous_completed_week(generated_at: datetime | None = None) -> tuple[datetime, datetime]:
    generated = generated_at or datetime.now(UTC)
    if generated.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    local = generated.astimezone(REPORT_TZ)
    end_date = local.date() - timedelta(days=local.weekday())
    end = datetime.combine(end_date, time.min, REPORT_TZ)
    return end - timedelta(days=7), end


def _money(value: Decimal | str | int | None) -> str:
    return f"{Decimal(value or 0).quantize(Decimal('0.01')):.2f}"


def _counts(rows: list[dict], key: str) -> dict[str, int]:
    return {str(row[key]): int(row["count"]) for row in rows}


def _query_data(cur, start_utc: datetime, end_utc: datetime) -> dict:
    cur.execute(
        "SELECT count(*) AS unique_documents, "
        "count(*) FILTER (WHERE document_type='invoice') AS invoice_count, "
        "count(*) FILTER (WHERE document_type='change_order') AS change_order_count, "
        "count(*) FILTER (WHERE document_type IS NULL) AS unclassified_invalid_count "
        "FROM documents.records WHERE created_at >= %s AND created_at < %s",
        (start_utc, end_utc),
    )
    volume = cur.fetchone()
    cur.execute(
        "SELECT outcome, count(*) AS count FROM documents.records "
        "WHERE created_at >= %s AND created_at < %s GROUP BY outcome ORDER BY outcome",
        (start_utc, end_utc),
    )
    validation = _counts(cur.fetchall(), "outcome")
    cur.execute(
        "SELECT count(*) AS count FROM documents.records "
        "WHERE document_type='invoice' AND outcome='needs_review' AND review_status='pending'"
    )
    pending = int(cur.fetchone()["count"])
    cur.execute(
        "SELECT review_status, count(*) AS count FROM documents.review_decisions "
        "WHERE decided_at >= %s AND decided_at < %s GROUP BY review_status ORDER BY review_status",
        (start_utc, end_utc),
    )
    reviews = _counts(cur.fetchall(), "review_status")
    cur.execute(
        "SELECT coalesce(sum(total_amount),0) AS total FROM documents.records "
        "WHERE created_at >= %s AND created_at < %s AND document_type='invoice' AND outcome='accepted'",
        (start_utc, end_utc),
    )
    valid_value = _money(cur.fetchone()["total"])
    cur.execute(
        "SELECT community, count(*) AS invoice_count, sum(total_amount) AS total "
        "FROM documents.records WHERE created_at >= %s AND created_at < %s "
        "AND document_type='invoice' AND outcome='accepted' "
        "GROUP BY community ORDER BY community",
        (start_utc, end_utc),
    )
    communities = [{"community": row["community"], "invoice_count": int(row["invoice_count"]), "total_valid_invoice_value": _money(row["total"])} for row in cur.fetchall()]
    cur.execute(
        "SELECT vendor_name, count(*) AS invoice_count, sum(total_amount) AS total "
        "FROM documents.records WHERE created_at >= %s AND created_at < %s "
        "AND document_type='invoice' AND outcome='accepted' "
        "GROUP BY vendor_name ORDER BY vendor_name",
        (start_utc, end_utc),
    )
    vendors = [{"vendor": row["vendor_name"], "invoice_count": int(row["invoice_count"]), "total_valid_invoice_value": _money(row["total"])} for row in cur.fetchall()]
    cur.execute(
        "SELECT reason->>'code' AS reason, count(*) AS count "
        "FROM documents.records r CROSS JOIN LATERAL jsonb_array_elements(coalesce(r.reasons,'[]'::jsonb)) reason "
        "WHERE r.created_at >= %s AND r.created_at < %s "
        "GROUP BY reason->>'code' ORDER BY count(*) DESC, reason->>'code'",
        (start_utc, end_utc),
    )
    reasons = [{"reason": row["reason"], "count": int(row["count"])} for row in cur.fetchall()]
    cur.execute(
        "SELECT (created_at AT TIME ZONE 'America/Los_Angeles')::date::text AS day, "
        "count(*) AS documents, count(*) FILTER (WHERE outcome='accepted') AS accepted, "
        "count(*) FILTER (WHERE outcome='needs_review') AS needs_review, "
        "count(*) FILTER (WHERE outcome='rejected_invalid') AS rejected_invalid "
        "FROM documents.records WHERE created_at >= %s AND created_at < %s "
        "GROUP BY day ORDER BY day",
        (start_utc, end_utc),
    )
    document_trend = [{key: (int(value) if key != "day" else value) for key, value in row.items()} for row in cur.fetchall()]
    cur.execute(
        "SELECT (decided_at AT TIME ZONE 'America/Los_Angeles')::date::text AS day, "
        "count(*) FILTER (WHERE review_status='approved_exception') AS approved_exception, "
        "count(*) FILTER (WHERE review_status='declined') AS declined "
        "FROM documents.review_decisions WHERE decided_at >= %s AND decided_at < %s "
        "GROUP BY day ORDER BY day",
        (start_utc, end_utc),
    )
    review_trend = [{key: (int(value) if key != "day" else value) for key, value in row.items()} for row in cur.fetchall()]
    cur.execute(
        "SELECT count(*) AS count FROM documents.records r "
        "WHERE r.created_at >= %s AND r.created_at < %s "
        "AND EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(r.reasons,'[]'::jsonb)) x WHERE x->>'code'='duplicate_invoice')",
        (start_utc, end_utc),
    )
    duplicate_documents = int(cur.fetchone()["count"])
    return {
        "document_volume": {key: int(value) for key, value in volume.items()},
        "validation_outcomes": {name: validation.get(name, 0) for name in ("accepted", "needs_review", "rejected_invalid")},
        "pending_human_reviews_as_of_generation": pending,
        "review_decisions_in_period": {name: reviews.get(name, 0) for name in ("approved_exception", "declined")},
        "total_valid_invoice_value": valid_value,
        "accepted_invoice_totals_by_community": communities,
        "accepted_invoice_totals_by_vendor": vendors,
        "validation_exception_reasons": reasons,
        "duplicate_invoice_documents": duplicate_documents,
        "document_processing_trend": document_trend,
        "review_decision_trend": review_trend,
    }


def generate_weekly_report(generated_at: datetime | None = None, connection_factory=connect) -> dict:
    generated = generated_at or datetime.now(UTC)
    if generated.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    generated = generated.astimezone(UTC)
    start_local, end_local = previous_completed_week(generated)
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL statement_timeout = '10000ms'")
        data = _query_data(cur, start_local.astimezone(UTC), end_local.astimezone(UTC))
    report = {
        "report_timezone": "America/Los_Angeles",
        "period": {
            "start_inclusive": start_local.isoformat(), "end_exclusive": end_local.isoformat(),
            "start_utc": start_local.astimezone(UTC).isoformat(), "end_utc": end_local.astimezone(UTC).isoformat(),
        },
        "generated_at": generated.isoformat(),
        **data,
        "processing_failures": {"available": False, "count": None, "reason": "Transport and API failures were not historically persisted reliably."},
        "duplicate_attempts": {"available": False, "count": None, "reason": "Idempotent retries and conflicting submission attempts are not stored as separate attempt rows."},
        "limitations": [
            "Pending human reviews are an as-of-generation snapshot, not a count created during the report week.",
            "Financial totals include validation-accepted invoices only; change orders, needs_review, and rejected_invalid amounts are excluded.",
            "approved_exception is a review decision and is not payment approval or spending.",
            "Invoice totals are not written to Project 1 budget actuals.",
        ],
    }
    report["report_digest"] = report_digest(report)
    report["markdown"] = render_markdown(report)
    report["html"] = render_html(report)
    return report


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(label for _, label in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(str(row.get(key, "")) for key, _ in columns) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def render_markdown(report: dict) -> str:
    volume, outcomes, decisions = report["document_volume"], report["validation_outcomes"], report["review_decisions_in_period"]
    return f"""# Weekly document operations report

Period: `{report['period']['start_inclusive']}` through `{report['period']['end_exclusive']}` (end exclusive)<br>
Generated: `{report['generated_at']}`<br>
Timezone: `America/Los_Angeles`

## KPIs

- Unique documents: {volume['unique_documents']} (invoices {volume['invoice_count']}, change orders {volume['change_order_count']}, unclassified invalid {volume['unclassified_invalid_count']})
- Validation: accepted {outcomes['accepted']}, needs review {outcomes['needs_review']}, rejected invalid {outcomes['rejected_invalid']}
- Pending human reviews as of generation: {report['pending_human_reviews_as_of_generation']}
- Review decisions during period: approved exception {decisions['approved_exception']}, declined {decisions['declined']}
- Total validation-accepted invoice value: ${report['total_valid_invoice_value']}
- Documents flagged duplicate invoice: {report['duplicate_invoice_documents']}

## Accepted invoice value by community

{_table(report['accepted_invoice_totals_by_community'], [('community','Community'),('invoice_count','Invoices'),('total_valid_invoice_value','Value')])}

## Accepted invoice value by vendor

{_table(report['accepted_invoice_totals_by_vendor'], [('vendor','Vendor'),('invoice_count','Invoices'),('total_valid_invoice_value','Value')])}

## Validation exception reasons

{_table(report['validation_exception_reasons'], [('reason','Reason'),('count','Count')])}

## Limitations

""" + "\n".join(f"- {item}" for item in report["limitations"])


def render_html(report: dict) -> str:
    cards = [
        ("Unique documents", report["document_volume"]["unique_documents"]),
        ("Accepted", report["validation_outcomes"]["accepted"]),
        ("Needs review", report["validation_outcomes"]["needs_review"]),
        ("Rejected invalid", report["validation_outcomes"]["rejected_invalid"]),
        ("Pending now", report["pending_human_reviews_as_of_generation"]),
        ("Valid invoice value", "$" + report["total_valid_invoice_value"]),
    ]
    card_html = "".join(f"<div class='card'><small>{html.escape(str(label))}</small><strong>{html.escape(str(value))}</strong></div>" for label, value in cards)
    def rows(items, keys):
        return "".join("<tr>" + "".join(f"<td>{html.escape(str(item.get(key,'')))}</td>" for key in keys) + "</tr>" for item in items) or "<tr><td colspan='3'>No rows</td></tr>"
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Weekly document report</title><style>
body{{font-family:system-ui;margin:2rem;color:#17202a}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}}.card{{padding:1rem;border:1px solid #ddd;border-radius:10px}}strong{{display:block;font-size:1.6rem}}table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}th,td{{border-bottom:1px solid #ddd;padding:.5rem;text-align:left}}</style></head><body>
<h1>Weekly document operations report</h1><p>{html.escape(report['period']['start_inclusive'])} to {html.escape(report['period']['end_exclusive'])} (end exclusive)</p>
<div class='cards'>{card_html}</div><h2>Accepted invoice value by community</h2><table><tr><th>Community</th><th>Invoices</th><th>Value</th></tr>{rows(report['accepted_invoice_totals_by_community'], ['community','invoice_count','total_valid_invoice_value'])}</table>
<h2>Accepted invoice value by vendor</h2><table><tr><th>Vendor</th><th>Invoices</th><th>Value</th></tr>{rows(report['accepted_invoice_totals_by_vendor'], ['vendor','invoice_count','total_valid_invoice_value'])}</table>
<h2>Exception reasons</h2><table><tr><th>Reason</th><th>Count</th></tr>{rows(report['validation_exception_reasons'], ['reason','count'])}</table>
<p><strong>Approved exception does not mean payment approval.</strong></p></body></html>"""


def report_digest(report: dict) -> str:
    payload = {key: value for key, value in report.items() if key not in {"markdown", "html"}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_report_run(payload: dict, connection_factory=connect) -> dict:
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '5000ms'")
        cur.execute(
            "INSERT INTO documents.report_runs (idempotency_key,period_start,period_end,report_digest,generated_at,source) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id,recorded_at::text AS recorded_at",
            (payload["idempotency_key"], payload["period_start"], payload["period_end"], payload["report_digest"], payload["generated_at"], payload.get("source", "n8n")),
        )
        inserted = cur.fetchone()
        if inserted:
            return {"report_run_id": inserted["id"], "recorded_at": inserted["recorded_at"], "created": True}
        cur.execute(
            "SELECT id,period_start::text AS period_start,period_end::text AS period_end,report_digest,generated_at::text AS generated_at,recorded_at::text AS recorded_at,source "
            "FROM documents.report_runs WHERE idempotency_key=%s OR (period_start=%s AND period_end=%s AND source=%s) ORDER BY id LIMIT 1",
            (payload["idempotency_key"], payload["period_start"], payload["period_end"], payload.get("source", "n8n")),
        )
        existing = cur.fetchone()
        if not existing:
            raise RuntimeError("report run conflict could not be resolved")
        return {"report_run_id": existing["id"], "recorded_at": existing["recorded_at"], "created": False,
                "report_digest_matches": existing["report_digest"] == payload["report_digest"]}
