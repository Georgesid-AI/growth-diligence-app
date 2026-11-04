"""The Excel export carries the yearly P&L work: four sheets and the true reason for a CAC payback a yearly P&L cannot give.
Synthetic yearly P&L (test_plan_lines.pnl): revenue, cost of revenue, S&M and OPEX for 2023-25, a plan for 2026-27. No client data."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
pytest.importorskip("fastapi")
pytest.importorskip("motor")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from test_plan_lines import pnl, run  # noqa: E402

import server  # noqa: E402
from app import ic_memo, plan_lines  # noqa: E402

REASON = "needs a monthly P&L; the P&L supplied is yearly"


@pytest.fixture(scope="module")
def results():
    return run(pnl())


@pytest.fixture(scope="module")
def wb(results):
    return openpyxl.load_workbook(server.build_export_workbook({"company_name": "SynthCo"}, results))


def rows(ws):
    return [[c.value for c in r] for r in ws.iter_rows()]


def test_yearly_pnl_metrics_sheet_has_metric_year_value_cells_estimate_flag_and_method(wb):
    data = rows(wb["Yearly P&L metrics"])
    assert data[0] == ["Metric", "Year", "Value", "Cells", "Estimate", "Method"]
    by = {(r[0], r[1]): r for r in data[1:]}
    gm = next(r for r in data[1:] if r[0].startswith("Gross margin"))
    assert gm[1] == "2025" and gm[2] == pytest.approx(0.75) and gm[3] == "pnl · P&L!D4" and gm[4] == "no" and "cost of revenue" in gm[5]
    est = [r for r in data[1:] if r[4] == "yes"]
    assert {r[0] for r in est} == {r[0] for r in data[1:] if r[0].startswith(("R&D", "G&A"))} and len(est) == 2
    assert all(r[5].startswith("Estimate:") and "B12" in r[3] for r in est), "the method text and every cell of an estimate"
    ws = wb["Yearly P&L metrics"]
    assert ws.cell(row=data.index(gm) + 1, column=3).number_format == "0%"
    assert len(by) == len(data) - 1


def test_estimates_sheet_holds_the_estimates_only_in_the_same_columns(wb):
    data = rows(wb["Estimates"])
    assert data[0] == rows(wb["Yearly P&L metrics"])[0]
    assert len(data) == 3 and {r[4] for r in data[1:]} == {"yes"}


def test_yearly_pnl_trend_sheet_has_actual_years_then_plan_years(wb):
    data = rows(wb["Yearly P&L trend"])
    assert data[0] == ["Metric", "2023", "2024", "2025", "2026 (plan)", "2027 (plan)"]
    revenue = next(r for r in data if r[0] == "Revenue")
    assert revenue[1:] == [1000, 1500, 2400, 3000, 4000]
    assert wb["Yearly P&L trend"].cell(row=data.index(revenue) + 1, column=2).number_format == "#,##0"
    rnd = next(r for r in data if r[0].startswith("R&D share"))
    assert "Estimate – plan split applied to actual OPEX: 2023, 2024, 2025" in rnd[0], "an estimate keeps its label and its years"


def test_what_the_plan_assumes_sheet_has_the_line_text_and_cells(wb, results):
    data = rows(wb["What the plan assumes"])
    assert data[0] == ["Line", "Cells"]
    rising = next(r for r in data if r[0].startswith("Plan assumes revenue"))
    assert rising == ["Plan assumes revenue rises from 2,400 EUR (2025) to 4,000 EUR (2027).", "pnl · P&L!D4, C10"]
    assert [r[0] for r in data[1:]] == [i["text"] for i in plan_lines.lines(results, "EUR")]


def test_cac_by_quarter_and_missing_data_give_the_true_reason_when_a_yearly_pnl_was_read(wb):
    assert rows(wb["CAC by Quarter"])[1] == [f"({REASON})"]
    md = rows(wb["Missing Data"])
    cac = next(r for r in md[1:] if r[0] == "CAC payback")
    assert cac[md[0].index("reason")] == REASON
    assert not any("P&L not provided" in str(c) for r in rows(wb["CAC by Quarter"]) + md for c in r)


def test_no_yearly_pnl_keeps_p_and_l_not_provided_and_adds_no_sheet():
    import pandas as pd
    import growth_engine as ge
    bare = ge.compute_all(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {"reporting_currency": "EUR", "target_arr": 1_000_000,
                                                                          "target_date": "2027-12-31", "fx": {"EUR": 1.0}, "as_of_month": "2026-06"}, {})
    book = openpyxl.load_workbook(server.build_export_workbook({"company_name": "SynthCo"}, bare))
    assert rows(book["CAC by Quarter"])[1] == ["(P&L not provided)"]
    assert not {"Yearly P&L metrics", "Estimates", "Yearly P&L trend", "What the plan assumes"} & set(book.sheetnames)


def test_the_memo_appendix_does_not_repeat_the_four_sheets(results):
    tables = ic_memo.workbook_tables(server.build_export_workbook({"company_name": "SynthCo"}, results))
    assert not {"Yearly P&L metrics", "Estimates", "Yearly P&L trend", "What the plan assumes"} & {t["sheet"] for t in tables}
    kept = ic_memo.memo_tables([{"sheet": "CAC by Quarter", "rows": [["Quarter"], [f"({REASON})"]]}])
    assert kept == []
