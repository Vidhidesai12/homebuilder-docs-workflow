-- Run once as a database administrator in the existing Project 1 PostgreSQL database.
-- Creates only a new documents schema. No public business table is changed.
CREATE SCHEMA IF NOT EXISTS documents;
REVOKE ALL ON SCHEMA documents FROM PUBLIC;

CREATE TABLE IF NOT EXISTS documents.records (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_digest CHAR(64) NOT NULL,
    source_filename TEXT NOT NULL,
    raw_extraction JSONB NOT NULL,
    extraction_confidence NUMERIC(5,4),
    extraction_uncertainty JSONB NOT NULL DEFAULT '[]'::jsonb,
    document_type TEXT,
    document_number TEXT,
    vendor_name TEXT,
    issue_date DATE,
    community TEXT,
    lot_number INTEGER,
    budget_category TEXT,
    total_amount NUMERIC(14,2),
    currency CHAR(3),
    extracted_fields JSONB,
    outcome TEXT CHECK (outcome IN ('accepted','needs_review','rejected_invalid')),
    reasons JSONB,
    response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (extraction_confidence IS NULL OR extraction_confidence BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS documents.invoice_claims (
    vendor_name TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    record_id BIGINT NOT NULL UNIQUE REFERENCES documents.records(id),
    PRIMARY KEY (vendor_name, invoice_number)
);

CREATE TABLE IF NOT EXISTS documents.audit_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    record_id BIGINT NOT NULL REFERENCES documents.records(id),
    event_type TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted','needs_review','rejected_invalid')),
    reasons JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS records_document_identity_idx
    ON documents.records (vendor_name, document_number);
