"""Bounded, read-only pending invoice summaries for the companion application."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from app.storage import connect


class InvalidPendingCursor(ValueError):
    pass


def _encode_cursor(cutoff: datetime, created_at: datetime, record_id: int, search: str) -> str:
    payload = {"cutoff": cutoff.isoformat(), "created_at": created_at.isoformat(),
               "record_id": record_id, "search": search}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode_cursor(value: str, search: str) -> tuple[datetime, datetime, int]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        cutoff = datetime.fromisoformat(payload["cutoff"])
        created_at = datetime.fromisoformat(payload["created_at"])
        record_id = payload["record_id"]
        if (payload["search"] != search or cutoff.tzinfo is None or created_at.tzinfo is None
                or type(record_id) is not int or record_id <= 0 or created_at > cutoff
                ):
            raise ValueError("Cursor values are invalid")
        return cutoff, created_at, record_id
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, binascii.Error) as exc:
        raise InvalidPendingCursor("Invalid pending invoice cursor") from exc


def list_pending_summaries(page_size: int = 25, search: str = "", cursor: str | None = None,
                           connection_factory=connect) -> dict:
    """Count and page from one repeatable-read snapshot; order by creation time and ID."""
    if not 1 <= page_size <= 50 or len(search) > 100:
        raise ValueError("Invalid pending invoice page options")
    search = search.strip()
    decoded = _decode_cursor(cursor, search) if cursor else None
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur.execute("SET LOCAL statement_timeout = '5000ms'")
        cur.execute("SELECT transaction_timestamp() AS as_of")
        as_of = cur.fetchone()["as_of"]
        cutoff = decoded[0] if decoded else as_of
        if cutoff > as_of:
            raise InvalidPendingCursor("Invalid pending invoice cursor")
        pending_sql = (
            " FROM documents.records WHERE document_type='invoice' "
            "AND outcome='needs_review' AND review_status='pending' AND created_at <= %s "
        )
        filter_sql = pending_sql + (
            "AND position(lower(%s) in lower(coalesce(document_number,'') || ' ' || "
            "coalesce(vendor_name,'') || ' ' || coalesce(community,''))) > 0"
        )
        params = (cutoff, search)
        cur.execute("SELECT count(*) AS total_count" + pending_sql, (cutoff,))
        all_pending_count = int(cur.fetchone()["total_count"])
        cur.execute("SELECT count(*) AS total_count" + filter_sql, params)
        total = int(cur.fetchone()["total_count"])
        after_sql = " AND (created_at, id) > (%s, %s)" if decoded else ""
        after_params = (decoded[1], decoded[2]) if decoded else ()
        cur.execute(
            "SELECT id AS document_id, document_number AS invoice_number, vendor_name, "
            "community, lot_number, issue_date::text AS issue_date, "
            "total_amount::text AS total_amount, outcome AS validation_outcome, "
            "review_status AS human_review_status, reasons AS validation_reasons, created_at"
            + filter_sql + after_sql + " ORDER BY created_at, id LIMIT %s",
            (*params, *after_params, page_size + 1),
        )
        rows = cur.fetchall()
    has_more = len(rows) > page_size
    visible = rows[:page_size]
    next_cursor = None
    if has_more:
        last = visible[-1]
        next_cursor = _encode_cursor(cutoff, last["created_at"], last["document_id"], search)
    items = []
    for row in visible:
        item = {key: value for key, value in row.items() if key != "created_at"}
        item["validation_reasons"] = [
            {"code": reason.get("code"), "detail": reason.get("detail")}
            for reason in (item["validation_reasons"] or [])
        ]
        items.append(item)
    return {"as_of": as_of.isoformat(), "all_pending_count": all_pending_count,
            "total_count": total, "page_size": page_size,
            "search": search, "items": items, "next_cursor": next_cursor}
