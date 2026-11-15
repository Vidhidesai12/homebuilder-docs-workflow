"""Live Stage 4B API/SQL comparison using synthetic documents; no Gemini calls."""
import json
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8001"
AS_OF = "2026-11-17T17:00:00Z"
START = "2026-11-09 08:00:00+00"
END = "2026-11-16 08:00:00+00"


def token() -> str:
    lines = (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    return next(line.split("=", 1)[1] for line in reversed(lines) if line.startswith("REPORT_API_TOKEN="))


def sql(statement: str) -> list[list[str]]:
    result = subprocess.run(
        ["docker", "exec", "homebuilder-ops-copilot-db-1", "psql", "-U", "homebuilder", "-d", "homebuilder_ops", "-At", "-F", "|", "-c", statement],
        check=True, capture_output=True, text=True,
    )
    return [line.split("|") for line in result.stdout.splitlines() if line]


def main() -> None:
    headers = {"Authorization": f"Bearer {token()}"}
    with httpx.Client(timeout=30) as client:
        response = client.get(API + "/v1/reports/weekly", params={"as_of": AS_OF}, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["period"]["start_utc"] == "2026-11-09T08:00:00+00:00"
        assert report["period"]["end_utc"] == "2026-11-16T08:00:00+00:00"
        volume = sql(f"SELECT count(*),count(*) FILTER(WHERE document_type='invoice'),count(*) FILTER(WHERE document_type='change_order'),count(*) FILTER(WHERE document_type IS NULL) FROM documents.records WHERE created_at>='{START}' AND created_at<'{END}'")[0]
        assert report["document_volume"] == {"unique_documents": int(volume[0]), "invoice_count": int(volume[1]), "change_order_count": int(volume[2]), "unclassified_invalid_count": int(volume[3])}
        outcome_rows = sql(f"SELECT outcome,count(*) FROM documents.records WHERE created_at>='{START}' AND created_at<'{END}' GROUP BY outcome")
        outcomes = {name: int(count) for name, count in outcome_rows}
        assert report["validation_outcomes"] == {name: outcomes.get(name, 0) for name in ("accepted", "needs_review", "rejected_invalid")}
        pending = int(sql("SELECT count(*) FROM documents.records WHERE document_type='invoice' AND outcome='needs_review' AND review_status='pending'")[0][0])
        assert report["pending_human_reviews_as_of_generation"] == pending
        decisions = {name: int(count) for name, count in sql(f"SELECT review_status,count(*) FROM documents.review_decisions WHERE decided_at>='{START}' AND decided_at<'{END}' GROUP BY review_status")}
        assert report["review_decisions_in_period"] == {name: decisions.get(name, 0) for name in ("approved_exception", "declined")}
        total = Decimal(sql(f"SELECT coalesce(sum(total_amount),0) FROM documents.records WHERE created_at>='{START}' AND created_at<'{END}' AND document_type='invoice' AND outcome='accepted'")[0][0])
        assert Decimal(report["total_valid_invoice_value"]) == total
        communities = sql(f"SELECT community,count(*),sum(total_amount) FROM documents.records WHERE created_at>='{START}' AND created_at<'{END}' AND document_type='invoice' AND outcome='accepted' GROUP BY community ORDER BY community")
        assert report["accepted_invoice_totals_by_community"] == [
            {"community": name, "invoice_count": int(count), "total_valid_invoice_value": f"{Decimal(value):.2f}"}
            for name, count, value in communities
        ]
        vendors = sql(f"SELECT vendor_name,count(*),sum(total_amount) FROM documents.records WHERE created_at>='{START}' AND created_at<'{END}' AND document_type='invoice' AND outcome='accepted' GROUP BY vendor_name ORDER BY vendor_name")
        assert report["accepted_invoice_totals_by_vendor"] == [
            {"vendor": name, "invoice_count": int(count), "total_valid_invoice_value": f"{Decimal(value):.2f}"}
            for name, count, value in vendors
        ]
        reasons = sql(f"SELECT x->>'code',count(*) FROM documents.records r CROSS JOIN LATERAL jsonb_array_elements(coalesce(r.reasons,'[]'::jsonb)) x WHERE r.created_at>='{START}' AND r.created_at<'{END}' GROUP BY x->>'code' ORDER BY count(*) DESC,x->>'code'")
        assert report["validation_exception_reasons"] == [{"reason": reason, "count": int(count)} for reason, count in reasons]
        run_suffix = uuid.uuid4().hex[:12]
        receipt = {
            "idempotency_key": f"stage4b-live-{run_suffix}", "period_start": report["period"]["start_utc"],
            "period_end": report["period"]["end_utc"], "report_digest": report["report_digest"],
            "generated_at": report["generated_at"], "source": f"live-test-{run_suffix}",
        }
        first = client.post(API + "/v1/reports/weekly/runs", json=receipt, headers=headers)
        second = client.post(API + "/v1/reports/weekly/runs", json=receipt, headers=headers)
        assert first.status_code == second.status_code == 200
        assert first.json()["report_run_id"] == second.json()["report_run_id"]
        assert first.json()["created"] is True and second.json()["created"] is False
        print(json.dumps({
            "passed": True, "period": report["period"], "document_volume": report["document_volume"],
            "validation_outcomes": report["validation_outcomes"], "pending_reviews_as_of_generation": pending,
            "review_decisions": report["review_decisions_in_period"], "total_valid_invoice_value": report["total_valid_invoice_value"],
            "communities": report["accepted_invoice_totals_by_community"], "vendors": report["accepted_invoice_totals_by_vendor"],
            "exception_reasons": report["validation_exception_reasons"], "report_run_id": first.json()["report_run_id"],
            "retry_created_second_record": second.json()["created"],
        }, indent=2))


if __name__ == "__main__":
    main()
