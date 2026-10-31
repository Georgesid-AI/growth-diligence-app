# ruff: noqa: F811, F401
"""The reading register and the cards (docs/design/read-check-review.md sections 5, 7.4, 11; PR 3 step c), on the synthetic monthly report of the
sheet reader flow tests: every figure with a check outcome lands on the register on its own, and a card exists for three cases only."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import cards, checks, lines, readings, register  # noqa: E402
from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION  # noqa: E402
from test_chat_upload import AUDIT  # noqa: E402
from test_reviewer import (ReviewRouter, audit_of, candidate, deck, finding, map_with, review, start)  # noqa: E402
from test_sheet_reader_flow import COMPANY, MONTHLY, SHEET, flow, good_map, monthly, upload  # noqa: E402

QUEUES_SHEET_READER = True      # tests/conftest.py: this module lets an upload queue the reader


def reading(flow):
    return flow.get(f"/api/audits/{AUDIT}/reading").json()


def wrong_figure(value=11000):
    fmap = good_map(revenue=value)
    return fmap


# ---------------------------------------------------------------------------
# Figures land on the register on their own
# ---------------------------------------------------------------------------
def test_every_figure_with_a_check_outcome_lands_on_the_register_with_no_card(flow):
    start(flow, map_with("bookings"))
    got = reading(flow)
    (confirmed,) = got["tables"]["confirmed"]
    assert confirmed["metric"] == "revenue" and confirmed["value"] == 10625.0 and confirmed["period"] == "2025-06"
    assert confirmed["basis"] == "monthly" and confirmed["actual_plan"] == "actual" and confirmed["row_role"] == "revenue"
    assert confirmed["source"] == {"file": MONTHLY, "file_hash": confirmed["source"]["file_hash"], "sheet": SHEET, "cell": "G4"}
    assert got["tables"]["rejected"] == [] and got["cards"] == [], "nothing flagged: no card"
    assert got["counts"] == {"confirmed": 1, "rejected": 0, "cannot_check": 0}
    (block,) = got["files"]
    assert block["kind"] == "sheet" and block["summary"]["last_actual"] == "2025-06" and block["summary"]["rejected"] == 0


def test_a_citation_that_fails_twice_is_rejected_on_the_register_and_opens_one_card_with_both_readings(flow):
    flow.state["adapter"] = ReviewRouter(wrong_figure(11000), again=wrong_figure(11000))
    upload(flow, MONTHLY, monthly())
    got = reading(flow)
    (rejected,) = got["tables"]["rejected"]
    assert rejected["value"] == 11000 and rejected["cell_value"] == 10625 and rejected["reread"] == "repeats the first reading"
    assert rejected["reason"] == "Reading says 11000; cell G4 holds 10625." and rejected["action"] == "card" and rejected["card_id"]
    (card,) = got["cards"]
    assert card["kind"] == cards.CITATION and card["status"] == "open" and card["id"] == rejected["card_id"]
    assert card["reader"]["value"] == 11000 and card["reader"]["label"] == "Reader, twice" and card["other"]["value"] == 10625
    assert card["other"]["label"] == "Cell G4" and card["source"]["cell"] == "G4" and card["actions"] == ["use_cell", "use_reader", "type_value"]
    # a second run of the checks opens no second card
    upload(flow, MONTHLY, monthly())
    assert len(flow.db[readings.CARDS].docs) == 1


@pytest.mark.parametrize("action,typed,expect", [("use_cell", None, 10625.0), ("use_reader", None, 11000.0), ("type_value", 10600.0, 10600.0)])
def test_a_card_is_decided_by_use_the_cell_use_the_reader_or_a_typed_value_and_the_reading_is_not_edited(flow, action, typed, expect):
    flow.state["adapter"] = ReviewRouter(wrong_figure(11000), again=wrong_figure(11000))
    upload(flow, MONTHLY, monthly())
    (card,) = reading(flow)["cards"]
    stored = json.loads(json.dumps(flow.db[readings.READINGS].docs[0]["file_map"]))
    done = flow.post(f"/api/audits/{AUDIT}/cards/{card['id']}", json={"action": action, **({"value": typed} if typed is not None else {})})
    assert done.status_code == 200 and done.json()["decision"]["value"] == expect
    assert flow.db[readings.READINGS].docs[0]["file_map"] == stored, "the reading is never edited"
    (override,) = flow.db[readings.OVERRIDES].docs
    assert override["path"] == "figures.0.value" and override["new"] == expect and override["old"] == 11000 and override["who"] == "analyst"
    got = reading(flow)
    assert got["tables"]["rejected"] == [] and got["tables"]["confirmed"][0]["value"] == expect
    row = got["tables"]["confirmed"][0]
    assert row["note"] == "set by analyst" and row["hover"] == "value set by analyst; the check did not confirm it"
    assert row["set_at"] and len(row["set_at"]) == 10, "a date"
    file_hash = flow.db[readings.READINGS].docs[0]["file_hash"]
    exported = flow.get(f"/api/audits/{AUDIT}/readings/{file_hash}/export").json()
    (mark,) = exported["set_by_analyst"]
    assert mark["note"] == "set by analyst" and mark["value"] == expect and mark["hover"] == row["hover"] and mark["set_at"] == row["set_at"]
    csv_text = flow.get(f"/api/audits/{AUDIT}/readings/{file_hash}/export?format=csv").text
    assert f"set by analyst, {row['set_at']}: value set by analyst; the check did not confirm it" in csv_text
    assert flow.post(f"/api/audits/{AUDIT}/cards/{card['id']}", json={"action": "use_cell"}).status_code == 404, "a decided card is closed"


def test_a_card_offers_only_the_actions_it_has_and_refuses_the_rest(flow):
    flow.state["adapter"] = ReviewRouter(map_with("revenue"), again=map_with("revenue"), review={"findings": [finding()]})
    upload(flow, MONTHLY, monthly())
    review(flow)
    (card,) = reading(flow)["cards"]
    assert card["kind"] == cards.DISAGREEMENT and card["actions"] == ["use_reader"]
    assert flow.post(f"/api/audits/{AUDIT}/cards/{card['id']}", json={"action": "use_cell"}).status_code == 400
    assert flow.post(f"/api/audits/{AUDIT}/cards/{card['id']}", json={"action": "use_reader"}).status_code == 200
    assert not flow.db[readings.OVERRIDES].docs, "keeping the reader's role overrides nothing"


def test_a_masked_value_the_reading_needs_opens_a_card_and_nothing_else_does():
    from test_checks import build  # noqa: F401
    import test_llm_gateway as t
    db = t.FakeDB()
    doc = {"reading_key": "k", "file": "f.xlsx", "file_hash": "h", "rereads": [], "items": [
        {"key": "figure:S:B2:revenue", "kind": "figure", "outcome": "cannot_check", "reason": "Depends on a name that was masked before reading.",
         "sheet": "S", "cell": "B2", "metric": "revenue", "value": 5.0},
        {"key": "figure:S:B3:revenue", "kind": "figure", "outcome": "cannot_check", "reason": "No cell reference given.", "sheet": "S", "cell": None,
         "metric": "revenue", "value": 6.0},
        {"key": "figure:S:B4:revenue", "kind": "figure", "outcome": "cannot_check", "sheet": "S", "cell": "B4", "metric": "revenue", "value": 7.0,
         "reason": "Some other reason that happens to say masked before reading."}]}
    db[readings.READINGS].docs.append({"key": "k", "file_map": {"figures": [{"metric": "revenue", "value": 5.0, "unit": "money", "currency": "EUR",
                                                                         "period": "2025-01", "evidence": "x", "source": {"sheet": "S", "cell": "B2"}}]}})
    made = asyncio.run(cards.open_for_checks(db, "a1", doc))
    assert [c["kind"] for c in made] == [cards.MASKED] and made[0]["actions"] == ["use_reader", "type_value"]
    assert made[0]["reader"]["value"] == 5.0 and made[0]["path"] == "figures.0.value"
    assert len(db[readings.CARDS].docs) == 1, "the card follows the check's own closed reason, not a word found in some text"


def test_a_figure_that_cannot_be_checked_is_on_the_register_with_its_reason_and_what_relies_on_it(flow):
    fmap = good_map()
    fmap["figures"].append({"metric": "customers", "value": 7.0, "unit": "count", "currency": None, "period": "2025-06", "basis": "monthly",
                            "actual_plan": "actual", "segment": None, "source": {"sheet": SHEET, "cell": None, "page": None, "text_layer": None},
                            "evidence": "no cell given"})
    start(flow, fmap)
    got = reading(flow)
    (row,) = got["tables"]["cannot_check"]
    assert row["reason"] == "No cell reference given." and row["metric"] == "customers" and row["used_in"] == "Customers series"
    assert got["cards"] == []


# ---------------------------------------------------------------------------
# The lines of a file block
# ---------------------------------------------------------------------------
def r(n, role, basis="yearly", **over):
    return {"row": n, "label_cell": f"A{n}", "role": role, "metric": None, "basis": basis, "actual_plan": "mixed", "boundary_col": "D", "segment": None,
            "parent_row": None, "unit": "money", "currency": None, "cells": f"B{n}:H{n}", "variance_of": None, "by_column": False, "evidence": "e", **over}


LABELS = {3: "revenue growth rate", 4: "Revenue (recognised)", 5: "Cloud video processing", 6: "Analytical suite", 7: "Cost of goods sold",
          8: "Gross margin", 9: "Gross margin as % of revenue"}


def test_a_rate_row_is_shown_directly_under_its_line_with_the_note_and_part_rows_are_indented_under_their_total():
    smap = {"rows": [r(3, "growth_rate", "rate"), r(4, "revenue"), r(5, "revenue", parent_row=4), r(6, "revenue", parent_row=4), r(7, "cost_of_revenue"),
                     r(8, "other"), r(9, "margin_rate", "rate")]}
    built = lines.build(smap, LABELS)
    assert [(ln["row"], ln["indent"], ln["moved"]) for ln in built] == [(4, 0, False), (3, 1, True), (5, 1, False), (6, 1, False), (7, 0, False),
                                                                          (8, 0, False), (9, 0, False)]
    assert built[1]["read_as"] == "growth rate" and built[2]["read_as"] == "revenue, part of row 4"
    assert built[0]["actual_plan"] == "mixed, boundary D" and built[0]["basis"] == "yearly" and built[0]["cells"] == "B4:H4"


def test_a_part_nested_under_another_part_is_a_line_indented_one_level_per_parent():
    smap = {"rows": [r(4, "revenue"), r(5, "revenue", parent_row=4), r(6, "revenue", parent_row=5), r(7, "revenue", parent_row=5), r(8, "revenue", parent_row=6),
                     r(9, "other")]}
    built = lines.build(smap, {n: f"Line {n}" for n in range(4, 10)})
    assert [(ln["row"], ln["indent"]) for ln in built] == [(4, 0), (5, 1), (6, 2), (8, 3), (7, 2), (9, 0)], "every mapped row is a line"
    assert built[2]["read_as"] == "revenue, part of row 5"
    ring = lines.build({"rows": [r(4, "revenue", parent_row=5), r(5, "revenue", parent_row=4)]}, {4: "A", 5: "B"})
    assert sorted(ln["row"] for ln in ring) == [4, 5], "a ring of parents loses no row"


def test_a_rate_whose_line_cannot_be_told_uniquely_stays_where_it_is():
    smap = {"rows": [r(3, "churn_rate", "rate"), r(4, "mrr"), r(5, "mrr")]}
    built = lines.build(smap, {3: "MRR churn rate", 4: "MRR from annual subscriptions", 5: "MRR from monthly subscriptions"})
    assert [(ln["row"], ln["moved"], ln["indent"]) for ln in built] == [(3, False, 0), (4, False, 0), (5, False, 0)]


def test_the_lines_of_an_uploaded_file_are_in_file_order_with_the_read_as_and_boundary(flow):
    start(flow, map_with("bookings"))
    (block,) = reading(flow)["files"]
    (sheet,) = block["lines"]
    assert [ln["row"] for ln in sheet["lines"]] == [4, 10] and sheet["lines"][0]["label"] == "Recognised revenue (EUR)"
    assert sheet["lines"][1]["read_as"] == "bookings" and sheet["lines"][1]["actual_plan"] == "mixed, boundary G"
    assert block["anchors"]["revenue_row"]["row"] == 4 and block["anchors"]["actual_plan"] == {"sheet": SHEET, "last_actual": "G", "plan_from": "H"}


def test_a_change_of_the_revenue_row_and_of_the_boundary_are_override_records_and_show_in_the_lines(flow):
    start(flow, map_with("bookings"))
    file_hash = reading(flow)["files"][0]["file_hash"]
    stored = json.loads(json.dumps(flow.db[readings.READINGS].docs[0]["file_map"]))
    done = flow.post(f"/api/audits/{AUDIT}/readings/{file_hash}/change", json={"what": "revenue_row", "sheet": SHEET, "row": 10})
    assert done.status_code == 200 and done.json()["overrides"] >= 2
    moved = flow.post(f"/api/audits/{AUDIT}/readings/{file_hash}/change", json={"what": "boundary", "sheet": SHEET, "column": "f"})
    assert moved.status_code == 200
    block = reading(flow)["files"][0]
    assert block["anchors"]["revenue_row"]["row"] == 10 and block["anchors"]["actual_plan"]["last_actual"] == "F"
    shown = {ln["row"]: ln["read_as"] for ln in block["lines"][0]["lines"]}
    assert shown[4] == "revenue" and shown[10] == "revenue", "the analyst named one row: the row that was the revenue row keeps the reader's role"
    assert {o["item"] for o in flow.db[readings.OVERRIDES].docs if o["why"] == "Change: revenue row"} == {f"row:{SHEET}:10"}
    assert block["lines"][0]["lines"][0]["actual_plan"] == "mixed, boundary F"
    assert flow.db[readings.READINGS].docs[0]["file_map"] == stored and all(o["who"] == "analyst" for o in flow.db[readings.OVERRIDES].docs)
    assert flow.post(f"/api/audits/{AUDIT}/readings/{file_hash}/change", json={"what": "revenue_row", "sheet": SHEET, "row": 99}).status_code == 400
    assert flow.post(f"/api/audits/{AUDIT}/readings/{file_hash}/change", json={"what": "boundary", "sheet": SHEET, "column": "ZZ"}).status_code == 400


# ---------------------------------------------------------------------------
# Decks on the register
# ---------------------------------------------------------------------------
def test_deck_figures_land_in_the_same_three_tables_and_the_deck_block_counts_them(flow):
    start(flow, map_with("bookings"))
    uid = audit_of(flow)["id"]
    flow.db[TEXT_COLLECTION].docs.append({**deck([{"page": 2, "text": "ARR 447,223 and customers 120", "kind": "text"}]), "audit_id": uid, "figure_pages": 1})
    flow.db[CANDIDATES_COLLECTION].docs += [
        {**candidate(447223), "audit_id": uid},
        {**candidate(999999, id="c2"), "audit_id": uid},                                           # on no line of the page
        {**candidate(5, id="c3", page=3), "audit_id": uid}]                                        # a page with no text
    got = reading(flow)
    assert [r_["source"]["page"] for r_ in got["tables"]["confirmed"] if r_["kind"] == "deck_figure"] == [2]
    assert [r_["reason"] for r_ in got["tables"]["rejected"]] == ["Reading says 999999; page 2 holds no such figure."]
    assert [r_["reason"] for r_ in got["tables"]["cannot_check"]] == ["Page 3 has no text layer; figure read from the image."]
    deck_block = next(b for b in got["files"] if b["kind"] == "deck")
    assert deck_block["anchors"]["figures"] == {"read": 3, "found_on_page": 1, "from_image": 1} and deck_block["summary"]["pages_with_figures"] == 1


def test_delete_audit_removes_the_reviews_and_the_cards(flow):
    flow.state["adapter"] = ReviewRouter(map_with("revenue"), again=map_with("revenue"), review={"findings": [finding()]})
    upload(flow, MONTHLY, monthly())
    review(flow)
    assert flow.db[readings.REVIEWS].docs and flow.db[readings.CARDS].docs
    assert flow.request("DELETE", f"/api/audits/{AUDIT}", json={"confirm": COMPANY}).status_code == 200
    assert all(not flow.db[c].docs for c in readings.COLLECTIONS), "no document of the audit survives in any collection"


def test_a_rejected_figure_the_second_reading_corrects_opens_no_card_and_is_confirmed_with_its_note(flow):
    flow.state["adapter"] = ReviewRouter(wrong_figure(11000), again=wrong_figure(10625))
    upload(flow, MONTHLY, monthly())
    got = reading(flow)
    assert got["cards"] == [] and got["tables"]["rejected"] == []
    assert [(c["value"], c["note"]) for c in got["tables"]["confirmed"]] == [(10625.0, "corrected automatically")]


def test_a_decision_the_card_does_not_offer_is_refused_even_when_a_cell_value_exists():
    import test_llm_gateway as t
    db = t.FakeDB()
    asyncio.run(cards.open_card(db, "a1", kind=cards.CITATION, item="row:S:4", title="t", source={}, reader={"value": 1.0}, other=None,
                                cell_value=9.0, actions=[cards.USE_READER]))
    (card,) = db[readings.CARDS].docs
    with pytest.raises(ValueError):
        asyncio.run(cards.decide(db, "a1", card["id"], cards.USE_CELL))
    assert asyncio.run(cards.decide(db, "a1", card["id"], cards.USE_READER))["decision"]["value"] == 1.0


def test_the_link_of_a_source_opens_the_cell_with_the_cells_around_it(flow):
    start(flow, map_with("bookings"))
    file_hash = reading(flow)["files"][0]["file_hash"]
    got = flow.get(f"/api/audits/{AUDIT}/readings/{file_hash}/cell", params={"sheet": SHEET, "cell": "G4"}).json()
    assert got["cell"] == "G4"
    cited = [c for r_ in got["rows"] for c in r_["cells"] if c["cited"]]
    assert cited == [{"ref": "G4", "text": "10625", "cited": True}]
    assert [r_["row"] for r_ in got["rows"]] == [1, 2, 3, 4, 5, 6, 7]
    assert flow.get(f"/api/audits/{AUDIT}/readings/{file_hash}/cell", params={"sheet": "No such", "cell": "G4"}).status_code == 404
    assert flow.get(f"/api/audits/{AUDIT}/readings/{'0' * 64}/cell", params={"sheet": SHEET, "cell": "G4"}).status_code == 404
    assert reading(flow)["files"][0]["summary"]["granularity"] == "monthly"


# ---------------------------------------------------------------------------
# Figures only: row-level outcomes are notes on their row, not table rows, and the summary counts what the tables count
# ---------------------------------------------------------------------------
def test_a_row_level_outcome_is_a_note_on_its_row_and_not_in_the_tables_and_the_summary_counts_the_tables(flow):
    start(flow, good_map())
    doc = flow.db[readings.CHECKS].docs[0]
    row_no = doc["lines"][0]["lines"][0]["row"]
    doc["items"] += [
        {"key": f"row:{SHEET}:{row_no}", "kind": "row", "outcome": "cannot_check", "reason": checks.C_SEGMENT_TOTAL, "sheet": SHEET, "cell": "A1", "row": row_no},
        {"key": f"parts:{SHEET}:{row_no}", "kind": "parts", "outcome": "rejected", "reason": "parts differ", "sheet": SHEET, "cell": "A1", "row": row_no},
        {"key": f"periods:{SHEET}", "kind": "periods", "outcome": "cannot_check", "reason": "header unclear", "sheet": SHEET, "cell": None}]
    got = reading(flow)
    shown = [x["reason"] for name in got["tables"] for x in got["tables"][name]]
    assert checks.C_SEGMENT_TOTAL not in shown and "parts differ" not in shown and "header unclear" not in shown
    (block,) = got["files"]
    line = next(ln for e in block["lines"] for ln in e["lines"] if ln["row"] == row_no)
    assert checks.C_SEGMENT_TOTAL in line["note"] and "parts differ" in line["note"]
    assert [n["reason"] for n in block["notes"]] == ["header unclear"]
    assert {k: block["summary"][k] for k in ("confirmed", "rejected", "cannot_check")} == got["counts"] == {"confirmed": 1, "rejected": 0, "cannot_check": 0}

