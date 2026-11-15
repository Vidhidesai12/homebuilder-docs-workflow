# 🏗️ Homebuilder AI Document Workflow

**AI-Powered Invoice Processing | Intelligent Workflow Automation | Human-in-the-Loop Review**

An end-to-end AI document automation system built with **Google Gemini, n8n, Python, FastAPI, PostgreSQL, and Streamlit**.

The system automatically extracts structured information from construction invoices and change orders, validates financial and business rules, identifies exceptions, routes flagged invoices to authenticated human reviewers, and generates weekly operational reports.

**Key engineering highlights**
- **46 passing automated tests**, including concurrency, authentication, reporting, and database validation.
- **Five n8n workflow exports**, covering document ingestion through weekly reporting.
- **16/16 extracted fields matched** on the first evaluated Gemini invoice; the remaining 19 documents have not been evaluated with saved live model outputs.
- **Concurrency-safe and auditable processing**, with idempotent submissions and immutable reviewer decisions.

All business records are fictional. Validation acceptance and human exception approval do not authorize payment.

**Technologies:** Python · Google Gemini · n8n · FastAPI · PostgreSQL · Pydantic · Streamlit · Docker · pytest

## Project Demonstration

### 1. AI Invoice Processing
![n8n Workflow](docs/images/n8n_invoice_workflow.png)

### 2. Human-in-the-Loop Review
![Human Review Dashboard](docs/images/human_review_dashboard.png)

### 3. Automated Weekly Reporting
![Weekly Report](docs/images/weekly_report_actual.png)
