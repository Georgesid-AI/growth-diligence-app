"""Column classes (board-pack layout fix, item 1): every period column is a month, a quarter or a year by its header. Monthly series are built from
month columns only; quarter and year columns (TOTAL 2021, Q1 2022, FY 2023) feed the quarterly and yearly metrics. Synthetic sheet only."""
import sys
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import checks, role_engine, series  # noqa: E402
from app.ic_memo import cell_ranges  # noqa: E402
from app.structures import redact  # noqa: E402
from test_role_engine import metric, run  # noqa: E402


def col(n):
    return redact.col_letters(n)


def board_pack():
    """Row 3 is the header. B-D hold TOTAL 2021..2023; from E on the months of 2022 as text (Jan-22) with a Qn subtotal after every third month,
    then the months of 2023 as real dates with their subtotals. Revenue is row 4, cost of revenue row 5."""
    grid = {(3, 1): "Metric", (4, 1): "Revenue", (5, 1): "Cost of revenue"}
    c = 5
    layout = {}                      # column -> ("month" | "quarter", period)
    for year in (2022, 2023):
        for q in range(1, 5):
            for k in range(3):
                m = 3 * (q - 1) + k + 1
                grid[(3, c)] = date(year, m, 28) if year == 2023 else f"{('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec').split()[m - 1]}-{year % 100}"
                layout[c] = ("month", f"{year}-{m:02d}")
                c += 1
            grid[(3, c)] = f"Q{q} {year}"
            layout[c] = ("quarter", f"{year}-Q{q}", year, q)
            c += 1
    month_rev = {}
    for cc, kind in layout.items():
        if kind[0] == "month":
            month_rev[kind[1]] = 100 + 3 * len(month_rev)
    quarter_total = {}
    for p, v in month_rev.items():
        y, m = int(p[:4]), int(p[5:])
        quarter_total[(y, (m - 1) // 3 + 1)] = quarter_total.get((y, (m - 1) // 3 + 1), 0) + v
    year_total = {2021: 1_000.0, 2022: float(sum(v for p, v in month_rev.items() if p.startswith("2022"))),
                  2023: float(sum(v for p, v in month_rev.items() if p.startswith("2023")))}
    for i, y in enumerate((2021, 2022, 2023)):
        grid[(3, 2 + i)] = f"TOTAL {y}"
        grid[(4, 2 + i)] = str(year_total[y])
        grid[(5, 2 + i)] = str(year_total[y] * 0.4)
    for cc, kind in layout.items():
        if kind[0] == "month":
            grid[(4, cc)] = str(month_rev[kind[1]])
            grid[(5, cc)] = str(month_rev[kind[1]] * 0.4)
        else:
            grid[(4, cc)] = str(quarter_total[(kind[2], kind[3])])
            grid[(5, cc)] = str(quarter_total[(kind[2], kind[3])] * 0.4)
    return grid, layout, month_rev, quarter_total, year_total, c - 1


def smap_of(last_col):
    def r(n, role):
        return {"row": n, "label_cell": f"A{n}", "role": role, "metric": role, "basis": "monthly", "actual_plan": "actual", "boundary_col": None, "segment": None,
                "parent_row": None, "unit": "money", "currency": "EUR", "cells": f"B{n}:{col(last_col)}{n}", "variance_of": None, "by_column": False,
                "evidence": "x"}
    return {"sheet": "Report", "header_row": 3, "label_col": "A", "first_period_col": "B", "last_period_col": col(last_col), "granularity": "monthly",
            "last_actual": None, "rows": [r(4, "revenue"), r(5, "cost_of_revenue")]}


def sheet_of(grid):
    text = redact.reading_text([{"name": "Report", "cells": [{"row": r, "col": c, "text": t.isoformat() if isinstance(t, date) else t}
                                                            for (r, c), t in grid.items()]}])
    return text, checks.Cells(text).sheet("Report")


@pytest.fixture(scope="module")
def pack():
    grid, layout, months, quarters, years, last = board_pack()
    smap = smap_of(last)
    text, sheet = sheet_of(grid)
    fmap = series.attach({"map_version": 1, "kind": "sheet", "figures": [], "sheets": [smap]}, text)
    return {"layout": layout, "months": months, "quarters": quarters, "years": years, "fmap": fmap, "last": last}


def test_the_monthly_series_holds_month_columns_only(pack):
    got = pack["fmap"]["sheets"][0]["rows"][0]["series"]
    assert got["periods"] == sorted(pack["months"]), "24 months of 2022-2023, no quarter or year column"
    assert got["values"] == [float(pack["months"][p]) for p in got["periods"]]
    first_q = next(c for c, k in pack["layout"].items() if k[0] == "quarter")
    assert col(first_q) + "4" not in got["refs"] and "B4" not in got["refs"]


def test_a_date_typed_header_is_a_month(pack):
    got = pack["fmap"]["sheets"][0]["rows"][0]["series"]
    assert "2023-06" in got["periods"] and got["values"][got["periods"].index("2023-06")] == pack["months"]["2023-06"]


def test_quarter_and_year_columns_are_kept_apart_in_their_own_form(pack):
    row = pack["fmap"]["sheets"][0]["rows"][0]
    sub = row["subtotal_series"]
    assert sub["periods"][:3] == ["2021", "2022", "2023"] and sub["values"][:3] == [1000.0, pack["years"][2022], pack["years"][2023]]
    assert sub["refs"][:3] == ["B4", "C4", "D4"]
    assert "2022-Q1" in sub["periods"] and sub["values"][sub["periods"].index("2022-Q1")] == pack["quarters"][(2022, 1)]


def test_the_cell_citation_is_one_range_per_run_of_months_and_the_subtotals_apart(pack):
    row = pack["fmap"]["sheets"][0]["rows"][0]
    runs = cell_ranges(row["series"]["refs"])
    assert runs[:2] == ["E4:G4", "I4:K4"], "three months, a subtotal column, three months: one range per contiguous run"
    assert len(runs) == 8 and not set(runs) & set(cell_ranges(row["subtotal_series"]["refs"]))
    assert cell_ranges(row["subtotal_series"]["refs"])[0] == "B4:D4", "the three TOTAL columns are one run of their own"


def files_of(pack):
    return [{"file": "board", "file_map": pack["fmap"], "rejected": [], "cannot": []}]


def test_yearly_revenue_comes_from_the_total_columns(pack):
    r = run(files_of(pack), as_of="2023-12")
    table = role_engine.build_table(files_of(pack))
    yearly = role_engine.pick(table, "revenue", "yearly")
    assert yearly is not None and set(yearly["actual"]) == {"2021", "2022", "2023"}
    assert yearly["actual"]["2022"] == (pack["years"][2022], "C4")
    monthly = role_engine.pick(table, "revenue", "monthly")
    assert monthly["granularity"] == "monthly" and len(monthly["actual"]) == 24
    by = {m["period"]: m for m in r["role_metrics"]["metrics"] if m["metric"] == "yearly_revenue"}
    assert by["2023"]["value"] == pack["years"][2023]
    years = {y["period"]: y for y in r["yearly_basis"]["years"]}
    assert [years[p]["revenue"] for p in ("2021", "2022", "2023")] == [1000.0, pack["years"][2022], pack["years"][2023]]
    assert [years[p]["revenue_cells"] for p in ("2021", "2022", "2023")] == [["B4"], ["C4"], ["D4"]]


def test_year_on_year_growth_and_gross_margin_use_the_year_columns(pack):
    r = run(files_of(pack), as_of="2023-12")
    growth = {g["period"]: g for g in r["role_metrics"]["growth_by_year"]}
    assert growth["2022"]["growth"] == pytest.approx(pack["years"][2022] / 1000.0 - 1), "2021 exists as its TOTAL column only"
    assert growth["2023"]["growth"] == pytest.approx(pack["years"][2023] / pack["years"][2022] - 1)
    assert metric(r, "gross_margin")["value"] == pytest.approx(0.6)
    years = {y["period"]: y for y in r["yearly_basis"]["years"]}
    assert all(years[p]["gross_margin_pct"] == pytest.approx(0.6) for p in years)


def test_a_growth_citation_lists_the_months_in_runs_and_never_a_subtotal_column(pack):
    r = run(files_of(pack), as_of="2023-12")
    cells = {g["period"]: g["source"]["cells"] for g in r["role_metrics"]["growth_by_year"]}
    subtotal_refs = {f"{col(c)}4" for c, k in pack["layout"].items() if k[0] == "quarter"}
    assert not subtotal_refs & set(cells["2023"]), "2022 and 2023 are cited by their month cells"
    shown = cell_ranges(cells["2023"])
    assert shown[:2] == ["E4:G4", "I4:K4"] and len(shown) == 8
    assert cells["2022"][0] == "B4", "the 2021 total column is cited on its own, before the months of 2022"


def test_headers_that_name_a_subtotal_are_periods():
    for text, grain in (("TOTAL 2021", "year"), ("Total FY22", "year"), ("FY 2021", "year"), ("Q3 2024", "quarter"), ("Q3 2024 Total", "quarter"),
                        ("Full year 2023", "year"), ("2023-04-30", "month")):
        assert checks.header_period(text)["grain"] == grain, text
    assert checks.header_period("Total") is None and checks.header_period("Grand total") is None
