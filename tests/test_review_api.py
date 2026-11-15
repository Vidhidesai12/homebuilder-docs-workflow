import os

from fastapi.testclient import TestClient

from app.main import app


def client_with_reviewer(monkeypatch):
    monkeypatch.setenv("REVIEW_USERNAME", "test_reviewer")
    monkeypatch.setenv("REVIEW_PASSWORD", "test-secret-long-enough")
    return TestClient(app)


def token(client):
    response = client.post("/v1/review/session", auth=("test_reviewer", "test-secret-long-enough"))
    assert response.status_code == 200
    return response.json()["access_token"]


def test_review_endpoints_require_authentication(monkeypatch):
    client = client_with_reviewer(monkeypatch)
    assert client.get("/v1/reviews/pending").status_code == 401
    assert client.get("/v1/reviews/1").status_code == 401
    assert client.get("/v1/reviews/1/history").status_code == 401
    assert client.post("/v1/reviews/1/approve", json={"justification": "Reviewed exception"}).status_code == 401
    assert client.post("/v1/reviews/1/decline", json={"justification": "Reviewed exception"}).status_code == 401
    assert client.post("/v1/review/session", auth=("test_reviewer", "wrong")).status_code == 401


def test_review_identity_comes_from_authenticated_session(monkeypatch):
    client = client_with_reviewer(monkeypatch)
    from app import main
    seen = []

    def fake_decide(record_id, status, justification, reviewer):
        seen.append((record_id, status, justification, reviewer))
        return {"review_status": status, "reviewer_identity": reviewer, "payment_authorized": False}

    monkeypatch.setattr(main, "decide", fake_decide)
    headers = {"Authorization": f"Bearer {token(client)}"}
    assert client.post("/v1/reviews/9/approve", json={"justification": "  Reviewed budget overage  "}, headers=headers).status_code == 200
    assert seen == [(9, "approved_exception", "Reviewed budget overage", "test_reviewer")]
    assert client.post("/v1/reviews/9/approve", json={"justification": "Valid reason", "reviewer_identity": "forged"}, headers=headers).status_code == 422
    assert len(seen) == 1


def test_justification_required_and_session_logout(monkeypatch):
    client = client_with_reviewer(monkeypatch)
    headers = {"Authorization": f"Bearer {token(client)}"}
    assert client.post("/v1/reviews/9/approve", json={}, headers=headers).status_code == 422
    assert client.post("/v1/reviews/9/decline", json={"justification": "          "}, headers=headers).status_code == 422
    assert client.delete("/v1/review/session", headers=headers).status_code == 200
    assert client.get("/v1/reviews/pending", headers=headers).status_code == 401
