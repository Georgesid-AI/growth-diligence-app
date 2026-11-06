"""Board-pack dating (synthetic sheet only, CLAUDE.md rules 13 and 15). The real layout: the months of 2023 are text headers with no year
("January" .. "December") with a Qn 2023 subtotal after every third month and TOTAL 2023 at the block end; TOTAL 2024 comes before the months of
2024, which are date cells. A year-less month takes its year from the year-total or quarter header that closes its block, or from a year title above
the block; periods increase left to right; a month that would go backwards is "undated" and left out of every series."""
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import role_engine, series  # noqa: E402
from test_column_classes import col, sheet_of  # noqa: E402
from test_role_engine import metric, run  # noqa: E402

NAMES = "January February March April May June July August September October November December".split()


def layout(total_2024=None, title=False):
    """(grid, header kinds, month revenue, year totals, last column). Row 3 is the header; revenue is row 4, ARR row 5."""
    grid = {(3, 1): "Metric", (4, 1): "Revenue", (5, 1): "ARR"}
    c, kinds, rev = 2, {}, {}
    if title:
        grid[(2, c)] = "2023"
    for q in range(1, 5):
        for k in range(3):
            m = 3 * (q - 1) + k + 1
            grid[(3, c)] = NAMES[m - 1]
            kinds[c] = ("month", f"2023-{m:02d}")
            rev[f"2023-{m:02d}"] = 100.0 + 3 * len(rev)
            c += 1
        grid[(3, c)] = f"Q{q} 2023"
        kinds[c] = ("quarter", f"2023-Q{q}")
        c += 1
    grid[(3, c)] = "TOTAL 2023"
    kinds[c] = ("year", "2023")
    c += 1
    grid[(3, c)] = "TOTAL 2024"
    kinds[c] = ("year", "2024")
    c += 1
    for m in range(1, 12):
        grid[(3, c)] = date(2024, m, monthrange(2024, m)[1])
        kinds[c] = ("month", f"2024-{m:02d}")
        rev[f"2024-{m:02d}"] = 100.0 + 3 * len(rev)
        c += 1
    totals = {2023: sum(v for p, v in rev.items() if p.startswith("2023")), 2024: sum(v for p, v in rev.items() if p.startswith("2024"))}
    if total_2024 is not None:
        totals[2024] = total_2024
    for cc, kind in kinds.items():
        if kind[0] == "month":
            value = rev[kind[1]]
        elif kind[0] == "quarter":
            value = sum(v for p, v in rev.items() if p.startswith("2023") and (int(p[5:]) - 1) // 3 + 1 == int(kind[1][-1]))
        else:
            value = totals[int(kind[1])]
        grid[(4, cc)] = str(value)
        grid[(5, cc)] = str(value * 12 if kind[0] == "month" else value)
    return grid, kinds, rev, totals, c - 1


def smap(last, rows=(4, 5)):
    def r(n, role):
        return {"row": n, "label_cell": f"A{n}", "role": role, "metric": role, "basis": "monthly", "actual_plan": "actual", "boundary_col": None,
                "segment": None, "parent_row": None, "unit": "money", "currency": "EUR", "cells": f"B{n}:{col(last)}{n}", "variance_of": None,
                "by_column": False, "evidence": "x"}
    return {"sheet": "Report", "header_row": 3, "label_col": "A", "first_period_col": "B", "last_period_col": col(last), "granularity": "monthly",
            "last_actual": None, "rows": [r(4, "revenue"), r(5, "arr")]}


def built(**kw):
    grid, kinds, rev, totals, last = layout(**kw)
    text, _ = sheet_of(grid)
    fmap = series.attach({"map_version": 1, "kind": "sheet", "figures": [], "sheets": [smap(last)]}, text)
    return fmap, kinds, rev, totals


def files(fmap):
    return [{"file": "board", "file_map": fmap, "rejected": [], "cannot": []}]


def test_a_year_less_month_takes_the_year_of_the_block_it_closes_with():
    fmap, kinds, rev, _ = built()
    got = fmap["sheets"][0]["rows"][0]["series"]
    assert got["periods"] == sorted(rev), "12 months of 2023 (dated by Q4 2023 / TOTAL 2023) then 11 months of 2024"
    assert got["values"] == [rev[p] for p in got["periods"]]
    assert "B4" in got["refs"] and got["periods"][0] == "2023-01"


def test_a_year_title_above_the_block_dates_its_months():
    fmap, _, rev, _ = built(title=True)
    assert fmap["sheets"][0]["rows"][0]["series"]["periods"] == sorted(rev)


def test_the_year_never_comes_from_a_date_header_elsewhere():
    """Without the closing header of its block, a text month beside the 2024 dates is not dated 2024."""
    grid, kinds, rev, totals, last = layout()
    for c, k in kinds.items():
        if k[0] in ("quarter", "year"):
            grid[(3, c)] = None          # the closing headers are gone: nothing states the year of the 2023 months
    grid = {k: v for k, v in grid.items() if v is not None}
    text, _ = sheet_of(grid)
    fmap = series.attach({"map_version": 1, "kind": "sheet", "figures": [], "sheets": [smap(last)]}, text)
    got = fmap["sheets"][0]["rows"][0]["series"]
    assert got["periods"] == [f"2024-{m:02d}" for m in range(1, 12)], "only the date-typed 2024 months; no 2023 month is dated 2024"
    assert len(fmap["sheets"][0]["undated"]) == 12, "the twelve year-less months are named, not guessed"


def test_a_month_that_goes_backwards_is_undated_and_left_out():
    grid, kinds, rev, totals, last = layout()
    c = next(c for c, k in kinds.items() if k == ("month", "2023-06"))
    grid[(3, c)] = "February"                    # goes back from May to February inside the 2023 block
    text, _ = sheet_of(grid)
    fmap = series.attach({"map_version": 1, "kind": "sheet", "figures": [], "sheets": [smap(last)]}, text)
    sheet_map = fmap["sheets"][0]
    got = sheet_map["rows"][0]["series"]
    assert got["periods"] == sorted(got["periods"]) and "2023-06" not in got["periods"] and len(set(got["periods"])) == len(got["periods"])
    assert [u["cell"] for u in sheet_map["undated"]] == [f"{col(c)}3"] and sheet_map["undated"][0]["text"] == "February"
    flags = role_engine.undated_flags(files(fmap))
    assert flags and "undated" in flags[0]["text"] and f"{col(c)}3" in flags[0]["text"]


def test_the_board_pack_months_and_totals_give_the_as_of_figures():
    fmap, kinds, rev, totals = built()
    r = run(files(fmap), as_of="2024-11")
    assert r["as_of_month"] == "2024-11"
    nov_col = next(c for c, k in kinds.items() if k == ("month", "2024-11"))
    arr = metric(r, "ending_arr")
    assert arr["value"] == pytest.approx(rev["2024-11"] * 12) and arr["period"] == "2024-11"
    assert f"{col(nov_col)}5" in arr["source"]["cells"]
    mom = metric(r, "growth", "month on month")
    assert mom["value"] == pytest.approx(rev["2024-11"] / rev["2024-10"] - 1)
    growth = {g["period"]: g for g in r["role_metrics"]["growth_by_year"]}
    assert growth["2024"]["value"] == totals[2024] and growth["2024"]["growth"] == pytest.approx(totals[2024] / totals[2023] - 1)
    total_col = next(c for c, k in kinds.items() if k == ("year", "2024"))
    assert f"{col(total_col)}4" in growth["2024"]["source"]["cells"]
    assert not [f for f in r["role_metrics"]["mapping_flags"] if "rows 4, 4" in f["text"]]


def test_mapping_flags_name_each_row_once_across_the_reads():
    """The same row twice in the table (first read, second read, the code fallback, its yearly and quarterly records) is one row."""
    fmap, *_ = built()
    two = files(fmap) + files(fmap)
    flags = role_engine.mapping_flags(role_engine.build_table(two))
    assert not [f for f in flags if f["rows"] != sorted(set(f["rows"]))]
    assert not any("4, 4" in f["text"] for f in flags)


def test_the_total_column_is_the_year_and_a_differing_sum_of_months_is_flagged_with_both_cells():
    fmap, kinds, rev, totals = built(total_2024=1_000_000.0)
    r = run(files(fmap), as_of="2024-11")
    growth = {g["period"]: g for g in r["role_metrics"]["growth_by_year"]}
    assert growth["2024"]["value"] == 1_000_000.0
    total_col = next(c for c, k in kinds.items() if k == ("year", "2024"))
    first, last = next(c for c, k in kinds.items() if k == ("month", "2024-01")), next(c for c, k in kinds.items() if k == ("month", "2024-11"))
    flag = [f for f in r["role_metrics"]["mapping_flags"] if "TOTAL column" in f["text"]]
    assert len(flag) == 1 and flag[0]["used_row"] == 4
    assert f"{col(total_col)}4" in flag[0]["text"] and f"{col(first)}4:{col(last)}4" in flag[0]["text"], flag[0]["text"]
    assert "1 000 000" in flag[0]["text"] or "1,000,000" in flag[0]["text"]


def test_a_total_within_one_percent_of_the_months_raises_no_flag():
    fmap, kinds, rev, totals = built()
    r = run(files(fmap), as_of="2024-11")
    assert not [f for f in r["role_metrics"]["mapping_flags"] if "TOTAL column" in f["text"]]
    assert metric(r, "yearly_revenue")["period"] == "2024" and metric(r, "yearly_revenue")["value"] == totals[2024], "the TOTAL column is the latest year"


# ---------------------------------------------------------------------------
# The latest year before its fiscal year end is "YYYY (to Mon)"
# ---------------------------------------------------------------------------
def test_the_latest_year_before_its_year_end_is_labelled_to_the_as_of_month_everywhere():
    from app import ic_memo, plan_lines
    fmap, _, rev, totals = built()
    r = run(files(fmap), as_of="2024-11")
    rm = r["role_metrics"]
    growth = {g["period"]: g for g in rm["growth_by_year"]}
    assert growth["2024"]["label"] == "2024 (to Nov)" and growth["2024"]["period"] == "2024"
    trend = rm["pnl_trend"]
    assert [p.get("label") or p["period"] for p in trend["periods"]] == ["2023", "2024 (to Nov)"]
    assert any(v.get("label") == "2024 (to Nov)" for row in trend["rows"] for v in row["values"])
    tables = dict((t, (h, rows)) for t, h, rows in ic_memo.role_tables(r, "EUR"))
    assert [row[0] for row in tables["Growth by year"][1]] == ["2023", "2024 (to Nov)"] or [row[0] for row in tables["Growth by year"][1]] == ["2024 (to Nov)"]
    assert "2024 (to Nov)" in {row[1] for row in tables["Yearly P&L trend"][1]}
    header, _ = plan_lines.table(trend, "EUR")
    assert header == ["Metric", "2023", "2024 (to Nov)"]
    assert any("2024 (to Nov)" in line["text"] for line in plan_lines.lines(r, "EUR"))
    summary = ic_memo.role_summary(r, "EUR", ic_memo.Notes())
    assert any("Growth by year: 2024 (to Nov)" in line for line in summary)


def test_a_year_that_is_over_has_no_to_month_label():
    fmap, *_ = built()
    r = run(files(fmap), as_of="2023-12")
    assert all(g.get("label") is None for g in r["role_metrics"]["growth_by_year"])
    assert all(p.get("label") is None for p in (r["role_metrics"]["pnl_trend"] or {"periods": []})["periods"])


def test_the_excel_trend_sheet_header_carries_the_to_month_label():
    from app import yearly_sheets
    fmap, *_ = built()
    r = run(files(fmap), as_of="2024-11")
    trend = yearly_sheets._trend(r)
    assert trend is not None and "2024 (to Nov)" in trend.header if hasattr(trend, "header") else "2024 (to Nov)" in str(trend)
