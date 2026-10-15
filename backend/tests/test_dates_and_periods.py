"""Dates and periods (docs/specs/dates-and-periods.md; plan of 15 Oct 2026, section 3 and 7.1).

Four dates kept apart: the requested analysis date (the analyst's, dates the memo), the latest valid source period (read from
the revenue file), the period and gaps of every metric, and each claim's period coverage. The regression of plan section 3 is
built from a synthetic revenue file made here (no client data). Python only, no network, no model.
"""
import copy
import csv
import io
import re
from functools import lru_cache

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import growth_engine as ge  # noqa: E402
import server  # noqa: E402
from claim_matching_support import SAMPLE, FILES  # noqa: E402
from test_claim_matching import run_claim  # noqa: E402
from test_claim_register_api import AUDIT, _get, _put, api  # noqa: E402,F401  (the fixture)
from test_ic_memo import USAGE, _ready  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import decks  # noqa: E402
from app import ic_memo as im  # noqa: E402
from app import verdict as vd  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402

MACHINE_DATE = "2026-10-15"          # the regression's machine date, October 2026
CUSTOMERS = (("C-01", "Enterprise", 9000.0), ("C-02", "Enterprise", 7000.0), ("C-03", "Mid-Market", 3000.0),
             ("C-04", "Mid-Market", 2500.0), ("C-05", "SMB", 800.0))


def _months(first: str, last: str):
    y, m = map(int, first.split("-"))
    while f"{y}-{m:02d}" <= last:
        yield f"{y}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def synthetic_revenue(first="2017-07", last="2019-06", skip=()) -> bytes:
    """Monthly recurring invoices for five synthetic customers, growing 1% a month."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Customer", "Invoice Date", "Amount", "Currency", "Segment", "Revenue Type"])
    for k, month in enumerate(_months(first, last)):
        if month in skip:
            continue
        for customer, segment, base in CUSTOMERS:
            w.writerow([customer, f"{month}-01", round(base * 1.01 ** k, 2), "EUR", segment, "recurring"])
    return out.getvalue().encode("utf-8")


def _upload(dtype, name, content):
    df, sheet = server.parse_file(content, name)
    return {"file": name, "sheet": sheet, "columns": list(df.columns), "rows": server.df_to_records(df),
            "mapping": server.suggest_mapping(dtype, list(df.columns))}


def run_engine(uploads: dict, as_of_month=None, last_month_complete=False) -> dict:
    norm = {d: server.normalize(u["rows"], d, u["mapping"]) for d, u in uploads.items()}
    empty = server.pd.DataFrame()
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None, "fx": {"EUR": 1.0}, "billing_terms": {},
              "default_l": 1, "as_of_month": as_of_month, "last_month_complete": last_month_complete}
    sources = {d: {"file": u["file"], "sheet": u["sheet"]} for d, u in uploads.items()}
    return server.sanitize(ge.compute_all(norm["revenue"], norm.get("crm", empty), norm.get("pnl", empty), config, sources,
                                          files=server.candidate_views(uploads)))


def synthetic_run(as_of_month="2026-06-30", last_month_complete=False, **kw) -> dict:
    return run_engine({"revenue": _upload("revenue", "revenue.csv", synthetic_revenue(**kw))}, as_of_month, last_month_complete)


@lru_cache(maxsize=None)
def _testco(last_month_complete: bool) -> str:
    uploads = {d: _upload(d, FILES[d], (SAMPLE / FILES[d]).read_bytes()) for d in ("revenue", "pnl", "crm")}
    import json
    return json.dumps(run_engine(uploads, None, last_month_complete))


def sample_run(last_month_complete=False) -> dict:
    """TestCo of sample_data/: as-of 2024-02 defaulted from the last P&L month, revenue to 2024-02."""
    import json
    return json.loads(_testco(last_month_complete))


def _claim(**fields) -> dict:
    c = {"id": "r1", "status": "approved", "claim_type": "revenue", "value_high": None, "unit": None, "currency": "EUR",
         "label_from": None, "file": "synthco_deck.pdf", "order": 0, "sources": [{"file": "synthco_deck.pdf", "page": 3}], **fields}
    deck_claims.resolve_period(c, 12)
    return c


# --- plan section 3: the regression (required in Release 1) -----------------------------------------------------------------

REGRESSION = [pytest.param({"as_of_month": "2026-06-30", "last_month_complete": False}, "as_of", id="as-of-2026-06-set"),
              pytest.param({"as_of_month": None, "last_month_complete": True}, "analyst", id="as-of-defaulted-last-month-ticked")]


@pytest.mark.parametrize("setting, complete_by", REGRESSION)
def test_plan_3_regression_revenue_to_june_2019_on_an_october_2026_machine_is_labelled_june_2019_everywhere(setting, complete_by):
    results = synthetic_run(**setting)
    assert results["source_period"] == {"month": "2019-06", "status": "Complete", "complete_by": complete_by,
                                        "evidence_to": "2019-06"}
    assert results["arr"]["month"] == "2019-06"
    periods = results["metric_periods"]
    assert periods and all(p["last"] == "2019-06" for p in periods.values()), periods

    # the memo: built on the frozen machine date with no requested analysis date, so its date is that day
    arr = results["arr"]["value"]
    audit = {"company_name": "SynthCo", "target_arr": 0, "target_date": None, "as_of_month": setting["as_of_month"],
             "analysis_date": None, "last_month_complete": setting["last_month_complete"]}
    sets = {"fiscal_year_end": 12, "as_of_month": setting["as_of_month"], "reporting_currency": "EUR", "fx": {"EUR": 1.0}}
    rows = cm.build_register([_claim(value=round(arr), target_date="2019-06", period_text="Jun 2019",
                                     snippet=f"ARR of EUR {round(arr):,} in June 2019")], results, sets)
    assert all("2026" not in (r["observed_at"] or "") for r in rows)
    top = vd.proposal(rows)
    ic = {"ratings": {"data_reliability": "Adequate", "growth_engine": "Adequate"}, "first_quarterly_review": "2027-01-13",
          "thesis": {"plan": "Grow with the current customer mix.", "evidence": "ARR is as claimed.", "condition": "None."},
          "judgment": {"reasons": "The selected claim agrees with the revenue file.", "unresolved_questions": "None."}}
    tables = im.workbook_tables(server.build_export_workbook({**audit, "results": results}, results))
    text = im.build_memo(audit=audit, results=results, rows=rows, ver=vd.verdict(rows, results, {"claim_ids": top}),
                         key=vd.key_gates(rows), gaps=vd.data_gaps(results, rows, top), ic=ic, blockers=[], narratives=[],
                         usage=copy.deepcopy(USAGE), files=[{"dtype": "revenue", "file": "revenue.csv", "sheet": "CSV"}],
                         decks=[{"file": "synthco_deck.pdf"}], tables=tables, today=MACHINE_DATE)
    lines = text.split("\n")
    assert lines[1] == f"Date: {MACHINE_DATE}" and lines[2] == "Evidence to June 2019"
    assert set(re.findall(r"2026[-\d]*", text)) == {MACHINE_DATE}, \
        "2026 appears only as the requested analysis date, which is the memo date"


def test_the_latest_valid_source_period_is_possibly_partial_until_the_as_of_month_is_later_or_the_box_is_ticked():
    partial = sample_run()
    assert partial["source_period"] == {"month": "2024-02", "status": "Possibly partial", "complete_by": None,
                                        "evidence_to": "2024-02"}
    assert partial["arr"]["month"] == "2024-02", "shown: ARR still reads the last month"
    assert partial["mrr_series"]["months"][-1] == "2024-02", "shown: the series keep it"
    assert [d["month"] for d in partial["nrr"]["series"]][-1] == "2024-01", "not used: NRR ends the month before"
    assert [d["month"] for d in partial["gross_churn"]["series"]][-1] == "2024-01", "not used: gross churn ends the month before"
    assert partial["gross_churn"]["month"] == "2024-01" and partial["metric_periods"]["gross_churn"]["last"] == "2024-01"
    complete = sample_run(last_month_complete=True)
    assert complete["source_period"]["status"] == "Complete" and complete["source_period"]["complete_by"] == "analyst"
    assert [d["month"] for d in complete["nrr"]["series"]][-1] == "2024-02"
    assert [d["month"] for d in complete["gross_churn"]["series"]][-1] == "2024-02"


def test_metric_periods_list_the_missing_months_not_a_count():
    results = synthetic_run(skip=("2018-03", "2018-04"))
    entry = results["metric_periods"]["revenue_series"]
    assert entry == {"first": "2017-07", "last": "2019-06", "missing": ["2018-03", "2018-04"]}


# --- section 4: claim-period coverage -------------------------------------------------------------------------------------------

def test_a_claim_period_partly_covered_is_inconclusive_with_the_figure_over_the_months_present():
    # Run C (March year-end): revenue for FY2023 = Apr 2022 to Mar 2023; the revenue file starts 2023-01
    row = run_claim({"value": 190000, "target_date": "2023", "period_text": "FY2023", "snippet": "Revenue €190,000 in FY2023"}, run="C")
    assert row["evidence_label"] == "Inconclusive"
    assert row["period_coverage"] == "Partly covered"
    assert row["months_missing"] == [f"2022-{m:02d}" for m in range(4, 13)]
    assert row["reason"] == "claim period partly covered (months missing: 2022-04 to 2022-12)"
    assert row["observed_at"] == "2023-01 to 2023-03 (3 of 12 months)" and row["observed_value"] > 0
    assert row["gap"] is None


def test_a_claim_period_before_the_data_is_not_covered_and_unverified():
    row = run_claim({"claim_type": "customers", "value": 8, "unit": None, "currency": None, "target_date": "2022",
                     "period_text": "Y/E 22", "snippet": "8 customers at Y/E 22"})
    assert (row["evidence_label"], row["period_coverage"]) == ("Unverified", "Not covered")
    assert row["reason"] == "claim period not in supplied data: before Customer count's first month, 2023-01"


def test_an_nrr_claim_for_a_possibly_partial_month_is_not_covered():
    results = sample_run()
    sets = {"fiscal_year_end": 12, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}}
    row = cm.build_register([_claim(claim_type="retention", value=112, unit="%", currency=None, target_date="2024-02",
                                    period_text="Feb 2024", snippet="NRR 112% in Feb 2024")], results, sets)[0]
    assert (row["evidence_label"], row["period_coverage"]) == ("Unverified", "Not covered")
    assert row["reason"] == "claim period not in supplied data: 2024-02 is possibly partial (tick 'Last month is complete' to use it)"


def test_a_gross_churn_claim_for_a_possibly_partial_month_is_not_covered():
    results = sample_run()
    sets = {"fiscal_year_end": 12, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}}
    row = cm.build_register([_claim(claim_type="retention", value=8, unit="%", currency=None, target_date="2024-02",
                                    period_text="Feb 2024", snippet="Gross revenue churn 8% in Feb 2024")], results, sets)[0]
    assert (row["metric"], row["evidence_label"], row["period_coverage"]) == ("Gross revenue churn", "Unverified", "Not covered")
    assert row["reason"] == "claim period not in supplied data: 2024-02 is possibly partial (tick 'Last month is complete' to use it)"


def test_a_claim_between_the_evidence_end_and_the_as_of_month_is_not_covered_and_never_a_forecast():
    results = synthetic_run()
    sets = {"fiscal_year_end": 12, "as_of_month": "2026-06-30", "reporting_currency": "EUR", "fx": {"EUR": 1.0}}
    row = cm.build_register([_claim(value=300000, target_date="2023-12", period_text="Dec 2023",
                                    snippet="ARR of EUR 300,000 in Dec 2023")], results, sets)[0]
    assert row["evidence_label"] == "Unverified" and row["gap_kind"] != "to go"
    assert row["reason"] == "claim period not in supplied data: after the latest valid source period, 2019-06"


# --- section 5 and plan 7.1: growth claims ---------------------------------------------------------------------------------------

def _yoy(results, month, base):
    totals = {d["month"]: d["total"] for d in results["revenue_series"]["data"]}
    return round((totals[month] / totals[base] - 1) * 100, 2)


def test_plan_7_1_growth_with_no_cue_is_unverified_with_set_growth_basis():
    row = run_claim({"claim_type": "revenue_growth", "value": 15, "unit": "%", "currency": None, "target_date": "2024-01",
                     "period_text": "Jan 2024", "snippet": "Revenue grew 15% in Jan 2024"})
    assert row["growth_basis"] == "unknown"
    assert row["evidence_label"] == "Unverified"
    assert row["reason"] == "growth basis unknown: set the growth basis"
    assert row["observed_value"] is None, "no basis, no figure"


def test_plan_7_1_growth_with_a_yoy_cue_is_matched_on_the_year_on_year_basis_only():
    from test_claim_matching import RUNS, results_for
    results = results_for(RUNS["A"])
    row = run_claim({"claim_type": "revenue_growth", "value": 15, "unit": "%", "currency": None, "target_date": "2024-01",
                     "period_text": "Jan 2024", "snippet": "Revenue grew 15% YoY in Jan 2024"})
    assert (row["growth_basis"], row["metric"]) == ("yoy", "Revenue growth")
    assert row["observed_value"] == _yoy(results, "2024-01", "2023-01")
    assert row["observed_at"] == "2024-01 vs 2023-01"
    assert row["gap"] == round(15 - row["observed_value"], 6), "tested in percentage points against the YoY figure"
    assert row["evidence_label"] in ("Verified", "Contradicted") or row["definition_check"] == "ask"


@pytest.mark.parametrize("line, basis", [
    ("Revenue grew 15% YoY in Jan 2024", "yoy"), ("Revenue grew 15% in Jan 2024", "unknown"),
    ("Revenues stand at €15K MRR and are growing 15% MoM", "mom"), ("55,000 users, growing 40% per month", "mom"),
    ("Annual recurring revenue grew 120% in 2023", "unknown"), ("Revenue CAGR of 40% since 2020", "unknown"),
    ("Revenue grew 300% over the last 3 years", "cumulative"), ("Revenue grew over 15% in 2023", "unknown"),
])
def test_the_parser_sets_the_growth_basis_from_cue_words(line, basis):
    found = deck_claims.detect_candidates([{"slide": 4, "kind": "text", "text": line, "box": 1}], "deck.pptx")
    growth = [c for c in found if c["claim_type"] in ("revenue_growth", "growth", "user_growth")]
    assert growth and {c["growth_basis"] for c in growth} == {basis}


def test_set_growth_basis_is_one_click_and_the_claim_is_then_matched(api):  # noqa: F811
    client, db = api
    db[decks.CANDIDATES_COLLECTION].docs.append({**_claim(id="g1", claim_type="revenue_growth", value=15, unit="%", currency=None,
                                                          target_date="2024-01", period_text="Jan 2024",
                                                          snippet="Revenue grew 15% in Jan 2024", file="testco_board.pptx"),
                                                 "audit_id": AUDIT, "order": 98})
    row = next(r for r in _get(client)["register"] if r["claim_id"] == "g1")
    assert row["reason"] == "growth basis unknown: set the growth basis"
    r = _put(client, "g1", {"growth_basis": "yoy"})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["register"] if x["claim_id"] == "g1")
    assert (row["growth_basis"], row["metric"]) == ("yoy", "Revenue growth") and row["observed_value"] is not None


# --- section 2 and 6: the requested analysis date ---------------------------------------------------------------------------------

def test_the_requested_analysis_date_changes_the_memo_date_and_nothing_else(api):  # noqa: F811
    client, db = api
    assert "analysis_date" not in server.RECOMPUTE_TRIGGER_FIELDS and "last_month_complete" in server.RECOMPUTE_TRIGGER_FIELDS
    _ready(client)
    before = copy.deepcopy(db["audits"].docs[0]["results"])
    register = _get(client)["register"]
    r = client.put(f"/api/audits/{AUDIT}", json={"analysis_date": "2026-11-02"})
    assert r.status_code == 200, r.text
    assert r.json()["analysis_date"] == "2026-11-02"
    assert db["audits"].docs[0]["results"] == before and not db["audits"].docs[0].get("metrics_stale")
    assert _get(client)["register"] == register, "no period label, figure or row changes"
    memo = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert memo.status_code == 200, memo.text
    assert memo.text.split("\n")[1] == "Date: 2026-11-02"
    assert "2026-11-02" not in memo.text.split("## Appendix A")[0].split("\n", 2)[2].replace("as of 2026-11-02", ""), \
        "never printed next to a value"
