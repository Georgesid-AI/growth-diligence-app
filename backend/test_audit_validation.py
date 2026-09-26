"""Pure unit tests for audit input validation (issue: target-date year/typo guard).

These test the pydantic models directly — no live server or Mongo connection
needed, since importing `server` only constructs a (lazy, unconnected)
AsyncIOMotorClient. Run with `pytest`.
"""
import pytest
from pydantic import ValidationError

import server


@pytest.mark.parametrize("bad_date", [
    "0027-01-01",   # the reported bug: "0027" instead of "2027"
    "1999-12-31",   # just below the allowed range
    "2101-01-01",   # just above the allowed range
    "27-01-01",     # too few year digits to be YYYY-MM-DD at all
    "not-a-date",
])
def test_create_audit_rejects_bad_target_date_year(bad_date):
    with pytest.raises(ValidationError):
        server.AuditCreate(company_name="Acme", target_date=bad_date)


@pytest.mark.parametrize("good_date", ["2000-01-01", "2027-01-01", "2100-12-31", None])
def test_create_audit_accepts_valid_target_date(good_date):
    a = server.AuditCreate(company_name="Acme", target_date=good_date)
    assert a.target_date == good_date


def test_create_audit_accepts_missing_target_date():
    a = server.AuditCreate(company_name="Acme")
    assert a.target_date is None


@pytest.mark.parametrize("bad_date", ["0027-01-01", "2101-06-30"])
def test_update_audit_rejects_bad_target_date_year(bad_date):
    with pytest.raises(ValidationError):
        server.AuditUpdate(target_date=bad_date)


def test_update_audit_accepts_valid_target_date():
    u = server.AuditUpdate(target_date="2028-06-30")
    assert u.target_date == "2028-06-30"
