"""Pure unit tests for audit input validation (issue: target-date year/typo guard).

These test the pydantic models directly — no live server or Mongo connection
needed, since importing `server` only constructs a (lazy, unconnected)
AsyncIOMotorClient. Run with `pytest`.
"""
import pytest
from pydantic import ValidationError

import server

# Every audit names its client (the investor) and the engagement reference (llm-structure-reading.md section 4).
REQUIRED = {"company_name": "Acme", "client_name": "Northbridge Capital", "engagement_reference": "ENG-1"}


@pytest.mark.parametrize("bad_date", [
    "0027-01-01",   # the reported bug: "0027" instead of "2027"
    "1999-12-31",   # just below the allowed range
    "2101-01-01",   # just above the allowed range
    "27-01-01",     # too few year digits to be YYYY-MM-DD at all
    "not-a-date",
])
def test_create_audit_rejects_bad_target_date_year(bad_date):
    with pytest.raises(ValidationError):
        server.AuditCreate(**REQUIRED, target_date=bad_date)


@pytest.mark.parametrize("good_date", ["2000-01-01", "2027-01-01", "2100-12-31", None])
def test_create_audit_accepts_valid_target_date(good_date):
    a = server.AuditCreate(**REQUIRED, target_date=good_date)
    assert a.target_date == good_date


def test_create_audit_accepts_missing_target_date():
    a = server.AuditCreate(**REQUIRED)
    assert a.target_date is None


@pytest.mark.parametrize("bad_date", ["0027-01-01", "2101-06-30"])
def test_update_audit_rejects_bad_target_date_year(bad_date):
    with pytest.raises(ValidationError):
        server.AuditUpdate(target_date=bad_date)


def test_update_audit_accepts_valid_target_date():
    u = server.AuditUpdate(target_date="2028-06-30")
    assert u.target_date == "2028-06-30"


# Create Growth Audit: both dates travel as ISO, whatever the browser displays.
def test_create_audit_accepts_iso_as_of_date():
    a = server.AuditCreate(**REQUIRED, target_date="2027-12-31", as_of_month="2026-06-30")
    assert (a.target_date, a.as_of_month) == ("2027-12-31", "2026-06-30")


@pytest.mark.parametrize("good", ["2026-06-30", "2026-06", None])
def test_as_of_month_accepts_iso(good):
    assert server.AuditUpdate(as_of_month=good).as_of_month == good


@pytest.mark.parametrize("bad", ["30/06/2026", "06/30/2026", "06/2026", "June 2026", "2026-6", "2026-02-30"])
def test_as_of_month_rejects_non_iso(bad):
    with pytest.raises(ValidationError):
        server.AuditCreate(**REQUIRED, as_of_month=bad)
    with pytest.raises(ValidationError):
        server.AuditUpdate(as_of_month=bad)


# Fiscal year-end: a month, December unless set (deck-parser.md section 2).
def test_fiscal_year_end_defaults_to_december_and_takes_a_month():
    assert server.AuditCreate(**REQUIRED).fiscal_year_end == 12
    assert server.AuditCreate(**REQUIRED, fiscal_year_end=3).fiscal_year_end == 3
    assert server.AuditUpdate(fiscal_year_end=6).fiscal_year_end == 6
    assert server.AuditUpdate().fiscal_year_end is None


@pytest.mark.parametrize("bad", [0, 13, -1])
def test_fiscal_year_end_outside_1_to_12_is_refused(bad):
    with pytest.raises(ValidationError):
        server.AuditCreate(**REQUIRED, fiscal_year_end=bad)
    with pytest.raises(ValidationError):
        server.AuditUpdate(fiscal_year_end=bad)


# Consent and the names it rests on (llm-structure-reading.md section 4).
@pytest.mark.parametrize("missing", ["client_name", "engagement_reference"])
def test_audit_creation_requires_a_client_name_and_an_engagement_reference(missing):
    with pytest.raises(ValidationError):
        server.AuditCreate(**{k: v for k, v in REQUIRED.items() if k != missing})
    with pytest.raises(ValidationError):
        server.AuditCreate(**{**REQUIRED, missing: "   "})


def test_consent_is_ticked_by_default_and_can_be_unticked():
    assert server.AuditCreate(**REQUIRED).structure_reading_consent is True
    assert server.AuditCreate(**REQUIRED, structure_reading_consent=False).structure_reading_consent is False
    assert server.AuditUpdate(structure_reading_consent=False).structure_reading_consent is False
