"""The verifier (docs/specs/llm-structure-reading.md section 2, period rules of deck-parser.md section 2).

A value is matched against its value_cell only, a period against its period_cells only; every
proposed flag is recomputed from the matched values. Pure functions: no model, no database.
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.structures import verify  # noqa: E402


def _struct(rows, header_rows=1, kind="table", spans=None):
    """A structure from a grid of texts ("" = no cell); spans: {(row, col): col_span}, 1-based."""
    cells = []
    for r, row in enumerate(rows, 1):
        for c, text in enumerate(row, 1):
            if text:
                cell = {"row": r, "col": c, "text": text}
                if (spans or {}).get((r, c)):
                    cell["col_span"] = spans[(r, c)]
                cells.append(cell)
    return {"type": kind, "header_rows": header_rows, "cells": cells}


def _item(value, value_cell, period=None, period_cells=(), metric="revenue", unit=None, flags=()):
    return {"metric": metric, "period": period, "value": value, "unit": unit, "actual_or_forecast": "forecast",
            "value_cell": value_cell, "period_cells": list(period_cells), "proposed_flags": list(flags)}


def _status(structure, item, year_end=12, mode="suggest"):
    out = verify.verify(structure, [item], year_end, mode)
    return out["items"][0]["status"] if out["items"] else "dropped"


PLAN = _struct([["", "FY2025", "FY2026"], ["Revenue", "£1,200,000", "£1,500,000"]])


# ---------------------------------------------------------------------------
# Numbers: normalised, then matched exactly
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rows, value", [
    ([["", "2025"], ["Revenue", "£1,200,000"]], 1200000),                 # currency and thousands separators
    ([["", "2025"], ["Revenue", "€1.234,5"]], 1234.5),                    # the structure writes 1.234,5
    ([["", "2025"], ["EBITDA", "(1,200)"]], -1200),                       # brackets are a negative
    ([["", "2025"], ["EBITDA", "-$1,200"]], -1200),                       # the currency symbol is removed first
    ([["", "2025"], ["Revenue", "$3.6m"]], 3600000),                      # m suffix
    ([["", "2025"], ["ARR", "2bn"]], 2000000000),                         # bn suffix
    ([["", "2025"], ["Users", "5K"]], 5000),                              # k suffix
    ([["", "2025", ""], ["Revenue", "1.2", "£m"]], 1200000),              # a scale in the neighbouring cell
    ([["£'000", "2025"], ["Revenue", "1,234"]], 1234000),                 # a scale in a header cell
    ([["", "2025 (£m)"], ["Revenue", "4.5"]], 4500000),                   # a scale in the column header
    ([["", "2025 %"], ["Gross margin", "62"]], 62),                       # % in a header: no scale
])
def test_a_value_matches_its_cell_after_normalisation(rows, value):
    structure = _struct(rows)
    assert _status(structure, _item(value, "r2c2", "2025", ["r1c2"])) == verify.VERIFIED


@pytest.mark.parametrize("rows, value", [
    ([["", "2025"], ["Revenue", "£1,234,567"]], 1230000),                 # a rounded number does not match
    ([["", "2025"], ["Revenue", "12,5"]], 12.5),                          # no 1.234,5 in the structure: no decimal comma
    ([["", "2025"], ["Revenue", "$12 - $13 million"]], 12000000),         # two figures: no single value
    ([["", "2025"], ["Revenue", "1.2"]], 1200000),                        # no scale anywhere
])
def test_a_value_that_is_not_its_cells_number_is_unmatched(rows, value):
    assert _status(_struct(rows), _item(value, "r2c2", "2025", ["r1c2"])) == verify.SUGGESTION


def test_the_value_is_matched_against_its_value_cell_only():
    assert _status(PLAN, _item(1500000, "r2c3", "FY2026", ["r1c3"])) == verify.VERIFIED
    # The same number sits in the structure, but not in the cited cell (whose period is cited right).
    assert _status(PLAN, _item(1500000, "r2c2", "FY2025", ["r1c2"])) == verify.SUGGESTION
    assert _status(PLAN, _item(1500000, "r9c9", "FY2026", ["r1c3"])) == verify.SUGGESTION, "a cell that does not exist"


def test_an_item_with_no_value_is_never_verified():
    roadmap = _struct([["Q3 2025", "Launch the API"]], header_rows=0, kind="roadmap")
    for c in roadmap["cells"]:
        c["box"] = c["col"]
    assert _status(roadmap, _item(None, "r1c2", "2025-Q3", ["r1c1"], metric="product")) == verify.SUGGESTION


# ---------------------------------------------------------------------------
# Periods: rebuilt from the cited cells only, compared by start and end date
# ---------------------------------------------------------------------------
def test_the_period_is_matched_against_its_period_cells_only():
    assert _status(PLAN, _item(1200000, "r2c2", "FY2025", ["r1c2"])) == verify.VERIFIED
    assert _status(PLAN, _item(1200000, "r2c2", "FY2025", [])) == verify.SUGGESTION, "the right header, not cited"
    assert _status(PLAN, _item(1200000, "r2c2", "FY2026", ["r1c3"])) == verify.SUGGESTION, "not a header of the value"
    assert _status(PLAN, _item(1200000, "r2c2", "FY2026", ["r1c2"])) == verify.SUGGESTION, "another period"


def test_a_two_cell_period_is_a_quarter_and_the_year_above_it_in_the_same_column_range():
    grid = _struct([["", "2025", "", "", ""], ["", "Q1", "Q2", "Q3", "Q4"], ["Revenue", "$1M", "$2M", "$3M", "$4M"]],
                   header_rows=2, spans={(1, 2): 4})
    assert _status(grid, _item(3000000, "r3c4", "2025-Q3", ["r2c4", "r1c2"])) == verify.VERIFIED
    assert _status(grid, _item(3000000, "r3c4", "2025-Q3", ["r2c4"])) == verify.SUGGESTION, "Q3 alone is no period"
    assert _status(grid, _item(3000000, "r3c4", "2025-Q3", ["r1c2", "r2c4"])) == verify.SUGGESTION, "year first"
    narrow = _struct([["", "2025", "", "", ""], ["", "Q1", "Q2", "Q3", "Q4"], ["Revenue", "$1M", "$2M", "$3M", "$4M"]],
                     header_rows=2)
    assert _status(narrow, _item(3000000, "r3c4", "2025-Q3", ["r2c4", "r1c2"])) == verify.SUGGESTION, \
        "the year cell does not cover the quarter's column"


@pytest.mark.parametrize("month, period", [("Mar", "2025-03"), ("März", "2025-03"), ("МАРТ", "2025-03"),
                                           ("okt", "2025-10"), ("дек", "2025-12"), ("September", "2025-09")])
def test_month_names_are_english_german_or_bulgarian_in_any_case(month, period):
    grid = _struct([["", "2025"], ["", month], ["Revenue", "€1M"]], header_rows=2)
    assert _status(grid, _item(1000000, "r3c2", period, ["r2c2", "r1c2"])) == verify.VERIFIED


@pytest.mark.parametrize("header, period, year_end, status", [
    ("FY2025", "FY2025", 3, verify.VERIFIED),
    ("FY2025", "2025", 12, verify.VERIFIED),          # December: FY2025 is the calendar year
    ("FY2025", "2025", 3, verify.SUGGESTION),         # March: FY2025 runs 2024-04-01 to 2025-03-31
    ("FY2024/25", "FY2024/25", 3, verify.VERIFIED),
    ("FY2024/25", "FY2025", 3, verify.VERIFIED),      # named by the year it ends in
    ("FY2024/25", "FY2024", 3, verify.SUGGESTION),
    ("Y/E 25", "FY2025", 6, verify.VERIFIED),
])
def test_fiscal_years_follow_the_audit_year_end(header, period, year_end, status):
    grid = _struct([["", header], ["Revenue", "£2M"]])
    assert _status(grid, _item(2000000, "r2c2", period, ["r1c2"]), year_end) == status


def test_a_null_period_matches_only_when_no_header_holds_a_period():
    no_period = _struct([["", "Plan"], ["Revenue", "£2M"]])
    assert _status(no_period, _item(2000000, "r2c2", None, [])) == verify.VERIFIED
    assert _status(PLAN, _item(1200000, "r2c2", None, [])) == verify.SUGGESTION, "the header holds FY2025"
    quarter_only = _struct([["", "Q3"], ["Revenue", "£2M"]])
    assert _status(quarter_only, _item(2000000, "r2c2", None, [])) == verify.VERIFIED, "Q3 with no year is no period"
    assert _status(quarter_only, _item(2000000, "r2c2", "2025-Q3", ["r1c2"])) == verify.SUGGESTION, "never inferred"
    assert _status(no_period, _item(2000000, "r2c2", None, ["r1c2"])) == verify.SUGGESTION, "null cites no cell"


def test_relative_columns_have_no_period_unless_a_cell_states_the_start_date():
    relative = _struct([["", "M1", "M2"], ["Revenue", "£1M", "£2M"]])
    assert _status(relative, _item(2000000, "r2c3", None, [])) == verify.VERIFIED
    assert _status(relative, _item(2000000, "r2c3", "2025-02", ["r1c3"])) == verify.SUGGESTION
    started = _struct([["Start: Jan 2025", "M1", "M2"], ["Revenue", "£1M", "£2M"]])
    assert _status(started, _item(2000000, "r2c3", "2025-02", ["r1c3", "r1c1"])) == verify.VERIFIED


def test_in_a_kpi_panel_the_top_line_of_the_box_is_its_header():
    panel = _struct([["23 Y/E"], ["Gross Profit £150K"], ["5K Users"]], header_rows=0, kind="kpi_panel")
    for c in panel["cells"]:
        c["box"] = 1
    assert _status(panel, _item(150000, "r2c1", "FY2023", ["r1c1"], metric="gross_profit")) == verify.VERIFIED
    assert _status(panel, _item(5000, "r3c1", "FY2023", ["r1c1"], metric="users")) == verify.VERIFIED
    other_box = _struct([["23 Y/E"], ["Gross Profit £150K"]], header_rows=0, kind="kpi_panel")
    other_box["cells"][0]["box"], other_box["cells"][1]["box"] = 1, 2
    assert _status(other_box, _item(150000, "r2c1", "FY2023", ["r1c1"])) == verify.SUGGESTION, \
        "another box's line is no header"


# ---------------------------------------------------------------------------
# Flags: recomputed from the matched values
# ---------------------------------------------------------------------------
TOTALS = _struct([["", "2025"], ["Product A", "£100"], ["Product B", "£200"], ["Total revenue", "£350"]])


def test_a_total_mismatch_is_kept_only_when_python_reproduces_it():
    parts = [_item(100, "r2c2", "2025", ["r1c2"]), _item(200, "r3c2", "2025", ["r1c2"])]
    flagged = _item(350, "r4c2", "2025", ["r1c2"], flags=["total_mismatch"])
    out = verify.verify(TOTALS, parts + [flagged])["items"]
    assert [i["status"] for i in out] == [verify.VERIFIED] * 3
    right = _struct([["", "2025"], ["Product A", "£100"], ["Product B", "£200"], ["Total revenue", "£300"]])
    out = verify.verify(right, parts + [{**flagged, "value": 300}])["items"]
    assert out[2]["status"] == verify.SUGGESTION and out[2]["checks"]["flags"] is False, "300 is the sum"
    out = verify.verify(TOTALS, [flagged])["items"]
    assert out[0]["status"] == verify.SUGGESTION, "no matched parts: the flag cannot be reproduced"


def test_a_growth_mismatch_is_kept_only_when_python_reproduces_it():
    grid = _struct([["", "2024", "2025"], ["Revenue", "£100", "£120"], ["Revenue growth", "", "50%"]])
    base = [_item(100, "r2c2", "2024", ["r1c2"]), _item(120, "r2c3", "2025", ["r1c3"])]
    stated = _item(50, "r3c3", "2025", ["r1c3"], metric="revenue_growth", unit="%", flags=["growth_mismatch"])
    out = verify.verify(grid, base + [stated])["items"]
    assert out[2]["status"] == verify.VERIFIED, "the values give 20%, the deck says 50%"
    fine = _struct([["", "2024", "2025"], ["Revenue", "£100", "£120"], ["Revenue growth", "", "20%"]])
    out = verify.verify(fine, base + [{**stated, "value": 20}])["items"]
    assert out[2]["status"] == verify.SUGGESTION


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------
def test_unmatched_items_are_suggestions_or_dropped_and_counted():
    items = [_item(1200000, "r2c2", "FY2025", ["r1c2"]), _item(999, "r2c3", "FY2026", ["r1c3"])]
    shown = verify.verify(PLAN, items, mode="suggest")
    assert [i["status"] for i in shown["items"]] == [verify.VERIFIED, verify.SUGGESTION] and shown["dropped"] == 0
    dropped = verify.verify(PLAN, items, mode="drop")
    assert [i["status"] for i in dropped["items"]] == [verify.VERIFIED] and dropped["dropped"] == 1
    assert verify.label(verify.SUGGESTION) == "AI suggestion, not verified" and verify.label(verify.VERIFIED) == "Verified"


@pytest.mark.parametrize("raw, mode", [("", "suggest"), ("drop", "drop"), ("DROP", "drop"), ("suggest", "suggest"),
                                       ("dorp", "suggest")])
def test_the_switch_defaults_to_suggest_and_a_typo_never_drops(monkeypatch, raw, mode):
    monkeypatch.setenv("STRUCTURE_UNMATCHED", raw)
    assert verify.unmatched_mode() == mode
