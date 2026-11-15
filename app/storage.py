"""PostgreSQL document store using a role limited to documents writes and catalog reads."""
from __future__ import annotations

import hashlib
import json
import os

import psycopg
from psycopg.rows import dict_row

from app.validation import validate_document


class IdempotencyConflict(Exception):
    pass


class PgCatalog:
    def __init__(self, cursor):
        self.cursor = cursor

    def vendor_id(self, name: str) -> int | None:
        self.cursor.execute("SELECT id FROM public.vendors WHERE name = %s", (name,))
        row = self.cursor.fetchone()
        return row["id"] if row else None

    def community_id(self, name: str) -> int | None:
        self.cursor.execute("SELECT id FROM public.communities WHERE name = %s", (name,))
        row = self.cursor.fetchone()
        return row["id"] if row else None

    def lot_exists(self, community_id: int, lot_number: int) -> bool:
        self.cursor.execute("SELECT 1 FROM public.lots WHERE community_id = %s AND lot_number = %s", (community_id, lot_number))
        return self.cursor.fetchone() is not None

    def budget_category(self, community_id: int, month: str) -> str | None:
        self.cursor.execute("SELECT category FROM public.budgets WHERE community_id = %s AND budget_month = %s", (community_id, month))
        row = self.cursor.fetchone()
        return row["category"] if row else None


def request_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def connect():
    url = os.environ.get("DOCUMENTS_DATABASE_URL")
    if not url:
        raise RuntimeError("DOCUMENTS_DATABASE_URL is required")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=3)


def validate_and_store(payload: dict, connection_factory=connect) -> dict:
    """One transaction covers idempotency, catalog reads, duplicate claim, and audit."""
    digest = request_digest(payload)
    with connection_factory() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL search_path = pg_catalog, documents")
            cur.execute("SET LOCAL statement_timeout = '5000ms'")
            cur.execute(
                "INSERT INTO documents.records (idempotency_key, request_digest, source_filename, raw_extraction, extraction_confidence, extraction_uncertainty) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb) ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
                (payload["idempotency_key"], digest, payload["source_filename"], json.dumps(payload["extracted"]),
                 payload.get("extraction_confidence"), json.dumps(payload.get("extraction_uncertainty", []))),
            )
            inserted = cur.fetchone()
            if inserted is None:
                cur.execute("SELECT request_digest, response, review_status FROM documents.records WHERE idempotency_key = %s", (payload["idempotency_key"],))
                existing = cur.fetchone()
                if existing["request_digest"] != digest:
                    raise IdempotencyConflict("idempotency_key was already used with different content")
                return {**existing["response"], "review_status": existing["review_status"]}
            record_id = inserted["id"]
            def claim_invoice(vendor: str, number: str) -> bool:
                # Unique index serializes competing submissions with the same vendor+number.
                cur.execute(
                    "INSERT INTO documents.invoice_claims (vendor_name, invoice_number, record_id) VALUES (%s, %s, %s) "
                    "ON CONFLICT (vendor_name, invoice_number) DO NOTHING RETURNING record_id",
                    (vendor, number, record_id),
                )
                return cur.fetchone() is not None

            doc, status, reasons = validate_document(payload["extracted"], payload["source_filename"], PgCatalog(cur), claim_invoice)
            response = {
                "record_id": record_id, "source_filename": payload["source_filename"],
                "document_type": doc.document_type if doc else None,
                "document_number": doc.document_number if doc else None,
                "outcome": status, "reasons": reasons,
                "extraction_confidence": payload.get("extraction_confidence"),
                "extraction_uncertainty": payload.get("extraction_uncertainty", []),
                "review_status": "pending" if status == "needs_review" and doc and doc.document_type == "invoice" else None,
            }
            cur.execute(
                "UPDATE documents.records SET document_type=%s, document_number=%s, vendor_name=%s, issue_date=%s, community=%s, lot_number=%s, "
                "budget_category=%s, total_amount=%s, currency=%s, extracted_fields=%s::jsonb, outcome=%s, reasons=%s::jsonb, response=%s::jsonb, review_status=%s "
                "WHERE id=%s",
                (doc.document_type if doc else None, doc.document_number if doc else None, doc.vendor_name if doc else None,
                 doc.issue_date if doc else None, doc.community if doc else None, doc.lot_number if doc else None,
                 doc.budget_category if doc else None, doc.total_amount if doc else None, doc.currency if doc else None,
                 json.dumps(doc.model_dump(mode="json")) if doc else None, status, json.dumps(reasons), json.dumps(response), response["review_status"], record_id),
            )
            cur.execute(
                "INSERT INTO documents.audit_history (record_id, event_type, outcome, reasons) VALUES (%s, %s, %s, %s::jsonb)",
                (record_id, "validated", status, json.dumps(reasons)),
            )
            return response
