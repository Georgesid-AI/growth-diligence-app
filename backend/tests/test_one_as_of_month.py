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
import test_llm_gateway as t  # noqa: E402
from app import as_of  # noqa: E402
from app import claim_matching as cm  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402
from app.structures import sheet as sh  # noqa: E402
from forecast_support import payback_claim, payback_results, row_of, yearly_input  # noqa: E402
from test_as_of_default_and_stale_setup import api  # noqa: E402,F401  (the set-up client, aud-1)
from test_chat_upload import AUDIT, mapping_reply, upload  # noqa: E402
from test_revenue_recognition import FIXTURES as RECOGNITION, MONTHLY, recognition_reply  # noqa: E402
from test_sheet_structure import YEARLY, sheet_of, stored_map  # noqa: E402

from app import column_rules as cr  # noqa: E402
from app import recognition as rec  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def revenue_file(rows, file="revenue.csv"):
    """A mapped revenue dataset as the server stores it: (invoice date, amount) rows and the column mapping."""
    return {"dtype": "revenue", "file": file, "mapping": {"invoice_date": "Date", "amount": "Amount"},
            "rows": [{"Date": d, "Amount": a} for d, a in rows]}


def yearly_pnl(fye):
    return {"dtype": "pnl", "file": "pnl.xlsx", "sheet_map": stored_map(YEARLY), "fye": fye}


# --- 1. detection: the model's suggested boundary, checked by rules (dates-and-periods.md section 2) ------------------------------

def test_detection_from_a_file_of_invoices_is_its_last_month_with_a_non_zero_amount():
    ds = revenue_file([("2019-04-01", 100), ("2019-05-01", 110), ("2019-06-01", 120), ("2019-07-01", 0), ("2019-08-01", None)])
    assert as_of.detect({"revenue": ds}) == {"month": "2019-06", "file": "revenue.csv", "cue": None}
    assert as_of.month_end("2019-06") == "2019-06-30"


def sheet_dataset(text: str, name: str = "pnl.csv", dtype: str = "pnl", column=None, cue=None, **extra) -> dict:
    """A file read as a sheet, as the server stores it: its sheets and the model's kept proposal (no months, no mapping, no rows)."""
    sheets = cr.read_workbook(text.encode(), name)
    proposal = {"sheet": 1, "file_type": "financial_statements", "revenue_row": None, "currency": None, "non_revenue_rows": [],
                "last_actual_column": column, "boundary_cue": {"cell": cue[0], "text": cue[1]} if cue else None}
    return {"dtype": dtype, "file": name, "months": None, "mapping": {}, "rows": [], "recognition_sheets": rec.pack_sheets(sheets),
            "recognition_proposal": proposal, "recognition_decisions": {}, **extra}


YEARLY_FORECAST = ("Annual P&L,,,,,,\n,,,,Forecast,,\nLine,FY 2019,FY 2020,FY 2021,FY 2022,FY 2023,FY 2024\n"
                   "Revenue,100,110,120,130,140,150\nCost of sales,50,55,60,65,70,75\n")
MONTHS = [f"{m} {y}" for y in (2021, 2022) for m in ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")]
MONTHLY_FORECAST = ("Monthly report,\n" + "Line," + ",".join(MONTHS) + "\n" + "Revenue," + ",".join(str(100 + i) for i in range(12)) + ",,,,,,,,,,,,\n"
                    + "Forecast," + ",,,,,,,,,,,," + ",".join(str(200 + i) for i in range(12)) + "\n")
NO_PLAN_WORD = YEARLY_FORECAST.replace("Forecast", "Notes")


def test_a_yearly_pnl_with_a_forecast_title_over_the_last_three_columns_gives_the_end_of_the_column_before_them():
    found = as_of.detect({"pnl": sheet_dataset(YEARLY_FORECAST, column=4, cue=("E2", "Forecast"))}, 12)
    assert found == {"month": "2021-12", "file": "pnl.csv", "cue": "Forecast"}
    june = as_of.detect({"pnl": sheet_dataset(YEARLY_FORECAST, column=4, cue=("r2c5", "forecast"))}, 6)
    assert june["month"] == "2021-06", "a yearly column ends in the fiscal year-end month"


def test_a_monthly_report_with_a_forecast_row_label_gives_the_month_before_it_starts():
    ds = sheet_dataset(MONTHLY_FORECAST, "report.csv", "revenue", column=13, cue=("r4", "Forecast"))
    assert as_of.detect({"revenue": ds}) == {"month": "2021-12", "file": "report.csv", "cue": "Forecast"}
    assert as_of.detect({"revenue": sheet_dataset(MONTHLY_FORECAST, "report.csv", "revenue", column=13, cue=("A4", "Forecast"))})["month"] == "2021-12"


def test_with_no_plan_word_anywhere_or_no_suggestion_detection_returns_nothing_and_never_the_last_column_with_a_number():
    assert as_of.detect({"pnl": sheet_dataset(NO_PLAN_WORD)}) is None, "no suggestion"
    assert as_of.detect({"pnl": sheet_dataset(NO_PLAN_WORD, column=4, cue=("E2", "Forecast"))}) is None, "the cell says Notes"
    assert as_of.detect({"pnl": sheet_dataset(NO_PLAN_WORD, column=4, cue=("E2", "Notes"))}) is None, "no plan word in the cell"
    assert as_of.detect({"revenue": sheet_dataset(MONTHLY_FORECAST.replace("Forecast", "Second"), "r.csv", "revenue", column=13,
                                                  cue=("r4", "Second"))}) is None
    assert as_of.detect({"pnl": sheet_dataset(YEARLY_FORECAST)}) is None, "a plan word on the sheet is not a suggestion"


@pytest.mark.parametrize("column, cue, why", [
    (4, ("E3", "FY 2022"), "the cue cell holds no plan word"),
    (4, ("E2", "Budget"), "the cue text is not the cell's text"),
    (4, ("Z9", "Forecast"), "the cue cell is not on the sheet"),
    (5, ("E2", "Forecast"), "the title is over the suggested column, not after it"),
    (3, ("B2", "Forecast"), "no cell"),
    (4, ("E4", "Revenue"), "a data cell"),
    (1, ("E2", "Forecast"), "column A holds labels, not a period"),
    (99, ("E2", "Forecast"), "the column is not on the sheet"),
])
def test_a_suggestion_that_fails_the_check_gives_nothing(column, cue, why):
    assert as_of.detect({"pnl": sheet_dataset(YEARLY_FORECAST, column=column, cue=cue)}) is None, why


def test_a_cue_left_of_the_suggested_column_fails_and_a_merged_title_reaching_past_it_holds():
    left = YEARLY_FORECAST.replace(",,,,Forecast,,", ",Forecast,,,,,")
    assert as_of.detect({"pnl": sheet_dataset(left, column=4, cue=("B2", "Forecast"))}) is None, "the title sits over FY 2019"
    from openpyxl import Workbook
    import io
    wb = Workbook()
    ws = wb.active
    for row in ([None] * 7, [None] * 7, ["Line", "FY 2019", "FY 2020", "FY 2021", "FY 2022", "FY 2023", "FY 2024"],
                ["Revenue", 100, 110, 120, 130, 140, 150], ["Cost of sales", 50, 55, 60, 65, 70, 75]):
        ws.append(row)
    ws["D2"] = "Forecast"
    ws.merge_cells("D2:G2")
    buf = io.BytesIO()
    wb.save(buf)
    sheets = cr.read_workbook(buf.getvalue(), "m.xlsx")
    ds = {**sheet_dataset(YEARLY_FORECAST), "recognition_sheets": rec.pack_sheets(sheets),
          "recognition_proposal": {"sheet": 1, "last_actual_column": 4, "boundary_cue": {"cell": "D2", "text": "Forecast"}}}
    assert as_of.detect({"pnl": ds}, 12)["month"] == "2021-12", "the merged title D2:G2 reaches FY 2022 to FY 2024"


def test_the_later_month_of_the_two_files_wins_and_the_cue_belongs_to_the_file_it_came_from():
    pnl = sheet_dataset(YEARLY_FORECAST, column=4, cue=("E2", "Forecast"))
    later = revenue_file([("2022-08-01", 100), ("2022-09-01", 120)])
    found = as_of.detect({"revenue": later, "pnl": pnl}, 12)
    assert found == {"month": "2022-09", "file": "revenue.csv", "cue": None}
    earlier = revenue_file([("2021-02-01", 100)])
    assert as_of.detect({"revenue": earlier, "pnl": pnl}, 12) == {"month": "2021-12", "file": "pnl.csv", "cue": "Forecast"}


def test_a_pnl_stored_with_a_statement_map_reads_the_suggested_column_from_it():
    ds = {**sheet_dataset(YEARLY_FORECAST, column=4, cue=("E2", "Forecast")), "sheet_map": sh.build(sh.read(
        cr.read_workbook(YEARLY_FORECAST.encode(), "pnl.csv")[0].grid, {}, 12))}
    assert as_of.detect({"pnl": ds}, 12)["month"] == "2021-12"


def test_nothing_detected_without_a_file_or_a_revenue_figure():
    assert as_of.detect({}) is None
    assert as_of.detect({"revenue": revenue_file([("2019-01-01", 0)])}) is None


# --- 1b. recognised files: stored with no months and no mapping (PR 196 review, finding 1) ----------------------------------

def recognised_dataset(name: str, dtype: str = "revenue", content: bytes = None, **suggestion) -> dict:
    """A file stored by recognition alone, as _store_recognised and the P&L path keep it: its sheets, no months, no mapping, no rows."""
    content = content if content is not None else (RECOGNITION / name).read_bytes()
    sheets = cr.read_workbook(content, name)
    proposal = {"sheet": 1, "last_actual_column": suggestion.get("column"),
                "boundary_cue": {"cell": suggestion["cue"][0], "text": suggestion["cue"][1]} if suggestion.get("cue") else None}
    return {"dtype": dtype, "file": name, "months": None, "mapping": {}, "rows": [], "recognition_only": dtype == "revenue",
            "recognition_sheets": rec.pack_sheets(sheets), "recognition_proposal": proposal, "recognition_decisions": {}}


def test_detection_from_a_recognised_monthly_report_is_the_checked_column_before_its_forecast_header():
    ds = recognised_dataset(MONTHLY, column=7, cue=("H2", "Forecast"))
    assert as_of.detect({"revenue": ds}) == {"month": "2025-06", "file": MONTHLY, "cue": "Forecast"}
    assert as_of.detect({"revenue": recognised_dataset(MONTHLY)}) is None, "July to December are marked Forecast, but no suggestion came"
    assert as_of.detect({"revenue": recognised_dataset(MONTHLY, column=7, cue=("B2", "Actual"))}) is None, "the cue cell holds no plan word"


def test_a_yearly_statement_ends_at_the_fiscal_year_end_and_a_snapshot_gives_nothing():
    text = b"Line,FY2022,FY2023,FY2024\nForecast,,,\nRevenue,100,120,\nCost of sales,50,55,60\nPayroll,20,22,24\nEBITDA,30,43,\n"
    yearly = recognised_dataset("statement.csv", dtype="pnl", content=text, column=3, cue=("r2", "Forecast"))
    assert as_of.detect({"pnl": yearly}, 6) == {"month": "2023-06", "file": "statement.csv", "cue": "Forecast"}
    assert as_of.detect({"revenue": recognised_dataset("arr_snapshot.csv", column=2, cue=("B1", "Forecast"))}) is None


@pytest.fixture()
def chat(monkeypatch):
    """The chat-upload client of conftest.api (the fixture name `api` is this file's set-up client, aud-1): the audit-chat audit with
    no as-of month and the fake adapter."""
    from fastapi.testclient import TestClient

    from app import usage as usage_mod
    from app.llm import gateway
    from test_chat_upload import AUDIT_DOC

    db = t.FakeDB()
    db["audits"].docs.append({**AUDIT_DOC, "usage": usage_mod.empty()})
    monkeypatch.setattr(server, "db", db)
    server._RECOGNITION_CACHE.clear()
    state = {"adapter": t.FakeAdapter(replies=[])}
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: state["adapter"])
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.state = db, state
    return client


def test_a_recognised_monthly_report_alone_sets_the_as_of_month_and_the_set_up_field_names_the_file(chat):
    """The chat-upload path: the report is stored with no months and no mapping; Map detects the month from its series."""
    assert chat.db["audits"].docs[0]["as_of_month"] is None
    chat.state["adapter"] = t.FakeAdapter(replies=[recognition_reply(last_actual_column=7, boundary_cue={"cell": "H2", "text": "Forecast"})])
    res = upload(chat, MONTHLY, (RECOGNITION / MONTHLY).read_bytes())
    assert res.status_code == 200, res.text
    got = chat.get(f"/api/audits/{AUDIT}").json()
    assert (got["as_of_month"], got["as_of_by"], got["as_of_file"], got["as_of_cue"]) == ("2025-06-30", "detected", MONTHLY, "Forecast")
    assert res.json()["recognition"]["last_actual"]["as_of"] == "2025-06", "the boundary is read from the month the file set"
    # the set-up field: auditForm.asOfSourceText reads as_of_by, as_of_file and as_of_cue: "(detected from <file>, cue: '<cue>')" (auditForm.test.js)
    js = (ROOT / "frontend/src/lib/auditForm.js").read_text()
    assert "(detected from ${audit.as_of_file}${audit.as_of_cue ? `, cue: '${audit.as_of_cue}'` : \"\"})" in js


def test_the_last_actual_column_is_read_from_the_as_of_month_and_the_plan_columns_start_the_month_after():
    m = stored_map(YEARLY)
    assert as_of.last_actual_column(m, 12, "2022-12")["header"] == "FY2022"
    assert as_of.last_actual_column(m, 6, "2022-06")["header"] == "FY2022"
    assert as_of.last_actual_column(m, 6, "2022-05")["header"] == "FY2021", "FY2022 ends June 2022: after May 2022 it is plan"
    plan = [c for c in as_of.statement_columns(m, 6) if c["end"] > "2023-06"]
    assert plan and plan[0]["end"] == "2024-06" and plan[0]["header"] == "FY2024"


# --- 1c. the statement feed applies the boundary (PR 196 review, finding 2) ----------------------------------------------------

SIX_YEARS = (b"Line,FY 2019,FY 2020,FY 2021,FY 2022,FY 2023,FY 2024\n"
             b"Revenue,500,600,700,800,900,1000\nCost of sales,200,220,240,260,280,300\nSales and marketing,100,110,120,130,140,150\n")


def test_the_statement_feed_picks_actual_columns_up_to_the_as_of_month_and_plan_columns_after_it_whatever_the_tag():
    m = sh.build(sh.read(sheet_of("six_years.csv", SIX_YEARS).grid, {}, 12))
    assert all(p["tag"] == "unknown" for p in m["periods"]), "no Actual or Forecast mark anywhere: the tag decides nothing"
    fed = sh.feed(m, 12, 1, {"file": "six_years.csv", "sheet": "CSV"}, "2021-12-31")
    assert [y["period"] for y in fed["yearly"]["actual"]] == ["FY 2019", "FY 2020", "FY 2021"]
    assert [y["period"] for y in fed["yearly"]["planned"]] == ["FY 2022", "FY 2023", "FY 2024"]
    assert [r["period"] for r in fed["yearly"]["reported"]] == ["FY 2019", "FY 2020", "FY 2021"]
    june = sh.feed(m, 6, 1, {}, "2021-12-31")
    assert [y["period"] for y in june["yearly"]["actual"]] == ["FY 2019", "FY 2020", "FY 2021"], "FY 2022 ends June 2022: plan"
    assert [y["period"] for y in sh.feed(m, 6, 1, {}, "2022-06-30")["yearly"]["actual"]][-1] == "FY 2022"
    tagged = stored_map(YEARLY)                   # FY2021-23 tagged actual, FY2024-26 forecast
    early = sh.feed(tagged, 12, 1, {}, "2022-12-31")["yearly"]
    assert [y["period"] for y in early["actual"]] == ["FY2021", "FY2022"], "an actual-tagged column after the as-of month is plan"
    assert [(y["period"], y["tag"]) for y in early["planned"]] == [("FY2023", "actual"), ("FY2024", "forecast"), ("FY2025", "forecast"),
                                                                   ("FY2026", "forecast")]
    assert sh.feed(m, 12, 1, {}, "2018-12-31")["yearly"] is None, "no column up to the as-of month: no yearly input"


def test_on_the_production_path_a_yearly_pnl_feeds_three_actual_and_three_plan_columns_from_the_as_of_month(chat, monkeypatch):
    """Run audit: the audit's stored as-of month (Dec 2021) reaches sheet.feed and the engine's yearly input."""
    chat.db["audits"].docs[0].update(as_of_month="2021-12-31", as_of_by="analyst")
    chat.state["adapter"] = t.FakeAdapter(replies=[mapping_reply()])
    assert upload(chat, "blank_vs_zero.csv").status_code == 200, "the revenue file of test_sheet_structure's compute tests"
    out = upload(chat, "six_years.csv", SIX_YEARS, dtype="pnl").json()
    assert out.get("sheet_map"), out
    seen = {}
    real = server.ge.compute_all

    def spy(*args, **kw):
        seen["yearly"] = kw.get("yearly")
        return real(*args, **kw)
    monkeypatch.setattr(server.ge, "compute_all", spy)
    results = chat.post(f"/api/audits/{AUDIT}/compute")
    assert results.status_code == 200, results.text
    assert [y["period"] for y in seen["yearly"]["actual"]] == ["FY 2019", "FY 2020", "FY 2021"]
    assert [y["period"] for y in seen["yearly"]["planned"]] == ["FY 2022", "FY 2023", "FY 2024"]
    assert [y["period"] for y in results.json()["yearly_basis"]["years"]] == ["FY 2019", "FY 2020", "FY 2021"]
    assert results.json()["as_of_month"] == "2021-12"


# --- stored once on the audit, typed override --------------------------------------------------------------------------------

def test_the_as_of_month_is_stored_once_detected_or_typed(api):  # noqa: F811
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


def test_a_changed_detected_month_marks_computed_results_stale(api):  # noqa: F811
    audit = api.db["audits"].docs[0]
    audit.update(as_of_by="detected", as_of_month="2024-02-29")
    api.db["datasets"].docs.append({"audit_id": "aud-1", **revenue_file([("2024-03-01", 10)])})
    asyncio.run(server._refresh_as_of("aud-1"))
    assert audit["as_of_month"] == "2024-03-31" and audit["setup_stale"] is True


def test_recognition_and_the_register_read_the_stored_field(api):  # noqa: F811
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


def test_every_reader_of_a_yearly_column_gets_the_same_end_month_rule():
    june = yearly_input()
    for a in june["actual"]:
        a["start"], a["end"] = f"{a['year'] - 1}-07", f"{a['year']}-06"
    results = payback_results(june)
    month = lambda y, m: y * 12 + m - 1  # noqa: E731  (the register's month index)
    year, why = cm.yearly_year(results, month(2023, 7), month(2024, 6))
    assert year["period"] == "FY2024" and why is None, "both end in June: matched"
    year, why = cm.yearly_year(results, month(2024, 1), month(2024, 12))
    assert year is None and why == "period not covered: the claim's period ends Dec 2024, the file's FY2024 ends Jun 2024"
    assert cm.yearly_year(results, month(2030, 1), month(2030, 12)) == (None, None), "no column of that year: not this reason"
