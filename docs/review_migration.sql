-- Stage 4A additive migration in the existing documents schema only.
-- Run as the database administrator. Existing validation and audit rows are retained.
BEGIN;

DROP TRIGGER IF EXISTS records_review_transition ON documents.records;
ALTER TABLE documents.records ADD COLUMN IF NOT EXISTS review_status TEXT;
ALTER TABLE documents.records DROP CONSTRAINT IF EXISTS records_review_status_check;
UPDATE documents.records SET review_status = 'pending'
WHERE outcome = 'needs_review' AND document_type = 'invoice' AND review_status IS NULL;
UPDATE documents.records SET review_status = NULL
WHERE outcome = 'needs_review' AND document_type <> 'invoice' AND review_status = 'pending';

ALTER TABLE documents.records ADD CONSTRAINT records_review_status_check
    CHECK (
      (outcome IS NULL AND review_status IS NULL)
      OR (outcome = 'needs_review' AND document_type = 'invoice' AND review_status IN ('pending','approved_exception','declined'))
      OR (outcome = 'needs_review' AND document_type <> 'invoice' AND review_status IS NULL)
      OR (outcome IN ('accepted','rejected_invalid') AND review_status IS NULL)
    );

CREATE OR REPLACE FUNCTION documents.guard_record_review_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.outcome IS NOT NULL AND NEW.outcome IS DISTINCT FROM OLD.outcome THEN
    RAISE EXCEPTION 'Validation outcome is immutable after initial processing';
  END IF;
  IF OLD.review_status IS DISTINCT FROM NEW.review_status THEN
    IF OLD.outcome IS NULL AND OLD.review_status IS NULL
       AND NEW.outcome = 'needs_review' AND NEW.review_status = 'pending' THEN
      RETURN NEW;
    END IF;
    IF OLD.outcome = 'needs_review' AND NEW.outcome = 'needs_review'
       AND OLD.review_status = 'pending'
       AND NEW.review_status IN ('approved_exception','declined') THEN
      IF EXISTS (SELECT 1 FROM documents.review_decisions d
                 WHERE d.record_id = OLD.id AND d.review_status = NEW.review_status) THEN
        RETURN NEW;
      END IF;
    END IF;
    RAISE EXCEPTION 'Invalid review state transition';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER records_review_transition BEFORE UPDATE ON documents.records
FOR EACH ROW EXECUTE FUNCTION documents.guard_record_review_transition();

CREATE TABLE IF NOT EXISTS documents.review_decisions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  record_id BIGINT NOT NULL UNIQUE REFERENCES documents.records(id),
  review_status TEXT NOT NULL CHECK (review_status IN ('approved_exception','declined')),
  justification TEXT NOT NULL CHECK (length(btrim(justification)) >= 10),
  reviewer_identity TEXT NOT NULL CHECK (length(btrim(reviewer_identity)) > 0),
  decided_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  exception_reasons JSONB NOT NULL,
  original_validation_outcome TEXT NOT NULL CHECK (original_validation_outcome = 'needs_review')
);

CREATE OR REPLACE FUNCTION documents.guard_review_decision_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE current_record documents.records%ROWTYPE;
BEGIN
  SELECT * INTO current_record FROM documents.records WHERE id = NEW.record_id FOR UPDATE;
  IF current_record.id IS NULL OR current_record.document_type <> 'invoice'
     OR current_record.outcome <> 'needs_review' OR current_record.review_status <> 'pending' THEN
    RAISE EXCEPTION 'Only pending needs_review invoices can receive a decision';
  END IF;
  IF NEW.exception_reasons IS DISTINCT FROM current_record.reasons THEN
    RAISE EXCEPTION 'Decision exception reasons must match validation record';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS review_decisions_eligible ON documents.review_decisions;
CREATE TRIGGER review_decisions_eligible BEFORE INSERT ON documents.review_decisions
FOR EACH ROW EXECUTE FUNCTION documents.guard_review_decision_insert();

CREATE OR REPLACE FUNCTION documents.apply_review_decision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE documents.records SET review_status = NEW.review_status WHERE id = NEW.record_id;
  INSERT INTO documents.audit_history
    (record_id, event_type, outcome, reasons, review_status, reviewer_identity, review_reason, original_validation_outcome)
  VALUES
    (NEW.record_id, 'review_decision', NEW.original_validation_outcome, NEW.exception_reasons,
     NEW.review_status, NEW.reviewer_identity, NEW.justification, NEW.original_validation_outcome);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS review_decisions_apply ON documents.review_decisions;
CREATE TRIGGER review_decisions_apply AFTER INSERT ON documents.review_decisions
FOR EACH ROW EXECUTE FUNCTION documents.apply_review_decision();

ALTER TABLE documents.audit_history ADD COLUMN IF NOT EXISTS review_status TEXT;
ALTER TABLE documents.audit_history ADD COLUMN IF NOT EXISTS reviewer_identity TEXT;
ALTER TABLE documents.audit_history ADD COLUMN IF NOT EXISTS review_reason TEXT;
ALTER TABLE documents.audit_history ADD COLUMN IF NOT EXISTS original_validation_outcome TEXT;

CREATE OR REPLACE FUNCTION documents.prevent_event_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Decision and audit events are immutable'; END $$;
DROP TRIGGER IF EXISTS audit_history_immutable ON documents.audit_history;
CREATE TRIGGER audit_history_immutable BEFORE UPDATE OR DELETE ON documents.audit_history
FOR EACH ROW EXECUTE FUNCTION documents.prevent_event_mutation();
DROP TRIGGER IF EXISTS review_decisions_immutable ON documents.review_decisions;
CREATE TRIGGER review_decisions_immutable BEFORE UPDATE OR DELETE ON documents.review_decisions
FOR EACH ROW EXECUTE FUNCTION documents.prevent_event_mutation();

GRANT SELECT, INSERT ON documents.review_decisions TO homebuilder_docs;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA documents TO homebuilder_docs;
COMMIT;
