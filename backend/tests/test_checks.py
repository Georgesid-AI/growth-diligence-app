"""The cell checks (docs/design/read-check-review.md section 5, tests 2, 4, 6-10 of section 15; PR 2). Every case is a synthetic sheet; the
reasons are compared word for word with the design note's wording."""
import copy
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import checks  # noqa: E402
from app.structures import redact  # noqa: E402

MONTHS = ["Jan-24", "Feb-24", "Mar-24", "Apr-24", "May-24", "Jun-24", "Jul-24", "Aug-24", "Sep-24", "Oct-24", "Nov-24", "Dec-24"]
ACTUAL = [100, 110, 120, 130, 140, 150]                       # Jan to Jun
PLAN = [100, 105, 118, 128, 138, 148, 160, 170, 180, 190, 200, 210]
HEADER = 3


def build(changes=None):
    """{(row, col): text} of the report: title A1, header row 3 (B..M = Jan-24..Dec-24), revenue row 4 (actual to F... G=Jun), plan row 5,
    customers row 6 (stops at G), variance row 7, a total at row 8 with parts at rows 9 and 10."""
    cells = {(1, 1): "Monthly report, EUR", (2, 8): "Forecast", (HEADER, 1): "Metric"}
    for i, m in enumerate(MONTHS):
        cells[(HEADER, 2 + i)] = m
    cells[(4, 1)], cells[(5, 1)], cells[(6, 1)], cells[(7, 1)] = "Revenue", "Plan revenue", "Customers", "Variance"
    cells[(8, 1)], cells[(9, 1)], cells[(10, 1)] = "Total by product", "Product A", "Product B"
    for i in range(12):
        col = 2 + i
        cells[(4, col)] = str(ACTUAL[i]) if i < 6 else str(PLAN[i])        # the plan copied after June
        cells[(5, col)] = str(PLAN[i])
        if i < 6:
            cells[(6, col)] = str(20 + i)
        cells[(7, col)] = str((ACTUAL[i] if i < 6 else PLAN[i]) - PLAN[i])
        cells[(8, col)] = "200"
        cells[(9, col)] = "120"
        cells[(10, col)] = "80"
    for (r, c), v in (changes or {}).items():
        if v is None:
            cells.pop((r, c), None)
        else:
            cells[(r, c)] = v
    return cells


def cells_of(grid, name="Report"):
    return checks.Cells(redact.reading_text([{"name": name, "cells": [{"row": r, "col": c, "text": t} for (r, c), t in grid.items()]}]))


def row(**over):
    base = {"row": 4, "label_cell": "A4", "role": "revenue", "metric": "revenue", "basis": "monthly", "actual_plan": "mixed", "boundary_col": "G",
            "segment": None, "parent_row": None, "unit": "money", "currency": "EUR", "cells": "B4:M4", "variance_of": None, "by_column": False,
            "evidence": "Revenue row"}
    return {**base, **over}


def piece(kind, **over):
    base = {"kind": kind, "text": f"{kind} evidence", "row": None, "column": None, "cell": None, "cells": None, "other_cells": None,
            "word": None, "multiple": None}
    return {**base, **over}


def figure(value=ACTUAL[2], cell="D4", period="2024-03", **over):
    base = {"metric": "revenue", "value": float(value), "unit": "money", "currency": "EUR", "period": period, "basis": "monthly",
            "actual_plan": "actual", "segment": None, "source": {"sheet": "Report", "cell": cell, "page": None, "text_layer": None},
            "evidence": "Revenue row"}
    return {**base, **over}


def sheet_map(evidence=None, rows=None, last_actual=True, **over):
    ev = evidence if evidence is not None else [piece("row_ends", row=6, column="G", text="Customers stops at G")]
    base = {"sheet": "Report", "header_row": HEADER, "label_col": "A", "first_period_col": "B", "last_period_col": "M", "granularity": "monthly",
            "currency": "EUR", "currency_cell": "A1",
            "last_actual": {"column": "G", "period": "2024-06", "evidence": ev} if last_actual else None, "rows": rows if rows is not None else [row()]}
    return {**base, **over}


def fmap(sheet=None, figures=None):
    return {"map_version": 1, "kind": "sheet", "sheets": [sheet or sheet_map()], "figures": figures or []}


def check(m, grid=None, fye=12):
    return checks.check_map(cells_of(grid or build()), m, fye)


def item(result, key):
    return next(i for i in result["items"] if i["key"] == key)


FIG = "figure:Report:D4:revenue"


# ---------------------------------------------------------------------------
# Confirmed, within the tolerances of section 5 (test 6)
# ---------------------------------------------------------------------------
def test_a_value_within_tolerance_is_confirmed_and_raises_no_card():
    grid = build({(4, 4): "447223.43"})
    got = item(check(fmap(figures=[figure(447223, period="2024-03")]), grid), FIG)
    assert got["outcome"] == checks.CONFIRMED and got["reason"] is None


def test_a_figure_with_no_unit_is_not_given_one_from_its_metric_name():
    """The reader states the unit. A churn rate or a customer count with no unit is compared with no tolerance at all: cannot check."""
    for metric, value, cell in (("churn_rate", 0.05, "0.045"), ("customers", 101, "100"), ("revenue", 100_000, "100500")):
        got = item(check(fmap(figures=[figure(value, unit=None, metric=metric)]), build({(4, 4): cell})), f"figure:Report:D4:{metric}")
        assert (got["outcome"], got["reason"]) == (checks.CANNOT, "No unit given; not compared."), metric
    text = item(check(fmap(figures=[figure(5, unit=None)]), build({(4, 4): "tbc"})), FIG)
    assert text["outcome"] == checks.REJECTED, "a cell that is no number is wrong whatever the unit"


@pytest.mark.parametrize("unit, reading, cell, outcome", [
    ("money", 100_000, "100500", checks.CONFIRMED),            # 0.5 % of the cell is 502.5
    ("money", 100_000, "100600", checks.REJECTED),
    ("count", 100, "100", checks.CONFIRMED),
    ("count", 101, "100", checks.REJECTED),                    # counts are exact
    ("rate", 0.05, "0.045", checks.CONFIRMED),                 # within one point
    ("rate", 0.06, "0.045", checks.REJECTED),
    ("rate", 4.0, "4.9", checks.CONFIRMED),                    # a rate written as a percent is compared in points
    ("rate", 6.5, "4.9", checks.REJECTED),
    ("money", 1200, "1,200", checks.CONFIRMED),                # a thousands comma is not a different number
    ("money", 1200, "(1,200)", checks.REJECTED),               # a bracket is a minus
    ("money", 1200, "n/a", checks.REJECTED),
])
def test_the_tolerances_of_each_unit(unit, reading, cell, outcome):
    got = item(check(fmap(figures=[figure(reading, unit=unit)]), build({(4, 4): cell})), FIG)
    assert got["outcome"] == outcome, got


def test_a_rejection_says_what_the_reading_said_and_what_the_cell_holds_in_the_notes_words():
    got = item(check(fmap(figures=[figure(450000)]), build({(4, 4): "447223.43"})), FIG)
    assert (got["outcome"], got["reason"]) == (checks.REJECTED, "Reading says 450000; cell D4 holds 447223.43.")
    empty = item(check(fmap(figures=[figure(5)]), build({(4, 4): None})), FIG)
    assert empty["reason"] == "Reading says 5; cell D4 holds nothing."


# ---------------------------------------------------------------------------
# Rejected: the period of the column (test 7), a cell outside the sheet
# ---------------------------------------------------------------------------
def test_a_column_off_by_one_is_rejected_with_the_header_period_reason():
    got = item(check(fmap(figures=[figure(ACTUAL[2], cell="D4", period="2024-02")])), FIG)
    assert (got["outcome"], got["reason"]) == (checks.REJECTED, "Reading says 2024-02; cell D3 is the header for 2024-03.")
    right = item(check(fmap(figures=[figure(ACTUAL[2], cell="D4", period="2024-03")])), FIG)
    assert right["outcome"] == checks.CONFIRMED


@pytest.mark.parametrize("header, period", [("Q1 2024", "2024-Q1"), ("2024-03-31", "2024-03"), ("Mar 2024", "2024-03"), ("FY2024", "2024"),
                                            ("2024A", "2024")])
def test_headers_in_other_forms_read_as_the_period_they_name(header, period):
    got = item(check(fmap(figures=[figure(ACTUAL[2], period=period)]), build({(HEADER, 4): header})), FIG)
    assert got["outcome"] == checks.CONFIRMED, (header, got)


def test_a_header_that_names_no_period_is_a_rejection_never_a_confirmation():
    got = item(check(fmap(figures=[figure(ACTUAL[2], period="2024-03")]), build({(HEADER, 4): "Notes"})), FIG)
    assert (got["outcome"], got["reason"]) == (checks.REJECTED, "Reading says 2024-03; cell D3 is the header for Notes.")


def test_a_cell_outside_the_sheet_is_rejected_with_the_column_it_ends_at():
    far = item(check(fmap(figures=[figure(1, cell="ZZ4")])), "figure:Report:ZZ4:revenue")
    assert (far["outcome"], far["reason"]) == (checks.REJECTED, "Reading cites ZZ4; the sheet ends at column M.")
    low = item(check(fmap(figures=[figure(1, cell="B40")])), "figure:Report:B40:revenue")
    assert low["reason"] == "Reading cites B40; the sheet ends at row 10."
    nameless = item(check(fmap(figures=[figure(1, source={"sheet": "Nowhere", "cell": "B4", "page": None, "text_layer": None})])),
                    "figure:Nowhere:B4:revenue")
    assert nameless["reason"] == "Reading cites sheet Nowhere; the file has no such sheet."


# ---------------------------------------------------------------------------
# Cannot check: the five cases, each explicit (tests 4 and 10)
# ---------------------------------------------------------------------------
def test_a_figure_with_no_cell_reference_cannot_be_checked_and_is_never_confirmed():
    for source in (None, {"sheet": "Report", "cell": None, "page": None, "text_layer": None}):
        got = checks.check_figure(0, figure(5, source=source), cells_of(build()), {}, 12)
        assert (got["outcome"], got["reason"]) == (checks.CANNOT, "No cell reference given.")


def test_a_deck_page_without_a_text_layer_cannot_be_checked():
    got = checks.check_figure(0, figure(5, source={"sheet": None, "cell": None, "page": 7, "text_layer": False}), cells_of(build()), {}, 12)
    assert (got["outcome"], got["reason"]) == (checks.CANNOT, "Page 7 has no text layer; figure read from the image.")


def test_a_row_that_describes_the_layout_only_has_no_cell_to_open():
    got = item(check(fmap(sheet_map(rows=[row(label_cell=None, cells=None)]))), "row:Report:4")
    assert (got["outcome"], got["reason"]) == (checks.CANNOT, "This describes the layout, not a value; no cell to open.")


def test_a_unit_or_scale_that_differs_is_not_compared_percentages_stored_as_fractions_included():
    thousands = item(check(fmap(figures=[figure(447.22)]), build({(4, 4): "447223.43"})), FIG)
    assert (thousands["outcome"], thousands["reason"]) == (
        checks.CANNOT, "Cell D4 holds 447223.43; reading says 447.22. Unit or scale differs; not compared.")
    as_percent = item(check(fmap(figures=[figure(4.5, unit="rate")]), build({(4, 4): "0.045"})), FIG)
    assert as_percent["outcome"] == checks.CANNOT and as_percent["reason"].endswith("Unit or scale differs; not compared.")
    as_fraction = item(check(fmap(figures=[figure(0.045, unit="rate")]), build({(4, 4): "0.045"})), FIG)
    assert as_fraction["outcome"] == checks.CONFIRMED
    text_percent = item(check(fmap(figures=[figure(0.045, unit="rate")]), build({(4, 4): "4.5%"})), FIG)
    assert text_percent["outcome"] == checks.CONFIRMED, "a percent written as text is the same fraction"


def test_a_figure_whose_cell_was_masked_before_reading_cannot_be_compared():
    got = item(check(fmap(figures=[figure(5)]), build({(4, 4): "[email]"})), FIG)
    assert (got["outcome"], got["reason"]) == (checks.CANNOT, "Depends on a name that was masked before reading.")
    row_cell = item(check(fmap(), build({(4, 5): "[person]"})), "row:Report:4")
    assert (row_cell["outcome"], row_cell["reason"]) == (checks.CANNOT, "Depends on a name that was masked before reading.")


def test_a_name_masked_before_reading_cannot_be_compared():
    grid = build({(2, 8): "[person]"})
    ev = [piece("label_contains", cell="H2", word="Forecast", text="Forecast title")]
    got = item(check(fmap(sheet_map(evidence=ev)), grid), "evidence:Report:0")
    assert (got["outcome"], got["reason"]) == (checks.CANNOT, "Depends on a name that was masked before reading.")


def test_a_masked_name_in_a_citation_is_compared_in_masked_space_and_confirmed():
    """Test 8: the reader saw Client-03; the cell, as sent, holds Client-03 revenue; the word it cites is the token."""
    grid = build({(2, 8): "Client-03 forecast"})
    ev = [piece("label_contains", cell="H2", word="Client-03", text="Client-03 forecast title")]
    got = item(check(fmap(sheet_map(evidence=ev)), grid), "evidence:Report:0")
    assert got["outcome"] == checks.CONFIRMED


# ---------------------------------------------------------------------------
# Rows: variance, parts
# ---------------------------------------------------------------------------
def test_a_variance_row_that_is_not_actual_minus_plan_is_rejected_with_the_count_of_periods():
    bad = build({(7, 5): "99", (7, 9): "5"})
    var = row(row=7, label_cell="A7", role="variance", actual_plan="variance", cells="B7:M7", variance_of={"actual_row": 4, "plan_row": 5})
    got = item(check(fmap(sheet_map(rows=[row(), row(row=5, label_cell="A5", role="forecast", cells="B5:M5"), var])), bad), "variance:Report:7")
    assert (got["outcome"], got["reason"]) == (checks.REJECTED, "Variance row A7 does not equal actual minus budget in 2 of 12 periods.")
    ok = item(check(fmap(sheet_map(rows=[row(), row(row=5, label_cell="A5", role="forecast", cells="B5:M5"), var]))), "variance:Report:7")
    assert ok["outcome"] == checks.CONFIRMED


def test_parts_that_do_not_sum_to_their_named_total_are_rejected_with_the_cells_and_the_sum():
    rows = [row(row=8, label_cell="A8", role="revenue", cells="B8:M8"),
            row(row=9, label_cell="A9", segment="Product A", parent_row=8, cells="B9:M9"),
            row(row=10, label_cell="A10", segment="Product B", parent_row=8, cells="B10:M10")]
    got = item(check(fmap(sheet_map(rows=rows)), build({(8, 4): "260"})), "parts:Report:8")
    assert (got["outcome"], got["reason"]) == (checks.REJECTED, "Parts D9, D10 sum to 200; the reading names D8 as their total, which holds 260.")
    assert item(check(fmap(sheet_map(rows=rows))), "parts:Report:8")["outcome"] == checks.CONFIRMED


def test_a_row_whose_cells_hold_text_where_numbers_are_expected_is_rejected():
    got = item(check(fmap(), build({(4, 5): "tbc"})), "row:Report:4")
    assert (got["outcome"], got["reason"]) == (checks.REJECTED, "Reading says a number; cell E4 holds tbc.")
    assert item(check(fmap(sheet_map(rows=[row(cells="B4:ZZ4")]))), "row:Report:4")["reason"] == "Reading cites ZZ4; the sheet ends at column M."


# ---------------------------------------------------------------------------
# The as-of month stands on confirmed evidence (section 6; test 2)
# ---------------------------------------------------------------------------
def months(result):
    return [(m["month"], m["column"]) for m in result["months"]]


def test_a_confirmed_row_end_at_the_boundary_column_makes_the_month():
    got = check(fmap())
    assert months(got) == [("2024-06", "G")]
    assert item(got, "last_actual:Report")["outcome"] == checks.CONFIRMED and item(got, "evidence:Report:0")["supports"] is True


def test_one_row_that_keeps_going_is_rejected_and_the_month_stands_on_the_rest():
    """Test 2: the Customers row stops at G, the Churn row claimed to stop at G does not."""
    grid = build({(11, 1): "Churn", **{(11, c): "1" for c in range(2, 11)}})          # churn runs B..J
    ev = [piece("row_ends", row=6, column="G", text="Customers stops at G"), piece("row_ends", row=11, column="G", text="Churn stops at G")]
    got = check(fmap(sheet_map(evidence=ev)), grid)
    assert item(got, "evidence:Report:0")["outcome"] == checks.CONFIRMED
    rejected = item(got, "evidence:Report:1")
    assert (rejected["outcome"], rejected["reason"]) == (checks.REJECTED, "Reading says row 11 ends at column G; cell H11 holds 1.")
    assert months(got) == [("2024-06", "G")], "the month stands on the remaining evidence"


def test_with_all_the_evidence_rejected_or_unchecked_there_is_no_month():
    none = check(fmap(sheet_map(evidence=[piece("row_ends", row=7, column="G"), piece("layout", text="the plan columns look different")])))
    assert months(none) == []
    assert item(none, "evidence:Report:0")["outcome"] == checks.REJECTED
    assert item(none, "evidence:Report:1")["reason"] == "This describes the layout, not a value; no cell to open."
    assert months(check(fmap(sheet_map(evidence=[])))) == []
    assert months(check(fmap(sheet_map(last_actual=False)))) == []


def test_evidence_that_is_true_but_points_at_another_column_does_not_make_the_month():
    got = check(fmap(sheet_map(evidence=[piece("row_ends", row=6, column="G")], last_actual=True)), build())
    assert months(got) == [("2024-06", "G")]
    off = fmap(sheet_map(evidence=[piece("row_ends", row=6, column="G")]))
    off["sheets"][0]["last_actual"].update(column="F", period="2024-05")
    wrong = check(off)
    assert item(wrong, "evidence:Report:0")["outcome"] == checks.CONFIRMED and item(wrong, "evidence:Report:0")["supports"] is False
    assert months(wrong) == [], "a fact that does not point at the column is not evidence for it"


def test_a_wrong_header_period_for_the_last_actual_column_gives_no_month_whatever_the_evidence():
    m = fmap()
    m["sheets"][0]["last_actual"]["period"] = "2024-05"
    got = check(m)
    assert (item(got, "last_actual:Report")["outcome"], item(got, "last_actual:Report")["reason"]) == (
        checks.REJECTED, "Reading says 2024-05; cell G3 is the header for 2024-06.")
    assert months(got) == []


@pytest.mark.parametrize("evidence, expected", [
    (piece("equals_range", cells="H4:M4", other_cells="H5:M5", text="plan copied down"), checks.CONFIRMED),
    (piece("equals_range", cells="B4:G4", other_cells="B5:G5", text="actuals equal plan"), checks.REJECTED),
    (piece("equals_range", cells="H4:M4", other_cells="H5:L5", text="shapes differ"), checks.REJECTED),
    (piece("label_contains", cell="H2", word="Forecast", text="Forecast title"), checks.CONFIRMED),
    (piece("label_contains", cell="H2", word="Budget", text="Budget title"), checks.REJECTED),
    (piece("repeated_values", cells="H9:M9", text="repeated"), checks.CONFIRMED),
    (piece("repeated_values", cells="B4:G4", text="repeated"), checks.REJECTED),
    (piece("round_values", cells="H4:M4", multiple=10, text="round"), checks.CONFIRMED),
    (piece("round_values", cells="B4:G4", multiple=100, text="round"), checks.REJECTED),
    (piece("range_empty", cells="H6:M6", text="no customers after June"), checks.CONFIRMED),
    (piece("range_empty", cells="G6:M6", text="no customers after June"), checks.REJECTED),
    (piece("row_ends", row=6, column="Z"), checks.REJECTED),
    (piece("equals_range", cells="H4:M4"), checks.CANNOT),
    (piece("label_contains", cell="H2"), checks.CANNOT),
])
def test_each_kind_of_structural_evidence_is_opened_and_tested(evidence, expected):
    assert item(check(fmap(sheet_map(evidence=[evidence]))), "evidence:Report:0")["outcome"] == expected


def test_a_range_that_should_be_empty_names_the_first_cell_that_is_not():
    got = item(check(fmap(sheet_map(evidence=[piece("range_empty", cells="G6:M6")]))), "evidence:Report:0")
    assert (got["outcome"], got["reason"]) == (checks.REJECTED, "Reading says G6:M6 is empty; cell G6 holds 25.")
    before = check(fmap(sheet_map(evidence=[piece("range_empty", cells="C6:F6")])))
    assert item(before, "evidence:Report:0")["supports"] is False, "blank cells before the boundary say nothing about it"


def test_a_label_word_counts_after_whitespace_and_case():
    got = item(check(fmap(sheet_map(evidence=[piece("label_contains", cell="H2", word="  forecast ")])), build({(2, 8): "Forecast   2024"})),
               "evidence:Report:0")
    assert got["outcome"] == checks.CONFIRMED


def test_a_plan_word_title_over_the_column_after_the_boundary_supports_it():
    title = check(fmap(sheet_map(evidence=[piece("label_contains", cell="H2", word="Forecast")])))
    assert months(title) == [("2024-06", "G")]
    merged = check(fmap(sheet_map(evidence=[piece("label_contains", cell="K2", word="Forecast")])),
                   build())                                                  # K2 is empty: the word is not there
    assert months(merged) == []
    row_label = check(fmap(sheet_map(evidence=[piece("label_contains", cell="A5", word="Plan")])))
    assert item(row_label, "evidence:Report:0")["outcome"] == checks.CONFIRMED and months(row_label) == [], \
        "a row label points at no column, so it cannot support one"
    early = check(fmap(sheet_map(evidence=[piece("label_contains", cell="D2", word="Forecast")])), build({(2, 4): "Forecast"}))
    assert months(early) == [], "a plan title over a column before the boundary does not point at it"
    not_plan = check(fmap(sheet_map(evidence=[piece("label_contains", cell="H2", word="Notes")])), build({(2, 8): "Notes"}))
    assert months(not_plan) == [], "the word is not a plan word"


# ---------------------------------------------------------------------------
# Only three outcomes; code never corrects (test 9)
# ---------------------------------------------------------------------------
def test_the_outcomes_are_three_and_no_check_changes_a_citation():
    assert checks.OUTCOMES == ("confirmed", "rejected", "cannot_check")
    m = fmap(sheet_map(evidence=[piece("row_ends", row=6, column="G"), piece("row_ends", row=7, column="G")]),
             [figure(450000), figure(ACTUAL[2], cell="D4", period="2024-02"), figure(3, source=None)])
    before = copy.deepcopy(m)
    got = check(m)
    assert m == before, "the map the reader gave is untouched: nothing is corrected"
    assert {i["outcome"] for i in got["items"]} <= set(checks.OUTCOMES) and set(got["counts"]) == set(checks.OUTCOMES)
    assert sum(got["counts"].values()) == len(got["items"])
    public = {n for n in dir(checks) if not n.startswith("_")}
    assert not {n for n in public if n.startswith(("fix", "correct", "repair", "autocorrect", "adjust", "guess", "infer"))}


def test_every_cannot_check_reason_is_one_of_the_five_or_the_two_missing_inputs_and_every_other_failure_is_a_rejection():
    five = {checks.C_LAYOUT, checks.C_NO_REF, checks.C_MASKED, checks.C_NO_TEXT.format(n=7), checks.C_VARIANCE_ROWS, checks.C_SEGMENT_TOTAL, checks.C_NO_UNIT}
    grid = build({(2, 8): "[email]"})
    m = fmap(sheet_map(evidence=[piece("layout"), piece("label_contains", cell="H2", word="x"), piece("equals_range", cells="H4:M4")],
                       rows=[row(), row(row=5, label_cell=None, cells=None)]),
             [figure(3, source=None), figure(1, source={"sheet": None, "cell": None, "page": 7, "text_layer": False}), figure(447.22)])
    for i in check(m, grid)["items"]:
        if i["outcome"] == checks.CANNOT:
            assert i["reason"] in five or i["reason"].startswith("Cell ") and i["reason"].endswith("Unit or scale differs; not compared."), i


# ---------------------------------------------------------------------------
# Sheet-level cells
# ---------------------------------------------------------------------------
def test_the_currency_cell_and_the_period_columns_are_opened():
    ok = check(fmap())
    assert item(ok, "currency:Report")["outcome"] == checks.CONFIRMED and item(ok, "periods:Report")["outcome"] == checks.CONFIRMED
    wrong = item(check(fmap(sheet_map(currency="USD"))), "currency:Report")
    assert (wrong["outcome"], wrong["reason"]) == (checks.REJECTED, "Reading says USD; cell A1 holds Monthly report, EUR.")
    assert item(check(fmap(sheet_map(currency_cell=None))), "currency:Report")["reason"] == "No cell reference given."
    far = item(check(fmap(sheet_map(last_period_col="AA"))), "periods:Report")
    assert (far["outcome"], far["reason"]) == (checks.REJECTED, "Reading cites AA3; the sheet ends at column M.")
    titled = item(check(fmap(), build({(HEADER, 2): "Notes"})), "periods:Report")
    assert titled["outcome"] == checks.REJECTED


# ---------------------------------------------------------------------------
# The second reading of a rejected item
# ---------------------------------------------------------------------------
def test_a_rejected_item_is_asked_again_by_key_and_only_the_asked_items_are_taken():
    first = fmap(sheet_map(rows=[row(), row(row=5, label_cell="A5", role="forecast", cells="B5:M5")]), [figure(450000), figure(ACTUAL[3], cell="E4", period="2024-04")])
    got = check(first)
    assert checks.reread_keys(got["items"]) == [FIG]
    second = copy.deepcopy(first)
    second["figures"] = [figure(ACTUAL[2])]
    second["sheets"][0]["rows"][0]["role"] = "bookings"                      # not asked about: ignored
    merged = checks.merge_reread(first, second, [FIG])
    assert merged["figures"][0]["value"] == ACTUAL[2] and merged["figures"][1] == first["figures"][1]
    assert merged["sheets"][0]["rows"][0]["role"] == "revenue" and merged is not first and first["figures"][0]["value"] == 450000
    after = check(merged)
    assert item(after, FIG)["outcome"] == checks.CONFIRMED
    assert checks.classify_reread(item(got, FIG), item(after, FIG)) == "agrees with the cell"
    same = check(checks.merge_reread(first, first, [FIG]))
    assert checks.classify_reread(item(got, FIG), item(same, FIG)) == "repeats the first reading"
    third = copy.deepcopy(first)
    third["figures"][0]["value"] = 460000
    assert checks.classify_reread(item(got, FIG), item(check(checks.merge_reread(first, third, [FIG])), FIG)) == "gives a third value"


def test_a_rejected_piece_of_evidence_is_asked_about_as_the_sheets_last_actual_column():
    got = check(fmap(sheet_map(evidence=[piece("row_ends", row=7, column="G")])))
    assert checks.reread_keys(got["items"]) == ["last_actual:Report"]
    first = fmap(sheet_map(evidence=[piece("row_ends", row=7, column="G")]))
    second = fmap(sheet_map(evidence=[piece("row_ends", row=6, column="G")]))
    merged = checks.merge_reread(first, second, ["last_actual:Report"])
    assert months(check(merged)) == [("2024-06", "G")]


def test_a_merged_quarter_header_is_the_header_of_each_column_it_covers():
    """Test 4: the quarter sits in the first cell of its span; the other cells of the span are blank in the file."""
    text = redact.reading_text([{"name": "Report", "cells": [
        {"row": 1, "col": 1, "text": "Report"}, {"row": 2, "col": 1, "text": "Metric"}, {"row": 2, "col": 2, "text": "Q1 2024", "col_span": 3},
        {"row": 2, "col": 5, "text": "Q2 2024", "col_span": 3}, {"row": 3, "col": 1, "text": "Revenue"},
        *({"row": 3, "col": c, "text": str(100 + c)} for c in range(2, 8))]}])
    smap = sheet_map(rows=[row(row=3, cells="B3:G3", label_cell="A3")], header_row=2, first_period_col="B", last_period_col="E",
                     granularity="quarterly", last_actual=False)
    smap["currency"] = None

    def fig(cell, value, period):
        return figure(value, cell=cell, period=period)
    m = fmap(smap, [fig("C3", 103, "2024-Q1"), fig("D3", 104, "2024-Q1"), fig("F3", 106, "2024-Q2"), fig("D3", 104, "2024-Q2")])
    got = checks.check_map(checks.Cells(text), m, 12)
    outcomes = [i["outcome"] for i in got["items"] if i["kind"] == "figure"]
    assert outcomes == [checks.CONFIRMED, checks.CONFIRMED, checks.CONFIRMED, checks.REJECTED], got["items"]
    assert [i["reason"] for i in got["items"] if i["outcome"] == checks.REJECTED] == ["Reading says 2024-Q2; cell D2 is the header for 2024-Q1."]
    assert item(got, "periods:Report")["outcome"] == checks.CONFIRMED


def test_without_a_span_a_blank_header_cell_is_blank_and_never_borrows_a_neighbour():
    grid = build({(HEADER, 4): None})
    got = item(check(fmap(figures=[figure(ACTUAL[2], period="2024-03")]), grid), FIG)
    assert (got["outcome"], got["reason"]) == (checks.REJECTED, "Reading says 2024-03; cell D3 is the header for nothing.")


# ---------------------------------------------------------------------------
# F1: a piece of evidence points at one column, the one right after the claimed boundary
# ---------------------------------------------------------------------------
def _boundary_at(letter, period, evidence):
    m = fmap(sheet_map(evidence=[evidence]))
    m["sheets"][0]["last_actual"].update(column=letter, period=period)
    return check(m)


@pytest.mark.parametrize("letter, period", [("G", "2024-06"), ("F", "2024-05"), ("D", "2024-03")])
@pytest.mark.parametrize("evidence", [
    piece("equals_range", cells="H4:M4", other_cells="H5:M5"),
    piece("range_empty", cells="H6:M6"),
    piece("repeated_values", cells="H9:M9"),
    piece("round_values", cells="H4:M4", multiple=10),
    piece("label_contains", cell="H2", word="Forecast"),
], ids=lambda e: e["kind"])
def test_evidence_starting_at_column_h_supports_a_boundary_at_g_only(letter, period, evidence):
    got = _boundary_at(letter, period, evidence)
    confirmed_here = item(got, "evidence:Report:0")
    assert confirmed_here["outcome"] == checks.CONFIRMED, "the fact is true wherever the boundary is claimed"
    if letter == "G":
        assert confirmed_here["supports"] is True and months(got) == [("2024-06", "G")]
    else:
        assert confirmed_here["supports"] is False and months(got) == [], "one or three columns early: the month is not confirmed on it"


def test_evidence_starting_one_column_late_confirms_nothing():
    late = _boundary_at("G", "2024-06", piece("range_empty", cells="I6:M6"))
    assert item(late, "evidence:Report:0")["supports"] is False and months(late) == []


def test_a_title_over_a_merged_span_counts_from_the_start_of_the_span():
    grid = build({(2, 9): None})
    sheet_cells = [{"row": r, "col": c, "text": t} for (r, c), t in grid.items() if (r, c) != (2, 8)] + \
                  [{"row": 2, "col": 8, "text": "Forecast", "col_span": 6}]
    cells = checks.Cells(redact.reading_text([{"name": "Report", "cells": sheet_cells}]))
    inside = checks.check_map(cells, fmap(sheet_map(evidence=[piece("label_contains", cell="H2", word="Forecast")])), 12)
    assert months(inside) == [("2024-06", "G")]


def test_a_month_header_over_three_columns_ends_at_its_last_column():
    """Layout 3: Jun-24 is merged over Q:S; the evidence starts at T. A boundary at the May group (N:P) or the Jun group is tested the same way."""
    grid = {(3, 14): "May-24", (3, 17): "Jun-24", (3, 20): "Jul-24", (5, 17): "430", (7, 17): "70"}
    cells = [{"row": r, "col": c, "text": t} for (r, c), t in grid.items() if t is not None]
    cells += [{"row": 3, "col": 14, "text": "May-24", "col_span": 3}, {"row": 3, "col": 17, "text": "Jun-24", "col_span": 3}]
    cells = [c for c in cells if not (c["row"] == 3 and c["col"] in (14, 17) and "col_span" not in c)]
    book = checks.Cells(redact.reading_text([{"name": "Report", "cells": cells}]))

    def run(letter, period):
        sm = sheet_map(evidence=[piece("range_empty", cells="T5:T7")], first_period_col="N", last_period_col="V", rows=[])
        sm["last_actual"].update(column=letter, period=period)
        return checks.check_map(book, fmap(sm), 12)
    assert months(run("Q", "2024-06")) == [("2024-06", "Q")]
    assert months(run("N", "2024-05")) == [], "T is three columns after the May group's last column"


# ---------------------------------------------------------------------------
# F2 and F3: the arithmetic the reading must be able to show
# ---------------------------------------------------------------------------
def _variance_rows(**over):
    var = row(row=7, label_cell="A7", role="variance", actual_plan="variance", cells="B7:M7", variance_of={"actual_row": 4, "plan_row": 5}, **over)
    return [row(), row(row=5, label_cell="A5", role="forecast", cells="B5:M5"), var]


def test_a_variance_row_is_confirmed_only_when_actual_minus_plan_holds_cell_by_cell():
    ok = check(fmap(sheet_map(rows=_variance_rows())))
    assert item(ok, "variance:Report:7")["outcome"] == checks.CONFIRMED
    assert not [i for i in ok["items"] if i["key"] == "row:Report:7"], "the variance row is one item: its cells and its arithmetic"
    wrong = check(fmap(sheet_map(rows=_variance_rows())), build({(7, 9): "5"}))
    assert (item(wrong, "variance:Report:7")["outcome"], item(wrong, "variance:Report:7")["reason"]) == (
        checks.REJECTED, "Variance row A7 does not equal actual minus budget in 1 of 12 periods.")


def test_a_variance_row_without_its_two_source_rows_cannot_be_checked_and_is_never_confirmed():
    for marked in ("variance", "mixed"):
        rows = [row(), row(row=7, label_cell="A7", role="variance", actual_plan=marked, cells="B7:M7", variance_of=None)]
        got = item(check(fmap(sheet_map(rows=rows))), "row:Report:7")
        assert (got["outcome"], got["reason"]) == (checks.CANNOT, "variance row without its two source rows")


def test_a_variance_row_whose_cells_are_text_is_still_rejected_before_its_arithmetic():
    got = item(check(fmap(sheet_map(rows=_variance_rows())), build({(7, 5): "tbc"})), "row:Report:7")
    assert got["outcome"] == checks.REJECTED and got["reason"] == "Reading says a number; cell E7 holds tbc."


def test_a_segment_row_with_no_total_cannot_be_checked_and_parts_that_do_not_sum_are_rejected():
    lone = [row(row=9, label_cell="A9", segment="Product A", cells="B9:M9")]
    got = item(check(fmap(sheet_map(rows=lone))), "row:Report:9")
    assert (got["outcome"], got["reason"]) == (checks.CANNOT, "segment row without its total row")
    rows = [row(row=8, label_cell="A8", cells="B8:M8"), row(row=9, label_cell="A9", segment="Product A", parent_row=8, cells="B9:M9"),
            row(row=10, label_cell="A10", segment="Product B", parent_row=8, cells="B10:M10")]
    bad = item(check(fmap(sheet_map(rows=rows)), build({(9, 6): "130"})), "parts:Report:8")
    assert (bad["outcome"], bad["reason"]) == (checks.REJECTED, "Parts F9, F10 sum to 210; the reading names F8 as their total, which holds 200.")


# Layout 3: actual | budget | variance per month, in the cells of one row.
def _triples(changes=None):
    """A5 Revenue; Jan to Mar over B..J: actual 100 + k, budget 100, variance k."""
    cells = {(1, 1): "Actual against budget, EUR", (5, 1): "Revenue"}
    for k, month in enumerate(["Jan-24", "Feb-24", "Mar-24"]):
        a = 2 + 3 * k
        cells[(3, a)] = month
        cells[(4, a)], cells[(4, a + 1)], cells[(4, a + 2)] = "Actual", "Budget", "Variance"
        cells[(5, a)], cells[(5, a + 1)], cells[(5, a + 2)] = str(100 + k), "100", str(k)
    cells.update(changes or {})
    return cells


def _triple_map(**over):
    r = row(row=5, label_cell="A5", cells="B5:J5", variance_columns={"actual": "B", "plan": "C", "variance": "D", "step": 3}, **over)
    return fmap(sheet_map(rows=[r], header_row=3, first_period_col="B", last_period_col="J", last_actual=False))


def test_the_variance_columns_of_actual_budget_variance_triples_are_tested_the_same_way():
    ok = check(_triple_map(), _triples())
    got = item(ok, "variance:Report:5")
    assert got["outcome"] == checks.CONFIRMED
    bad = item(check(_triple_map(), _triples({(5, 7): "9"})), "variance:Report:5")
    assert (bad["outcome"], bad["reason"]) == (checks.REJECTED, "Variance row D5 does not equal actual minus budget in 1 of 3 periods.")


# (d) a figure's actual/plan against its row's boundary
def test_a_figure_marked_actual_after_its_rows_boundary_or_plan_before_it_is_rejected():
    after = item(check(fmap(figures=[figure(PLAN[7], cell="I4", period="2024-08", actual_plan="actual")]),
                       build()), "figure:Report:I4:revenue")
    assert (after["outcome"], after["reason"]) == (checks.REJECTED, "figure marked actual; column I is plan for this row")
    before = item(check(fmap(figures=[figure(ACTUAL[2], cell="D4", period="2024-03", actual_plan="plan")])), FIG)
    assert (before["outcome"], before["reason"]) == (checks.REJECTED, "figure marked plan; column D is actual for this row")
    ok = check(fmap(figures=[figure(ACTUAL[2], cell="D4", period="2024-03", actual_plan="actual"),
                             figure(PLAN[7], cell="I4", period="2024-08", actual_plan="plan"),
                             figure(ACTUAL[5], cell="G4", period="2024-06", actual_plan="actual")]))
    assert [i["outcome"] for i in ok["items"] if i["kind"] == "figure"] == [checks.CONFIRMED] * 3


def test_a_figure_marked_variance_or_mixed_or_nothing_is_not_compared_and_a_row_with_no_boundary_has_nothing_to_compare():
    for marked in ("variance", "mixed", None):
        got = item(check(fmap(figures=[figure(ACTUAL[2], cell="D4", actual_plan=marked)])), FIG)
        assert got["outcome"] == checks.CONFIRMED, marked
    no_boundary = fmap(sheet_map(rows=[row(boundary_col=None)], last_actual=False), [figure(PLAN[7], cell="I4", period="2024-08", actual_plan="actual")])
    assert item(check(no_boundary), "figure:Report:I4:revenue")["outcome"] == checks.CONFIRMED


def test_the_boundary_of_the_sheet_is_used_when_the_row_has_none_and_only_when_the_month_stands():
    m = fmap(sheet_map(rows=[row(boundary_col=None)]), [figure(PLAN[7], cell="I4", period="2024-08", actual_plan="actual")])
    assert item(check(m), "figure:Report:I4:revenue")["outcome"] == checks.REJECTED
    unconfirmed = fmap(sheet_map(rows=[row(boundary_col=None)], evidence=[piece("layout")]), [figure(PLAN[7], cell="I4", period="2024-08", actual_plan="actual")])
    assert item(check(unconfirmed), "figure:Report:I4:revenue")["outcome"] == checks.CONFIRMED, "a boundary no evidence confirmed rejects nothing"


def test_a_row_of_actual_budget_variance_triples_has_no_single_boundary_to_compare_with():
    r = row(row=5, label_cell="A5", cells="B5:J5", boundary_col="D", variance_columns={"actual": "B", "plan": "C", "variance": "D", "step": 3})
    m = fmap(sheet_map(rows=[r], header_row=3, first_period_col="B", last_period_col="J", last_actual=False),
             [figure(100, cell="C5", period="2024-01", actual_plan="plan")])
    assert item(check(m, _triples({(3, 3): "Jan-24"})), "figure:Report:C5:revenue")["outcome"] == checks.CONFIRMED
