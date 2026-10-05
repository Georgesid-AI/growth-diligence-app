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


CORRECTED = "verified, period corrected"


def _status(structure, item, year_end=12, mode="suggest"):
    """The item's status, or CORRECTED when it is verified with the period Python rebuilt in place of the model's."""
    out = verify.verify(structure, [item], year_end, mode)
    if not out["items"]:
        return "dropped"
    got = out["items"][0]
    return CORRECTED if got["status"] == verify.VERIFIED and got["checks"].get("period_corrected") else got["status"]


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
    assert _status(PLAN, _item(1200000, "r2c2", "FY2026", ["r1c2"])) == CORRECTED, \
        "another period: the value matches, so the period its cell gives replaces it"


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
    ("FY2025", "2025", 3, verify.VERIFIED),           # March: both run 2024-04-01 to 2025-03-31
    ("2025E", "FY2025", 3, verify.VERIFIED),          # every year label is fiscal unless December
    ("FY2025", "2024", 3, CORRECTED),                 # the value matches: FY2025 replaces 2024
    ("Q3 25", "2025-Q3", 3, verify.VERIFIED),
    ("Q1 FY25", "2025-Q1", 3, verify.VERIFIED),
    ("Q1 FY25", "FY2025", 3, CORRECTED),              # a quarter is not its fiscal year: 2025-Q1 replaces it
    ("Mar 2025", "2025-03", 3, verify.VERIFIED),      # a month stays a calendar month
    ("FY2024/25", "FY2024/25", 3, verify.VERIFIED),
    ("FY2024/25", "FY2025", 3, verify.VERIFIED),      # named by the year it ends in
    ("FY2024/25", "FY2024", 3, CORRECTED),
    ("Y/E 25", "FY2025", 6, verify.VERIFIED),
])
def test_fiscal_years_follow_the_audit_year_end(header, period, year_end, status):
    grid = _struct([["", header], ["Revenue", "£2M"]])
    assert _status(grid, _item(2000000, "r2c2", period, ["r1c2"]), year_end) == status


def test_a_quarter_under_a_fiscal_year_is_that_fiscal_quarter():
    grid = _struct([["", "FY2025", ""], ["", "Q3", "Q4"], ["Revenue", "$3M", "$4M"]], header_rows=2, spans={(1, 2): 2})
    assert _status(grid, _item(3000000, "r3c2", "2025-Q3", ["r2c2", "r1c2"]), 3) == verify.VERIFIED
    assert _status(grid, _item(4000000, "r3c3", "2025-Q4", ["r2c3", "r1c2"]), 12) == verify.VERIFIED


@pytest.mark.parametrize("header, month, year_end, period, status", [
    ("FY2025", "Mar", 3, "2025-03", verify.VERIFIED),       # up to the year-end month: the named year
    ("FY2025", "Apr", 3, "2024-04", verify.VERIFIED),       # after it: the calendar year before
    ("FY2025", "Apr", 3, "2025-04", CORRECTED),          # read literally: Python's April 2024 replaces it
    ("2025", "Jul", 6, "2024-07", verify.VERIFIED),         # a plain year header too
    ("2025", "Jul", 6, "2025-07", CORRECTED),
    ("2025", "Jun", 6, "2025-06", verify.VERIFIED),
    ("FY2025", "Apr", 12, "2025-04", verify.VERIFIED),      # December: unchanged
    ("2025", "Jul", 12, "2025-07", verify.VERIFIED),
])
def test_a_month_under_a_year_header_falls_inside_that_year(header, month, year_end, period, status):
    grid = _struct([["", header], ["", month], ["Revenue", "$5M"]], header_rows=2)
    assert _status(grid, _item(5000000, "r3c2", period, ["r2c2", "r1c2"]), year_end) == status


def test_the_period_comes_from_the_lowest_period_header():
    quarters = _struct([["", "2025", "", "", ""], ["", "Q1", "Q2", "Q3", "Q4"], ["Revenue", "$1M", "$2M", "$3M", "$4M"]],
                       header_rows=2, spans={(1, 2): 4})
    assert _status(quarters, _item(3000000, "r3c4", "2025", ["r1c2"])) == verify.SUGGESTION, \
        "a quarterly value cited against its year header only"
    assert _status(PLAN, _item(1200000, "r2c2", "FY2025", ["r1c2"])) == verify.VERIFIED, "a yearly value"
    months = _struct([["", "2025", ""], ["", "Q3", ""], ["", "Jul", "Aug"], ["Revenue", "$1M", "$2M"]],
                     header_rows=3, spans={(1, 2): 2, (2, 2): 2})
    assert _status(months, _item(1000000, "r4c2", "2025-Q3", ["r2c2", "r1c2"])) == verify.SUGGESTION, \
        "a monthly value cited against its quarter"
    assert _status(months, _item(1000000, "r4c2", "2025-07", ["r3c2", "r1c2"])) == verify.VERIFIED
    by_row = _struct([["", "2025"], ["Jan", "£1M"]])
    assert _status(by_row, _item(1000000, "r2c2", "2025", ["r1c2"])) == verify.SUGGESTION, \
        "the month in its row is lower than the year above it"
    relative = _struct([["", "2025", ""], ["", "M1", "M2"], ["Revenue", "£1M", "£2M"]], header_rows=2,
                       spans={(1, 2): 2})
    assert _status(relative, _item(1000000, "r3c2", "2025", ["r1c2"])) == verify.SUGGESTION
    years_by_row = _struct([["", "Revenue"], ["FY2025", "£1M"]])
    assert _status(years_by_row, _item(1000000, "r2c2", "FY2025", ["r2c1"])) == verify.VERIFIED


def test_a_matched_value_takes_the_period_python_rebuilds_from_its_cells():
    grid = _struct([["", "FY2025"], ["", "Apr"], ["Revenue", "$5M"]], header_rows=2)
    literal = _item(5000000, "r3c2", "2025-04", ["r2c2", "r1c2"])      # the model does not know the year-end
    out = verify.verify(grid, [literal], 3)
    item, = out["items"]
    assert (item["status"], item["period"], item["model_period"], out["periods_corrected"]) == \
        (verify.VERIFIED, "FY2025-04", "2025-04", 1)
    assert item["checks"] == {"value": True, "period": True, "period_corrected": True, "flags": True,
                              "dot_reading": None}
    out = verify.verify(grid, [literal], 12)
    item, = out["items"]
    assert (item["status"], item["period"], out["periods_corrected"]) == (verify.VERIFIED, "FY2025-04", 0), \
        "December: the model's reading holds, nothing is counted"
    assert "model_period" not in item and item["checks"]["period_corrected"] is False
    # No correction without the value, without cited cells, or from cells that are not the lowest period header.
    out = verify.verify(grid, [_item(4000000, "r3c2", "2025-04", ["r2c2", "r1c2"])], 3)
    assert (out["items"][0]["status"], out["items"][0]["period"], out["periods_corrected"]) == \
        (verify.SUGGESTION, "2025-04", 0), "a value that does not match keeps the model's period and counts nothing"
    assert _status(grid, _item(5000000, "r3c2", "2025-04", []), 3) == verify.SUGGESTION
    assert _status(grid, _item(5000000, "r3c2", "2025", ["r1c2"]), 3) == verify.SUGGESTION
    # A relative column: one month names a period; a longer span names none, so nothing replaces the model's.
    month = _struct([["Start: Jan 2025", "M2"], ["Revenue", "£1M"]])
    out = verify.verify(month, [_item(1000000, "r2c2", "2025-03", ["r1c2", "r1c1"])])
    assert (out["items"][0]["period"], out["periods_corrected"]) == ("2025-02", 1)
    year = _struct([["Start: Jan 2025", "Year 1"], ["Revenue", "£1M"]])
    assert _status(year, _item(1000000, "r2c2", "2026", ["r1c2", "r1c1"])) == verify.SUGGESTION


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
    fiscal_start = _struct([["Start: Apr FY25", "Year 1"], ["Revenue", "£1M"]])
    assert _status(fiscal_start, _item(1000000, "r2c2", "FY2025", ["r1c2", "r1c1"]), 3) == verify.VERIFIED, \
        "April of FY25 is April 2024 with a March year-end: Year 1 is FY2025"
    assert _status(fiscal_start, _item(1000000, "r2c2", "FY2025", ["r1c2", "r1c1"]), 12) == verify.SUGGESTION


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
# Cells the first live consistency run left unverified (docs/test-runs/consistency_2026-10-05_diagnostic.md),
# parsed here from the public test decks they come from
# ---------------------------------------------------------------------------
DECKS = BACKEND.parent / "tests" / "fixtures" / "decks" / "decks"


def _deck_structure(file, page, kind):
    pytest.importorskip("pdfplumber")
    pytest.importorskip("docx")
    from app.decks import parser
    deck = parser.parse_deck((DECKS / file).read_bytes(), file)
    return next(s for s in deck["structures"] if (s.get("slide") or s.get("page")) == page and s["type"] == kind)


def _text(structure, cell):
    return next(c["text"] for c in structure["cells"] if f"r{c['row']}c{c['col']}" == cell)


def _checked(structure, item, year_end=12):
    got, = verify.verify(structure, [item], year_end)["items"]
    return got


def test_a_dot_before_exactly_three_digits_matches_either_reading_and_records_which():
    """clevergig p7: "Approx. 2.500 hours" is 2,500 hours written with a dot; read as 2.5 it never matched."""
    panel = _deck_structure("04-clevergig.docx", 7, "kpi_panel")
    assert (_text(panel, "r4c1"), _text(panel, "r6c1")) == ("Approx. 2.500 hours", "Approx. 6.250 hours")
    for value, cell, reading in ((2500, "r4c1", "thousands"), (2.5, "r4c1", "decimal"),
                                 (6250, "r6c1", "thousands"), (6.25, "r6c1", "decimal")):
        got = _checked(panel, _item(value, cell))
        assert (got["status"], got["checks"]["dot_reading"]) == (verify.VERIFIED, reading), (value, cell)
    for value, cell in ((25000, "r4c1"), (250, "r4c1"), (9500, "r2c1")):
        got = _checked(panel, _item(value, cell))
        assert (got["status"], got["checks"]["dot_reading"]) == (verify.SUGGESTION, None), (value, cell)
    got = _checked(panel, _item(950, "r2c1"))
    assert (got["status"], got["checks"]["dot_reading"]) == (verify.VERIFIED, None), "no dot: nothing to record"


@pytest.mark.parametrize("text, value, matched", [
    ("12.500", 12500, True), ("12.500", 12.5, True),
    ("$2.500M", 2500000000, True), ("$2.500M", 2500000, True),
    ("0.500", 500, False),                  # a leading 0 never groups thousands
    ("1234.500", 1234500, False),           # nor does a group of four
    ("2.5000", 25000, False),               # four digits after the dot: a decimal
    ("2.50", 250, False),
])
def test_only_a_dot_before_exactly_three_digits_is_ambiguous(text, value, matched):
    structure = _struct([["", "Plan"], ["Revenue", text]])
    assert _status(structure, _item(value, "r2c2")) == (verify.VERIFIED if matched else verify.SUGGESTION)


def test_with_a_decimal_comma_a_dot_before_three_digits_groups_thousands_only():
    structure = _struct([["", "Plan", ""], ["Revenue", "2.500", "1.234,5"]])
    assert _checked(structure, _item(2500, "r2c2"))["checks"]["dot_reading"] is None
    assert _status(structure, _item(2500, "r2c2")) == verify.VERIFIED
    assert _status(structure, _item(2.5, "r2c2")) == verify.SUGGESTION


def test_a_bracketed_number_after_text_is_positive():
    """zero2hero p17: "Telegram(30K)" is 30,000 members; read as a negative it never matched."""
    panel = _deck_structure("05-zero2hero.pdf", 17, "kpi_panel")
    for cell, text, value in (("r1c1", "Telegram(30K)", 30000), ("r2c1", "Discord(150)", 150),
                              ("r3c1", "Twitter(6.5K)", 6500), ("r4c1", "Instagram(85K)", 85000),
                              ("r6c1", "MeetUp((3K)", 3000), ("r7c1", "LinkedIn(10K)", 10000)):
        assert _text(panel, cell) == text
        assert _checked(panel, _item(value, cell, metric="users", unit="count"))["status"] == verify.VERIFIED, text
        assert _checked(panel, _item(-value, cell, metric="users", unit="count"))["status"] == verify.SUGGESTION, text


@pytest.mark.parametrize("text, value", [
    ("(1,200)", -1200), ("£(1,200)", -1200), ("(£1.2m)", -1200000), ("( 1,200 )", -1200), ("(12%)", -12),
    ("Telegram(30K)", 30000), ("MeetUp((3K)", 3000), ("Net loss (1,200)", 1200), ("(1,200", 1200),
])
def test_brackets_make_a_negative_only_around_the_whole_figure(text, value):
    structure = _struct([["", "Plan"], ["EBITDA", text]])
    assert _status(structure, _item(value, "r2c2")) == verify.VERIFIED
    assert _status(structure, _item(-value, "r2c2")) == verify.SUGGESTION


def test_a_period_in_the_value_cells_own_text_rebuilds_from_that_cell():
    """genesisai-2024 p5: "$8,000 revenue in 2022" states its own period; no header holds one, so it never matched."""
    panel = _deck_structure("09-genesisai-2024.pdf", 5, "kpi_panel")
    assert _text(panel, "r1c1") == "$8,000 revenue in 2022"
    for cells in ([], ["r1c1"]):
        got = _checked(panel, _item(8000, "r1c1", "2022", cells, unit="USD"))
        assert (got["status"], got["period"], got["checks"]["period_corrected"]) == (verify.VERIFIED, "2022", False), \
            cells
    got = _checked(panel, _item(8000, "r1c1", "2021", [], unit="USD"))
    assert (got["status"], got["period"], got["model_period"]) == (verify.VERIFIED, "2022", "2021"), \
        "a matched value takes the period Python rebuilds from the cell, as from a header"
    assert _status(panel, _item(8001, "r1c1", "2022", [])) == verify.SUGGESTION, "no value, no period"
    assert _status(panel, _item(8000, "r1c1", "2022", ["r2c1"])) == verify.SUGGESTION, "another cell"
    assert _status(panel, _item(8000, "r1c1", None, [])) == verify.VERIFIED, "the null-period rule is unchanged"


def test_a_cells_own_period_is_read_only_from_that_cell():
    table = _struct([["", "Plan"], ["Revenue", "£1.2m in 2023"], ["Costs", "£0.4m"]])
    assert _status(table, _item(1200000, "r2c2", "2023", [])) == verify.VERIFIED
    assert _status(table, _item(1200000, "r2c2", "2023-Q1", [])) == CORRECTED, "the cell says the year"
    assert _status(table, _item(400000, "r3c2", "2023", [])) == verify.SUGGESTION, "another cell's period"
    assert _status(table, _item(400000, "r3c2", "2023", ["r2c2"])) == verify.SUGGESTION


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
