"""page_check: Python checks each claim the model read from a page at cell level (docs/design/ai-reads-rules-check.md section 2,
decisions 2a and 3a of 2026-10-22). Pure tests on hand-built page grids: a figure moved to another cell, a unit removed, a period
from a sentence and a label not adjacent each fail; today's normalisation holds (1.5M = 1,500,000; €, EUR; K, MM)."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.structures import page_check  # noqa: E402

MATCHED, UNMATCHED = page_check.MATCHED, page_check.UNMATCHED


def line(row, text, box, col=1, **more):
    return {"row": row, "col": col, "text": text, "box": box, **more}


def grid(cells, tables=None, page=5):
    return {"type": "page", "page": page, "header_rows": 0, "cells": cells, "tables": tables or []}


def claim(value_cell, value, metric="revenue", unit="EUR", period=None, period_cell=None, label_cell=None, value_high=None,
          unit_other=None, basis="actual", scenario="none"):
    return {"metric": metric, "value": value, "value_high": value_high, "unit": unit, "unit_other": unit_other, "period": period,
            "basis": basis, "scenario": scenario, "value_cell": value_cell, "label_cell": label_cell, "period_cell": period_cell}


def one(grid_, claim_, fiscal_year_end=12):
    out = page_check.check(grid_, [claim_], fiscal_year_end)
    assert len(out["items"]) == 1, out
    return out["items"][0]


# A KPI-style page: a title box next to a box of three lines; a far box that is next to nothing.
TRACTION = grid([
    line(1, "Traction", 1, title=True, next_to=["r2c1"]),
    line(2, "800 Paying Users", 2, next_to=["r1c1"]),
    line(3, "$150,000 annual revenue run rate", 2, next_to=[]),
    line(4, "97% margins", 2, next_to=[]),
    line(5, "Revenue", 3, next_to=[]),
    line(6, "€1.5M", 3, next_to=[]),
    line(7, "Far away heading", 4, next_to=[]),
])


# ---------------------------------------------------------------------------
# 1. Figure in its cell
# ---------------------------------------------------------------------------
def test_a_figure_in_its_cell_with_its_unit_and_no_period_around_is_matched():
    got = one(TRACTION, claim("r3c1", 150000, unit="USD", label_cell="r3c1"))
    assert got["status"] == MATCHED and got["value"] == 150000 and got["period"] is None and got["period_cells"] == []
    assert got["checks"] == {"value": True, "unit": True, "period": True, "label": True, "period_corrected": False,
                             "dot_reading": None, "bracket_reading": None}


def test_a_figure_moved_to_another_cell_is_not_matched():
    """The value is on the page, but not in the cited cell: "AI suggestion, not matched" (decision 2a, not 2b). The row shows the
    model's value, never the cell's first figure (George, 2026-10-22, decision 2a on the review of PR #159): one right row to
    confirm or reject, not "revenue $97"."""
    got = one(TRACTION, claim("r4c1", 150000, unit="USD"))
    assert got["status"] == UNMATCHED and got["checks"]["value"] is False
    assert got["value"] == 150000 and got["values"] == [] and got["position"] is None, "the row shows the model's value"
    assert page_check.label(got["status"]) == "AI suggestion, not matched"


def test_a_value_the_cell_does_not_hold_at_all_is_not_matched():
    got = one(TRACTION, claim("r6c1", 1500, unit="EUR"))
    assert got["status"] == UNMATCHED and got["checks"]["value"] is False and got["value"] == 1500


def test_a_split_figure_read_as_one_number_is_not_matched_and_the_row_shows_the_models_value():
    """The live "€27K" case (design note section 6): the pdf word reader splits the figure into "€2 7K"; the model reads 27,000.
    Python finds 2 and 7,000 in the cell, so the claim is unmatched, and the row shows 27,000 (never "revenue €2")."""
    page = grid([line(1, "Revenue", 1, next_to=[]), line(2, "€2 7K", 1, next_to=[])])
    got = one(page, claim("r2c1", 27000, unit="EUR", label_cell="r1c1"))
    assert got["status"] == UNMATCHED and got["checks"]["value"] is False
    assert got["value"] == 27000 and got["value_high"] is None and got["values"] == []
    assert page_check.label(got["status"]) == "AI suggestion, not matched"
    high = one(page, claim("r2c1", 27000, unit="EUR", value_high=30000))
    assert high["status"] == UNMATCHED and (high["value"], high["value_high"]) == (27000, 30000)


@pytest.mark.parametrize("text, value", [
    ("€1.5M", 1500000), ("€1.5M", 1.5), ("€1,500,000", 1500000), ("EUR 1.5M", 1500000), ("€15K", 15000), ("€15K", 15),
    ("€5.3MM", 5300000), ("1.5 million EUR", 1500000), ("€ 1.5 Mio", 1500000)])
def test_figures_are_normalised_before_comparing(text, value):
    """1.5M = 1,500,000; "€" and "EUR" are one currency; K and MM are scales. The written number ("1.5") passes too; the row's
    value is Python's full-units reading."""
    g = grid([line(1, "Revenue", 1), line(2, text, 1)])
    got = one(g, claim("r2c1", value, unit="EUR"))
    assert got["status"] == MATCHED, got["checks"]
    assert got["value"] in (1500000, 15000, 5300000)


def test_a_scale_in_the_row_header_of_a_table_applies_and_the_period_comes_from_the_column_header():
    g = grid([{"row": 1, "col": 2, "text": "FY2025", "table": 1, "trow": 1, "tcol": 2},
              {"row": 1, "col": 3, "text": "FY2026", "table": 1, "trow": 1, "tcol": 3},
              {"row": 2, "col": 1, "text": "Revenue (£'000)", "table": 1, "trow": 2, "tcol": 1},
              {"row": 2, "col": 2, "text": "1,200", "table": 1, "trow": 2, "tcol": 2},
              {"row": 2, "col": 3, "text": "1,500", "table": 1, "trow": 2, "tcol": 3}],
             tables=[{"table": 1, "header_rows": 1}])
    got = one(g, claim("r2c2", 1200000, unit="GBP", period="FY2025", period_cell="r1c2", label_cell="r2c1"))
    assert got["status"] == MATCHED and got["period"] == "2025" and got["period_cells"] == ["r1c2"] and got["label_cell"] == "r2c1"
    other = one(g, claim("r2c2", 1200000, unit="GBP", period="FY2026", period_cell="r1c3"))
    assert other["status"] == UNMATCHED and other["checks"]["period"] is False, "another column's header is no source of this cell"


def test_a_range_is_one_row_with_both_ends_checked():
    g = grid([line(1, "2011 Estimated Revenue", 1, title=True, next_to=["r2c1"]), line(2, "$12 -$13 million", 2, next_to=["r1c1"])])
    got = one(g, claim("r2c1", 12000000, unit="USD", period="2011", period_cell="r1c1", value_high=13000000))
    assert got["status"] == MATCHED and (got["value"], got["value_high"]) == (12000000, 13000000)
    assert one(g, claim("r2c1", 12000000, unit="USD", period="2011", period_cell="r1c1"))["value_high"] == 13000000, "Python's range"
    wrong = one(g, claim("r2c1", 12000000, unit="USD", period="2011", period_cell="r1c1", value_high=14000000))
    assert wrong["status"] == UNMATCHED and wrong["checks"]["value"] is False


def test_a_level_keeps_its_positive_reading_only_and_a_bracketed_loss_keeps_both():
    g = grid([line(1, "Net loss (1,200)", 1), line(2, "Customers (30)", 2)])
    loss = one(g, claim("r1c1", -1200, metric="net_profit", unit=None))
    assert loss["status"] == MATCHED and [v["value"] for v in loss["values"]] == [-1200, 1200]
    level = one(g, claim("r2c1", 30, metric="customers", unit="count"))
    assert level["status"] == MATCHED and [v["value"] for v in level["values"]] == [30]


# ---------------------------------------------------------------------------
# 2. Unit in the cell or next to it
# ---------------------------------------------------------------------------
def test_a_unit_removed_from_the_cell_and_its_neighbours_is_not_matched():
    """"€1.5M" labelled USD, or labelled nothing: the currency is not where the model says it is."""
    for unit in ("USD", None):
        got = one(TRACTION, claim("r6c1", 1500000, unit=unit))
        assert got["status"] == UNMATCHED and got["checks"]["unit"] is False, unit


def test_a_currency_stated_as_a_code_or_a_symbol_next_to_the_cell_counts():
    g = grid([line(1, "Revenue (EUR)", 1), line(2, "1.5M", 1)])
    assert one(g, claim("r2c1", 1500000, unit="EUR"))["status"] == MATCHED
    g = grid([line(1, "Revenue (EUR)", 1), line(2, "1.5M", 1), line(3, "Costs", 2), line(4, "€2M", 2)])
    assert one(g, claim("r2c1", 1500000, unit="USD"))["checks"]["unit"] is False
    assert one(g, claim("r4c1", 2000000, unit="EUR", metric="costs"))["status"] == MATCHED


def test_percent_times_count_and_time_units_are_read_from_the_cell_or_its_neighbours():
    g = grid([line(1, "Metrics", 1, title=True, next_to=["r2c1"]), line(2, "97", 2, next_to=["r1c1"]), line(3, "% margins", 2),
              line(4, "4.9x", 3), line(5, "18", 4), line(6, "months", 4), line(7, "2300", 5, next_to=[])])
    assert one(g, claim("r2c1", 97, metric="gross_margin", unit="%"))["status"] == MATCHED
    assert one(g, claim("r4c1", 4.9, metric="ltv_cac", unit="x"))["status"] == MATCHED
    assert one(g, claim("r5c1", 18, metric="runway", unit="months"))["status"] == MATCHED
    assert one(g, claim("r5c1", 18, metric="runway", unit="years"))["checks"]["unit"] is False
    assert one(g, claim("r7c1", 2300, metric="customers", unit="count"))["checks"]["unit"] is False, "no noun anywhere near"
    assert one(TRACTION, claim("r2c1", 800, metric="customers", unit="count"))["status"] == MATCHED


def test_a_null_unit_passes_only_when_the_figure_carries_none():
    g = grid([line(1, "2300 companies use us today", 1), line(2, "€1.5M", 1), line(3, "97%", 1)])
    assert one(g, claim("r1c1", 2300, metric="customers", unit=None))["status"] == MATCHED
    assert one(g, claim("r2c1", 1500000, unit=None))["checks"]["unit"] is False
    assert one(g, claim("r3c1", 97, metric="gross_margin", unit=None))["checks"]["unit"] is False


# ---------------------------------------------------------------------------
# 3. Period from the cell's own sources
# ---------------------------------------------------------------------------
BARS = grid([
    line(1, "Revenue forecast 2022 -2024", 1, title=True, next_to=["r2c1"]),
    line(2, "IN 2022 WE FOCUS ON GROWTH OF ARPA AND KEY ACCOUNTS", 2, next_to=["r1c1"]),
    line(3, "€5.3MM", 3, next_to=["r2c1"], bar_year="2024"),
    line(4, "2024", 4, next_to=[]),
    line(5, "2023", 5, next_to=[]),
])


def test_a_period_from_a_sentence_is_not_matched():
    """Issue #154 stays: the sentence next to the bar holds a year, but a sentence is no date source."""
    got = one(BARS, claim("r3c1", 5300000, period="2022", period_cell="r2c1"))
    assert got["status"] == UNMATCHED and got["checks"]["period"] is False and got["period"] == "2022" and got["period_cells"] == []


def test_a_period_from_a_cell_that_is_not_next_to_the_value_is_not_matched():
    got = one(BARS, claim("r3c1", 5300000, period="2023", period_cell="r5c1"))
    assert got["status"] == UNMATCHED and got["checks"]["period"] is False


def test_the_bars_year_by_place_is_a_source_with_or_without_the_label_cited():
    """Issue #148: Python placed the bar over its axis label ("bar_year"); the model may cite that label or none."""
    placed = one(BARS, claim("r3c1", 5300000, period="2024", period_cell=None))
    assert placed["status"] == MATCHED and placed["period"] == "2024" and placed["period_cells"] == []
    cited = one(BARS, claim("r3c1", 5300000, period="2024", period_cell="r4c1"))
    assert cited["status"] == MATCHED and cited["period"] == "2024" and cited["period_cells"] == ["r4c1"]
    assert one(BARS, claim("r3c1", 5300000, period="2023", period_cell=None))["checks"]["period"] is False


def test_the_heading_with_a_year_range_gives_no_period_and_a_null_period_is_not_matched_under_a_bar_year():
    assert one(BARS, claim("r3c1", 5300000, period="2022", period_cell="r1c1"))["checks"]["period"] is False
    assert one(BARS, claim("r3c1", 5300000, period=None, period_cell=None))["checks"]["period"] is False, "the bar has a year"


def test_a_period_in_the_cells_own_text_and_a_date_label_next_to_it_are_sources():
    g = grid([line(1, "$8,000 revenue in 2022", 1), line(2, "Launched web app", 2), line(3, "January 2011", 2),
              line(4, "55,000 users ($150K revenue)", 2)])
    own = one(g, claim("r1c1", 8000, unit="USD", period="2022", period_cell="r1c1"))
    assert own["status"] == MATCHED and own["period"] == "2022" and own["period_cells"] == ["r1c1"]
    below = one(g, claim("r4c1", 55000, metric="users", unit="count", period="2011-01", period_cell="r3c1"))
    assert below["status"] == MATCHED and below["period"] == "2011-01" and below["period_cells"] == ["r3c1"]
    assert one(g, claim("r1c1", 8000, unit="USD", period="2023", period_cell="r1c1"))["checks"]["period_corrected"] is True


def test_a_null_period_stands_only_when_no_source_holds_one():
    g = grid([line(1, "2021 Estimated Revenue", 1, title=True, next_to=["r2c1"]), line(2, "$12M", 2, next_to=["r1c1"]),
              line(3, "Costs", 3), line(4, "$2M", 3)])
    assert one(g, claim("r2c1", 12000000, unit="USD", period=None))["checks"]["period"] is False, "the title next to it holds a year"
    assert one(g, claim("r4c1", 2000000, metric="costs", unit="USD", period=None))["status"] == MATCHED
    assert one(g, claim("r4c1", 2000000, metric="costs", unit="USD", period="2021", period_cell=None))["checks"]["period"] is False


def test_pythons_rebuilt_period_replaces_the_models_and_a_difference_is_a_correction():
    g = grid([{"row": 1, "col": 2, "text": "2025", "table": 1, "trow": 1, "tcol": 2},
              {"row": 2, "col": 2, "text": "Apr", "table": 1, "trow": 2, "tcol": 2},
              {"row": 3, "col": 1, "text": "Revenue", "table": 1, "trow": 3, "tcol": 1},
              {"row": 3, "col": 2, "text": "$5M", "table": 1, "trow": 3, "tcol": 2}],
             tables=[{"table": 1, "header_rows": 2}])
    got = one(g, claim("r3c2", 5000000, unit="USD", period="2025-04", period_cell="r2c2"), fiscal_year_end=3)
    assert got["status"] == MATCHED and got["period"] == "FY2025-04" and got["period_cells"] == ["r2c2", "r1c2"]
    assert got["checks"]["period_corrected"] is True and got["model_period"] == "2025-04"
    assert one(g, claim("r3c2", 5000000, unit="USD", period="2025-04", period_cell="r2c2"))["checks"]["period_corrected"] is False


# ---------------------------------------------------------------------------
# The label, the metric, milestones and drops
# ---------------------------------------------------------------------------
def test_a_label_not_adjacent_to_the_value_is_dropped_and_the_match_stands():
    """The metric is the analyst's (decision 2a): a far label does not unmatch the figure, but the row has no "Label from"."""
    got = one(TRACTION, claim("r6c1", 1500000, unit="EUR", label_cell="r7c1"))
    assert got["status"] == MATCHED and got["label_cell"] is None and got["checks"]["label"] is False
    near = one(TRACTION, claim("r6c1", 1500000, unit="EUR", label_cell="r5c1"))
    assert near["label_cell"] == "r5c1" and near["checks"]["label"] is True
    title = one(TRACTION, claim("r2c1", 800, metric="customers", unit="count", label_cell="r1c1"))
    assert title["label_cell"] == "r1c1", "the title directly next to the line"


def test_an_other_metric_is_never_matched():
    got = one(TRACTION, claim("r6c1", 1500000, metric="other", unit="EUR"))
    assert got["status"] == UNMATCHED and all(got["checks"][k] for k in ("value", "unit", "period"))


def test_a_claim_with_no_value_is_a_milestone_dated_from_its_source_and_never_matched():
    g = grid([line(1, "Launch the API", 1), line(2, "October 2011", 1)])
    got = one(g, claim("r1c1", None, metric="product", unit=None, period="2011-10", period_cell="r2c1"))
    assert got["status"] == UNMATCHED and got["value"] is None and got["period"] == "2011-10" and got["checks"]["value"] is False
    assert one(g, claim("r1c1", None, metric="product", unit="count", period="2011-10", period_cell="r2c1"))["checks"]["unit"] is False


def test_an_axis_tick_and_a_funds_raised_line_are_dropped_and_counted():
    g = grid([line(1, "8,000", 1, tick=True), line(2, "Raised $2M in our seed round", 2), line(3, "€1.5M", 3)])
    out = page_check.check(g, [claim("r1c1", 8000, unit=None), claim("r2c1", 2000000, unit="USD"), claim("r3c1", 1500000)])
    assert out["dropped"] == 2 and [i["value_cell"] for i in out["items"]] == ["r3c1"]
    assert (out["matched"], out["unmatched"]) == (1, 0)


def test_the_checks_are_booleans_and_closed_words_only():
    got = one(TRACTION, claim("r3c1", 150000, unit="USD", label_cell="r7c1"))
    assert set(got["checks"]) == {"value", "unit", "period", "label", "period_corrected", "dot_reading", "bracket_reading"}
    for key, value in got["checks"].items():
        assert value in ((True, False) if key not in ("dot_reading", "bracket_reading") else
                         (None, "decimal", "thousands", "negative", "positive")), key


def test_batch_claims_split_by_page_and_a_label_on_another_page_is_none():
    claims_ = [{"value_cell": "p5r2c1", "label_cell": "p5r1c1", "period_cell": "p6r3c1"}, {"value_cell": "p6r4c1", "label_cell": None,
                                                                                            "period_cell": "p6r3c1"}]
    split = page_check.by_page(claims_)
    assert set(split) == {5, 6}
    assert split[5] == [{"value_cell": "r2c1", "label_cell": "r1c1", "period_cell": None}]
    assert split[6] == [{"value_cell": "r4c1", "label_cell": None, "period_cell": "r3c1"}]
    assert (page_check.label(MATCHED), page_check.label(UNMATCHED)) == ("Matched to page", "AI suggestion, not matched")


def test_a_value_matches_the_figure_whose_own_unit_agrees_before_a_written_number():
    """"€15K in MRR, 15% MoM growth over last 15 months": the 15% claim is the second figure, not the 15 written before K; and a
    unit the figure's own text contradicts fails whatever stands next to the cell."""
    g = grid([line(1, "€15K in MRR, 15% MoM growth over last 15 months", 1)])
    pct = one(g, claim("r1c1", 15, metric="revenue_growth", unit="%"))
    assert pct["status"] == MATCHED and (pct["value"], pct["position"]) == (15, 2)
    months = one(g, claim("r1c1", 15, metric="other", unit="months"))
    assert months["position"] == 3 and months["checks"]["value"] is True and months["checks"]["unit"] is True
    mrr = one(g, claim("r1c1", 15000, unit="EUR"))
    assert mrr["status"] == MATCHED and mrr["position"] == 1
    assert one(g, claim("r1c1", 15000, unit="USD"))["checks"]["unit"] is False
    assert one(g, claim("r1c1", 15000, unit="%"))["checks"]["unit"] is False


# ---------------------------------------------------------------------------
# Follow-up to PR #161 (docs/test-runs/pages_2026-10-22_analysis.md section 6, changes 1, 2, 3 and 7)
# ---------------------------------------------------------------------------
def test_a_figure_in_a_title_line_is_found_by_the_value_check():
    """Change 1 (front-b p6 r1c1, moz p31 r1c1, moz p35 r1c2, moz p3 r3c1): list_items skips title cells, so no item was found."""
    page = grid([line(1, "2300 companies use Front today", 1, title=True), line(2, "Support teams", 2)])
    got = one(page, claim("r1c1", 2300, metric="customers", unit="count", label_cell="r1c1"))
    assert got["checks"]["value"] is True and got["status"] == MATCHED and got["value"] == 2300 and got["position"] == 1


def test_a_plus_between_the_number_and_its_scale_is_read_with_the_scale():
    """Change 2 (moz p3 r5c2 "1.2+MM", moz p9 r6c2 "$31+ Billion"): the "+" hid the scale, the figure read 1.2 and 31."""
    page = grid([line(1, "Users", 1), line(2, "1.2+MM", 2), line(3, "Market", 3), line(4, "$31+ Billion", 4)])
    users = one(page, claim("r2c1", 1200000, metric="users", unit="count", label_cell="r1c1"))
    market = one(page, claim("r4c1", 31000000000, metric="market", unit="USD", label_cell="r3c1"))
    assert users["checks"]["value"] is True and users["value"] == 1200000
    assert market["checks"]["value"] is True and market["value"] == 31000000000


def test_the_trillion_scale_is_read():
    """Change 3 (genesisai-2024 p4 r3c1 "$2.8T"): verify.figures read 2.8; claims._SCALE already knew T."""
    page = grid([line(1, "Market", 1), line(2, "$2.8T", 2), line(3, "Opportunity of 1.5 trillion dollars", 3)])
    got = one(page, claim("r2c1", 2.8e12, metric="market", unit="USD", label_cell="r1c1"))
    assert got["checks"]["value"] is True and got["value"] == 2.8e12
    assert one(page, claim("r3c1", 1.5e12, metric="market", unit="USD"))["checks"]["value"] is True


def test_a_neighbouring_line_with_its_own_figure_is_not_a_date_source():
    """Change 7 (genesisai-2024 p5 r4c1 "2,600+ users"): r3c1 "$8,000 revenue in 2022" is a figure's line, not the date of the
    users line next to it, so a null period stands."""
    page = grid([line(1, "STRONG", 1, title=True),
                 line(2, "$8,000 revenue in 2022", 2, next_to=["r3c1"]),
                 line(3, "2,600+ users", 3, next_to=["r2c1"])])
    got = one(page, claim("r3c1", 2600, metric="users", unit="count", label_cell="r3c1"))
    assert got["checks"]["period"] is True and got["status"] == MATCHED
    pure = grid([line(1, "STRONG", 1, title=True), line(2, "in 2022", 2, next_to=["r3c1"]), line(3, "2,600+ users", 3, next_to=["r2c1"])])
    assert one(pure, claim("r3c1", 2600, metric="users", unit="count"))["checks"]["period"] is False, "a pure date line still is one"
