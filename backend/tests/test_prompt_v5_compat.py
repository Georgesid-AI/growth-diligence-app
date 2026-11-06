"""Prompt v5 compatibility (George, 2026-11-06), no other change of behaviour:
1. a `label_contains` title supports the boundary when its word is a plan word of the longer list, or a year followed by E, F, B or P;
2. a segment "scenario: <name>" is a scenario, not a product or region: never summed with other segments, shown by its name;
3. a last_actual with one to three pieces of evidence passes (no check asks for more), and one whose pieces are all weak is rejected."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from test_checks import build, check, fmap, item, months, piece, sheet_map  # noqa: E402
from test_part_rows_cost_roles import both, part_rows, pnl  # noqa: E402

from app import checks, consistency, role_engine  # noqa: E402


# ---- 1. the plan words -------------------------------------------------------------------------------------------------------------------
def supports(word, cell_text=None):
    grid = build({(2, 8): cell_text or word})
    got = check(fmap(sheet_map(evidence=[piece("label_contains", cell="H2", word=word)])), grid)
    return item(got, "evidence:Report:0")["supports"], months(got)


@pytest.mark.parametrize("word", ["forecast", "budget", "plan", "estimate", "projection", "outlook", "reforecast", "pro forma", "Pro-forma", "Outlook",
                                  "Reforecast", "FY24E", "2025F", "2024B", "2024P", "FY25E", "fy24e", "Budget 2025", "Outlook 2025"])
def test_these_words_in_a_title_over_the_column_after_the_boundary_support_it(word):
    assert supports(word) == (True, [("2024-06", "G")])


@pytest.mark.parametrize("word", ["Notes", "2024", "FY24", "2024A", "FY24 actuals", "Perform", "Sales", "2024Q", "A2024E"])
def test_other_words_do_not(word):
    assert supports(word)[0] is False


def test_the_check_of_the_cited_word_in_the_cell_is_not_a_list_and_a_word_not_in_the_cell_is_rejected():
    got = item(check(fmap(sheet_map(evidence=[piece("label_contains", cell="H2", word="Outlook")])), build({(2, 8): "Forecast"})), "evidence:Report:0")
    assert got["outcome"] == checks.REJECTED


# ---- 2. scenario segments ----------------------------------------------------------------------------------------------------------------
def test_a_cost_row_with_a_scenario_segment_is_not_summed_with_the_parts():
    scenario = both(30, "sales_marketing", [999, 999, 999], [888, 888, 888], segment="scenario: Best case")
    table = role_engine.build_table(pnl(sm_rows=[*part_rows(), scenario]))
    summed = role_engine.sum_role(table, "sales_marketing", "yearly")
    assert summed["rows"] == list(range(10, 18)) and summed["actual"]["2025"][0] == 600, "the eight products only"
    assert "B30" not in summed["actual"]["2023"][1] and 30 not in summed["rows"]
    plan = role_engine.sum_role(table, "sales_marketing", "yearly", key="plan")
    assert 30 not in plan["rows"]


def test_a_scenario_row_alone_is_not_a_cost_row_to_read():
    scenario = both(30, "sales_marketing", [999, 999, 999], [888, 888, 888], segment="scenario: Worst")
    table = role_engine.build_table(pnl(sm_rows=[scenario]))
    assert role_engine.sum_role(table, "sales_marketing", "yearly") is None


def test_the_scenario_name_is_what_the_mapping_page_shows_not_a_segment():
    row = {"role": "revenue", "metric": "revenue", "segment": "scenario: Best case", "series": {"periods": []}}
    assert consistency.row_view(row)["scenario"] == "Best case" and consistency.row_view(row)["segment"] is False
    plain = consistency.row_view({**row, "segment": "Product A"})
    assert plain["segment"] is True and plain["scenario"] is None


# ---- 3. the evidence ---------------------------------------------------------------------------------------------------------------------
STRONG = piece("label_contains", cell="H2", word="Forecast", text="Forecast title")
WEAK = [piece("row_ends", row=6, column="G"), piece("repeated_values", cells="H9:M9"), piece("round_values", cells="H4:M4", multiple=10), piece("layout")]


def last(evidence):
    return item(check(fmap(sheet_map(evidence=evidence))), "last_actual:Report")


@pytest.mark.parametrize("n", [1, 2, 3])
def test_one_to_three_pieces_of_evidence_pass_and_no_check_asks_for_more(n):
    pieces = [STRONG, piece("range_empty", cells="H6:M6"), piece("equals_range", cells="H4:M4", other_cells="H5:M5")][:n]
    got = check(fmap(sheet_map(evidence=pieces)))
    assert item(got, "last_actual:Report")["outcome"] == checks.CONFIRMED and months(got) == [("2024-06", "G")]


def test_one_strong_piece_is_enough_beside_weak_ones():
    got = check(fmap(sheet_map(evidence=[WEAK[0], STRONG])))
    assert item(got, "last_actual:Report")["outcome"] == checks.CONFIRMED and months(got) == [("2024-06", "G")]


@pytest.mark.parametrize("pieces", [[WEAK[0]], [WEAK[1]], [WEAK[2]], [WEAK[3]], WEAK[:2], WEAK, [WEAK[0], WEAK[2], WEAK[3]]])
def test_a_last_actual_with_only_weak_evidence_is_rejected(pieces):
    got = last(pieces)
    assert (got["outcome"], got["reason"]) == (checks.REJECTED, "weak evidence only")
    assert check(fmap(sheet_map(evidence=pieces)))["months"] == []


def test_a_rejection_for_the_header_keeps_its_own_reason_and_no_evidence_is_not_weak_evidence():
    wrong = sheet_map(evidence=[WEAK[0]])
    wrong["last_actual"]["period"] = "2024-05"
    assert "weak evidence" not in (item(check(fmap(wrong)), "last_actual:Report")["reason"] or "")
    assert (last([])["outcome"], last([])["reason"]) == (checks.CONFIRMED, None)


# ---- 3b. a row's end is strong evidence in one layout (George, 2026-11-06) ---------------------------------------------------------------------------------
PLAN_SHEETS = ["Budget", "Plan 2025", "Forecast", "Projection", "Outlook", "Estimates", "Pro forma", "Reforecast", "AOP", "LRP", "Q3 reforecast"]


def two_sheets(other_name="Budget", other_title=None, end_col="G", last_period="G"):
    """The report as sheet 'Report' (actuals to G, no column after, no title over H) beside another sheet; the row end cited is row 6 at `end_col`."""
    report = {(r, c): t for (r, c), t in build().items() if c <= 7 and r != 2}
    other = [{"row": 1, "col": 1, "text": other_title or "Notes"}, {"row": 2, "col": 1, "text": "Metric"}, {"row": 3, "col": 2, "text": "1"}]
    text = checks.redact.reading_text([
        {"name": "Report", "cells": [{"row": r, "col": c, "text": t} for (r, c), t in report.items()]},
        {"name": other_name, "cells": other}])
    sheet = sheet_map(evidence=[piece("row_ends", row=6, column=end_col)], last_period_col=last_period)
    return checks.check_map(checks.Cells(text), {"map_version": 1, "kind": "sheet", "sheets": [sheet], "figures": []}, 12)


def verdict_of(got):
    return item(got, "last_actual:Report"), months(got)


@pytest.mark.parametrize("name", PLAN_SHEETS)
def test_a_row_end_at_the_last_period_column_is_strong_when_another_sheet_is_named_for_a_plan(name):
    got = two_sheets(other_name=name)
    assert verdict_of(got) == (item(got, "last_actual:Report"), [("2024-06", "G")]) and item(got, "last_actual:Report")["outcome"] == checks.CONFIRMED


@pytest.mark.parametrize("title", ["Budget 2025", "Operating plan", "Outlook", "AOP", "Pro forma P&L"])
def test_a_plan_word_in_the_title_of_the_other_sheet_is_enough(title):
    got = two_sheets(other_name="Sheet2", other_title=title)
    assert months(got) == [("2024-06", "G")]


def test_no_plan_word_on_any_other_sheet_leaves_the_row_end_weak():
    got = two_sheets(other_name="Sheet2", other_title="Notes")
    assert (item(got, "last_actual:Report")["outcome"], item(got, "last_actual:Report")["reason"]) == (checks.REJECTED, "weak evidence only")
    assert months(got) == []


def test_a_plan_word_on_the_same_sheet_does_not_count_as_another_sheet():
    report = {(r, c): t for (r, c), t in build().items() if c <= 7}          # row 2 keeps a 'Forecast' title: it is this sheet's own
    text = checks.redact.reading_text([{"name": "Report", "cells": [{"row": r, "col": c, "text": t} for (r, c), t in report.items()]},
                                       {"name": "Sheet2", "cells": [{"row": 1, "col": 1, "text": "Notes"}]}])
    report_cells = checks.Cells(text)
    report_cells.sheets["Report"].cells[(1, 1)] = "Budget report"
    got = checks.check_map(report_cells, {"map_version": 1, "kind": "sheet", "figures": [],
                                          "sheets": [sheet_map(evidence=[piece("row_ends", row=6, column="G")], last_period_col="G")]}, 12)
    assert item(got, "last_actual:Report")["reason"] == "weak evidence only", "a plan word on the sheet itself is not another sheet's"


def test_a_row_end_before_the_last_period_column_stays_weak_even_with_a_plan_sheet():
    got = two_sheets(other_name="Budget", end_col="G", last_period="M")
    assert (item(got, "last_actual:Report")["outcome"], item(got, "last_actual:Report")["reason"]) == (checks.REJECTED, "weak evidence only")
    assert months(got) == []


def test_the_other_weak_kinds_stay_weak_beside_a_plan_sheet():
    text = checks.redact.reading_text([
        {"name": "Report", "cells": [{"row": r, "col": c, "text": t} for (r, c), t in build().items()]},
        {"name": "Budget", "cells": [{"row": 1, "col": 1, "text": "x"}]}])
    for weak in (piece("repeated_values", cells="H9:M9"), piece("round_values", cells="H4:M4", multiple=10), piece("layout")):
        got = checks.check_map(checks.Cells(text), fmap(sheet_map(evidence=[weak])), 12)
        assert item(got, "last_actual:Report")["reason"] == "weak evidence only"
