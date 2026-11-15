"""Local reviewer login with short-lived, in-memory bearer sessions."""
from __future__ import annotations

import hmac
import os
import secrets
import threading
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer

basic = HTTPBasic(auto_error=False)
bearer = HTTPBearer(auto_error=False)
_sessions: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()
SESSION_SECONDS = 3600


def create_session(credentials: HTTPBasicCredentials | None = Depends(basic)) -> dict:
    expected_user = os.environ.get("REVIEW_USERNAME")
    expected_password = os.environ.get("REVIEW_PASSWORD")
    if not expected_user or not expected_password:
        raise HTTPException(status_code=503, detail="Reviewer login is not configured")
    if credentials is None or not (
        hmac.compare_digest(credentials.username, expected_user)
        and hmac.compare_digest(credentials.password, expected_password)
    ):
        raise HTTPException(status_code=401, detail="Invalid reviewer credentials", headers={"WWW-Authenticate": "Basic"})
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions[token] = (expected_user, time.time() + SESSION_SECONDS)
    return {"access_token": token, "token_type": "bearer", "expires_in": SESSION_SECONDS, "reviewer_identity": expected_user}


def require_reviewer(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    token = credentials.credentials if credentials else None
    with _lock:
        session = _sessions.get(token) if token else None
        if session and session[1] <= time.time():
            _sessions.pop(token, None)
            session = None
    if not session:
        raise HTTPException(status_code=401, detail="Reviewer session required", headers={"WWW-Authenticate": "Bearer"})
    return session[0]


def end_session(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    token = credentials.credentials if credentials else None
    if token:
        with _lock:
            _sessions.pop(token, None)
    return {"ended": True}
