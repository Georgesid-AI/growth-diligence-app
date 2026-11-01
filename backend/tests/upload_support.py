"""What the upload tests share (the audit document, the upload helper and the fixture folders). Not a test file."""
from pathlib import Path

from app import usage as usage_mod

BACKEND = Path(__file__).resolve().parents[1]
MESSY = BACKEND / "tests" / "fixtures" / "messy"
FIXTURES = BACKEND / "tests" / "fixtures" / "recognition"
SAMPLE = BACKEND.parent / "sample_data"
MONTHLY = "monthly_report_actual_forecast.csv"
AUDIT = "audit-chat"
COMPANY = "Fixture Target Ltd"

AUDIT_DOC = {"id": AUDIT, "company_name": COMPANY,
             "structure_reading_consent": True, "fiscal_year_end": 12,
             "reporting_currency": "EUR", "target_arr": 1000000, "target_date": "2027-12-31", "as_of_month": None,
             "results": None, "status": "draft", "usage": usage_mod.empty()}


def upload(client, name, content=None, **params):
    content = content if content is not None else (MESSY / name).read_bytes()
    return client.post(f"/api/audits/{AUDIT}/datasets/upload", params=params, files={"file": (name, content)})
