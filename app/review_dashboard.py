"""Local reviewer UI. Uses the authenticated API; holds no database credentials."""
from __future__ import annotations

import os

import httpx
import streamlit as st

API = os.environ.get("REVIEW_API_URL", "http://localhost:8001").rstrip("/")
st.set_page_config(page_title="Homebuilder review", layout="wide")
st.title("Document exception review")
st.caption("An approved exception does not authorize payment.")


def call(method: str, path: str, **kwargs) -> dict:
    headers = {"Authorization": f"Bearer {st.session_state['review_token']}"}
    response = httpx.request(method, API + path, headers=headers, timeout=10, **kwargs)
    if response.status_code == 401:
        st.session_state.pop("review_token", None)
        st.error("Reviewer session expired. Sign in again.")
        st.stop()
    response.raise_for_status()
    return response.json()


if "review_token" not in st.session_state:
    with st.form("reviewer_login"):
        username = st.text_input("Reviewer username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Sign in")
    if submit:
        try:
            response = httpx.post(API + "/v1/review/session", auth=(username, password), timeout=10)
            response.raise_for_status()
            st.session_state["review_token"] = response.json()["access_token"]
            st.session_state["reviewer_identity"] = response.json()["reviewer_identity"]
            st.rerun()
        except httpx.HTTPError:
            st.error("Sign-in failed or review API is unavailable.")
    st.stop()

left, right = st.columns([5, 1])
left.write(f"Signed in as **{st.session_state.get('reviewer_identity', 'reviewer')}**")
if right.button("Sign out"):
    try:
        call("DELETE", "/v1/review/session")
    finally:
        st.session_state.pop("review_token", None)
        st.session_state.pop("reviewer_identity", None)
        st.rerun()

try:
    queue = call("GET", "/v1/reviews/pending")["documents"]
except httpx.HTTPError as exc:
    st.error(f"Could not load review queue: {exc}")
    st.stop()

st.subheader(f"Pending invoices ({len(queue)})")
if queue:
    st.dataframe([{
        "ID": row["record_id"], "Invoice": row["document_number"], "Vendor": row["vendor_name"],
        "Community": row["community"], "Lot": row["lot_number"], "Total": row["total_amount"],
        "Reasons": ", ".join(reason["code"] for reason in row["reasons"]),
    } for row in queue], hide_index=True, use_container_width=True)
    selected = st.selectbox("Document to inspect", [row["record_id"] for row in queue],
                            format_func=lambda record_id: next(f"#{r['record_id']} — {r['document_number']}" for r in queue if r["record_id"] == record_id))
else:
    st.info("No pending invoices.")
    selected = None

manual_id = st.number_input("Or open a document ID to view its history", min_value=0, step=1, value=0)
record_id = int(manual_id) if manual_id else selected
if record_id:
    try:
        doc = call("GET", f"/v1/reviews/{record_id}")
        history = call("GET", f"/v1/reviews/{record_id}/history")["events"]
    except httpx.HTTPError as exc:
        st.error(f"Could not load document: {exc}")
        st.stop()
    st.subheader(f"Document #{record_id}: {doc['document_number']}")
    a, b, c = st.columns(3)
    a.write(f"**Vendor:** {doc['vendor_name']}\n\n**Community:** {doc['community']}\n\n**Lot:** {doc['lot_number']}")
    b.write(f"**Total:** {doc['total_amount']}\n\n**Issue date:** {doc['issue_date']}\n\n**Category:** {doc['budget_category']}")
    c.write(f"**Validation:** {doc['outcome']}\n\n**Review:** {doc['review_status'] or 'not applicable'}\n\n**Source:** {doc['source_filename']}")
    st.write("**Extracted line items**")
    st.dataframe((doc["extracted_fields"] or {}).get("line_items", []), hide_index=True, use_container_width=True)
    st.write("**Validation exception reasons**")
    for item in doc["reasons"] or []:
        st.write(f"- `{item['code']}`: {item['detail']}")
    if doc["document_type"] == "invoice" and doc["outcome"] == "needs_review" and doc["review_status"] == "pending":
        with st.form(f"decision_{record_id}"):
            justification = st.text_area("Required reviewer justification (at least 10 characters)")
            approve = st.form_submit_button("Approve exception")
            decline = st.form_submit_button("Decline")
        if approve or decline:
            action = "approve" if approve else "decline"
            try:
                result = call("POST", f"/v1/reviews/{record_id}/{action}", json={"justification": justification})
                st.success(f"Review saved: {result['review_status']} by {result['reviewer_identity']}. Payment remains unauthorized.")
                st.rerun()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.json().get("detail", str(exc))
                st.error(f"Decision was not saved: {detail}")
            except httpx.HTTPError as exc:
                st.error(f"Decision request failed: {exc}")
    else:
        st.info("This document cannot receive a new review decision. Invalid documents must be corrected and revalidated.")
    st.write("**Audit history**")
    st.dataframe(history, hide_index=True, use_container_width=True)
