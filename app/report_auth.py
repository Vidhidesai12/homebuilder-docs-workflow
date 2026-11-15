"""Bearer authentication dedicated to automated reporting."""
import hmac
import os

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def require_report_service(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    expected = os.environ.get("REPORT_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Reporting service authentication is not configured")
    supplied = credentials.credentials if credentials else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Reporting service credential required", headers={"WWW-Authenticate": "Bearer"})
    return "n8n_reporting_service"


def require_document_reader(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Separate credential accepted only by read-only document report routes."""
    expected = os.environ.get("DOCUMENT_READ_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Document reader authentication is not configured")
    supplied = credentials.credentials if credentials else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Document reader credential required", headers={"WWW-Authenticate": "Bearer"})
    return "document_read_service"
