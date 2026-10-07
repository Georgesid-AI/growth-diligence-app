"""The verifier (docs/specs/structure-labelling.md section 4, period rules of deck-parser.md section 2).

Values and cells are Python's (app/structures/items.py), so nothing matches a value any more. The verifier joins
each label to its item and rebuilds the period itself: from the item's lowest period header (with the year cell
above), from its own cell, or in a roadmap from its adjacent date line. It records the dot and bracket readings,
computes total_mismatch and growth_mismatch over the Verified items, drops not_a_metric items and never verifies an
"other" item or a milestone. Pure functions: no model, no database.
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.structures import items, verify  # noqa: E402


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


def _lab(period=None, metric="revenue", unit=None, actual_or_forecast="forecast"):
    """A label's fields, without its item id."""
    return {"metric": metric, "period": period, "unit": unit, "unit_other": None,
            "actual_or_forecast": actual_or_forecast}


def _verify(structure, labels, pairs=(), year_end=12, mode="suggest"):
    """verify.verify over Python's item list. `labels`: {cell or (cell, position): label fields}; every other
    listed item is labelled not_a_metric, as a complete reply must. `pairs`: (line cell, date cell, category)."""
    listed = items.list_items(structure)
    reply = []
    for item in listed["items"]:
        given = labels.get((item["cell"], item["position"])) or \
            (labels.get(item["cell"]) if item["position"] == 1 else None)
        reply.append({"item": item["id"], **(given or _lab(metric=verify.NOT_A_METRIC))})
    ids = {x["cell"]: x["id"] for x in listed["dates"] + listed["lines"]}
    paired = [{"line": ids[line], "date": ids[date], "category": category} for line, date, category in pairs]
    return verify.verify(structure, listed, reply, paired, year_end, mode)


def _one(structure, cell, period=None, year_end=12, position=1, **label):
    """The checked item of one cell, labelled with `period`."""
    out = _verify(structure, {(cell, position): _lab(period, **label)}, year_end=year_end)
    return next(i for i in out["items"] if i["value_cell"] == cell and i.get("position") == position)


CORRECTED = "verified, period corrected"


def _status(structure, cell, period=None, year_end=12, **label):
    """The item's status, or CORRECTED when it is verified with the period Python rebuilt in place of the model's."""
    got = _one(structure, cell, period, year_end, **label)
    return CORRECTED if got["status"] == verify.VERIFIED and got["checks"]["period_corrected"] else got["status"]


PLAN = _struct([["", "FY2025", "FY2026"], ["Revenue", "£1,200,000", "£1,500,000"]])


# ---------------------------------------------------------------------------
# A checked item: its label joined to Python's item
# ---------------------------------------------------------------------------
def test_a_checked_item_keeps_todays_fields_plus_its_id_and_position():
    got = _one(PLAN, "r2c2", "FY2025", unit="GBP")
    assert got == {"item": "i1", "position": 1, "metric": "revenue", "period": "2025", "unit": "GBP",
                   "unit_other": None, "actual_or_forecast": "forecast", "value": 1200000,
                   "values": [{"value": 1200000, "dot_reading": None, "bracket_reading": None}],
                   "value_cell": "r2c2", "period_cells": ["r1c2"], "proposed_flags": [], "status": verify.VERIFIED,
                   "checks": {"period": True, "period_corrected": False, "dot_reading": None, "bracket_reading": None}}


def test_the_value_and_the_cell_are_pythons_whatever_the_label_says():
    out = _verify(PLAN, {"r2c2": _lab("FY2025"), "r2c3": _lab("FY2026", metric="costs")})
    assert [(i["value_cell"], i["value"], i["metric"]) for i in out["items"]] == \
        [("r2c2", 1200000, "revenue"), ("r2c3", 1500000, "costs")]


# ---------------------------------------------------------------------------
# Periods: rebuilt by Python from the item's own period cells, compared by start and end date
# ---------------------------------------------------------------------------
def test_the_period_is_rebuilt_from_the_lowest_period_header_and_replaces_the_models():
    assert _status(PLAN, "r2c2", "FY2025") == verify.VERIFIED
    got = _one(PLAN, "r2c2", "FY2026")
    assert (got["status"], got["period"], got["model_period"], got["period_cells"]) == \
        (verify.VERIFIED, "2025", "FY2026", ["r1c2"]), "another period: the header's replaces it, a correction"
    got = _one(PLAN, "r2c2", None)
    assert (got["period"], got["model_period"], got["checks"]["period_corrected"]) == ("2025", None, True)
    out = _verify(PLAN, {"r2c2": _lab("2024"), "r2c3": _lab("FY2026")})
    assert out["periods_corrected"] == 1


def test_a_two_cell_period_is_a_quarter_and_the_year_above_it_in_the_same_column_range():
    grid = _struct([["", "2025", "", "", ""], ["", "Q1", "Q2", "Q3", "Q4"], ["Revenue", "$1M", "$2M", "$3M", "$4M"]],
                   header_rows=2, spans={(1, 2): 4})
    got = _one(grid, "r3c4", "2025-Q3")
    assert (got["status"], got["period"], got["period_cells"]) == (verify.VERIFIED, "2025-Q3", ["r2c4", "r1c2"])
    narrow = _struct([["", "2025", "", "", ""], ["", "Q1", "Q2", "Q3", "Q4"], ["Revenue", "$1M", "$2M", "$3M", "$4M"]],
                     header_rows=2)
    assert _status(narrow, "r3c4", "2025-Q3") == verify.SUGGESTION, "the year cell does not cover the quarter's column"


@pytest.mark.parametrize("month, period", [("Mar", "2025-03"), ("März", "2025-03"), ("МАРТ", "2025-03"),
                                           ("okt", "2025-10"), ("дек", "2025-12"), ("September", "2025-09")])
def test_month_names_are_english_german_or_bulgarian_in_any_case(month, period):
    grid = _struct([["", "2025"], ["", month], ["Revenue", "€1M"]], header_rows=2)
    assert _status(grid, "r3c2", period) == verify.VERIFIED


@pytest.mark.parametrize("header, period, year_end, status", [
    ("FY2025", "FY2025", 3, verify.VERIFIED),
    ("FY2025", "2025", 12, verify.VERIFIED),          # December: FY2025 is the calendar year
    ("FY2025", "2025", 3, verify.VERIFIED),           # March: both run 2024-04-01 to 2025-03-31
    ("2025E", "FY2025", 3, verify.VERIFIED),          # every year label is fiscal unless December
    ("FY2025", "2024", 3, CORRECTED),                 # FY2025 replaces 2024
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
    assert _status(grid, "r2c2", period, year_end) == status


def test_a_quarter_under_a_fiscal_year_is_that_fiscal_quarter():
    grid = _struct([["", "FY2025", ""], ["", "Q3", "Q4"], ["Revenue", "$3M", "$4M"]], header_rows=2, spans={(1, 2): 2})
    assert _status(grid, "r3c2", "2025-Q3", 3) == verify.VERIFIED
    assert _status(grid, "r3c3", "2025-Q4", 12) == verify.VERIFIED


@pytest.mark.parametrize("header, month, year_end, period, status", [
    ("FY2025", "Mar", 3, "2025-03", verify.VERIFIED),       # up to the year-end month: the named year
    ("FY2025", "Apr", 3, "2024-04", verify.VERIFIED),       # after it: the calendar year before
    ("FY2025", "Apr", 3, "2025-04", CORRECTED),             # read literally: Python's April 2024 replaces it
    ("2025", "Jul", 6, "2024-07", verify.VERIFIED),         # a plain year header too
    ("2025", "Jul", 6, "2025-07", CORRECTED),
    ("2025", "Jun", 6, "2025-06", verify.VERIFIED),
    ("FY2025", "Apr", 12, "2025-04", verify.VERIFIED),      # December: unchanged
    ("2025", "Jul", 12, "2025-07", verify.VERIFIED),
])
def test_a_month_under_a_year_header_falls_inside_that_year(header, month, year_end, period, status):
    grid = _struct([["", header], ["", month], ["Revenue", "$5M"]], header_rows=2)
    assert _status(grid, "r3c2", period, year_end) == status
    got = _one(grid, "r3c2", period, year_end)
    assert got["period"] == f"FY{header[-4:]}-{got['period'][-2:]}" and got["period_cells"] == ["r2c2", "r1c2"]


def test_the_period_comes_from_the_lowest_period_header():
    quarters = _struct([["", "2025", "", "", ""], ["", "Q1", "Q2", "Q3", "Q4"], ["Revenue", "$1M", "$2M", "$3M", "$4M"]],
                       header_rows=2, spans={(1, 2): 4})
    got = _one(quarters, "r3c4", "2025")
    assert (got["period"], got["status"], got["checks"]["period_corrected"]) == ("2025-Q3", verify.VERIFIED, True), \
        "a quarterly value read as its year: its quarter replaces it"
    months = _struct([["", "2025", ""], ["", "Q3", ""], ["", "Jul", "Aug"], ["Revenue", "$1M", "$2M"]],
                     header_rows=3, spans={(1, 2): 2, (2, 2): 2})
    got = _one(months, "r4c2", "2025-Q3")
    assert (got["period"], got["period_cells"]) == ("FY2025-07", ["r3c2", "r1c2"]), "a month, then the year above it"
    by_row = _struct([["", "2025"], ["Jan", "£1M"]])
    assert _status(by_row, "r2c2", "2025") == verify.SUGGESTION, "period headers above and beside: no rule builds it"
    relative = _struct([["", "2025", ""], ["", "M1", "M2"], ["Revenue", "£1M", "£2M"]], header_rows=2,
                       spans={(1, 2): 2})
    assert _status(relative, "r3c2", "2025") == verify.SUGGESTION
    years_by_row = _struct([["", "Revenue"], ["FY2025", "£1M"]])
    assert _status(years_by_row, "r2c2", "FY2025") == verify.VERIFIED


def test_a_model_period_with_nothing_to_rebuild_from_is_period_not_rebuilt():
    no_period = _struct([["", "Plan"], ["Revenue", "£2M"]])
    got = _one(no_period, "r2c2", "2025")
    assert (got["status"], got["period"], got["checks"]["period"], got["period_cells"]) == \
        (verify.SUGGESTION, "2025", False, []), "the model's period stays, as an AI suggestion"


def test_a_null_period_matches_when_no_header_holds_a_period():
    no_period = _struct([["", "Plan"], ["Revenue", "£2M"]])
    assert _status(no_period, "r2c2", None) == verify.VERIFIED
    quarter_only = _struct([["", "Q3"], ["Revenue", "£2M"]])
    assert _status(quarter_only, "r2c2", None) == verify.VERIFIED, "Q3 with no year is no period"
    assert _status(quarter_only, "r2c2", "2025-Q3") == verify.SUGGESTION, "never inferred"
    by_row = _struct([["", "2025"], ["Jan", "£1M"]])
    assert _status(by_row, "r2c2", None) == verify.SUGGESTION, "a header period Python cannot rebuild"


def test_relative_columns_have_no_period_unless_a_cell_states_the_start_date():
    relative = _struct([["", "M1", "M2"], ["Revenue", "£1M", "£2M"]])
    assert _status(relative, "r2c3", None) == verify.VERIFIED
    assert _status(relative, "r2c3", "2025-02") == verify.SUGGESTION
    started = _struct([["Start: Jan 2025", "M1", "M2"], ["Revenue", "£1M", "£2M"]])
    got = _one(started, "r2c3", "2025-03")
    assert (got["status"], got["period"], got["period_cells"]) == (verify.VERIFIED, "2025-02", ["r1c3", "r1c1"])
    fiscal_start = _struct([["Start: Apr FY25", "Year 1"], ["Revenue", "£1M"]])
    assert _status(fiscal_start, "r2c2", "FY2025", 3) == verify.VERIFIED, \
        "April of FY25 is April 2024 with a March year-end: Year 1 is FY2025"
    assert _status(fiscal_start, "r2c2", "FY2025", 12) == verify.SUGGESTION, "a year long: no label replaces the model's"


def test_in_a_kpi_panel_the_top_line_of_the_box_is_its_header():
    panel = _struct([["23 Y/E"], ["Gross Profit £150K"], ["5K Users"]], header_rows=0, kind="kpi_panel")
    for c in panel["cells"]:
        c["box"] = 1
    assert _status(panel, "r2c1", "FY2023", metric="gross_profit") == verify.VERIFIED
    assert _status(panel, "r3c1", "FY2023", metric="users") == verify.VERIFIED
    other_box = _struct([["23 Y/E"], ["Gross Profit £150K"]], header_rows=0, kind="kpi_panel")
    other_box["cells"][0]["box"], other_box["cells"][1]["box"] = 1, 2
    assert _status(other_box, "r2c1", "FY2023") == verify.SUGGESTION, "another box's line is no header"


DECKS = BACKEND.parent / "tests" / "fixtures" / "decks" / "decks"


def _deck_structure(file, page, kind):
    pytest.importorskip("pdfplumber")
    pytest.importorskip("docx")
    from app.decks import parser
    deck = parser.parse_deck((DECKS / file).read_bytes(), file)
    return next(s for s in deck["structures"] if (s.get("slide") or s.get("page")) == page and s["type"] == kind)


def _text(structure, cell):
    return next(c["text"] for c in structure["cells"] if f"r{c['row']}c{c['col']}" == cell)


def test_a_period_in_the_items_own_cell_rebuilds_from_that_cell():
    """genesisai-2024 p5: "$8,000 revenue in 2022" states its own period; no header holds one."""
    panel = _deck_structure("09-genesisai-2024.pdf", 5, "kpi_panel")
    assert _text(panel, "r1c1") == "$8,000 revenue in 2022"
    got = _one(panel, "r1c1", "2022", unit="USD")
    assert (got["status"], got["period"], got["period_cells"], got["checks"]["period_corrected"]) == \
        (verify.VERIFIED, "2022", ["r1c1"], False)
    got = _one(panel, "r1c1", "2021", unit="USD")
    assert (got["status"], got["period"], got["model_period"]) == (verify.VERIFIED, "2022", "2021")
    table = _struct([["", "Plan"], ["Revenue", "£1.2m in 2023"], ["Costs", "£0.4m"]])
    assert _status(table, "r2c2", "2023") == verify.VERIFIED
    assert _status(table, "r3c2", "2023") == verify.SUGGESTION, "another cell's period is not its own"


# ---------------------------------------------------------------------------
# The adjacent date line (docs/specs/structure-labelling.md section 2): a text line of a roadmap with exactly one
# date line directly above or below it in the same text box has that date line as a period cell
# ---------------------------------------------------------------------------
def _roadmap(rows, boxes):
    structure = _struct(rows, header_rows=0, kind="roadmap")
    for c in structure["cells"]:
        c["box"] = boxes[(c["row"], c["col"])] if isinstance(boxes, dict) else boxes[c["col"] - 1]
    return structure


def _adjacent(structure, cell):
    by_id = {f"r{c['row']}c{c['col']}": c for c in structure["cells"]}
    found = verify.adjacent_date_line(structure, by_id[cell])
    return f"r{found['row']}c{found['col']}" if found else None


def test_a_text_line_with_one_date_line_directly_above_or_below_it_in_its_box_takes_it():
    below = _roadmap([["Launch the API"], ["Q3 2025"]], [1])
    assert _adjacent(below, "r1c1") == "r2c1"
    above = _roadmap([["Q3 2025"], ["Launch the API"]], [1])
    assert _adjacent(above, "r2c1") == "r1c1"


def test_one_date_line_on_each_side_is_no_adjacent_date_line():
    both = _roadmap([["Q3 2025"], ["Launch the API"], ["Q4 2025"]], [1])
    assert _adjacent(both, "r2c1") is None


def test_only_a_date_line_directly_next_to_the_line_in_the_same_box_counts():
    other_box = _roadmap([["Q3 2025"], ["Launch the API"]], {(1, 1): 1, (2, 1): 2})
    assert _adjacent(other_box, "r2c1") is None, "the date line above sits in another box"
    gap = _roadmap([["Q3 2025"], ["Our API"], ["Launch the API"]], [1])
    assert _adjacent(gap, "r3c1") is None, "a line between"
    beside = _roadmap([["Launch the API", "Q3 2025"]], [1, 1])
    assert _adjacent(beside, "r1c1") is None, "beside it is not above or below"
    dates = _roadmap([["Q3 2025"], ["Q4 2025"]], [1])
    assert _adjacent(dates, "r1c1") is None, "a date line is not a text line"
    panel = {**_roadmap([["Launch the API"], ["Q3 2025"]], [1]), "type": "kpi_panel"}
    assert _adjacent(panel, "r1c1") is None, "roadmaps only"


def test_a_timeline_with_dates_below_its_lines_dates_every_line_from_below():
    """Decisions of 2026-10-06: a line with a date line on each side takes the one in the timeline's direction, decided
    once from its lines with a date on one side only: here the first line alone, date below."""
    below = _roadmap([["Launched web app"], ["January 2011"], ["Launch the API"], ["October 2011"],
                      ["Integrated in 50 apps"], ["December 2011"]], [1])
    assert [_adjacent(below, cell) for cell in ("r1c1", "r3c1", "r5c1")] == ["r2c1", "r4c1", "r6c1"]
    tail = _roadmap([["Launched web app"], ["January 2011"], ["Launch the API"], ["October 2011"], ["Series A"]], [1])
    assert _adjacent(tail, "r5c1") == "r4c1", "a line with a date on one side only keeps it, whatever the direction"


def test_a_timeline_with_dates_above_its_lines_dates_every_line_from_above():
    """Here the only line with a date on one side only is the last one, its date above."""
    above = _roadmap([["January 2011"], ["Launched web app"], ["October 2011"], ["Launch the API"],
                      ["December 2011"], ["Integrated in 50 apps"]], [1])
    assert [_adjacent(above, cell) for cell in ("r2c1", "r4c1", "r6c1")] == ["r1c1", "r3c1", "r5c1"]


def test_the_date_direction_is_decided_once_for_the_whole_timeline():
    """The one-sided line sits in box 1 (date below); box 2's line with a date on each side follows it."""
    timeline = _roadmap([["Launch the API", "Q2 2025"], ["Q3 2025", "Hire 5 engineers"], ["", "Q4 2025"]],
                        {(1, 1): 1, (2, 1): 1, (1, 2): 2, (2, 2): 2, (3, 2): 2})
    assert (_adjacent(timeline, "r1c1"), _adjacent(timeline, "r2c2")) == ("r2c1", "r3c2")
    flipped = _roadmap([["Q1 2025", "Q2 2025"], ["Launch the API", "Hire 5 engineers"], ["", "Q4 2025"]],
                       {(1, 1): 1, (2, 1): 1, (1, 2): 2, (2, 2): 2, (3, 2): 2})
    assert (_adjacent(flipped, "r2c1"), _adjacent(flipped, "r2c2")) == ("r1c1", "r1c2"), "box 1 decides: date above"
    boxes = {(1, 1): 1, (2, 1): 1, (1, 2): 2, (2, 2): 2, (1, 3): 3, (2, 3): 3, (3, 3): 3}
    disagree = _roadmap([["Launch the API", "Q1 2025", "Q2 2025"], ["Q3 2025", "Hire 5 engineers", "Break even"],
                         ["", "", "Q4 2025"]], boxes)
    assert _adjacent(disagree, "r2c3") == "r1c3", \
        "one-sided lines disagree (below in box 1, above in box 2): only the one holding a figure counts, date above"
    neither = _roadmap([["Launch the API", "Q1 2025", "Q2 2025"], ["Q3 2025", "Hire engineers", "Break even"],
                        ["", "", "Q4 2025"]], boxes)
    assert _adjacent(neither, "r2c3") is None, "they disagree and neither holds a figure: no direction"


def test_a_title_over_a_timeline_with_dates_above_does_not_turn_it_downwards():
    """The title has a date line below only, the last line one above only. They disagree, so only the lines holding a
    figure count: the last line, date above."""
    titled = _roadmap([["Product roadmap"], ["January 2011"], ["Launched web app"], ["October 2011"],
                       ["55,000 users"], ["December 2011"], ["100,000 users"]], [1])
    assert [_adjacent(titled, cell) for cell in ("r3c1", "r5c1", "r7c1")] == ["r2c1", "r4c1", "r6c1"]
    no_figure = _roadmap([["Product roadmap"], ["January 2011"], ["55,000 users"], ["October 2011"],
                          ["Launch the API"]], [1])
    assert (_adjacent(no_figure, "r3c1"), _adjacent(no_figure, "r5c1")) == (None, "r4c1"), \
        "neither the title nor the last line holds a figure: no direction, the one-sided line keeps its date"
    quarter = _roadmap([["Q3"], ["2025"], ["55,000 users"], ["2026"], ["Launch the API"]], [1])
    assert _adjacent(quarter, "r3c1") is None, "a period header such as Q3 holds no figure (section 1 lists none)"


def test_a_title_over_a_timeline_with_dates_below_leaves_it_unchanged():
    """The title sits over the first line, not over a date line, so it has no date line; the first line alone has
    one on one side only, below. A rule ignoring the lines before the first date line would leave no direction."""
    plain = [["Launched web app"], ["January 2011"], ["55,000 users"], ["October 2011"], ["100,000 users"],
             ["December 2011"]]
    titled = _roadmap([["Product roadmap"]] + plain, [1])
    assert [_adjacent(titled, cell) for cell in ("r1c1", "r2c1", "r4c1", "r6c1")] == [None, "r3c1", "r5c1", "r7c1"]
    untitled = _roadmap(plain, [1])
    assert [_adjacent(untitled, cell) for cell in ("r1c1", "r3c1", "r5c1")] == ["r2c1", "r4c1", "r6c1"]


def test_on_the_buffer_timeline_every_line_takes_the_date_below_it():
    """Buffer p6 alternates line, date, line, date in one box: the first line has its date below only, so the timeline
    runs downwards and every later line, with a date above and below, takes the one below."""
    roadmap = _deck_structure("03-buffer.pptx", 6, "roadmap")
    assert [(cell, _adjacent(roadmap, cell)) for cell in ("r1c1", "r3c1", "r5c1", "r7c1", "r9c1", "r11c1")] == \
        [("r1c1", "r2c1"), ("r3c1", "r4c1"), ("r5c1", "r6c1"), ("r7c1", "r8c1"), ("r9c1", "r10c1"), ("r11c1", "r12c1")]


# What the moz p2 and TEA p11 timelines gave before the date direction (2026-10-06): no line has a date line on each
# side, so nothing changes. Every other text line has no adjacent date line.
BEFORE_DIRECTION = {("02-moz.pdf", 2): {},
                    ("10-tea.pdf", 11): {"r2c1": "r1c1", "r2c4": "r1c4", "r8c1": "r7c1", "r8c4": "r7c4",
                                         "r10c1": "r9c1", "r10c4": "r9c4", "r14c1": "r13c1", "r14c4": "r13c4"}}


@pytest.mark.parametrize("deck, page", list(BEFORE_DIRECTION))
def test_timelines_with_no_line_dated_on_both_sides_are_unchanged(deck, page):
    roadmap = _deck_structure(deck, page, "roadmap")
    lines = [f"r{c['row']}c{c['col']}" for c in roadmap["cells"] if not verify.is_date_line(c["text"])]
    assert {cell: _adjacent(roadmap, cell) for cell in lines if _adjacent(roadmap, cell)} == BEFORE_DIRECTION[(deck, page)]


# ---------------------------------------------------------------------------
# Roadmaps: the adjacent date line, pair-dated figures and milestones
# ---------------------------------------------------------------------------
def _boxed(rows, box=1):
    structure = _struct(rows, header_rows=0, kind="roadmap")
    for c in structure["cells"]:
        c["box"] = box
    return structure


def test_in_a_roadmap_a_line_takes_its_period_from_its_adjacent_date_line():
    roadmap = _boxed([["5K users"], ["Q3 2025"]])
    got = _one(roadmap, "r1c1", None, metric="users")
    assert (got["status"], got["period"], got["period_cells"]) == (verify.VERIFIED, "2025-Q3", ["r2c1"])
    both = _boxed([["Plan"], ["Q2 2025"], ["5K users"], ["Q3 2025"]])
    got = _one(both, "r3c1", None, metric="users")
    assert (got["status"], got["period"], got["period_cells"]) == (verify.VERIFIED, "2025-Q3", ["r4c1"]), \
        "a date on each side: the timeline runs downwards from Plan, so the one below"


def test_a_paired_line_takes_its_position_date_and_its_figure_is_verified():
    """Spec section 2 (decision of 2026-10-06 on issue #47, option a): a paired line with a position date takes it,
    whatever date the model paired: Python builds it, so the milestone carries it and a figure in the line is
    Verified with it; a model period that differs is a period corrected."""
    agree = _boxed([["5K users"], ["Q3 2025"], ["Hire 5 engineers"], ["Q4 2025"]])
    out = _verify(agree, {"r1c1": _lab("2025-Q4", "users")}, pairs=[("r1c1", "r4c1", "launch")])
    got = next(i for i in out["items"] if i.get("item") == "i1")
    assert (got["status"], got["period"], got["period_cells"], got["model_period"]) == \
        (verify.VERIFIED, "2025-Q3", ["r2c1"], "2025-Q4"), "paired with Q4, but its date line below is Q3"
    milestone, = [i for i in out["items"] if "line" in i]
    assert (milestone["date"], milestone["period"], milestone["period_cells"], milestone["status"]) == \
        ("d2", "2025-Q3", ["r2c1"], verify.SUGGESTION), "the model's date id stays; the period is Python's"
    roadmap = _deck_structure("03-buffer.pptx", 6, "roadmap")
    assert _text(roadmap, "r3c1") == "55,000 users ($150K revenue)"
    out = _verify(roadmap, {("r3c1", 1): _lab("2011-01", "users", "count", "actual")},
                  pairs=[("r3c1", "r2c1", "other")])
    got = next(i for i in out["items"] if i.get("item") and i["value_cell"] == "r3c1" and i["position"] == 1)
    assert (got["status"], got["period"], got["period_cells"]) == (verify.VERIFIED, "2011-10", ["r4c1"]), \
        "buffer p6: paired with the date above, dated by its date line below"


def test_a_paired_line_with_no_position_date_keeps_the_models_date_and_needs_its_own_cells():
    """Spec section 2: with no adjacent date line and no date box beside it, the pair's date stands, and a figure is
    Verified only when Python rebuilds the same period from its own period cells."""
    apart = _roadmap([["5K users", "Q3 2025"]], [1, 2])
    out = _verify(apart, {"r1c1": _lab("2025-Q3", "users")}, pairs=[("r1c1", "r1c2", "launch")])
    got = next(i for i in out["items"] if i.get("item") == "i1")
    assert (got["status"], got["period"], got["period_cells"]) == (verify.SUGGESTION, "2025-Q3", ["r1c2"])
    milestone, = [i for i in out["items"] if "line" in i]
    assert (milestone["period"], milestone["period_cells"]) == ("2025-Q3", ["r1c2"])


def _positions(file, page):
    roadmap = _deck_structure(file, page, "roadmap")
    out = {}
    for line in items.list_items(roadmap)["lines"]:
        cell = next(c for c in roadmap["cells"] if f"r{c['row']}c{c['col']}" == line["cell"])
        found = verify.position_date(roadmap, cell)
        out[line["cell"]] = (found[0], found[2]) if found else None
    return out


def test_tea_p11_lines_take_the_quarter_of_the_date_box_beside_them():
    """Spec section 2: a date box of a year with a quarter below it gives that quarter (the two-cell rule). The
    "Q2"-style lines of the date boxes are text lines with their year line above. "Mainnet starts" sits beside
    "2023" / "Q1-Q2", which is no date box, so it has no position date."""
    got = _positions("10-tea.pdf", 11)
    box = lambda label, part, year: (label, [part, year])  # noqa: E731
    assert got == {
        "r1c2": box("2021-Q2", "r2c1", "r1c1"), "r1c3": box("2021-Q3", "r2c4", "r1c4"), "r2c1": ("2021", ["r1c1"]),
        "r2c2": box("2021-Q2", "r2c1", "r1c1"), "r2c3": box("2021-Q3", "r2c4", "r1c4"), "r2c4": ("2021", ["r1c4"]),
        "r3c2": box("2021-Q2", "r2c1", "r1c1"), "r3c3": box("2021-Q3", "r2c4", "r1c4"),
        "r4c2": box("2021-Q2", "r2c1", "r1c1"), "r4c3": box("2021-Q3", "r2c4", "r1c4"),
        "r5c2": box("2021-Q2", "r2c1", "r1c1"), "r6c2": box("2021-Q2", "r2c1", "r1c1"),
        "r7c2": box("2021-Q4", "r8c1", "r7c1"), "r7c3": box("2022-Q1", "r8c4", "r7c4"), "r8c1": ("2021", ["r7c1"]),
        "r8c2": box("2021-Q4", "r8c1", "r7c1"), "r8c3": box("2022-Q1", "r8c4", "r7c4"), "r8c4": ("2022", ["r7c4"]),
        "r9c2": box("2022-Q2", "r10c1", "r9c1"), "r9c3": box("2022-Q3", "r10c4", "r9c4"),
        "r10c1": ("2022", ["r9c1"]), "r10c2": box("2022-Q2", "r10c1", "r9c1"), "r10c4": ("2022", ["r9c4"]),
        "r11c2": box("2022-Q2", "r10c1", "r9c1"), "r12c2": box("2022-Q2", "r10c1", "r9c1"),
        "r13c2": box("2022-Q4", "r14c1", "r13c1"), "r13c3": None, "r14c1": ("2022", ["r13c1"]),
        "r14c2": box("2022-Q4", "r14c1", "r13c1"), "r14c4": ("2023", ["r13c4"])}


def test_moz_p2_paragraphs_take_their_date_box_and_buffer_p6_lines_their_date_line_below():
    assert _positions("02-moz.pdf", 2) == {
        "r1c1": ("1997", ["r2c1"]), "r1c2": ("2004", ["r2c2"]), "r1c3": ("2007-11", ["r2c3"]),
        "r1c4": ("2010-09", ["r2c4"]), "r4c1": ("1981", ["r3c1"]), "r4c2": ("2001", ["r3c2"]),
        "r4c3": ("2007-02", ["r3c3"]), "r4c4": ("2008-10", ["r3c4"]), "r4c5": ("2011-07", ["r3c5"])}
    assert _positions("03-buffer.pptx", 6) == {
        "r1c1": ("2011-01", ["r2c1"]), "r3c1": ("2011-10", ["r4c1"]), "r5c1": ("2011-10", ["r6c1"]),
        "r7c1": ("2011-12", ["r8c1"]), "r9c1": ("2012-01", ["r10c1"]), "r11c1": ("2013-01", ["r12c1"])}


def test_a_date_box_gives_a_date_only_as_one_date_or_a_year_with_a_part_below_it():
    def dated(texts):
        roadmap = _roadmap([["Launch"] + texts], [1] + [2] * len(texts))
        for c in roadmap["cells"]:
            c["row"], c["col"] = (c["col"] - 1, 2) if c["box"] == 2 else (1, 1)
        roadmap["cells"][0]["date_box"] = 2
        found = verify.position_date(roadmap, roadmap["cells"][0])
        return found and found[1]
    assert [dated(["2021", "Q2"]), dated(["Nov. 2007"]), dated(["2021", "H2"]), dated(["2021", "Mar"])] == \
        [("2021-04-01", "2021-06-30"), ("2007-11-01", "2007-11-30"), ("2021-07-01", "2021-12-31"),
         ("2021-03-01", "2021-03-31")], "start and end dates, as the two-cell rule builds them"
    assert [dated(["Q2", "2021"]), dated(["2021", "2022"]), dated(["2021", "Q2", "Q3"])] == [None, None, None], \
        "a part above its year, two years, two parts: no one date"


def test_each_pair_is_a_milestone_dated_by_its_date_cell_and_never_verified():
    roadmap = _boxed([["Launch the API"], ["Q3 2025"], ["Hire 5 engineers"], ["Q4 2025"], ["Seed round"], ["2026"]])
    out = _verify(roadmap, {"r3c1": _lab(None, "people", "count")},
                  pairs=[("r1c1", "r2c1", "launch"), ("r3c1", "r4c1", "hiring"), ("r5c1", "r6c1", "funding")])
    milestones = [i for i in out["items"] if "line" in i]
    assert [(m["line"], m["date"], m["category"], m["metric"], m["period"], m["value"], m["value_cell"],
             m["period_cells"], m["status"]) for m in milestones] == [
        ("t1", "d1", "launch", "product", "2025-Q3", None, "r1c1", ["r2c1"], verify.SUGGESTION),
        ("t2", "d2", "hiring", "people", "2025-Q4", None, "r3c1", ["r4c1"], verify.SUGGESTION),
        ("t3", "d3", "funding", "other", "2026", None, "r5c1", ["r6c1"], verify.SUGGESTION)]
    assert all(m["item"] == m["line"] and m["checks"]["period"] for m in milestones)
    out = _verify(roadmap, {}, pairs=[("r1c1", "r2c1", "launch")], mode="drop")
    assert not [i for i in out["items"] if "line" in i] and out["dropped"] >= 1, "the switch applies to milestones"


# ---------------------------------------------------------------------------
# Separator and sign: both readings come from the item's cell, the default is recorded
# ---------------------------------------------------------------------------
def test_a_dot_reading_is_recorded_with_the_default_and_the_item_can_be_verified():
    """clevergig p7: "Approx. 2.500 hours" is 2,500 hours written with a dot."""
    panel = _deck_structure("04-clevergig.docx", 7, "kpi_panel")
    assert _text(panel, "r4c1") == "Approx. 2.500 hours"
    got = _one(panel, "r4c1", None, metric="product")
    assert (got["status"], got["value"], got["checks"]["dot_reading"]) == (verify.VERIFIED, 2500, "thousands")
    assert [v["value"] for v in got["values"]] == [2500, 2.5], "both readings, the default first"


def test_a_bracket_reading_is_recorded_with_the_default_and_the_item_can_be_verified():
    """zero2hero p17: "Telegram(30K)" is 30,000 members; "Net loss (1,200)" a loss."""
    panel = _deck_structure("05-zero2hero.pdf", 17, "kpi_panel")
    assert _text(panel, "r1c1") == "Telegram(30K)"
    got = _one(panel, "r1c1", None, metric="users", unit="count")
    assert (got["status"], got["value"], got["checks"]["bracket_reading"]) == (verify.VERIFIED, 30000, "positive")
    loss = _struct([["", "2025"], ["EBITDA", "Net loss (1,200)"]])
    got = _one(loss, "r2c2", "2025", metric="ebitda")
    assert (got["status"], got["value"], got["checks"]["bracket_reading"]) == (verify.VERIFIED, -1200, "negative")
    assert [v["value"] for v in got["values"]] == [-1200, 1200]


@pytest.mark.parametrize("metric", ["customers", "users", "people"])
def test_a_bracketed_level_keeps_the_positive_reading_only(metric):
    """Issue #46, zero2hero p17: a count of customers, users or people is never below zero, so "Telegram(30K)"
    labelled one has one value, and its approval row shows one."""
    panel = _deck_structure("05-zero2hero.pdf", 17, "kpi_panel")
    assert [v["value"] for v in items.list_items(panel)["items"][0]["values"]] == [30000, -30000], "listed with both"
    got = _one(panel, "r1c1", None, metric=metric, unit="count")
    assert [v["value"] for v in got["values"]] == [30000], "the negative reading is dropped"
    assert (got["status"], got["value"], got["checks"]["bracket_reading"]) == (verify.VERIFIED, 30000, "positive")


def test_a_bracketed_growth_keeps_both_readings_and_a_whole_cell_bracket_stays_negative():
    panel = _deck_structure("05-zero2hero.pdf", 17, "kpi_panel")
    got = _one(panel, "r1c1", None, metric="user_growth", unit="count")
    assert [v["value"] for v in got["values"]] == [30000, -30000], "user_growth keeps both readings"
    whole = _struct([["Users"], ["(30K)"]], header_rows=1)
    got = _one(whole, "r2c1", None, metric="users", unit="count")
    assert [v["value"] for v in got["values"]] == [-30000] and got["checks"]["bracket_reading"] is None, \
        "brackets around a whole cell: accounting style, negative only"


# ---------------------------------------------------------------------------
# Metrics: not_a_metric dropped and counted, other never verified
# ---------------------------------------------------------------------------
def test_not_a_metric_items_are_dropped_and_counted():
    out = _verify(PLAN, {"r2c2": _lab("FY2025")})
    assert [i["value_cell"] for i in out["items"]] == ["r2c2"] and out["not_a_metric"] == 1
    assert out["dropped"] == 0, "not the switch's count"


def test_an_other_item_is_listed_as_type_other_and_never_verified():
    got = _one(PLAN, "r2c2", "FY2025", metric="other")
    assert (got["metric"], got["status"], got["checks"]["period"]) == ("other", verify.SUGGESTION, True)


# ---------------------------------------------------------------------------
# Flags: computed by Python over the Verified items
# ---------------------------------------------------------------------------
TOTALS = _struct([["", "2025"], ["Product A", "£100"], ["Product B", "£200"], ["Total revenue", "£350"]])


def test_python_computes_a_total_mismatch_over_the_verified_items():
    labels = {cell: _lab("2025", unit="GBP") for cell in ("r2c2", "r3c2", "r4c2")}
    out = _verify(TOTALS, labels)
    assert [i["proposed_flags"] for i in out["items"]] == [[], [], ["total_mismatch"]]
    assert all(i["status"] == verify.VERIFIED for i in out["items"]), "a flag never changes the status"
    right = _struct([["", "2025"], ["Product A", "£100"], ["Product B", "£200"], ["Total revenue", "£300"]])
    assert [i["proposed_flags"] for i in _verify(right, labels)["items"]] == [[], [], []], "300 is the sum"
    unverified = {**labels, "r2c2": _lab("2025", metric="other", unit="GBP")}
    assert [i["proposed_flags"] for i in _verify(TOTALS, unverified)["items"]] == [[], [], []], \
        "over the Verified items only: one part is not, so the total has one part left"


def test_python_computes_a_growth_mismatch_over_the_verified_items():
    grid = _struct([["", "2024", "2025"], ["Revenue", "£100", "£120"], ["Revenue growth", "", "50%"]])
    labels = {"r2c2": _lab("2024"), "r2c3": _lab("2025"), "r3c3": _lab("2025", "revenue_growth", "%")}
    out = _verify(grid, labels)
    assert [i["proposed_flags"] for i in out["items"]] == [[], [], ["growth_mismatch"]], "20%, not 50%"
    fine = _struct([["", "2024", "2025"], ["Revenue", "£100", "£120"], ["Revenue growth", "", "20%"]])
    assert [i["proposed_flags"] for i in _verify(fine, labels)["items"]] == [[], [], []]


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------
def test_unverified_items_are_suggestions_or_dropped_and_counted():
    labels = {"r2c2": _lab("FY2025"), "r2c3": _lab("FY2026", metric="other")}
    shown = _verify(PLAN, labels, mode="suggest")
    assert [i["status"] for i in shown["items"]] == [verify.VERIFIED, verify.SUGGESTION] and shown["dropped"] == 0
    dropped = _verify(PLAN, labels, mode="drop")
    assert [i["status"] for i in dropped["items"]] == [verify.VERIFIED] and dropped["dropped"] == 1
    assert verify.label(verify.SUGGESTION) == "AI suggestion, not verified" and verify.label(verify.VERIFIED) == "Verified"


@pytest.mark.parametrize("raw, mode", [("", "suggest"), ("drop", "drop"), ("DROP", "drop"), ("suggest", "suggest"),
                                       ("dorp", "suggest")])
def test_the_switch_defaults_to_suggest_and_a_typo_never_drops(monkeypatch, raw, mode):
    monkeypatch.setenv("STRUCTURE_UNMATCHED", raw)
    assert verify.unmatched_mode() == mode
