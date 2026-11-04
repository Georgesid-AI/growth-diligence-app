"""Presentation of the OPEX-split estimates (no engine value changes): the Data gaps wording, the plan cells cited as ranges per row, and the
total-row guard's note on the metric whose role triggered it only. Synthetic maps only."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from test_memo_cleanup_4f import YEARS  # noqa: E402
from test_part_rows_cost_roles import PLAN_YEARS, TOTAL_NOTE, part_rows, pnl, unlinked_total  # noqa: E402
from test_role_engine import file_of, metric, row, run, sheet  # noqa: E402

from app import ic_memo, role_engine, verdict  # noqa: E402

ESTIMATED = "Estimated (plan split applied to actual OPEX); actual split requested"
PLAN = {"sales_marketing": (1_000, 1_200, 1_400), "rnd": (600, 700, 800), "ga": (400, 500, 600), "opex": (2_000, 2_400, 2_800)}


def three_way_files():
    """Actual years carry OPEX only; the three plan years carry S&M, R&D, G&A (rows 10-12) and OPEX (row 13) in columns B-D."""
    rows = [row(4, "revenue", [1_000, 1_500, 2_400], YEARS, basis="yearly"), row(5, "opex", [800, 1_100, 1_900], YEARS, basis="yearly")]
    rows += [row(n, role, list(values), PLAN_YEARS, basis="yearly", actual_plan="plan", plan=True) for n, (role, values) in enumerate(PLAN.items(), start=10)]
    return [file_of("p", [sheet("P&L", rows, granularity="yearly")])]


# --- 1. Data gaps ---------------------------------------------------------------------------------------------------------------------------

def test_a_metric_with_an_estimate_reads_estimated_and_keeps_its_request():
    r = run(three_way_files())
    lines = {x["metric"]: x for x in role_engine.missing_reasons(r["role_metrics"])}
    for name in ("S&M expense", "R&D expense", "G&A expense"):
        assert lines[name]["reason"] == ESTIMATED, name
    gaps = {g["item"]: g for g in verdict.data_gaps(r, [], [], table=role_engine.build_table(three_way_files()))}
    for name in ("R&D expense", "G&A expense"):
        assert ESTIMATED in gaps[name]["why"] and "split only in plan years" not in gaps[name]["why"], gaps[name]["why"]
        assert gaps[name]["requested"].startswith("A P&L with"), "the Requested text stays"


def test_the_plan_years_wording_stays_where_there_is_no_estimate():
    r = run(three_way_files())
    share = metric(r, "yearly_cac_payback")
    assert share["status"] != "computed" and not share["estimate"]
    lines = {x["metric"]: x for x in role_engine.missing_reasons(r["role_metrics"])}
    assert lines["S&M share of revenue"]["reason"] != ESTIMATED


# --- 2. estimate citations as ranges per row -------------------------------------------------------------------------------------------------

def test_the_plan_cells_of_an_estimate_are_cited_as_one_range_per_row():
    r = run(three_way_files())
    expected = "D5, B10:D10, B11:D11, B12:D12, B13:D13"
    for name in ("sm_expense", "rnd_expense", "ga_expense"):
        m = metric(r, name)
        assert ic_memo._cells_text(m["source"]) == "p · P&L!" + expected, (name, ic_memo._cells_text(m["source"]))
        assert f"[{expected.split(', ', 1)[1]}]" in m["source"]["rule"], m["source"]["rule"]
        assert "[D5]" in m["source"]["rule"]


def test_the_trend_cites_the_plan_cells_of_an_estimate_as_ranges():
    r = run(three_way_files())
    trend = r["role_metrics"]["pnl_trend"]
    value = next(v for x in trend["rows"] if x["metric"] == "sm_share" for v in x["values"] if v["estimate"] and v["period"] == "2025")
    assert ic_memo._trend_cells(trend, value).endswith("B10:D10, B11:D11, B12:D12, B13:D13"), ic_memo._trend_cells(trend, value)


def test_the_two_way_estimate_cites_its_plan_cells_as_ranges():
    rows = [row(4, "revenue", [1_000, 1_500, 2_400], YEARS, basis="yearly"), row(5, "opex", [800, 1_100, 1_900], YEARS, basis="yearly"),
            row(6, "sales_marketing", [300, 400, 900], YEARS, basis="yearly")]
    rows += [row(n, role, list(PLAN[role]), PLAN_YEARS, basis="yearly", actual_plan="plan", plan=True) for n, role in enumerate(PLAN, start=10)]
    r = run([file_of("p", [sheet("P&L", rows, granularity="yearly")])])
    rnd = metric(r, "rnd_expense")
    assert rnd["estimate"] is True
    assert ic_memo._cells_text(rnd["source"]).endswith("B10:D10, B11:D11, B12:D12, B13:D13"), ic_memo._cells_text(rnd["source"])


# --- 3. the total-row note on the metric whose role triggered it ---------------------------------------------------------------------------------

def test_the_total_row_note_is_not_on_an_estimate_of_another_role():
    files = pnl([unlinked_total(), *part_rows()])
    r = run(files)
    assert TOTAL_NOTE in metric(r, "sm_share")["source"]["rule"], "the S&M metrics keep it"
    for name in ("rnd_expense", "ga_expense"):
        m = metric(r, name)
        assert m["estimate"] is True and TOTAL_NOTE not in m["source"]["rule"], m["source"]["rule"]


def test_the_notes_of_an_estimate_are_those_of_its_own_role_only():
    sm, rd = {"role": "sales_marketing", "note": "S&M note"}, {"role": "rnd", "note": "R&D note"}
    assert role_engine.notes_of_role("rnd", sm, rd, None, names={"sales_marketing": "S&M", "rnd": "R&D"}) == ["R&D: R&D note"]
    assert role_engine.notes_of_role("sales_marketing", sm, rd) == ["S&M note"]
