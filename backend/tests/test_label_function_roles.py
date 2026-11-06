# ruff: noqa: F811, F401
"""Function from label for the cost sub-lines (George, 2026-11-06). A part row whose parent is an OPEX or cost-of-revenue total, and whose role
the model gave as opex, other or none, gets its role from its label by keyword (checks.classify_by_label, one list FUNCTION_KEYWORDS). The row
is marked "classified by label"; a combined personnel line gets no function; the double read compares the rows after the rule, so the two
reads agree on them. Synthetic sheets only: the shapes are a P&L with a block of OPEX lines (rows 22-29) and a sheet that already has
function subtotals."""
import copy
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import checks, consistency, report_text, role_engine  # noqa: E402
from app.structures import redact  # noqa: E402
from test_role_engine import file_of, metric, run, series, sheet  # noqa: E402
from test_memo_cleanup_4f import YEARS  # noqa: E402

LABELS = {                                           # the GV PNL shape: a revenue line, a cost-of-revenue total, an OPEX total and its lines
    4: "Revenue", 5: "COST OF REVENUE",
    6: "Cloud hosting", 7: "Customer support", 8: "Third-party licences",
    20: "OPERATING EXPENSES (OPEX)",
    22: "PERSONNEL COSTS (EMPLOYEES+CONTRACTORS)", 23: "Office rent", 24: "IT equipment", 25: "Business development",
    26: "Marketing and events", 27: "Legal and accounting", 28: "Software development", 29: "Miscellaneous",
}


def cells_for(labels, name="PNL"):
    grid = [{"row": r, "col": 1, "text": t} for r, t in labels.items()]
    return checks.Cells(redact.reading_text([{"name": name, "cells": grid}]))


def part(n, role="opex", parent=20, **over):
    return {"row": n, "label_cell": f"A{n}", "role": role, "metric": "opex" if role == "opex" else None, "parent_row": parent, "basis": "yearly",
            "actual_plan": "actual", "unit": "money", "cells": f"B{n}:D{n}", "evidence": "x", **over}


def pnl_map(parts=None, extra=()):
    rows = [{**part(4, "revenue", None), "metric": "revenue"}, {**part(5, "cost_of_revenue", None), "metric": "cost_of_revenue"},
            part(20, "opex", None)]
    rows += parts if parts is not None else [part(6, "opex", 5), part(7, "other", 5), part(8, None, 5),
                                             part(22), part(23, "other"), part(24, None), part(25), part(26, "opex"), part(27, "other"), part(28),
                                             part(29, "other")]
    rows += list(extra)
    smap = {"sheet": "PNL", "header_row": 2, "label_col": "A", "first_period_col": "B", "last_period_col": "D", "granularity": "yearly", "rows": rows}
    return {"map_version": 1, "kind": "sheet", "sheets": [smap], "figures": []}


def by_row(fmap):
    return {r["row"]: r for r in fmap["sheets"][0]["rows"]}


def test_the_gv_shape_gets_its_function_roles_from_the_labels():
    fmap = pnl_map()
    got = by_row(checks.classify_by_label(fmap, cells_for(LABELS)))
    assert {n: got[n]["role"] for n in (23, 24, 25, 26, 27, 28)} == {23: "ga", 24: "ga", 25: "sales_marketing", 26: "sales_marketing", 27: "ga", 28: "rnd"}
    assert {n: got[n]["metric"] for n in (23, 25, 28)} == {23: "ga_expense", 25: "sm_expense", 28: "rnd_expense"}, "the metric follows the role"
    assert all(got[n]["classified_by"] == "label" for n in (23, 24, 25, 26, 27, 28))
    assert all(got[n].get("parent_row") == 20 for n in (23, 24, 25, 26, 27, 28)), "the link to the total stays"


def test_a_label_on_two_lists_or_on_none_keeps_the_models_role():
    labels = {**LABELS, 26: "Product marketing", 27: "Sundries"}
    got = by_row(checks.classify_by_label(pnl_map(), cells_for(labels)))
    assert got[26]["role"] == "opex" and got[26].get("classified_by") is None, "product (R&D) and marketing (S&M): two lists"
    assert got[27]["role"] == "other" and got[27].get("classified_by") is None
    assert got[29]["role"] == "other" and got[29].get("classified_by") is None, "Miscellaneous matches no list"


def test_business_development_is_sales_not_r_and_d():
    got = by_row(checks.classify_by_label(pnl_map(), cells_for(LABELS)))
    assert got[25]["role"] == "sales_marketing", "the longer keyword decides over 'development'"
    assert got[28]["role"] == "rnd"


def test_only_the_models_roles_opex_other_and_none_are_replaced():
    parts = [part(23, "rnd"), part(24, "ga"), part(25, "cost_of_revenue"), part(26, "headcount")]
    got = by_row(checks.classify_by_label(pnl_map(parts), cells_for({**LABELS, 23: "Marketing", 24: "Marketing", 25: "Marketing", 26: "Marketing"})))
    assert [got[n]["role"] for n in (23, 24, 25, 26)] == ["rnd", "ga", "cost_of_revenue", "headcount"]


def test_a_row_whose_parent_is_no_total_of_opex_or_cost_of_revenue_is_not_touched():
    parts = [part(23, "other", parent=None), part(24, "other", parent=4)]
    got = by_row(checks.classify_by_label(pnl_map(parts), cells_for({**LABELS, 23: "Marketing", 24: "Marketing"})))
    assert got[23]["role"] == "other" and got[24]["role"] == "other"


def test_cost_of_revenue_parts_keep_the_parents_role():
    got = by_row(checks.classify_by_label(pnl_map(), cells_for(LABELS)))
    assert got[6]["role"] == "cost_of_revenue" and got[6]["metric"] == "cost_of_revenue" and got[6]["classified_by"] == "label"
    assert got[7]["role"] == "cost_of_revenue", "support"
    assert got[8]["role"] is None and got[8].get("classified_by") is None, "licences: no word of the list"


def test_a_function_word_under_a_cost_of_revenue_total_is_no_function():
    parts = [part(6, "other", 5)]
    got = by_row(checks.classify_by_label(pnl_map(parts), cells_for({**LABELS, 6: "Marketing"})))
    assert got[6]["role"] == "other"


def test_a_combined_personnel_line_gets_no_function_and_is_marked():
    got = by_row(checks.classify_by_label(pnl_map([part(22, "other")]), cells_for(LABELS)))
    assert got[22]["role"] == "opex" and got[22]["metric"] == "opex" and got[22]["classified_by"] == "combined", "an OPEX line, split by no function"


def test_a_function_that_the_sheet_already_has_as_a_subtotal_is_not_assigned_by_label():
    # Tc shape: S&M and R&D subtotal rows with their own parts; loose lines under the OPEX total. G&A has no subtotal.
    extra = [part(10, "sales_marketing", 20, metric="sm_expense"), part(11, "other", 10), part(12, "rnd", 20, metric="rnd_expense"), part(13, "other", 12)]
    parts = [part(23, "other"), part(24, "other"), part(25, "other")]
    labels = {**LABELS, 10: "Sales and marketing", 11: "Advertising", 12: "Research and development", 13: "Engineering team",
              23: "Office rent", 24: "Events", 25: "Software"}
    got = by_row(checks.classify_by_label(pnl_map(parts, extra), cells_for(labels)))
    assert got[11]["role"] == "other" and got[13]["role"] == "other", "parts of a subtotal are covered by it"
    assert got[23]["role"] == "ga" and got[23]["classified_by"] == "label", "G&A has no subtotal row"
    assert got[24]["role"] == "other" and got[25]["role"] == "other", "S&M and R&D are the subtotals' own"


def test_the_rule_is_idempotent_and_leaves_its_input_alone():
    fmap, cells = pnl_map(), cells_for(LABELS)
    before = copy.deepcopy(fmap)
    once = checks.classify_by_label(fmap, cells)
    assert fmap == before
    assert checks.classify_by_label(once, cells) == once


def test_the_keyword_list_is_one_constant_and_matches_whole_words_only():
    assert isinstance(checks.FUNCTION_KEYWORDS, dict) and set(checks.FUNCTION_KEYWORDS) == {"sales_marketing", "rnd", "ga"}
    assert checks.function_of("Current liabilities") is None, "'rent' inside a word"
    assert checks.function_of("PR agency") == "sales_marketing" and checks.function_of("Sprint") is None
    assert checks.function_of("HR costs") == "ga" and checks.function_of("Trade shows") == "sales_marketing"


# ---------------------------------------------------------------------------
# The engine reads the rows: S&M, R&D and G&A from the classified parts, the method text says so
# ---------------------------------------------------------------------------
def engine_rows(fmap):
    out = []
    for r in fmap["sheets"][0]["rows"]:
        r = copy.deepcopy(r)
        r.update(basis="yearly", segment=None, series=series([100 + r["row"], 110 + r["row"], 120 + r["row"]], YEARS, first_row=r["row"]))
        out.append(r)
    return out


def test_the_engine_sums_the_classified_parts_and_the_method_text_names_them():
    fmap = checks.classify_by_label(pnl_map(), cells_for(LABELS))
    rows = engine_rows(fmap)
    rows[0]["series"] = series([1_000, 1_500, 2_400], YEARS, first_row=4)
    sm = metric(run([file_of("pnl", [sheet("PNL", rows, granularity="yearly")])]), "sm_share")
    assert sm["status"] == "computed", sm["reason"]
    assert sm["value"] == pytest.approx((145 + 146) / 2_400), "rows 25 and 26 of the latest year"
    assert "rows 25, 26 classified by label" in sm["source"]["rule"], "the rows classified are named"


# ---------------------------------------------------------------------------
# The double read: the rows are compared after the rule
# ---------------------------------------------------------------------------
def test_rows_the_two_reads_gave_as_opex_other_or_none_are_no_uncertain_item_once_classified():
    cells = cells_for(LABELS)
    first, second = pnl_map(), pnl_map([part(6, "opex", 5), part(7, "opex", 5), part(8, "other", 5), part(22, "other"), part(23, "opex"), part(24, "opex"),
                                         part(25, "other"), part(26, "other"), part(27, "opex"), part(28, "other"), part(29, "opex")])
    assert consistency.compare(first, second), "unclassified the reads differ: the premise"
    items = consistency.compare(checks.classify_by_label(first, cells), checks.classify_by_label(second, cells))
    left = sorted(n for i in items for n in i.get("rows") or [])
    assert left == [8, 29], left        # a row with no word of the list keeps the models role: those two reads still differ on it, as before


# ---------------------------------------------------------------------------
# Data gaps: a combined personnel line says so
# ---------------------------------------------------------------------------
def test_the_data_gaps_name_the_unsplit_personnel_line_and_not_a_missing_row():
    fmap = checks.classify_by_label(pnl_map([part(22), part(29, "other")]), cells_for(LABELS))
    rows = engine_rows(fmap)
    rows[0]["series"] = series([1_000, 1_500, 2_400], YEARS, first_row=4)
    files = [file_of("pnl", [sheet("PNL", rows, granularity="yearly")])]
    table = role_engine.build_table(files)
    reason = report_text.missing_reason(table, ["revenue", "sales_marketing"], "needs a sales_marketing row")
    assert reason == "personnel costs not split by function; the split is requested", reason
    assert "needs a sales and marketing row" not in reason
    assert report_text.request_line(report_text.request_roles(table, ["sales_marketing"])) == "A file with the split of personnel costs by function"


def test_without_a_combined_line_the_missing_row_wording_stays():
    fmap = checks.classify_by_label(pnl_map([part(29, "other")]), cells_for(LABELS))
    rows = engine_rows(fmap)
    rows[0]["series"] = series([1_000, 1_500, 2_400], YEARS, first_row=4)
    table = role_engine.build_table([file_of("pnl", [sheet("PNL", rows, granularity="yearly")])])
    assert report_text.missing_reason(table, ["revenue", "sales_marketing"], "needs a sales_marketing row") == "needs a sales and marketing row", "the wording of a row no file maps"


# ---------------------------------------------------------------------------
# Through the upload: two scripted reads that disagree on the roles of the sub-lines
# ---------------------------------------------------------------------------
from test_reading_consistency import TwoReads, checks_doc, upload  # noqa: E402
from test_reading_consistency import flow  # noqa: E402,F401,F811
from test_sheet_reader_flow import good_map  # noqa: E402

QUEUES_SHEET_READER = True      # tests/conftest.py: an upload queues the reader
OPEX_CSV = "\n".join(["P&L by month,,,,,,", "All figures in thousands,,,,,,", "Month,Jan-25,Feb-25,Mar-25,Apr-25,May-25,Jun-25", "Revenue,100,110,120,130,140,150",
                      "OPEX,60,61,62,63,64,65", "Marketing and events,10,10,10,10,10,10", "Office rent,5,5,5,5,5,5", "Sundries,3,3,3,3,3,3"]).encode()


def opex_map(roles):
    fmap = good_map()
    fmap["figures"] = []
    smap = fmap["sheets"][0]
    smap["last_period_col"], smap["last_actual"], smap["granularity"], smap["currency"], smap["currency_cell"] = "G", None, "monthly", None, None

    def line(n, role, parent=None, **over):
        return {**smap["rows"][0], "row": n, "label_cell": f"A{n}", "role": role, "metric": None, "parent_row": parent, "actual_plan": "actual",
                "boundary_col": None, "cells": f"B{n}:G{n}", "currency": None, "evidence": "x", **over}
    smap["rows"] = [line(4, "revenue", metric="revenue"), line(5, "opex", metric="opex"),
                    line(6, roles[0], 5), line(7, roles[1], 5), line(8, roles[2], 5)]
    return fmap


def test_the_two_reads_agree_on_the_sub_lines_through_the_upload(flow):
    flow.state["adapter"] = TwoReads(opex_map(["opex", "opex", "other"]), opex_map(["other", "other", "opex"]))
    upload(flow, "opex.csv", OPEX_CSV)
    doc = checks_doc(flow)
    assert doc["consistency"]["status"] == "compared"
    rows = sorted(n for i in doc["consistency"]["items"] for n in i.get("rows") or [])
    assert rows == [8], "the label rule gave rows 6 and 7 their roles in both reads; 'Sundries' names no function and still differs"
    stored = flow.db["readings"].docs[0]["file_map"]["sheets"][0]["rows"]
    assert [(r["row"], r["role"], r.get("classified_by")) for r in stored[2:]] == [(6, "sales_marketing", "label"), (7, "ga", "label"), (8, "other", None)]
    lines = doc["lines"][0]["lines"]
    assert [ln["read_as"] for ln in lines if ln["row"] in (6, 7)] == ["sales & marketing, classified by label, part of row 5", "G&A, classified by label, part of row 5"]


# ---------------------------------------------------------------------------
# Tc shape (George, 2026-11-06): no subtotals; eight S&M part rows the model already labelled, one R&D row, one G&A row
# ---------------------------------------------------------------------------
def test_rows_the_model_already_gave_a_function_keep_it_whatever_their_label_says():
    s_and_m = [part(10 + i, "sales_marketing", metric="sm_expense") for i in range(8)]
    parts = [*s_and_m, part(18, "rnd", metric="rnd_expense"), part(19, "ga", metric="ga_expense")]
    labels = {**{10 + i: name for i, name in enumerate(["Office rent", "Software", "Legal", "Marketing", "Events", "Sales", "Insurance", "Product"])},
              18: "Marketing", 19: "Marketing"}
    got = by_row(checks.classify_by_label(pnl_map(parts), cells_for({**LABELS, **labels})))
    assert [got[10 + i]["role"] for i in range(8)] == ["sales_marketing"] * 8 and got[18]["role"] == "rnd" and got[19]["role"] == "ga"
    assert all(got[n].get("classified_by") is None for n in range(10, 20)), "the model's own roles carry no mark"


# ---------------------------------------------------------------------------
# Stored readings: the register applies the rule at read time, no model call; an analyst's Change still wins
# ---------------------------------------------------------------------------
import asyncio  # noqa: E402

import test_llm_gateway as t  # noqa: E402
from app import readings, register  # noqa: E402

SMALL = {1: "P&L", 2: "Revenue", 3: "OPEX", 4: "Marketing", 5: "Office rent", 6: "Sundries"}


def stored_db(overrides=()):
    db = t.FakeDB()
    rows = [{**part(2, "revenue", None), "metric": "revenue"}, part(3, "opex", None), part(4, "other", 3), part(5, "opex", 3), part(6, "other", 3)]
    smap = {"sheet": "PNL", "header_row": 1, "label_col": "A", "first_period_col": "B", "last_period_col": "D", "granularity": "yearly", "rows": rows}
    db[readings.READINGS].docs.append({"key": "k", "file_map": {"map_version": 1, "kind": "sheet", "sheets": [smap], "figures": []}})
    grid = [[SMALL[r], 1, 2, 3] if r in SMALL else [] for r in range(1, 7)]
    db["datasets"].docs.append({"audit_id": "a1", "file_hash": "h", "recognition_sheets": [{"name": "PNL", "csv": True, "grid": grid, "indents": [], "merged": []}]})
    db[readings.OVERRIDES].docs.extend(overrides)
    return db


def effective_roles(db):
    reading = db[readings.READINGS].docs[0]
    overrides = asyncio.run(readings.overrides_for(db, "a1", "k"))
    fmap = asyncio.run(register.effective_map(db, "a1", {"file_hash": "h"}, reading["file_map"], overrides))
    return {r["row"]: (r["role"], r.get("classified_by")) for r in fmap["sheets"][0]["rows"]}


def test_the_register_applies_the_label_rule_to_a_stored_reading_that_has_none():
    got = effective_roles(stored_db())
    assert got[4] == ("sales_marketing", "label") and got[5] == ("ga", "label") and got[6] == ("other", None)


def test_an_analysts_change_wins_over_the_label_rule_at_register_time():
    change = {"id": "o1", "reading": "k", "audit_id": "a1", "item": "row:PNL:4", "path": "sheets.0.rows.2.role", "old": "other", "new": "rnd",
              "who": "analyst", "at": "2026-11-06T10:00:00", "why": "Change"}
    assert effective_roles(stored_db([change]))[4][0] == "rnd"


def test_a_file_without_stored_cells_is_read_as_stored():
    db = stored_db()
    db["datasets"].docs.clear()
    reading = db[readings.READINGS].docs[0]
    fmap = asyncio.run(register.effective_map(db, "a1", {"file_hash": "h"}, reading["file_map"], []))
    assert fmap == reading["file_map"]
