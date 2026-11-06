"""Totals that don't add up, the written form of a period on stored checks, a formula error in a cited cell, and the card that is a note
(mapping-page brief of 2026-11-06, items 1 to 4). Synthetic sheets only; no client data (CLAUDE.md rule 15)."""
import asyncio
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import cards, checks, ic_memo, integrity, role_engine  # noqa: E402
from test_checks import build, cells_of, check, figure, fmap, row, sheet_map  # noqa: E402
from test_percent_and_period_forms import sheet_with, verdict  # noqa: E402
from test_role_engine import MONTHS, file_of, run, sheet  # noqa: E402
from test_role_engine import row as engine_row  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Parts that do not sum to their total are an integrity finding, never a rejection, a re-read or a card
# ---------------------------------------------------------------------------
def parts_rows(total_row=8):
    return [row(row=total_row, label_cell=f"A{total_row}", role="revenue", cells=f"B{total_row}:M{total_row}"),
            row(row=9, label_cell="A9", segment="Product A", parent_row=total_row, cells="B9:M9"),
            row(row=10, label_cell="A10", segment="Product B", parent_row=total_row, cells="B10:M10")]


def parts_result(total, a="120", b="80", col=(8, 4)):
    grid = build({col: str(total), (9, col[1]): a, (10, col[1]): b})
    return check(fmap(sheet_map(rows=parts_rows())), grid)


# (total, part A, part B, expected % shown or None when the parts add up)  -- the six shapes of the board-pack parts cases, synthetic figures
CASES = [
    ("129200", "40000", "22891", 51),         # a part row unmapped: parts are half the total
    ("260", "120", "80", 23),                 # a hard-coded total
    ("200", "120", "80", None),               # adds up
    ("201", "120", "80", None),               # 0.5 % off: within 1 %
    ("203", "120", "80", 1),                  # 1.5 % off: a finding
    ("-129200", "-40000", "-22891", 51),      # costs printed as negatives: the same finding, absolute values
]


@pytest.mark.parametrize("total,a,b,pct", CASES)
def test_a_total_that_its_parts_do_not_add_up_to_is_a_finding_with_no_rejected_item(total, a, b, pct):
    got = parts_result(total, a, b)
    assert not [i for i in got["items"] if i["outcome"] == checks.REJECTED], "the total row is kept as read"
    assert checks.reread_keys(got["items"]) == [], "nothing is read again"
    if pct is None:
        assert got["totals"] == []
        return
    (found,) = got["totals"]
    assert found["sheet"] == "Report" and found["row"] == 8 and found["cell"] == "D8"
    assert found["total"] == abs(float(total)) and found["parts_sum"] == abs(float(a) + float(b))
    assert found["difference"] == pytest.approx(abs(abs(float(total)) - abs(float(a) + float(b))))
    assert round(found["pct"] * 100) == pct


def test_the_finding_reaches_the_integrity_table_and_worth_flagging_over_5_percent_only():
    def results_for(total, a, b):
        grid = build({(8, 4): total, (9, 4): a, (10, 4): b})
        totals = check(fmap(sheet_map(rows=parts_rows())), grid)["totals"]
        book = file_of("f.xlsx", [sheet("CASHFLOW", [engine_row(4, "revenue", [1, 2, 3], MONTHS[:3])])])
        book["totals"] = [{**t, "sheet": "CASHFLOW", "row": 23, "cell": "D23"} for t in totals]
        return run([book], as_of="2025-03")

    big = results_for("129200", "40000", "22891")
    flag = big["role_metrics"]["integrity_flags"][0]
    assert flag["kind"] == "totals_mismatch" and flag["file"] == "f.xlsx"
    assert flag["text"] == "CASHFLOW row 23: total 129,200 vs parts 62,891, 51% — a part row may be unmapped or the total hard-coded", flag["text"]
    table = integrity.assess(big, deck_count=0, candidates=[])["statement_findings"]
    assert [f["kind"] for f in table] == ["totals_mismatch"] and table[0]["line"] == "Totals that don't add up"
    worth = ic_memo.role_flags(big, None, "EUR", ic_memo.Notes())
    assert any(line.startswith("CASHFLOW row 23: total 129,200 vs parts 62,891, 51%") for line in worth)

    small = results_for("203", "120", "80")                 # 1.5 %: in the table, not in Worth flagging
    assert small["role_metrics"]["integrity_flags"][0]["kind"] == "totals_mismatch"
    assert not [line for line in ic_memo.role_flags(small, None, "EUR", ic_memo.Notes()) if "total 203" in line]


def test_no_card_is_opened_for_a_parts_mismatch():
    got = parts_result("260")
    doc = {"reading_key": "k", "file": "f.xlsx", "file_hash": "h", "items": got["items"], "rereads": []}
    import test_llm_gateway as t
    db = t.FakeDB()
    assert asyncio.run(cards.open_for_checks(db, "a1", doc)) == []


# ---------------------------------------------------------------------------
# 2. A month named in words takes its year from a title, a neighbour or the block's closing header
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,period,header_cells", [
    ("January", "2024-01", {(2, 2): "2024", (3, 2): "January"}),                                  # the year in a title above
    ("November", "2024-11", {(3, 1): "2024", (3, 2): "November"}),                              # the year in the neighbouring cell
    ("January", "2024-01", {(3, 2): "January", (3, 3): "February", (3, 4): "March", (3, 5): "Q1 2024"}),     # the block's Qn header
    ("November", "2024-11", {(3, 2): "November", (3, 3): "December", (3, 4): "TOTAL 2024"}),    # the block's TOTAL header
])
def test_a_month_name_with_the_year_elsewhere_is_the_same_period_as_the_reading(name, period, header_cells):
    got = verdict(sheet_with(header_cells, "1200"), figure(1200, cell="B4", period=period))
    assert got["outcome"] == checks.CONFIRMED, (name, got)


# ---------------------------------------------------------------------------
# 3. The value check opens the cited cell; a formula error there is a formula error, not a disagreement
# ---------------------------------------------------------------------------
def test_the_cell_the_reading_cites_is_the_one_opened_not_the_first_of_the_row():
    grid = build({(4, 2): "1"})                          # B4, the first cell of the row's range, holds another value
    got = checks.check_figure(0, figure(130, cell="E4", period="2024-04"), cells_of(grid), {"Report": sheet_map()}, 12)
    assert got["found_value"] == 130.0 and got["outcome"] == checks.CONFIRMED, got


def test_a_cited_cell_holding_a_formula_error_is_a_formula_error_and_no_disagreement():
    grid = build({(4, 5): "#REF!"})
    got = checks.check_figure(0, figure(130, cell="E4", period="2024-04"), cells_of(grid), {"Report": sheet_map()}, 12)
    assert got["outcome"] == checks.CANNOT and got["reason"] == "cell E4 holds #REF!" and got["formula_error"] == "#REF!"
    assert checks.reread_keys([got]) == []


def test_a_formula_error_in_a_cited_cell_is_counted_in_the_formula_error_flag_once():
    item_ = {"key": "figure:Report:AW4:revenue", "kind": "figure", "outcome": checks.CANNOT, "reason": "cell AW4 holds #REF!", "sheet": "Report",
             "cell": "AW4", "formula_error": "#REF!"}
    counted = checks.formula_errors_of({"formula_errors": [{"sheet": "Report", "cell": "AW4", "error": "#REF!"}], "items": [item_]})
    assert counted == [{"sheet": "Report", "cell": "AW4", "error": "#REF!"}], "the cell is counted once"
    stored_without = checks.formula_errors_of({"formula_errors": [], "items": [item_]})
    assert stored_without == [{"sheet": "Report", "cell": "AW4", "error": "#REF!"}]
    flags = role_engine.formula_error_flags([{"file": "f.xlsx", "formula_errors": counted}])
    assert flags[0]["text"] == "f.xlsx: 1 formula error, Report!AW4"


# ---------------------------------------------------------------------------
# 4. A card is shown only when the analyst has a real choice
# ---------------------------------------------------------------------------
def citation_doc(first_value, found_value, row_item=False):
    key = "row:S:4" if row_item else "figure:S:B4:revenue"
    first = {"metric": "revenue", "value": first_value, "unit": "money", "currency": "EUR", "period": "2024-11", "evidence": "x"}
    return {"reading_key": "k", "file": "f.xlsx", "file_hash": "h", "items": [
        {"key": key, "kind": "row" if row_item else "figure", "outcome": "rejected", "reason": "x", "sheet": "S", "cell": "B4", "metric": "revenue",
         "value": first_value, "found_value": found_value, "found_period": "2024-10"}],
        "rereads": [{"item": key, "first_reason": "x", "reread": "repeats the first reading", "outcome": "rejected", "reason": "x", "action": "card",
                     "first": first, "second": first}]}


def opened(doc):
    import test_llm_gateway as t
    db = t.FakeDB()
    db["readings"].docs.append({"key": "k", "file_map": {"figures": [{"metric": "revenue", "value": 1.0, "unit": "money", "currency": "EUR",
                                                                      "period": "2024-11", "evidence": "x", "source": {"sheet": "S", "cell": "B4"}}]}})
    return asyncio.run(cards.open_for_checks(db, "a1", doc))


def test_two_different_values_are_a_card_with_the_choice_and_a_typed_value():
    (card,) = opened(citation_doc(1200.0, 1100.0))
    assert card["actions"] == ["use_cell", "use_reader", "type_value"]


def test_one_value_and_a_typed_one_is_still_a_card():
    (card,) = opened(citation_doc(1200.0, None))
    assert card["actions"] == ["use_reader", "type_value"]
    (card,) = opened(citation_doc(1200.0, 1200.0))
    assert card["actions"] == ["use_reader", "type_value"], "the cell and the reader hold one value: one button for it"


def test_a_card_with_no_value_to_choose_is_a_note():
    (card,) = opened(citation_doc(None, None, row_item=True))
    assert card["actions"] == []


# ---------------------------------------------------------------------------
# 2 again: a stored check is recomputed on every page load, from the stored cells, with no model call
# ---------------------------------------------------------------------------
def stored_doc(period, reason="Reading says 2024-11; cell B4 holds 1200."):
    key = "figure:Report:B4:revenue"
    first = {"metric": "revenue", "value": 1200.0, "unit": "money", "currency": "EUR", "period": period, "evidence": "x"}
    return {"reading_key": "k", "file": "f.xlsx", "file_hash": "h", "months": [], "items": [
        {"key": key, "kind": "figure", "outcome": "rejected", "reason": reason, "sheet": "Report", "cell": "B4", "metric": "revenue", "value": 1200.0,
         "found_value": 1200.0, "found_period": "2024-11"}],
        "rereads": [{"item": key, "first_reason": reason, "reread": "repeats the first reading", "outcome": "rejected", "reason": reason, "action": "card",
                     "first": first, "second": first}]}


def effective_map(period):
    smap = sheet_map(rows=[])
    smap["first_period_col"], smap["last_period_col"] = "B", "B"
    return fmap(smap, figures=[figure(1200, cell="B4", period=period)])


@pytest.mark.parametrize("header_cells,period", [({(2, 2): "2024", (3, 2): "November"}, "2024-11"),
                                                 ({(3, 2): "January", (3, 3): "TOTAL 2024"}, "2024-01"),
                                                 ({(3, 1): "2024", (3, 2): "January"}, "2024-01")])
def test_a_stored_rejection_that_only_the_written_form_of_the_period_caused_is_confirmed_on_recompute(header_cells, period):
    cells = sheet_with(header_cells, "1200")
    doc = stored_doc(period)
    got = checks.recheck_stored(doc, effective_map(period), cells)
    assert got["cleared"] == ["figure:Report:B4:revenue"] and got["items"][0]["outcome"] == checks.CONFIRMED
    other = checks.recheck_stored(stored_doc("2024-10"), effective_map("2024-10"), cells)
    assert other["cleared"] == [] and other["items"][0]["outcome"] == checks.REJECTED, "another month is still a disagreement"


def test_the_register_recomputes_the_stored_check_and_shows_no_card_for_it():
    import test_llm_gateway as t
    from app import register, stored_sheets
    db = t.FakeDB()
    grid = [["Report, EUR", None], [None, "2024"], ["Metric", "November"], ["Revenue", 1200]]
    db["datasets"].docs.append({"audit_id": "a1", "file_hash": "h", "recognition_sheets": [{"name": "Report", "csv": True, "grid": grid, "indents": [], "merged": []}]})
    assert stored_sheets.unpack_sheets(db["datasets"].docs[0]["recognition_sheets"]), "the fixture stores a readable sheet"
    doc = stored_doc("2024-11")
    smap = sheet_map(rows=[])
    smap["first_period_col"], smap["last_period_col"] = "B", "B"
    got = asyncio.run(register.refreshed(db, "a1", doc, fmap(smap, figures=[figure(1200, cell="B4", period="2024-11")])))
    assert got["cleared"] == ["figure:Report:B4:revenue"], got
