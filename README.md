# 🏗️ Homebuilder AI Document Workflow

Companion repository: [Homebuilder Ops Copilot](https://github.com/Vidhidesai12/homebuilder-ops-copilot). The repositories stay separate and share the existing local PostgreSQL database and Docker network.

For combined Windows startup, configure both repositories' ignored `.env` files and run `./start-platform.ps1` from the Ops Copilot repository in PowerShell. The main dashboard is at `http://localhost:8501`, the document API at `http://localhost:8001`, and the authenticated reviewer dashboard at `http://localhost:8502`. The Ops Copilot **Document Operations** tab reads this service's bearer-protected `GET /v1/reports/operations` endpoint. See the companion [integration architecture](https://github.com/Vidhidesai12/homebuilder-ops-copilot/blob/main/docs/integration_architecture.md).

The integrated pending invoice table uses [the read-only pending invoice API](docs/pending_read_api.md) with a separate `DOCUMENT_READ_API_TOKEN`. The combined startup script creates that token in this repository's ignored `.env` if absent and passes it to Project 1 in process memory. Reviewer actions remain in this project's authenticated dashboard. Keep the local dashboard and APIs bound to localhost; the main dashboard has no user login.

The authenticated operations report also supplies current-week needs-review invoice counts and validation reason counts by verified `public.communities.id`. It resolves the stored community name through an exact join to the shared catalog and reports unmatched records separately. Project 1 uses these IDs for its side-by-side Operations Risk Insights view; no delay causation is inferred.

**AI-Powered Invoice Processing | Intelligent Workflow Automation | Human-in-the-Loop Review**

An end-to-end AI document automation system built with **Google Gemini, n8n, Python, FastAPI, PostgreSQL, and Streamlit**.

The system automatically extracts structured information from construction invoices and change orders, validates financial and business rules, identifies exceptions, routes flagged invoices to authenticated human reviewers, and generates weekly operational reports.

**Key engineering highlights**
- **55 passing automated tests** in the complete local suite, including concurrency, authentication, reporting, and database validation.
- **Five n8n workflow exports**, covering document ingestion through weekly reporting.
- **92/92 extracted fields matched and 6/6 exact documents** in the six saved extraction JSON files (4 invoices, 2 change orders). This is a 6-of-20 synthetic document sample; 14 documents have no saved extraction output. See [final evaluation](docs/final_evaluation.md) for per-document results and the provenance limit.
- **Concurrency-safe and auditable processing**, with idempotent submissions and immutable reviewer decisions.

All business records are fictional. Validation acceptance and human exception approval do not authorize payment.

**Technologies:** Python · Google Gemini · n8n · FastAPI · PostgreSQL · Pydantic · Streamlit · Docker · pytest
