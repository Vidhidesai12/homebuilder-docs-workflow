"""Read-only review views and atomic, append-audited human decisions."""
from __future__ import annotations

import json

from app.storage import connect


class ReviewNotFound(Exception):
    pass


class ReviewConflict(Exception):
    pass


def list_pending(connection_factory=connect) -> list[dict]:
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL statement_timeout = '5000ms'")
        cur.execute(
            "SELECT id AS record_id, source_filename, document_type, document_number, vendor_name, "
            "community, lot_number, total_amount::text AS total_amount, outcome, review_status, reasons, created_at::text AS created_at "
            "FROM documents.records WHERE outcome = 'needs_review' AND review_status = 'pending' "
            "AND document_type = 'invoice' ORDER BY created_at, id LIMIT 100"
        )
        return cur.fetchall()


def get_document(record_id: int, connection_factory=connect) -> dict:
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL statement_timeout = '5000ms'")
        cur.execute(
            "SELECT id AS record_id, source_filename, document_type, document_number, vendor_name, "
            "issue_date::text AS issue_date, community, lot_number, budget_category, "
            "total_amount::text AS total_amount, currency, extracted_fields, raw_extraction, "
            "outcome, reasons, review_status, created_at::text AS created_at "
            "FROM documents.records WHERE id = %s", (record_id,)
        )
        row = cur.fetchone()
        if row is None:
            raise ReviewNotFound(record_id)
        return row


def get_history(record_id: int, connection_factory=connect) -> list[dict]:
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL statement_timeout = '5000ms'")
        cur.execute("SELECT 1 FROM documents.records WHERE id = %s", (record_id,))
        if cur.fetchone() is None:
            raise ReviewNotFound(record_id)
        cur.execute(
            "SELECT id, record_id, event_type, outcome AS original_validation_outcome, reasons AS exception_reasons, "
            "review_status, reviewer_identity, review_reason, recorded_at::text AS recorded_at "
            "FROM documents.audit_history WHERE record_id = %s ORDER BY id", (record_id,)
        )
        return cur.fetchall()


def decide(record_id: int, decision: str, justification: str, reviewer: str, connection_factory=connect) -> dict:
    if decision not in {"approved_exception", "declined"}:
        raise ValueError("unsupported decision")
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '5000ms'")
        cur.execute("SET LOCAL lock_timeout = '3000ms'")
        cur.execute(
            "SELECT id, document_type, outcome, review_status, reasons FROM documents.records "
            "WHERE id = %s FOR UPDATE", (record_id,)
        )
        row = cur.fetchone()
        if row is None:
            raise ReviewNotFound(record_id)
        if row["document_type"] != "invoice" or row["outcome"] != "needs_review" or row["review_status"] != "pending":
            raise ReviewConflict("Only pending needs_review invoices can receive a decision")
        cur.execute(
            "INSERT INTO documents.review_decisions "
            "(record_id, review_status, justification, reviewer_identity, exception_reasons, original_validation_outcome) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s) RETURNING id, decided_at::text AS decided_at",
            (record_id, decision, justification, reviewer, json.dumps(row["reasons"]), row["outcome"]),
        )
        decision_row = cur.fetchone()
        # The database AFTER INSERT trigger changes review_status and appends the
        # immutable audit event in this transaction. A decision cannot omit it.
        return {
            "record_id": record_id, "review_status": decision, "review_reason": justification,
            "reviewer_identity": reviewer, "decided_at": decision_row["decided_at"],
            "exception_reasons": row["reasons"], "original_validation_outcome": row["outcome"],
            "decision_id": decision_row["id"], "payment_authorized": False,
        }
