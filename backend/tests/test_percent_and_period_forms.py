"""Percentages and the written form of a period (board-pack layout fix, items 4 and 5). Synthetic cells only.

A deck figure printed as a percentage in the page text ("93% of the plan") matches a reading of 93 or of 0.93. A sheet figure whose value matches its
cell is no disagreement when only the written form of its period differs ("November" under a year title against 2024-11, "Q3 2024" against 2024-Q3)
or when the cell carries a % sign the reading dropped: the period is resolved from the header and the nearest year cell, and the figure is accepted."""
import sys
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import checks  # noqa: E402
from app.structures import page_check  # noqa: E402
from test_checks import cells_of, figure, sheet_map  # noqa: E402
from test_page_check import claim, grid, line, one  # noqa: E402

PAGE = grid([line(1, "ARR: 1 774 628 EUR - 93% of the plan!", 1, next_to=[])])


@pytest.mark.parametrize("value", [93, 0.93])
def test_a_percentage_in_the_page_text_matches_a_reading_of_93_or_0_93(value):
    got = one(PAGE, claim("r1c1", value, metric="other", unit="%"))
    assert got["status"] == page_check.MATCHED and got["checks"]["value"] is True, value


def test_a_percentage_that_is_not_in_the_text_is_still_unmatched():
    got = one(PAGE, claim("r1c1", 0.5, metric="other", unit="%"))
    assert got["status"] == page_check.UNMATCHED
    assert one(PAGE, claim("r1c1", 9.3, metric="other", unit="%"))["status"] == page_check.UNMATCHED


def test_0_93_is_not_a_money_figure_93():
    got = one(PAGE, claim("r1c1", 0.93, metric="revenue", unit="EUR"))
    assert got["status"] == page_check.UNMATCHED, "the scale of a percentage applies to a percentage claim only"


# ---------------------------------------------------------------------------
# Sheet figures
# ---------------------------------------------------------------------------
def sheet_with(header_cells, value_text, rate=False):
    """Row 3 holds the month headers from B; the cells above hold a year title; row 4 holds one value in B."""
    grid_ = {(1, 1): "Report, EUR", (3, 1): "Metric", (4, 1): "Share of plan" if rate else "Revenue", (4, 2): value_text}
    grid_.update(header_cells)
    return cells_of(grid_)


def verdict(cells, fig):
    smap = sheet_map(rows=[])
    smap["first_period_col"], smap["last_period_col"] = "B", "B"
    return checks.check_figure(0, fig, cells, {"Report": smap}, 12)


def test_a_month_name_under_a_year_title_resolves_to_the_month():
    cells = sheet_with({(2, 2): "2024", (3, 2): "November"}, "1200")
    got = verdict(cells, figure(1200, cell="B4", period="2024-11"))
    assert got["outcome"] == checks.CONFIRMED and got["found_period"] == "2024-11"


def test_the_nearest_year_cell_is_the_one_to_the_left_or_above():
    cells = sheet_with({(2, 2): "2023", (2, 3): "2024", (3, 2): "Nov", (3, 3): "Dec"}, "1200")
    assert verdict(cells, figure(1200, cell="B4", period="2023-11"))["outcome"] == checks.CONFIRMED
    assert verdict(cells, figure(1200, cell="B4", period="2024-11"))["outcome"] == checks.REJECTED, "the year is read, not assumed"


def test_a_month_name_with_no_year_anywhere_is_still_a_disagreement():
    cells = sheet_with({(3, 2): "November"}, "1200")
    assert verdict(cells, figure(1200, cell="B4", period="2024-11"))["outcome"] == checks.REJECTED


def test_a_quarter_written_q3_2024_is_the_quarter_2024_q3():
    cells = sheet_with({(3, 2): "Q3 2024"}, "1200")
    assert verdict(cells, figure(1200, cell="B4", period="2024-Q3", basis="quarterly"))["outcome"] == checks.CONFIRMED
    assert verdict(cells, figure(1200, cell="B4", period="Q3 2024", basis="quarterly"))["outcome"] == checks.CONFIRMED, "the reading's own form may be the written one"


def test_a_different_month_is_still_a_disagreement():
    cells = sheet_with({(2, 2): "2024", (3, 2): "November"}, "1200")
    got = verdict(cells, figure(1200, cell="B4", period="2024-10"))
    assert got["outcome"] == checks.REJECTED and "2024-10" in got["reason"]


def test_a_cell_with_a_percent_sign_the_reading_dropped_is_the_same_value():
    cells = sheet_with({(3, 2): date(2024, 11, 30).isoformat()}, "93%", rate=True)
    got = verdict(cells, figure(93, cell="B4", period="2024-11", unit="rate", metric="other"))
    assert got["outcome"] == checks.CONFIRMED, got
    again = verdict(cells, figure(0.93, cell="B4", period="2024-11", unit="rate", metric="other"))
    assert again["outcome"] == checks.CONFIRMED
    other = verdict(cells, figure(94, cell="B4", period="2024-11", unit="rate", metric="other"))
    assert other["outcome"] == checks.REJECTED


# ---------------------------------------------------------------------------
# Item 8: no "Reader and the file disagree" card when the check and the reader agree on the value
# ---------------------------------------------------------------------------
def card_doc(reader_value, found_value, found_period="2024-11", period="2024-11", unit="money"):
    first = {"metric": "revenue", "value": reader_value, "unit": unit, "currency": "EUR", "period": period, "evidence": "Revenue row"}
    return {"reading_key": "k", "file": "f.xlsx", "file_hash": "h", "items": [
        {"key": "figure:S:B4:revenue", "kind": "figure", "outcome": "rejected", "reason": "Figure period.", "sheet": "S", "cell": "B4", "metric": "revenue",
         "value": reader_value, "found_value": found_value, "found_period": found_period}],
        "rereads": [{"item": "figure:S:B4:revenue", "first_reason": "Figure period.", "reread": "repeats the first reading", "outcome": "rejected",
                     "reason": "Figure period.", "action": "card", "first": first, "second": first}]}


def opened(doc):
    import asyncio

    import test_llm_gateway as t
    from app import cards
    db = t.FakeDB()
    db["readings"].docs.append({"key": "k", "file_map": {"figures": [{"metric": "revenue", "value": doc["rereads"][0]["first"]["value"], "unit": "money",
                                                                      "currency": "EUR", "period": "2024-11", "evidence": "x", "source": {"sheet": "S", "cell": "B4"}}]}})
    return asyncio.run(cards.open_for_checks(db, "a1", doc))


def test_a_value_both_agree_on_with_the_period_in_another_written_form_opens_no_card():
    assert opened(card_doc(1200.0, 1200.0, found_period="2024-Q3", period="Q3 2024")) == []
    assert opened(card_doc(93.0, 0.93, unit="rate")) == [], "the reading dropped the % sign"


def test_a_value_the_cell_does_not_hold_or_a_period_that_differs_still_opens_the_card():
    (card,) = opened(card_doc(1200.0, 1100.0))
    assert card["title"] == "The reader and the file disagree"
    assert len(opened(card_doc(1200.0, 1200.0, found_period="2024-10"))) == 1, "same value, another month: the period is the disagreement"
