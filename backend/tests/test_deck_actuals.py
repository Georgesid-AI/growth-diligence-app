"""Deck figures: actuals, plan and segments (docs/design/deck-actuals.md, sections 1 to 6; the test case of section 7).

Synthetic company and figures (rule 15). Every test here was seen failing on a deliberate violation before the code was written or while it
was broken on purpose (the session log names the violations)."""
import copy

import pytest

from deck_actuals_support import AS_OF, DECK, FY, page3, reading, register, results, settings

from app import claim_groups as cg
from app import claim_matching as cm
from app import deck_actuals as da
from app import verdict as vd
from app.decks import claims as deck_claims


def cards(rows, candidates):
    """Everything that would ask the analyst: a row whose reason asks, a required field still unknown, a review flag, a Definition check,
    a conflict or a review of the groups."""
    related = cg.relate(rows)
    asking = [r["claim_id"] for r in rows if cm.asks_analyst(r) or r["required_unknown"] or r.get("definition_check") == cm.DEFINITION_ASK]
    flagged = [c["id"] for c in candidates if cm.review_flags_of(c, AS_OF)]
    return {"rows": asking, "flags": flagged, "conflicts": related["conflicts"], "reviews": related["reviews"]}


def row_of(rows, value, **match):
    found = [r for r in rows if r["claimed_value"] == value and all(r[k] == v for k, v in match.items())]
    assert len(found) == 1, (value, [(r["claim_id"], r["claimed_value"], r["period"]) for r in rows])
    return found[0]


# --- 7. the test case: page 3 ------------------------------------------------------------------------------------------------------

def test_page_3_reads_eight_figures_with_no_card_and_the_verdicts_of_the_addendum():
    stored = page3()
    assert len([c for c in stored if c["sources"][0]["page"] == 3]) == 8, "eight figures on the page"
    folded = deck_claims.fold_twins(copy.deepcopy(stored))
    rows = cm.build_register(folded, results(), settings())
    assert len(rows) == 7, "501,378 and 501,378 are one figure, and page 12 states the table again"
    assert cards(rows, folded) == {"rows": [], "flags": [], "conflicts": [], "reviews": []}, "zero cards, nothing to set, nothing for Needs your attention"

    # the three years: deck actuals, reconciled with the P&L revenue row, Verified
    for year, value in FY.items():
        r = row_of(rows, value)
        assert (r["metric"], r["period"], r["period_sort"], r["evidence_label"], r["deck_status"]) == ("Revenue", f"FY{year}", "actual", "Verified", "consistent")
        assert r["observed_value"] == value and r["deck_only"] is False
    fy21 = row_of(rows, FY[2021])
    assert fy21["page_ref"] == "p3, p12" and fy21["source"] == "File P&L!E3"
    assert [c["label_from"] for c in folded if c["value"] == FY[2021]] == ["Recognised Revenue"], "the metric name, not the heading"

    # the two parts of the bar: segments of the FY 2021 total, no card
    new, committed = row_of(rows, 482_475), row_of(rows, 18_903)
    for r, name in ((new, "New business"), (committed, "Committed from 2020")):
        assert (r["segment"], r["metric"], r["period"], r["group_role"]) == (name, "Revenue", "FY2021", "segment_part")
        assert r["deck_only"] is True and r["evidence_label"] == "Unverified" and r["source"] == "Deck p3"
        assert r["value_at_stake_arr"] is None
    assert new["group_id"] == fy21["group_id"] == committed["group_id"] and fy21["group_role"] == "total"

    # the multiples: growth recomputed from the P&L, Verified within tolerance
    for value, observed in ((0.9, 0.89), (3.3, 3.32)):
        r = row_of(rows, value)
        assert (r["metric"], r["period_sort"], r["evidence_label"], r["deck_status"]) == ("Revenue growth multiple", "actual", "Verified", "consistent")
        assert round(r["observed_value"], 2) == observed


# --- 1. the period sort ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("period, expected", [("FY2021", "actual"), ("FY2019", "actual"), ("2021-12", "actual"), ("FY2022", "plan"),
                                              ("2022-01", "plan"), (None, "unset")])
def test_a_figure_is_sorted_by_its_own_period_against_the_as_of_month(period, expected):
    c = reading("c1", 100.0, "Revenue", period)
    assert da.period_sort(c, AS_OF) == expected
    assert register([c])[0]["period_sort"] == expected


def test_the_deck_date_is_never_used_to_sort_a_figure():
    old, new = reading("c1", 100.0, "Revenue", "FY2021"), reading("c1", 100.0, "Revenue", "FY2021")
    old["deck_date"], new["deck_date"] = "2018-03-01", "2026-10-28"
    old["sources"][0]["date"], new["sources"][0]["date"] = "2018-03-01", "2026-10-28"
    assert da.period_sort(old, AS_OF) == da.period_sort(new, AS_OF) == "actual"
    assert da.period_sort(reading("c1", 100.0, "Revenue", "FY2022", deck_date="2018-03-01"), AS_OF) == "plan"


def test_a_plan_figure_is_a_claim_that_is_never_verified_or_contradicted():
    row = register([reading("c1", 900_000.0, "Revenue", "FY2022", basis="projection")])[0]
    assert (row["period_sort"], row["deck_status"]) == ("plan", None)
    assert row["evidence_label"] not in ("Verified", "Contradicted")


def test_a_figure_with_no_readable_period_asks_for_it_once():
    row = register([reading("c1", 100.0, "Revenue", None)])[0]
    assert row["period_sort"] == "unset" and cm.asks_analyst(row) and row["reason"].startswith(cm.PERIOD_NOT_READ)


# --- 2. what happens to a deck actual ----------------------------------------------------------------------------------------------

def test_a_deck_actual_beyond_tolerance_differs_from_the_file_and_is_listed_under_worth_flagging():
    r = register([reading("c1", 600_000.0, "Recognised Revenue", "FY2021")])[0]
    assert (r["deck_status"], r["evidence_label"]) == ("differs", "Contradicted"), "the data shows the deck figure false"
    assert r["reason"].startswith(da.DIFFERS) and "501,378" in r["reason"]
    assert vd.flagged_rows([r]) == [r] and da.DIFFERS in vd.flag_text(r)


@pytest.mark.parametrize("mark", [{"basis": "projection"}, {"basis": "scenario"}, {"basis": "actual"}])
@pytest.mark.parametrize("value", [400_000.0, 600_000.0])
def test_a_past_period_figure_marked_projection_is_still_a_deck_actual_and_the_mark_is_a_note(value, mark):
    """Review of PR 201, finding (a): the figure's own period decides, never the reader's mark."""
    r = register([reading("c1", value, "Recognised Revenue", "FY2021", **mark)])[0]
    assert (r["period_sort"], r["deck_status"], r["evidence_label"]) == ("actual", "differs", "Contradicted")
    assert r["reason"].startswith(da.DIFFERS) and vd.flagged_rows([r]) == [r]
    assert ("marks this figure as a" in r["details"].get("note", "")) == (mark["basis"] != "actual")


def test_an_unmarked_deck_actual_has_no_mark_note():
    assert "note" not in register([reading("c1", 600_000.0, "Recognised Revenue", "FY2021")])[0]["details"]


@pytest.mark.parametrize("value", [1_002_756.08, 250_000.0, 15_000_000.0])
def test_a_deck_actual_far_from_the_file_is_contradicted_with_no_card_before_the_definition_check(value):
    """Finding (b): the reconcile-with-file check runs before the Definition check, so a figure at 2x the file (or beyond 50% off) needs no answer."""
    r = register([reading("c1", value, "Recognised Revenue", "FY2021")])[0]
    assert (r["deck_status"], r["evidence_label"]) == ("differs", "Contradicted") and r["reason"].startswith(da.DIFFERS)
    assert r.get("definition_check") in (None, "") or r["definition_check"] != cm.DEFINITION_ASK
    assert not cm.asks_analyst(r) and vd.flagged_rows([r]) == [r]
    checked = r["details"]["checked"][0]
    assert "differs from File P&L!E3 by" in checked and "matches" not in checked
    assert "100%" in register([reading("c1", 1_002_756.08, "Recognised Revenue", "FY2021")])[0]["details"]["checked"][0]


def test_a_deck_actual_within_tolerance_is_verified_and_not_flagged():
    r = register([reading("c1", 510_000.0, "Recognised Revenue", "FY2021")])[0]      # +1.7%: inside ±5%
    assert (r["deck_status"], r["evidence_label"]) == ("consistent", "Verified") and vd.flagged_rows([r]) == []


def test_a_deck_actual_the_files_hold_nothing_for_is_used_unverified_and_tagged_deck_only():
    r = register([reading("c1", 90_000.0, "Recognised Revenue", "FY2018")], res=results({2019: 1.0, 2020: 2.0, 2021: 3.0}))[0]
    assert (r["deck_status"], r["deck_only"], r["evidence_label"], r["source"]) == ("deck only", True, "Unverified", "Deck p3")
    assert r["period_sort"] == "actual" and "nothing in the files for this period" in r["reason"]


def test_an_analyst_figure_and_a_plan_are_not_deck_actuals():
    mine = register([reading("c1", 600_000.0, "Recognised Revenue", "FY2021", origin="analyst")])[0]
    assert mine["deck_status"] is None and mine["evidence_label"] == "Contradicted", "the analyst's own claim keeps its test"


# --- 3. the details block ----------------------------------------------------------------------------------------------------------

def test_the_details_block_of_a_file_based_metric_has_the_four_parts_with_cell_references():
    r = register([reading("c1", 501_378.04, "Recognised Revenue", "FY2021")])[0]
    d = r["details"]
    assert list(d) == ["inputs", "formula", "checked", "not_checked"]
    assert d["inputs"] == [{"label": "Recognised Revenue", "value": 501_378.04, "page": "p3"}]
    assert "501,378" in d["formula"] and "FY2021" in d["formula"]
    assert d["checked"] == ["Revenue, FY2021 matches File P&L!E3 (501,378)"] and d["not_checked"] == []


def test_the_details_block_of_a_deck_only_metric_names_what_no_file_confirmed():
    r = register([reading("c1", 90_000.0, "Recognised Revenue", "FY2018")], res=results({2019: 1.0, 2020: 2.0, 2021: 3.0}))[0]
    d = r["details"]
    assert d["checked"] == ["nothing in the files for this period"] and d["not_checked"] == ["Recognised Revenue, FY2018 (p3)"]
    assert da.TAG == "deck only"


def test_the_growth_multiple_details_show_the_formula_with_the_numbers_filled_in():
    d = row_of(register(page3()), 3.3)["details"]
    assert d["formula"] == "FY2021 revenue ÷ FY2020 revenue = 501,378 ÷ 151,057 = 3.3x"
    assert d["checked"] == ["Revenue growth multiple, FY2021 matches File P&L!D3, File P&L!E3 (3.3x)"]


def test_the_memo_prints_the_details_blocks_in_appendix_c():
    rows = register(page3())
    lines = da.appendix_lines(rows)
    text = "\n".join(lines)
    assert "Metric details" in lines[0] and "Inputs" in text and "Formula" in text and "Checked against files" in text and "Not checked" in text
    assert "File P&L!E3" in text and "Deck p3" in text


# --- 4. segments on a page ---------------------------------------------------------------------------------------------------------

def test_figures_of_a_page_that_sum_to_a_third_are_its_segments_and_take_its_period_and_metric():
    stored = [reading("c1", 1_000.0, "Total", "FY2021", currency="EUR"), reading("c2", 700.0, "Alpha", None), reading("c3", 300.0, "Beta", "FY2020")]
    found = da.page_splits(copy.deepcopy(stored))
    parts = {c["id"]: c for c in found if c["id"] != "c1"}
    assert all(c["split_of"] == "c1" and c["target_date"] == "FY2021" and c["claim_type"] == "revenue" for c in parts.values())
    assert [c["split_segment"] for c in parts.values()] == ["Alpha", "Beta"]


def test_a_sum_outside_the_tolerance_makes_no_split():
    stored = [reading("c1", 1_000.0, "Total", "FY2021"), reading("c2", 700.0, "Alpha", "FY2021"), reading("c3", 200.0, "Beta", "FY2021")]
    assert not any(c.get("split_of") for c in da.page_splits(copy.deepcopy(stored)))


def test_a_split_is_searched_on_one_page_only():
    stored = [reading("c1", 1_000.0, "Total", "FY2021"), reading("c2", 700.0, "Alpha", "FY2021"), reading("c3", 300.0, "Beta", "FY2021", page=4)]
    assert not any(c.get("split_of") for c in da.page_splits(copy.deepcopy(stored)))


def test_the_memo_builds_with_the_details_block_in_appendix_c_and_the_data_request_in_appendix_b():
    from app import ic_memo as im
    from test_ic_memo import inputs
    kw = inputs()
    row = kw["rows"][0]
    row.update(deck_status=da.TAG, deck_only=True, source="Deck p12", data_request="revenue by customer and month behind page 12",
               details={"inputs": [{"label": "Recognised Revenue", "value": 123456.0, "page": "p12"}], "formula": "Revenue, FY2020 = 123,456 as printed on page 12",
                        "checked": [da.NOT_CHECKED_NOTHING], "not_checked": ["Recognised Revenue, FY2020 (p12)"]})
    text = im.build_memo(**kw)
    appendix_c = text.split("## " + im.APPENDICES[2])[1].split("## " + im.APPENDICES[3])[0]
    assert "Metric details" in appendix_c and "Source: Deck p12" in appendix_c and "Not checked: Recognised Revenue, FY2020 (p12)" in appendix_c
    assert "Inputs: Recognised Revenue 123,456 (p12)" in appendix_c, "numbers are stored in the row, so the memo's number check accepts them"
    appendix_b = text.split("## " + im.APPENDICES[1])[1].split("## " + im.APPENDICES[2])[0]
    assert "- Revenue by customer and month behind page 12" in appendix_b
    assert any(line.startswith("Revenue growth multiple") or line.startswith("ARR") or "Source: File" in line or "computed from" in appendix_c for line in appendix_c.split("\n"))


def test_a_data_request_names_the_table_only_for_a_deck_only_metric_a_deck_can_carry():
    asked = register([reading("c1", 90_000.0, "Recognised Revenue", "FY2018", page=12, sources=[{"file": DECK, "page": 12, "kind": "page"}])],
                     res=results({2019: 1.0, 2020: 2.0, 2021: 3.0}))[0]
    assert asked["data_request"] == "revenue by customer and month behind page 12"
    assert da.data_request({"metric": "Win rate", "page_ref": "p12", "deck_status": da.TAG}) is None, "win rate needs a CRM, not a deck table"
    assert da.data_request({"metric": "Revenue", "page_ref": "p12", "deck_status": "consistent"}) is None, "a figure the files confirm asks for nothing"


def test_the_fold_keeps_the_specific_label_the_precise_value_and_every_page_and_never_folds_other_figures():
    stored = [reading("c1", 501_378, "2021 REVENUE", "FY2021"), reading("c2", 501_378.04, "Recognised Revenue", "FY2021", page=12, structure_key="page-12")]
    one, = deck_claims.fold_twins(copy.deepcopy(stored))
    assert (one["label_from"], one["value"], [s["page"] for s in one["sources"]]) == ("Recognised Revenue", 501_378.04, [3, 12])
    other_period = [stored[0], reading("c2", 501_378.04, "Recognised Revenue", "FY2020", page=12, structure_key="page-12")]
    assert len(deck_claims.fold_twins(copy.deepcopy(other_period))) == 2, "another period is another figure"
    far = [stored[0], reading("c2", 600_000.0, "Recognised Revenue", "FY2021", page=12, structure_key="page-12")]
    assert len(deck_claims.fold_twins(copy.deepcopy(far))) == 2, "values outside the tolerance stay two readings"
    rate = [reading("c1", 12.0, "Churn", "FY2021", unit="%"), reading("c2", 12.0, "Churn", "FY2021", unit="%", page=12, structure_key="page-12")]
    assert len(deck_claims.fold_twins(copy.deepcopy(rate))) == 2, "only money amounts fold"


def test_figures_with_their_own_different_periods_never_form_a_split_whatever_the_arithmetic():
    """Finding (d) a: a revenue table 2019/2020/2021 of 1M, 2M, 3M is three totals; each is Verified against its own year, with no card."""
    revenue = {2019: 1_000_000.0, 2020: 2_000_000.0, 2021: 3_000_000.0}
    stored = [reading(f"c{k}", v, "Revenue", f"FY{y}", cell=f"p3t1r1c{k + 1}") for k, (y, v) in enumerate(revenue.items(), 1)]
    assert not any(c.get("split_of") for c in da.page_splits(copy.deepcopy(stored)))
    folded = deck_claims.fold_twins(copy.deepcopy(stored))
    rows = cm.build_register(folded, results(revenue), settings())
    assert [(r["period"], r["evidence_label"], r["deck_status"], r["group_role"]) for r in rows] == \
        [(f"FY{y}", "Verified", "consistent", r["group_role"]) for y, r in zip(revenue, rows)]
    assert all(r["segment"] == "Company" or r["segment"] in (None, "Whole company") or r["group_role"] != "segment_part" for r in rows)
    assert cards(rows, folded) == {"rows": [], "flags": [], "conflicts": [], "reviews": []}


def test_a_part_with_no_label_of_its_own_is_an_unlabelled_segment_under_the_total_with_no_card():
    """Finding (d) b: page 3 with "New business" unlabelled gives the seven rows of the fixture, the part named "Unlabelled part"."""
    stored = page3()
    stored[1] = {**stored[1], "label_from": None, "flags": ["no label read"]}
    folded = deck_claims.fold_twins(copy.deepcopy(stored))
    rows = cm.build_register(folded, results(), settings())
    assert len(rows) == 7
    part = row_of(rows, 482_475)
    assert (part["segment"], part["group_role"], part["period"], part["deck_only"]) == (da.UNLABELLED, "segment_part", "FY2021", True)
    assert da.UNLABELLED == "Unlabelled part"
    assert cards(rows, folded) == {"rows": [], "flags": [], "conflicts": [], "reviews": []}
    assert row_of(rows, FY[2021])["evidence_label"] == "Verified", "the total is still the only FY2021 company revenue"


def test_a_part_with_the_label_of_the_total_is_an_unlabelled_segment_too():
    stored = [reading("c1", 1_000.0, "Revenue", "FY2021"), reading("c2", 700.0, "Revenue", "FY2021"), reading("c3", 300.0, "Beta", "FY2021")]
    parts = {c["id"]: c["split_segment"] for c in da.page_splits(copy.deepcopy(stored)) if c.get("split_of")}
    assert parts == {"c2": da.UNLABELLED, "c3": "Beta"}


# --- 4. segment names from the nearest label ------------------------------------------------------------------------------------------

def test_a_segment_is_named_by_the_legend_item_of_its_bar_or_the_rotated_chart_label_not_by_the_page_heading():
    from test_source_association import bar_chart, cell, grid, legend_chart

    from app.structures import association
    cells, rects = legend_chart()
    layout = association.Layout(grid(cells, rects))
    assert layout.nearest_label(cells[1]) == "Enterprise" and layout.nearest_label(cells[2]) == "SMB"
    assert layout.is_heading("revenue  by segment") and not layout.is_heading("Enterprise")
    cells, rects = bar_chart()
    assert association.Layout(grid(cells, rects)).nearest_label(cells[1]) == "Revenue (EUR M)", "rotated chart label"
    cells.append(cell(4, "Customers", (0.52, 0.30, 0.56, 0.80), 4, rot=90))
    assert association.Layout(grid(cells, rects)).nearest_label(cells[1]) is None, "two different rotated labels: none is chosen"


def test_the_row_of_a_page_claim_whose_label_is_the_page_heading_takes_the_legend_item_instead():
    from test_source_association import grid, legend_chart

    from app.structures import pages as pipeline
    cells, rects = legend_chart()
    item = {"metric": "revenue", "value": 42.0, "value_high": None, "unit": "EUR", "unit_other": None, "period": "2021", "basis": "actual",
            "scenario": "none", "value_cell": "r2c1", "label_cell": None, "label_text": "Revenue by segment", "values": [42.0], "status": "matched",
            "checks": {}, "flags": [], "period_cells": []}
    row = pipeline.row_from_claim(item, grid(cells, rects), {"file": "d.pdf", "blocks": []}, 12)
    assert row["label_from"] == "Enterprise"
    item["label_text"] = "Core platform"
    assert pipeline.row_from_claim(item, grid(cells, rects), {"file": "d.pdf", "blocks": []}, 12)["label_from"] == "Core platform", "a real label stands"


@pytest.mark.parametrize("first, second, kept", [
    ("FINANCIAL HIGHLIGHTS", "Recognised Revenue", "Recognised Revenue"),
    ("Recognised Revenue", "FINANCIAL HIGHLIGHTS", "Recognised Revenue"),
    ("2021 REVENUE", "Recognised Revenue", "Recognised Revenue"),
    ("REVENUE OVERVIEW", "Revenue", "Revenue"),
    ("Revenue", "REVENUE OVERVIEW", "Revenue"),
    ("Key figures", "ARR", "ARR"),
    ("Revenue", "Recognised Revenue", "Recognised Revenue"),
    ("FINANCIAL HIGHLIGHTS 2021", "KEY FIGURES", "KEY FIGURES"),
    ("KEY FIGURES", "FINANCIAL HIGHLIGHTS", "FINANCIAL HIGHLIGHTS"),
])
def test_the_fold_label_prefers_a_metric_name_to_a_heading_then_the_longer_metric_then_the_heading_without_digits(first, second, kept):
    """Finding (e)."""
    assert deck_claims.specific_label(first, second) == kept


def test_the_fold_keeps_the_metric_name_over_a_heading_without_digits():
    stored = [reading("c1", 501_378, "FINANCIAL HIGHLIGHTS", "FY2021"), reading("c2", 501_378.04, "Recognised Revenue", "FY2021", page=12, structure_key="page-12")]
    one, = deck_claims.fold_twins(copy.deepcopy(stored))
    assert one["label_from"] == "Recognised Revenue"
