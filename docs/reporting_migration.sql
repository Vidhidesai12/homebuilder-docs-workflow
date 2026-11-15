-- Stage 4B additive migration. Stores successful report-generation receipts only.
BEGIN;
CREATE TABLE IF NOT EXISTS documents.report_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  period_start TIMESTAMPTZ NOT NULL,
  period_end TIMESTAMPTZ NOT NULL,
  report_digest CHAR(64) NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  source TEXT NOT NULL DEFAULT 'n8n',
  CHECK (period_end > period_start)
);
CREATE UNIQUE INDEX IF NOT EXISTS report_runs_period_key
  ON documents.report_runs(period_start, period_end, source);

CREATE OR REPLACE FUNCTION documents.prevent_report_run_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Report generation records are immutable'; END $$;
DROP TRIGGER IF EXISTS report_runs_immutable ON documents.report_runs;
CREATE TRIGGER report_runs_immutable BEFORE UPDATE OR DELETE ON documents.report_runs
FOR EACH ROW EXECUTE FUNCTION documents.prevent_report_run_mutation();

GRANT SELECT, INSERT ON documents.report_runs TO homebuilder_docs;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA documents TO homebuilder_docs;
COMMIT;
