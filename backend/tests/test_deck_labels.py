"""Items 4, 5 and 7 of the task of 2026-10-09: the explanation of a deck inconsistency, currency and period read from a
label's brackets before scoring, and the "count" unit. Synthetic decks only (rule 15)."""
import pytest

from app.decks import claims


def _found(*blocks):
    return claims.detect_candidates([{"slide": s, "kind": "text", "text": t, "box": b} for b, (s, t) in enumerate(blocks, 1)], "d.pptx")


# --- item 5 ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("label, expected", [
    ("Turnover (£/year)", ("GBP", "per year")), ("Turnover (€ per month)", ("EUR", "per month")), ("ARR ($, annual)", ("USD", "per year")),
    ("Revenue [GBP / quarter]", ("GBP", "per quarter")), ("Revenue (£)", ("GBP", None)), ("Revenue (per year)", (None, "per year")),
    ("Revenue (€m)", (None, None)), ("Revenue ($k / year)", (None, None)), ("Revenue (FY23)", (None, None)), ("Revenue", (None, None)),
])
def test_a_bracket_gives_currency_and_period_and_a_scale_is_never_read_as_a_currency(label, expected):
    assert claims.bracket_units(label) == expected


def test_a_figure_under_a_label_with_a_currency_and_period_in_brackets_is_scored_with_both_parsed():
    found = _found((1, "Turnover (£/year)\n150,000"))
    c, = [c for c in found if c["value"] == 150000]
    assert (c["currency"], c["period_basis"], c["target_date"]) == ("GBP", "per year", None), "the date stays missing: no year is given"
    got = claims.confidence(c, [c])
    assert got["failed"] == ["no date", "not corroborated"], "no unit is not listed: the bracket gave it"
    assert got["text"] == "Low – no date, not corroborated"


def test_the_reason_lists_only_what_is_still_missing_after_parsing():
    c = {"claim_type": "revenue", "value": 100, "value_high": None, "unit": None, "currency": None, "target_date": "2025",
         "type_from": "heading", "label_from": "Turnover (£/year)", "sources": [{"slide": 2}, {"slide": 5}]}
    assert claims.confidence(c, [])["failed"] == [], "stored before the label was read: the bracket still counts"
    bare = {**c, "label_from": "Turnover", "target_date": None}
    assert claims.confidence(bare, [])["failed"] == ["no date", "no unit"]
    both = {**c, "target_date": None}
    assert claims.confidence(both, [])["failed"] == ["no date"]


def test_a_figure_with_its_own_currency_keeps_it():
    found = _found((1, "Turnover (£/year)\n€150,000"))
    c, = [c for c in found if c["value"] == 150000]
    assert c["currency"] == "EUR"


# --- item 4 ------------------------------------------------------------------------------------------------------------
def test_each_flagged_claim_carries_the_two_figures_and_where_each_is_stated():
    found = _found((1, "5 customers in 2024"), (4, "6 customers in 2024"))
    five, = [c for c in found if c["value"] == 5]
    assert five["inconsistent_dates"] == ["2024"]
    pair, = five["inconsistencies"]
    assert (pair["this"]["value"], pair["other"]["value"]) == (5, 6)
    assert (pair["this"]["source"]["slide"], pair["other"]["source"]["slide"]) == (1, 4)
    assert pair["this"]["date"] == pair["other"]["date"] == "2024"


def test_a_claim_that_is_not_flagged_has_no_explanation_and_no_tag():
    one, = _found((1, "5 customers in 2024"))
    assert one["inconsistent_dates"] == [] and one["inconsistencies"] == []


def test_every_flagged_claim_has_an_explanation():
    for c in _found((1, "5 customers in 2024"), (4, "6 customers in 2024"), (6, "7 customers in 2024")):
        assert bool(c["inconsistent_dates"]) == bool(c["inconsistencies"])


# --- item 7 ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("snippet, claim_type", [("40 customers", "customers"), ("120 headcount", "people"), ("30 deals", "sales")])
def test_a_claim_in_the_count_unit_is_a_count_and_never_a_currency(snippet, claim_type):
    from app import claim_matching as cm
    assert cm._claim_unit({"unit": "count", "currency": None}) == "count"
    assert cm._claim_unit({"unit": "count", "currency": "EUR"}) == "currency", "currency stays its own field"
    assert cm.fits_metric("Customer count", "count", None)
    assert not cm.fits_metric("ARR", "count", None)
