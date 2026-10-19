"""The engine reads a recognised file with no customer rows (docs/specs/revenue-file-recognition.md sections 8 and 9): its revenue
series, the basis it was read on, the reconciliation that does not compare the P&L with itself, the data-inventory lines of the
analyses the file cannot supply, and the closed-word block that no narrative slice carries (rule 14). Synthetic files only."""
import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import growth_engine as ge  # noqa: E402
import server  # noqa: E402
from app import column_rules as cr  # noqa: E402
from app import integrity  # noqa: E402
from app import recognition as rec  # noqa: E402
from app.llm import gateway  # noqa: E402
from schemas import metrics  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONFIG = {"reporting_currency": "EUR", "target_arr": 1_000_000, "target_date": "2027-12-31", "fx": {"EUR": 1.0}, "billing_terms": {},
          "default_l": 1, "as_of_month": None}


def recognised(name, folder="recognition", as_of="2025-12-31"):
    return rec.recognise(cr.read_workbook((FIXTURES / folder / name).read_bytes(), name), as_of_month=as_of, reporting_currency="EUR")


def pnl_frame(name="accountant_pnl.csv"):
    sheet = cr.read_workbook((FIXTURES / "mapping" / name).read_bytes(), name)[0]
    mapping = server.suggest_mapping("pnl", list(sheet.columns))
    rows = server.df_to_records(sheet.frame)
    return server.normalize(rows, "pnl", mapping, sheet.row_numbers, sheet.unit_scale), sheet


def run(feed, pnl=None, sources=None):
    return ge.compute_all(pd.DataFrame(), pd.DataFrame(), pnl if pnl is not None else pd.DataFrame(), {**CONFIG, "recognition": feed},
                          sources or {"revenue": {"file": "report.csv", "sheet": "CSV"}})


def test_a_monthly_report_supplies_the_revenue_series_with_its_basis_its_citation_and_the_name_of_its_growth_figure():
    result = recognised("monthly_report_actual_forecast.csv", as_of="2025-06-30")
    feed = rec.engine_feed(result, "report.csv", "CSV")
    out = run(feed)
    series = out["revenue_series"]
    assert [d["month"] for d in series["data"]] == ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"], "to the last actual"
    assert series["data"][0]["total"] == 10570 and (series["basis"], series["file_type"]) == ("row", "monthly_revenue_report")
    assert series["growth_label"] == "Revenue growth"
    assert series["source"]["file"] == "report.csv" and "row 4" in series["source"]["rows"] and series["source"]["rule"]
    assert out["recognition"] == {"file_type": "monthly_revenue_report", "series_basis": "row", "periods": 12, "excluded_columns": 6,
                                  "currency_confirmed": True, "source": "revenue_file"}
    assert out["contract_version"] == metrics.CONTRACT_VERSION


def test_an_mrr_row_names_its_growth_figure_mrr_growth_and_never_revenue_growth():
    result = rec.recognise(cr.read_workbook(b"Metric,Jan-25,Feb-25,Mar-25\nMRR (EUR),100,110,120\nCustomers,4,5,6\nChurn,1,2,3\nCash,5,6,7\n", "x.csv"),
                           as_of_month="2025-03-31")
    series = run(rec.engine_feed(result, "x.csv", "CSV"))["revenue_series"]
    assert series["growth_label"] == "MRR growth" and "MRR or ARR" in series["source"]["rule"]


def test_a_yearly_file_keeps_the_series_empty_and_the_inventory_names_the_monthly_series_it_lacks():
    """Yearly, half-yearly and quarterly columns are never split into months (chat-upload.md 26.6)."""
    out = run(rec.engine_feed(recognised("revenue_summary_by_product.csv"), "summary.csv", "CSV"))
    assert out["revenue_series"]["data"] == []
    lines = {(m["metric"], m["unlocked_by"]) for m in out["missing_data"]}
    assert ("Monthly series missing", rec.NEEDS_MONTHLY) in lines and ("Customer-level analysis (NRR, gross churn, concentration, cohorts)",
                                                                       rec.NEEDS_BY_CUSTOMER) in lines
    assert all(m["status"] == "Missing" for m in out["missing_data"])


def test_a_pnl_that_is_the_only_revenue_source_gets_not_applicable_never_a_reconciliation_of_itself():
    pnl, sheet = pnl_frame()
    result = rec.recognise([sheet], as_of_month="2024-11-30", reporting_currency="EUR")
    feed = rec.engine_feed(result, "pnl.csv", "CSV", sheet.unit_scale, from_pnl=True)
    out = run(feed, pnl, {"pnl": {"file": "pnl.csv", "sheet": "CSV"}})
    assert out["revenue_reconciliation"] == {"available": False, "status": "not_applicable", "reason": "Not applicable – same source", "by_month": []}
    assert out["recognition"]["source"] == "pnl" and out["revenue_series"]["data"], "the series is read from the P&L's revenue column"
    assessed = integrity.assess(out, deck_count=0, candidates=[])
    row = next(r for r in assessed["coverage"] if r["check"] == "Revenue reconciliation")
    assert (row["status"], row["reason"]) == ("Not applicable", "Not applicable – same source")


def test_a_report_beside_a_separate_pnl_is_reconciled_as_before_with_status_computed():
    months = [f"2025-{m:02d}-01" for m in range(1, 7)]
    text = "Month,S&M Expense,Revenue,Cost of Revenue\n" + "".join(
        f"{d},1000,{10570 + 11 * i},500\n" for i, d in enumerate(months))
    sheet = cr.read_workbook(text.encode(), "pnl.csv")[0]
    pnl = server.normalize(server.df_to_records(sheet.frame), "pnl", server.suggest_mapping("pnl", list(sheet.columns)), sheet.row_numbers)
    feed = rec.engine_feed(recognised("monthly_report_actual_forecast.csv", as_of="2025-06-30"), "report.csv", "CSV")
    out = run(feed, pnl, {"revenue": {"file": "report.csv", "sheet": "CSV"}, "pnl": {"file": "pnl.csv", "sheet": "CSV"}})
    recon = out["revenue_reconciliation"]
    assert recon["available"] is True and recon["status"] == "computed" and recon["blocker"] is False
    assert (recon["first"], recon["last"], recon["gap"]) == ("2025-01", "2025-06", 0)
    assert recon["source"]["revenue_file"]["file"] == "report.csv", "the file's side of the evidence cites the recognised file"
    row = next(r for r in integrity.assess(out, deck_count=0, candidates=[])["coverage"] if r["check"] == "Revenue reconciliation")
    assert row["status"] == "Completed" and row["result"] == "Green"


def test_no_narrative_slice_carries_the_recognition_block_or_the_basis_of_the_series():
    """Rule 14: the block is server-only; the words it holds reach no model."""
    out = run(rec.engine_feed(recognised("monthly_report_actual_forecast.csv", as_of="2025-06-30"), "report.csv", "CSV"))
    for step in gateway.STEP_CONFIG:
        text = json.dumps(gateway._slice_for_step(out, step), default=str)
        for word in ("series_basis", "currency_confirmed", "excluded_columns", "monthly_revenue_report"):
            assert word not in text, f"{word!r} reached the {step} slice"


def test_the_memo_lists_a_dated_list_that_does_not_match_the_revenue_row_under_worth_flagging():
    """Revenue-file-recognition.md section 6.7: the mismatch is a finding, never a banner blocker (CLAUDE.md rule 21)."""
    from test_ic_memo import inputs
    from claim_matching_support import engine_results
    from app import ic_memo
    sheets = cr.read_workbook((FIXTURES / "recognition" / "two_tables_side_mismatch.csv").read_bytes(), "two.csv")
    result = rec.recognise(sheets, as_of_month="2025-12-31", decisions={"series_source": "dated_list"})
    stored = {**engine_results(), "recognition": {"file_type": "monthly_revenue_report", "series_basis": "column", "periods": 6,
                                                  "excluded_columns": 0, "currency_confirmed": True, "source": "revenue_file",
                                                  "series_source": "dated_list", "cross_check": "mismatch", "cross_check_months": 6,
                                                  "cross_check_gaps": rec.engine_feed(result, "two.csv", "two.csv")["cross_check_gaps"]}}
    text = ic_memo.build_memo(**inputs(stored=stored))
    flagged = text.split("## Worth flagging")[1].split("## Data gaps")[0]
    assert "2 of 6 months differ between the dated list and the revenue row" in flagged and "the revenue series is read from the dated list" in flagged
    assert result["series_source"]["cross_check"]["status"] == "mismatch"
    matched = ic_memo.build_memo(**inputs(stored={**stored, "recognition": {**stored["recognition"], "cross_check": "match"}}))
    assert "months differ between the dated list" not in matched
