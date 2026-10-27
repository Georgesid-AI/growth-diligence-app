"""Answer form and rule changes of docs/design/page-image.md sections 4 and 5 (George, 2026-10-27). Synthetic pages only (rule 15).

1. Four nullable fields on a page claim: label_text, segment, share_of, is_quote. The claim's label is label_text when present; label_cell is location only.
2. Label corrections (L1 in page_check.check, C4 in corrections.plan) run only when label_text is empty; with it a mismatch is a flag.
3. Period fills (P2 in page_check.period_check, C1 and C3 in corrections.plan) fill a blank period only; a period the model set is kept.
4. The no-minus-sign rule (X2) sets "sign not on page" and no longer changes the value.
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")
pytest.importorskip("pptx")

import test_checker as tc  # noqa: E402
import test_claim_corrections as cc  # noqa: E402
import test_claims_list_changes as lc  # noqa: E402
import test_source_association as sa  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.llm import schemas  # noqa: E402
from app.structures import checker, pages as pipeline  # noqa: E402

FORM = ("label_text", "segment", "share_of", "is_quote")


def form(claim_, **more):
    """A claim of the test builders with the four fields of the new answer form (null unless given)."""
    return {**claim_, **{k: None for k in FORM}, **more}


def corrections_of(item, field):
    return [p for p in item["corrections"] if p["field"] == field]


# ---------------------------------------------------------------------------
# 1. The answer form
# ---------------------------------------------------------------------------
BASE = {"metric": "revenue", "value": 1.0, "value_high": None, "unit": "USD", "unit_other": None, "period": None, "basis": "actual",
        "scenario": "none", "value_cell": "p1r2c1", "label_cell": None, "period_cell": None}


def test_the_four_fields_are_nullable_short_text_and_a_boolean_and_the_schema_asks_for_them():
    assert {k: getattr(schemas.PageClaim.model_validate(BASE), k) for k in FORM} == dict.fromkeys(FORM)
    got = schemas.PageClaim.model_validate({**BASE, "label_text": " Paying  customers ", "segment": "EMEA", "share_of": "Total revenue", "is_quote": True})
    assert (got.label_text, got.segment, got.share_of, got.is_quote) == ("Paying customers", "EMEA", "Total revenue", True)
    assert schemas.PageClaim.model_validate({**BASE, "label_text": "  "}).label_text is None, "blank is not read"
    for field in ("label_text", "segment", "share_of"):
        with pytest.raises(ValidationError):
            schemas.PageClaim.model_validate({**BASE, field: "x" * (schemas.PAGE_TEXT_MAX + 1)})
        with pytest.raises(ValidationError):
            schemas.PageClaim.model_validate({**BASE, field: 5})
    with pytest.raises(ValidationError):
        schemas.PageClaim.model_validate({**BASE, "is_quote": "yes"})
    claim_schema = schemas.page_claims_output_schema()["properties"]["claims"]["items"]
    assert set(FORM) <= set(claim_schema["required"]) and set(claim_schema["properties"]) == set(schemas.PageClaim.model_fields)


def test_the_label_of_a_row_is_label_text_and_the_label_cell_only_locates_it():
    parsed = tc.deck([tc.TITLE, (50, 500, 12, "Paying customers"), (50, 480, 12, "800")])
    cell, near = cc.at(parsed, "800"), cc.at(parsed, "Paying customers")
    claim_ = form(tc.claim(cell, 800, metric="customers", unit="count", label_cell=near), label_text="Active subscribers")
    row, = cc.read(parsed, claim_)[0]
    assert row["label_from"] == "Active subscribers", "the label is the text the model read, not the text of the cell it cites"
    assert checker.LABEL_MISMATCH in row["flags"], "the cited cell says something else: flagged"
    agree = form(tc.claim(cell, 800, metric="customers", unit="count", label_cell=near), label_text="paying customers")
    row, = cc.read(parsed, agree)[0]
    assert row["label_from"] == "paying customers" and checker.LABEL_MISMATCH not in row["flags"]


def test_a_stored_item_keeps_no_label_text_segment_or_share_of():
    """Rule 17: the checked claim is stored with cell ids, never printed text; the row (the approval list) carries the label."""
    parsed = tc.deck([tc.TITLE, (50, 480, 12, "800")])
    item = tc.one(parsed, form(tc.claim(cc.at(parsed, "800"), 800, metric="customers", unit="count"),
                               label_text="Active subscribers", segment="EMEA", share_of="Total", is_quote=False))
    assert item["label_text"] == "Active subscribers" and item["is_quote"] is False
    kept = pipeline.stored_items([item])["claims"][0]
    assert {"label_text", "segment", "share_of"}.isdisjoint(kept) and kept["is_quote"] is False
    assert "Active subscribers" not in json.dumps(kept) and "EMEA" not in json.dumps(kept)


# ---------------------------------------------------------------------------
# 2. Label corrections (L1, C4) run only when label_text is empty
# ---------------------------------------------------------------------------
def test_a_chart_with_a_legend_and_label_text_set_is_not_corrected_and_the_cited_cell_stays():
    cells, rects = lc.chart_page()
    page = sa.grid(cells, rects)
    plain = sa.check(page, sa.claim("r3c1", 42, unit="EUR", label_cell="r9c1"))
    assert [p["field"] for p in plain["corrections"]] == ["segment"], "label_text empty: the legend items are offered as before"
    item = sa.check(page, form(sa.claim("r3c1", 42, unit="EUR", label_cell="r9c1"), label_text="Platform Subscriptions"))
    assert item["corrections"] == [], "label_text present: no correction"
    assert item["label_cell"] == "r9c1", "label_cell is location only: neither dropped nor swapped for a legend entry"
    assert checker.LABEL_MISMATCH in item["flags"], "the cited cell does not say what label_text says: a flag, never a change"
    row, _ = pipeline.corrected_row(item, page, {"file": "deck.pdf", "blocks": []}, 12, 1)
    assert "corrections" not in row and row["label_from"] == "Platform Subscriptions"


def test_a_legend_label_found_by_position_is_not_swapped_in_when_label_text_is_set():
    cells, rects = sa.legend_chart()
    page = sa.grid(cells, rects)
    assert sa.check(page, sa.claim("r2c1", 42, label_cell=None))["label_cell"] == "r4c1", "empty label_text: L1 finds the legend entry by colour"
    item = sa.check(page, form(sa.claim("r2c1", 42, label_cell=None), label_text="Enterprise"))
    assert item["label_cell"] is None and item["corrections"] == [] and checker.LABEL_MISMATCH not in item["flags"]


def test_a_far_label_with_only_the_title_as_fallback_and_label_text_set_is_not_corrected():
    parsed = tc.deck([tc.TITLE, (50, 480, 12, "800"), (400, 200, 12, "Footnote words")])
    cell, far = cc.at(parsed, "800"), cc.at(parsed, "Footnote words")
    bare = tc.one(parsed, form(tc.claim(cell, 800, metric="customers", unit="count", label_cell=far)))
    assert bare["label_cell"] is None and checker.LABEL_MISMATCH in bare["flags"], "empty label_text: as before"
    item = tc.one(parsed, form(tc.claim(cell, 800, metric="customers", unit="count", label_cell=far), label_text="Paying customers"))
    assert item["corrections"] == [] and item["label_cell"] == tc.cell_of(parsed, "Footnote words")
    assert checker.LABEL_MISMATCH in item["flags"]
    row, = cc.read(parsed, form(tc.claim(cell, 800, metric="customers", unit="count", label_cell=far), label_text="Paying customers"))[0]
    assert "corrections" not in row and row["label_from"] == "Paying customers"


def test_one_candidate_label_is_applied_only_without_label_text():
    parsed = tc.deck([(50, 560, 12, "Overview"), (50, 500, 12, "Paying customers"), (50, 480, 12, "800"), (400, 200, 12, "Footnote words")])
    cell, far = cc.at(parsed, "800"), cc.at(parsed, "Footnote words")
    item = tc.one(parsed, form(tc.claim(cell, 800, metric="customers", unit="count", label_cell=far)))
    assert corrections_of(item, "label"), "the existing C4 correction still runs when label_text is empty"
    item = tc.one(parsed, form(tc.claim(cell, 800, metric="customers", unit="count", label_cell=far), label_text="Paying customers"))
    assert item["corrections"] == [] and checker.LABEL_MISMATCH in item["flags"]


# ---------------------------------------------------------------------------
# 3. Period fills (P2, C1, C3) fill a blank period only
# ---------------------------------------------------------------------------
HEADED = [(50, 560, 20, "Plan 2025"), (50, 480, 12, "$150,000 annual revenue run rate")]


def test_a_model_period_and_a_conflicting_heading_keep_the_model_period_with_a_flag():
    parsed = tc.deck(HEADED)
    cell, title = cc.at(parsed, "$150,000 annual revenue run rate"), cc.at(parsed, "Plan 2025")
    item = tc.one(parsed, form(tc.claim(cell, 150_000, period="2027", period_cell=title)))
    assert item["period"] == "2027" and item["checks"]["period_corrected"] is False and "model_period" not in item
    assert checker.SOURCES_DISAGREE in item["flags"] and checker.PERIOD_FROM_HEADING not in item["flags"]
    assert not corrections_of(item, "period") or all(len(p["options"]) > 1 for p in corrections_of(item, "period")), "never an applied correction"
    row, = cc.read(parsed, form(tc.claim(cell, 150_000, period="2027", period_cell=title)))[0]
    assert row["target_date"] == "2027" and checker.SOURCES_DISAGREE in row["flags"], "the row keeps the model's period"
    assert all(e["state"] != "applied" for e in row.get("corrections", ())), "nothing was applied"


def test_a_model_period_on_no_cell_is_flagged_and_never_replaced_by_the_heading():
    parsed = tc.deck(HEADED)
    cell = cc.at(parsed, "$150,000 annual revenue run rate")
    item = tc.one(parsed, form(tc.claim(cell, 150_000, period="2027")))
    assert checker.PERIOD_NOT_ON_PAGE in item["flags"] and item["period"] == "2027" and corrections_of(item, "period") == []
    row, = cc.read(parsed, form(tc.claim(cell, 150_000, period="2027")))[0]
    assert row["target_date"] == "2027" and "corrections" not in row


def test_a_null_model_period_is_still_filled_from_the_heading_and_from_another_cell():
    parsed = tc.deck(HEADED)
    cell, title = cc.at(parsed, "$150,000 annual revenue run rate"), cc.at(parsed, "Plan 2025")
    item = tc.one(parsed, form(tc.claim(cell, 150_000, period=None, period_cell=title)))
    assert item["period"] == "2025" and checker.PERIOD_FROM_HEADING in item["flags"] and checker.SOURCES_DISAGREE not in item["flags"]
    other = tc.deck([tc.TITLE, (50, 480, 12, "$150,000 annual revenue run rate"), (400, 300, 12, "Plan year 2024")])
    row, = cc.read(other, form(tc.claim(cc.at(other, "$150,000 annual revenue run rate"), 150_000, period=None,
                                        period_cell=cc.at(other, "Plan year 2024"))))[0]
    assert row["target_date"] == "2024" and row["corrections"][0]["reason"] == checker.PERIOD_FROM_OTHER_CELL
    assert row["corrections"][0]["original"] is None and row["corrections"][0]["state"] == "applied"


def test_a_model_period_that_agrees_with_the_heading_is_unchanged():
    parsed = tc.deck(HEADED)
    cell, title = cc.at(parsed, "$150,000 annual revenue run rate"), cc.at(parsed, "Plan 2025")
    item = tc.one(parsed, form(tc.claim(cell, 150_000, period="2025", period_cell=title)))
    assert item["period"] == "2025" and checker.SOURCES_DISAGREE not in item["flags"] and checker.PERIOD_FROM_HEADING in item["flags"]


# ---------------------------------------------------------------------------
# 4. is_quote rides with the claim; the sign rule flags and changes nothing
# ---------------------------------------------------------------------------
def test_a_figure_inside_a_quoted_sentence_keeps_is_quote_true_and_is_checked_like_any_figure():
    parsed = tc.deck([tc.TITLE, (50, 480, 12, '"We reached $150,000 annual revenue run rate," says our founder')])
    cell = cc.at(parsed, '"We reached $150,000 annual revenue run rate," says our founder')
    item = tc.one(parsed, form(tc.claim(cell, 150_000), is_quote=True))
    assert item["is_quote"] is True and item["status"] == "matched" and item["corrections"] == []
    assert tc.one(parsed, form(tc.claim(cell, 150_000)))["is_quote"] is None, "null stays null: the model did not say"


def test_a_negative_value_with_no_minus_keeps_its_value_and_sets_the_flag():
    parsed = tc.deck([tc.TITLE, (50, 500, 12, "(71%) annually")])
    cell = cc.at(parsed, "(71%) annually")
    item = tc.one(parsed, form(tc.claim(cell, -71, metric="other", unit="%")))
    assert checker.SIGN_NOT_ON_PAGE in item["flags"] and item["status"] == "matched"
    assert item["value"] == -71 and item["values"][0]["value"] == -71, "the model's value is not retyped"
    unmatched = tc.deck([tc.TITLE, (50, 500, 12, "Revenue 1,200")])
    gone = tc.one(unmatched, form(tc.claim(cc.at(unmatched, "Revenue 1,200"), -1200)))
    assert checker.SIGN_NOT_ON_PAGE in gone["flags"] and gone["value"] == -1200
    row, = cc.read(parsed, form(tc.claim(cell, -71, metric="other", unit="%")))[0]
    assert row["value"] == -71 and checker.SIGN_NOT_ON_PAGE in row["flags"]
    assert checker.review_flags(row["flags"]), "listed under Review"
