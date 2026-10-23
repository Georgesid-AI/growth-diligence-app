"""Matched to page means the figure is in the cited cell (George, 2026-10-23; docs/specs/chat-upload.md section 28, claim-matching.md
section 4.2). The unit and the period no longer gate the match: they become flags, and the flags set the confidence label.

Synthetic pages only (hand-built grids): the period on the figure's line or block gives no flag; a period cited from the page heading is
informational (as is one cited from any other cell outside the figure's block); a period set that no cell of the page states is a review flag; a period null gives none; a unit not next to the cell is the
informational "currency assumed"; a label never counts; a metric "other" is matched like any other. Confidence: High = matched, no review
flag; Medium = matched with an informational flag or no date; Low = not matched or a review flag.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.decks import claims  # noqa: E402
from app.structures import checker, page_check  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402

DECK = {"file": "deck.pdf", "page_unit": "page", "blocks": []}


def line(row, text, box, col=1, **more):
    return {"row": row, "col": col, "text": text, "box": box, **more}


def grid(cells, page=5):
    return {"type": "page", "page": page, "header_rows": 0, "cells": cells, "tables": []}


def claim(value_cell, value, metric="revenue", unit="EUR", period=None, period_cell=None, label_cell=None):
    return {"metric": metric, "value": value, "value_high": None, "unit": unit, "unit_other": None, "period": period, "basis": "actual",
            "scenario": "none", "value_cell": value_cell, "label_cell": label_cell, "period_cell": period_cell}


def one(grid_, claim_):
    out = checker.check(grid_, [claim_], 12)
    assert len(out["items"]) == 1
    return out["items"][0]


def confidence(item, grid_):
    row = pipeline.row_from_claim(item, grid_, DECK, 12)
    return claims.confidence(row, [row])["level"]


# A figure with its period on its own line, one under a page heading far from it, one with no period anywhere.
OWN_LINE = grid([line(1, "Plan", 1, title=True), line(2, "€1.5M revenue in 2026", 2)])
HEADING = grid([line(1, "2026 plan", 1, title=True), line(2, "Revenue", 2), line(3, "€1.5M", 3)])
NO_DATE = grid([line(1, "Traction", 1, title=True), line(2, "€1.5M revenue", 2)])


def test_the_period_on_the_figures_own_line_is_matched_with_no_flag():
    item = one(OWN_LINE, claim("r2c1", 1_500_000, period="2026", period_cell="r2c1"))
    assert item["status"] == page_check.MATCHED and item["flags"] == [] and confidence(item, OWN_LINE) == "High"


def test_a_period_cited_from_the_page_heading_is_matched_with_an_informational_flag():
    item = one(HEADING, claim("r3c1", 1_500_000, period="2026", period_cell="r1c1"))
    assert item["status"] == page_check.MATCHED and item["period"] == "2026" and item["period_cells"] == ["r1c1"]
    assert item["flags"] == [checker.PERIOD_FROM_HEADING] and not checker.flagged(item)
    assert checker.PERIOD_FROM_HEADING in checker.INFORMATIONAL_FLAGS
    assert confidence(item, HEADING) == "Medium"


# Decision 1 and 2 (George, 2026-10-23, comment on PR 174): the heading is the title cell or any cell in the top 20% of the page height
# ("top_band", set by the page grid from the line's position); a period cited from any other cell outside the figure's block is informational.
TOP_BAND = grid([line(1, "Traction", 1, title=True), line(2, "Plan 2026", 2, top_band=True), line(3, "Revenue", 3), line(4, "€1.5M", 3)])
OTHER_CELL = grid([line(1, "Traction", 1, title=True), line(2, "Revenue", 2), line(3, "€1.5M", 2), line(4, "Outlook 2026", 3), line(5, "Team", 4)])
SENTENCE_IN_BLOCK = grid([line(1, "Traction", 1, title=True), line(2, "Revenue", 2), line(3, "€1.5M", 2), line(4, "Plan for 2026 and beyond", 2)])


def test_a_period_cited_from_a_top_band_cell_is_a_page_heading():
    item = one(TOP_BAND, claim("r4c1", 1_500_000, period="2026", period_cell="r2c1"))
    assert item["status"] == page_check.MATCHED and item["period"] == "2026" and item["period_cells"] == ["r2c1"]
    assert item["flags"] == [checker.PERIOD_FROM_HEADING] and not checker.flagged(item) and confidence(item, TOP_BAND) == "Medium"


def test_a_period_cited_from_another_cell_outside_the_block_is_informational():
    item = one(OTHER_CELL, claim("r3c1", 1_500_000, period="2026", period_cell="r4c1"))
    assert item["status"] == page_check.MATCHED and item["period"] == "2026" and item["period_cells"] == ["r4c1"]
    assert item["flags"] == [checker.PERIOD_FROM_OTHER_CELL] and not checker.flagged(item)
    assert checker.PERIOD_FROM_OTHER_CELL in checker.INFORMATIONAL_FLAGS and confidence(item, OTHER_CELL) == "Medium"


def test_a_cited_cell_that_states_no_period_is_not_a_period_source():
    item = one(OTHER_CELL, claim("r3c1", 1_500_000, period="2026", period_cell="r5c1"))
    assert checker.PERIOD_FROM_OTHER_CELL not in item["flags"] and checker.PERIOD_FROM_HEADING not in item["flags"]


def test_a_sentence_in_the_figures_own_block_stays_no_source():
    item = one(SENTENCE_IN_BLOCK, claim("r3c1", 1_500_000, period="2026", period_cell="r4c1"))
    assert checker.PERIOD_FROM_OTHER_CELL not in item["flags"] and checker.PERIOD_FROM_HEADING not in item["flags"]


def test_the_page_grid_marks_the_cells_in_the_top_fifth_of_the_page():
    from app.decks import pages
    blocks = [{"page": 1, "kind": "text", "text": "Plan 2026", "box": 1, "bbox": [0.1, 0.05, 0.4, 0.1]},
              {"page": 1, "kind": "text", "text": "Revenue €1.5M", "box": 2, "bbox": [0.1, 0.5, 0.4, 0.55]}]
    cells = {c["text"]: c for c in pages.page_grid(blocks)["cells"]}
    assert cells["Plan 2026"].get("top_band") is True and "top_band" not in cells["Revenue €1.5M"]


def test_a_period_no_cell_of_the_page_states_is_matched_with_a_review_flag():
    item = one(OWN_LINE, claim("r2c1", 1_500_000, period="2031"))
    assert item["status"] == page_check.MATCHED and item["flags"] == [checker.PERIOD_NOT_ON_PAGE] and checker.flagged(item)
    assert confidence(item, OWN_LINE) == "Low"


def test_a_null_period_gives_no_flag_and_a_medium_confidence_for_no_date():
    item = one(NO_DATE, claim("r2c1", 1_500_000))
    assert item["status"] == page_check.MATCHED and item["flags"] == [] and confidence(item, NO_DATE) == "Medium"


def test_a_unit_not_next_to_the_cell_is_the_informational_currency_assumed():
    page = grid([line(1, "Traction", 1, title=True), line(2, "Generates 20-30M+ per year profit in 2026", 2)])
    item = one(page, claim("r2c1", 20_000_000, metric="net_profit", unit="USD", period="2026", period_cell="r2c1"))
    assert item["status"] == page_check.MATCHED and item["flags"] == [checker.CURRENCY_ASSUMED] and not checker.flagged(item)
    assert confidence(item, page) == "Medium"
    percent = one(page, claim("r2c1", 20_000_000, metric="gross_margin", unit="%", period="2026", period_cell="r2c1"))
    assert percent["status"] == page_check.MATCHED and percent["flags"] == [checker.UNIT_ASSUMED] and not checker.flagged(percent)


def test_a_label_never_counts():
    far = grid([line(1, "Traction", 1, title=True), line(2, "€1.5M revenue in 2026", 2), line(3, "Far away heading", 3)])
    item = one(far, claim("r2c1", 1_500_000, period="2026", period_cell="r2c1", label_cell="r3c1"))
    assert item["status"] == page_check.MATCHED and item["label_cell"] is None and item["flags"] == []


def test_a_metric_other_is_matched_like_any_other():
    item = one(OWN_LINE, claim("r2c1", 1_500_000, metric="other", period="2026", period_cell="r2c1"))
    assert item["status"] == page_check.MATCHED and item["flags"] == [] and confidence(item, OWN_LINE) == "High"


def test_a_value_that_fails_is_not_matched_and_low():
    item = one(OWN_LINE, claim("r2c1", 999_000, period="2026", period_cell="r2c1"))
    assert item["status"] == page_check.UNMATCHED and checker.VALUE_NOT_ON_PAGE in item["flags"] and confidence(item, OWN_LINE) == "Low"


def test_a_cell_corrected_figure_is_medium():
    page = grid([line(1, "Traction", 1, title=True), line(2, "Revenue", 2), line(3, "€1.5M in 2026", 3)])
    item = one(page, claim("r2c1", 1_500_000, period="2026", period_cell="r3c1"))
    assert item["status"] == page_check.MATCHED and item["flags"] == [checker.CELL_CORRECTED] and confidence(item, page) == "Medium"


def test_the_rows_that_are_not_ai_reads_keep_the_parser_confidence():
    row = {"origin": "analyst"}
    assert claims.confidence(row, [row])["text"] == "Analyst-entered"
