# Stage 1 test results — 2026-11-13

| Check | Actual result |
| --- | --- |
| Python dependencies | Installed pinned packages in project-local `.venv` |
| Generator | Passed: 20 PDFs and 20 JSON records generated |
| Unit tests | Passed: `3 passed in 1.22s` |
| Document counts | Passed: 15 invoices, 5 change orders |
| Ground truth | Passed: every PDF has an exact matching JSON record |
| Line item arithmetic | Passed for all 20 records |
| Deliberate exceptions | Passed: invoice 12 budget threshold; invoice 14 duplicate vendor+number; change order 19 unknown vendor; no other exceptions |
| PDF text extraction | Passed with pypdf on `invoice_01.pdf`: number, vendor, community, and total found |
| Docker Compose | Passed: n8n image `2.46.7` pulled and container started |
| Local n8n HTTP | Passed: GET `http://localhost:5678` returned HTTP 200; port published at `127.0.0.1:5678` |
| Workflow import | Passed: n8n CLI reported `Successfully imported 1 workflow.` |
| Live form upload and n8n extraction | Not run: n8n owner setup and form activation require interactive UI steps. The export is importable, but live execution remains unverified. |

These tests did not connect to or modify Project 1. The expected validation statuses in ground truth represent the Stage 2 validation contract; Stage 1's n8n workflow only extracts text and metadata.
