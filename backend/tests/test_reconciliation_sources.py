"""Reconciliation sources and parts-sum sign (commit 1 of the reconciliation and reading-consistency PR).

A source for the reconciliation is a file's sheet or a deck page, never a row. Within one sheet the metric's value is the total row; part rows
and a second row of the same role are never separate sources. Reconciliation runs on yearly revenue only. Two rows of one role with no parent
link give one mapping flag. The percentage difference is the difference over the largest value. Synthetic maps only; no client data."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import checks  # noqa: E402
from test_checks import build, fmap, item, check, row as check_row, sheet_map  # noqa: E402
from test_role_engine import file_of, row, run, sheet  # noqa: E402

M25 = [f"2025-{m:02d}" for m in range(1, 13)]
FLAG = "two rows mapped as customers (rows 23, 24); the calculation uses row 23"


def tc_shape():
    """The Tc shape: an ARR total with four segment rows, and two customers rows with no parent link, on one monthly sheet."""
    arr = [1_000 + 10 * i for i in range(12)]
    parts = [row(n, "arr", [v / 4 for v in arr], M25, segment=f"Segment {n}") for n in (11, 12, 13, 14)]
    for p in parts:
        p["parent_row"] = 10
    unlabelled = [row(n, "arr", [v / 4 for v in arr], M25) for n in (15, 16)]       # a part with a parent link and no segment label
    for p in unlabelled:
        p["parent_row"] = 10
    return [file_of("tc", [sheet("Tc", [row(10, "arr", arr, M25), *parts, *unlabelled,
                                         row(23, "customers", [50 + i for i in range(12)], M25, unit="count"),
                                         row(24, "customers", [60 + i for i in range(12)], M25, unit="count")])])]


def test_the_tc_shape_gives_no_reconciliation_line_and_one_mapping_flag():
    rm = run(tc_shape(), as_of="2025-12")["role_metrics"]
    assert rm["reconciliation"] == []
    assert [f["text"] for f in rm["mapping_flags"]] == [FLAG]
    assert rm["mapping_flags"][0]["role"] == "customers" and rm["mapping_flags"][0]["rows"] == [23, 24] and rm["mapping_flags"][0]["used_row"] == 23


def test_only_yearly_revenue_is_reconciled_arr_and_customers_in_two_files_are_not():
    two = [file_of("a", [sheet("S", [row(4, "arr", [1_000] * 12, M25), row(5, "customers", [50] * 12, M25, unit="count")])]),
           file_of("b", [sheet("S", [row(4, "arr", [900] * 12, M25), row(5, "customers", [40] * 12, M25, unit="count")])])]
    assert run(two, as_of="2025-12")["role_metrics"]["reconciliation"] == []
    deck = [{"metric": "customers", "period": "2025", "value": 70.0, "currency": None, "actual_plan": "actual", "file": "deck", "page": 3}]
    assert run(two, as_of="2025-12", deck=deck)["role_metrics"]["reconciliation"] == []


def yearly(name, rows):
    return file_of(name, [sheet("P&L", rows, granularity="yearly")])


def test_yearly_revenue_across_the_pnl_a_revenue_file_and_a_deck_still_reconciles():
    monthly = file_of("report", [sheet("Report", [row(4, "revenue", [100] * 12, M25)])])
    pnl = yearly("pnl", [row(4, "revenue", [1_150], ["2025"], basis="yearly")])
    deck = [{"metric": "revenue", "period": "2025", "value": 1_200.0, "currency": "EUR", "actual_plan": "actual", "file": "deck", "page": 4,
             "label": "Total revenue FY2025"}]
    rec = [x for x in run([monthly, pnl], as_of="2025-12", deck=deck)["role_metrics"]["reconciliation"] if x["period"] == "2025"]
    assert len(rec) == 1 and {s["kind"] for s in rec[0]["sources"]} == {"file", "deck"} and len(rec[0]["sources"]) == 3
    assert rec[0]["status"] == "differs" and rec[0]["gap"] == 50


def test_part_rows_and_a_second_row_of_the_same_role_are_not_separate_sources():
    parts = [row(5, "revenue", [700], ["2025"], basis="yearly"), row(6, "revenue", [450], ["2025"], basis="yearly")]
    for p in parts:
        p["parent_row"] = 4
    other = file_of("other", [sheet("P&L", [row(4, "revenue", [1_150], ["2025"], basis="yearly")], granularity="yearly")])
    pnl = yearly("pnl", [row(4, "revenue", [1_150], ["2025"], basis="yearly"), *parts])
    rec = run([pnl, other], as_of="2025-12")["role_metrics"]["reconciliation"]
    assert len(rec) == 1 and len(rec[0]["sources"]) == 2 and rec[0]["status"] == "agrees"
    assert {s["where"] for s in rec[0]["sources"]} == {"P&L!B4"}  # both files cite their total row, never a part row
    twice = yearly("twice", [row(4, "revenue", [1_150], ["2025"], basis="yearly"), row(7, "revenue", [999], ["2025"], basis="yearly")])
    r = run([twice, other], as_of="2025-12")
    rec = r["role_metrics"]["reconciliation"]
    assert len(rec) == 1 and len(rec[0]["sources"]) == 2 and rec[0]["status"] == "agrees", "one source per sheet: the second row is no source"
    assert [f["text"] for f in r["role_metrics"]["mapping_flags"]] == ["two rows mapped as revenue (rows 4, 7); the calculation uses row 4"]


@pytest.mark.parametrize("values,gap,pct", [([100.0, 150.0], 50.0, 50 / 150), ([0.0, 100.0], 100.0, 1.0), ([0.0, 0.0], 0.0, None)])
def test_the_percentage_difference_is_over_the_largest_value(values, gap, pct):
    a = yearly("a", [row(4, "revenue", [values[0]], ["2025"], basis="yearly")])
    b = file_of("b", [sheet("P&L", [row(4, "revenue", [values[1]], ["2025"], basis="yearly")], granularity="yearly")])
    rec = run([a, b], as_of="2025-12")["role_metrics"]["reconciliation"][0]
    assert rec["gap"] == gap and (rec["gap_pct"] == pytest.approx(pct) if pct is not None else rec["gap_pct"] is None)


def test_the_legacy_revenue_reconciliation_divides_by_the_largest_value_too():
    import growth_engine as ge
    assert ge.gap_fraction(-50.0, 100.0, 150.0) == pytest.approx(-50 / 150)
    assert ge.gap_fraction(100.0, 0.0, 100.0) == pytest.approx(1.0)
    assert ge.gap_fraction(0.0, 0.0, 0.0) is None


def test_a_total_with_the_opposite_sign_to_its_parts_is_not_a_disagreement():
    rows = [check_row(row=8, label_cell="A8", role="revenue", cells="B8:M8"),
            check_row(row=9, label_cell="A9", segment="Product A", parent_row=8, cells="B9:M9"),
            check_row(row=10, label_cell="A10", segment="Product B", parent_row=8, cells="B10:M10")]
    negative_total = {(8, 2 + i): "-200" for i in range(12)}
    assert item(check(fmap(sheet_map(rows=rows)), build(negative_total)), "parts:Report:8")["outcome"] == checks.CONFIRMED
    negative_parts = {(r, 2 + i): v for r, v in ((9, "-120"), (10, "-80")) for i in range(12)}
    assert item(check(fmap(sheet_map(rows=rows)), build(negative_parts)), "parts:Report:8")["outcome"] == checks.CONFIRMED
    (wrong,) = check(fmap(sheet_map(rows=rows)), build({(8, 4): "-260"}))["totals"]
    assert wrong["cell"] == "D8" and wrong["total"] == 260.0 and wrong["parts_sum"] == 200.0, "a real difference of size is a total finding"


def test_the_mapping_flag_is_a_worth_flagging_line_of_the_memo():
    from app import ic_memo
    results = run(tc_shape(), as_of="2025-12")
    lines = ic_memo.role_flags(results, None, "EUR", ic_memo.Notes())
    assert len([x for x in lines if x.startswith(FLAG[:1].upper() + FLAG[1:])]) == 1
