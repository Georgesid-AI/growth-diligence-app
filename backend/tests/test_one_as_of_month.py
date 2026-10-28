"""One as-of month (docs/specs/dates-and-periods.md section 2 and 3, amended 2026-10-28): detected on Map from the revenue file and the
P&L, stored once on the audit, typed over by the analyst; it always counts as complete; a fiscal year-end sets the months of a yearly
column. Synthetic data only (rule 15)."""
import asyncio
import re
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

import server  # noqa: E402
from app import as_of  # noqa: E402
from app import claim_matching as cm  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402
from app.structures import sheet as sh  # noqa: E402
from forecast_support import payback_claim, payback_results, row_of, yearly_input  # noqa: E402
from test_as_of_default_and_stale_setup import api  # noqa: E402,F401  (the fixture)
from test_sheet_structure import YEARLY, stored_map  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def revenue_file(rows, file="revenue.csv"):
    """A mapped revenue dataset as the server stores it: (invoice date, amount) rows and the column mapping."""
    return {"dtype": "revenue", "file": file, "mapping": {"invoice_date": "Date", "amount": "Amount"},
            "rows": [{"Date": d, "Amount": a} for d, a in rows]}


def yearly_pnl(fye):
    return {"dtype": "pnl", "file": "pnl.xlsx", "sheet_map": stored_map(YEARLY), "fye": fye}


# --- 1. detection ------------------------------------------------------------------------------------------------------------

def test_detection_from_a_monthly_revenue_file_is_its_last_month_with_a_non_zero_amount():
    ds = revenue_file([("2019-04-01", 100), ("2019-05-01", 110), ("2019-06-01", 120), ("2019-07-01", 0), ("2019-08-01", None)])
    assert as_of.detect({"revenue": ds}) == {"month": "2019-06", "file": "revenue.csv"}
    assert as_of.month_end("2019-06") == "2019-06-30"


@pytest.mark.parametrize("fye, month", [(12, "2023-12"), (6, "2023-06")])
def test_detection_from_a_yearly_pnl_is_the_fiscal_year_end_month_of_its_last_actual_column(fye, month):
    found = as_of.detect({"pnl": yearly_pnl(fye)}, fye)
    assert found == {"month": month, "file": "pnl.xlsx"}, "FY2024 to FY2026 are forecast columns and are never the as-of month"


def test_a_yearly_column_after_the_revenue_files_last_month_is_not_actual_and_the_revenue_month_wins():
    revenue = revenue_file([("2022-08-01", 100), ("2022-09-01", 120)])
    assert as_of.detect({"revenue": revenue, "pnl": yearly_pnl(6)}, 6)["month"] == "2022-09", "FY2022 (June) ends before September 2022"
    assert as_of.detect({"revenue": revenue, "pnl": yearly_pnl(12)}, 12)["month"] == "2022-09", "FY2022 (December) ends after it"
    assert as_of.detect({"revenue": revenue, "pnl": yearly_pnl(12)}, 12)["file"] == "revenue.csv"


def test_with_no_actual_column_up_to_the_revenue_month_the_last_unmarked_column_with_revenue_stands():
    old = revenue_file([("2019-01-01", 100), ("2019-02-01", 120)])
    assert as_of.detect({"revenue": old, "pnl": yearly_pnl(12)}, 12) == {"month": "2023-12", "file": "pnl.xlsx"}


def test_nothing_detected_without_a_revenue_figure():
    assert as_of.detect({}) is None
    assert as_of.detect({"revenue": revenue_file([("2019-01-01", 0)])}) is None


def test_the_last_actual_column_is_read_from_the_as_of_month_and_the_plan_columns_start_the_month_after():
    m = stored_map(YEARLY)
    assert as_of.last_actual_column(m, 12, "2022-12")["header"] == "FY2022"
    assert as_of.last_actual_column(m, 6, "2022-06")["header"] == "FY2022"
    assert as_of.last_actual_column(m, 6, "2022-05")["header"] == "FY2021", "FY2022 ends June 2022: after May 2022 it is plan"
    plan = [c for c in as_of.statement_columns(m, 6) if c["end"] > "2023-06"]
    assert plan and plan[0]["end"] == "2024-06" and plan[0]["header"] == "FY2024"


# --- stored once on the audit, typed override --------------------------------------------------------------------------------

def test_the_as_of_month_is_stored_once_detected_or_typed(api):
    audit = api.db["audits"].docs[0]
    audit.update(as_of_by="detected", as_of_month=None)
    api.db["datasets"].docs.append({"audit_id": "aud-1", **revenue_file([("2019-05-01", 10), ("2019-06-01", 12)])})
    asyncio.run(server._refresh_as_of("aud-1"))
    got = api.get("/api/audits/aud-1").json()
    assert (got["as_of_month"], got["as_of_by"], got["as_of_file"]) == ("2019-06-30", "detected", "revenue.csv")

    typed = api.put("/api/audits/aud-1", json={"as_of_month": "2019-03-31"}).json()
    assert (typed["as_of_month"], typed["as_of_by"]) == ("2019-03-31", "analyst")
    api.db["datasets"].docs.append({"audit_id": "aud-1", **{**revenue_file([("2019-09-01", 15)]), "dtype": "pnl"}})
    asyncio.run(server._refresh_as_of("aud-1"))
    assert api.get("/api/audits/aud-1").json()["as_of_month"] == "2019-03-31", "Map never overwrites a typed month"

    cleared = api.put("/api/audits/aud-1", json={"as_of_month": None}).json()
    assert (cleared["as_of_month"], cleared["as_of_by"]) == ("2019-06-30", "detected"), "cleared: back to detection"


def test_a_changed_detected_month_marks_computed_results_stale(api):
    audit = api.db["audits"].docs[0]
    audit.update(as_of_by="detected", as_of_month="2024-02-29")
    api.db["datasets"].docs.append({"audit_id": "aud-1", **revenue_file([("2024-03-01", 10)])})
    asyncio.run(server._refresh_as_of("aud-1"))
    assert audit["as_of_month"] == "2024-03-31" and audit["setup_stale"] is True


def test_recognition_and_the_register_read_the_stored_field(api):
    api.db["audits"].docs[0].update(as_of_month="2024-02-29", as_of_by="analyst")
    assert asyncio.run(server._effective_as_of("aud-1", api.db["audits"].docs[0])) == "2024-02-29"
    assert server._register_settings(api.db["audits"].docs[0], {})["as_of_by"] == "analyst"


# --- 2. completeness ----------------------------------------------------------------------------------------------------------

def test_no_last_month_is_complete_or_possibly_partial_string_anywhere_in_the_code_or_the_specs():
    files = subprocess.run(["git", "ls-files", "backend", "frontend/src", "docs/specs"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    me = Path(__file__).resolve()
    hits = []
    for name in files:
        path = ROOT / name
        if path.resolve() == me or path.suffix not in (".py", ".js", ".jsx", ".json", ".md") or not path.exists():
            continue
        text = path.read_text(errors="ignore")
        if re.search(r"(?i)last month is complete|possibly partial|possibly_partial|last_month_complete", text):
            hits.append(name)
    assert hits == [], hits


# --- 3. the fiscal year-end drives the periods --------------------------------------------------------------------------------

@pytest.mark.parametrize("header", ["FY 2021", "FY2021", "2021"])
def test_a_yearly_column_maps_to_the_twelve_months_ending_at_the_fiscal_year_end_month(header):
    june, december = sh.period_of(header, 6), sh.period_of(header, 12)
    assert (june["start"], june["end"]) == ("2020-07", "2021-06")
    assert (december["start"], december["end"]) == ("2021-01", "2021-12")


def test_a_deck_2021_matches_the_file_year_only_when_both_end_in_the_same_month():
    def june_year_end():
        y = yearly_input()
        for k, a in enumerate(y["actual"]):
            a["start"], a["end"] = f"{a['year'] - 1}-07", f"{a['year']}-06"
        return payback_results(y)

    text = "CAC payback 24 months in FY2024: sales and marketing spend over revenue growth, gross margin adjusted"
    row = row_of(payback_claim(text, 24), results=june_year_end())
    assert row["evidence_label"] == "Unverified" and row["observed_value"] is None
    assert row["reason"] == ("annual payback not calculated for FY2024: period not covered: the claim's period ends Dec 2024, "
                             "the file's FY2024 ends Jun 2024"), "never a mismatch"
    same = row_of(payback_claim(text, 24), results=payback_results())
    assert same["observed_value"] == 24.0 and same["evidence_label"] != "Unverified", "both end in December: matched"


def test_year_on_year_revenue_growth_runs_fiscal_year_to_fiscal_year_for_a_june_year_end():
    from test_dates_and_periods import _claim, synthetic_run
    results = synthetic_run(as_of_month=None, first="2017-07", last="2019-06")
    rows = {}
    for fye in (6, 12):
        sets = {"fiscal_year_end": fye, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}}
        claim = _claim(claim_type="revenue_growth", value=10, unit="%", currency=None, target_date="FY2019", period_text="FY2019",
                       snippet="Revenue grew 10% YoY in FY2019")
        deck_claims.resolve_period(claim, fye)          # the audit's fiscal year-end sets the claim's months
        rows[fye] = cm.build_register([claim], results, sets)[0]
    assert rows[6]["observed_at"] == "2018-07 to 2019-06 vs 2017-07 to 2018-06", "the twelve months to June against the twelve before"
    assert rows[6]["period_coverage"] == "Covered"
    assert rows[12]["observed_at"] != rows[6]["observed_at"]
