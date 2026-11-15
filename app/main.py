"""Local HTTP validation endpoint for n8n."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.storage import IdempotencyConflict, validate_and_store
from app.review_auth import create_session, end_session, require_reviewer
from app.review_store import ReviewConflict, ReviewNotFound, decide, get_document, get_history, list_pending
from app.report_auth import require_document_reader, require_report_service
from app.reporting import generate_operations_summary, generate_weekly_report, record_report_run
from app.pending_reporting import InvalidPendingCursor, list_pending_summaries

app = FastAPI(title="Homebuilder document validation and review", version="0.4.0")


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=200)
    source_filename: str = Field(min_length=5)
    extracted: dict
    extraction_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    extraction_uncertainty: list[str] = Field(default_factory=list)

    @field_validator("source_filename")
    @classmethod
    def pdf_basename(cls, value: str) -> str:
        if "/" in value or "\\" in value or not value.lower().endswith(".pdf"):
            raise ValueError("source_filename must be a PDF basename")
        return value


@app.post("/v1/validate")
def validate(request: ValidationRequest):
    try:
        return validate_and_store(request.model_dump(mode="json"))
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/health")
def health():
    return {"status": "ok"}


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    justification: str = Field(min_length=10, max_length=2000)

    @field_validator("justification")
    @classmethod
    def meaningful_justification(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 10:
            raise ValueError("justification must contain at least 10 nonblank characters")
        return cleaned


@app.post("/v1/review/session")
def reviewer_login(session: dict = Depends(create_session)):
    return session


@app.delete("/v1/review/session")
def reviewer_logout(_: str = Depends(require_reviewer), result: dict = Depends(end_session)):
    return result


@app.get("/v1/reviews/pending")
def pending_reviews(_: str = Depends(require_reviewer)):
    return {"documents": list_pending()}


@app.get("/v1/reviews/{record_id}")
def review_document(record_id: int, _: str = Depends(require_reviewer)):
    try:
        return get_document(record_id)
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc


@app.get("/v1/reviews/{record_id}/history")
def review_history(record_id: int, _: str = Depends(require_reviewer)):
    try:
        return {"events": get_history(record_id)}
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc


def _decision_response(record_id: int, status: str, body: ReviewDecisionRequest, reviewer: str) -> dict:
    try:
        return decide(record_id, status, body.justification, reviewer)
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/reviews/{record_id}/approve")
def approve_exception(record_id: int, body: ReviewDecisionRequest, reviewer: str = Depends(require_reviewer)):
    return _decision_response(record_id, "approved_exception", body, reviewer)


@app.post("/v1/reviews/{record_id}/decline")
def decline_exception(record_id: int, body: ReviewDecisionRequest, reviewer: str = Depends(require_reviewer)):
    return _decision_response(record_id, "declined", body, reviewer)


class ReportRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=200)
    period_start: datetime
    period_end: datetime
    report_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    generated_at: datetime
    source: str = Field(default="n8n", min_length=1, max_length=50)

    @field_validator("period_start", "period_end", "generated_at")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


@app.get("/v1/reports/weekly")
def weekly_report(as_of: datetime | None = None, _: str = Depends(require_report_service)):
    if as_of is not None and as_of.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must be timezone-aware")
    return generate_weekly_report(as_of)


@app.get("/v1/reports/operations")
def operations_summary(_: str = Depends(require_document_reader)):
    return generate_operations_summary()


@app.get("/v1/reports/pending-invoices")
def pending_invoice_summaries(
    page_size: int = Query(default=25, ge=1, le=50),
    search: str = Query(default="", max_length=100),
    cursor: str | None = Query(default=None, max_length=1024),
    _: str = Depends(require_document_reader),
):
    try:
        return list_pending_summaries(page_size=page_size, search=search, cursor=cursor)
    except InvalidPendingCursor as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/reports/weekly/runs")
def report_run(body: ReportRunRequest, _: str = Depends(require_report_service)):
    if body.period_end <= body.period_start:
        raise HTTPException(status_code=422, detail="period_end must be after period_start")
    return record_report_run(body.model_dump(mode="json"))
