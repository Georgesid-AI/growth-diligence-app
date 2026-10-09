"""Turnover and transaction volume (docs/specs/claim-matching.md section 11). Synthetic claims over the sample data."""
import pytest

from claim_matching_support import engine_results, fixture

from app import claim_matching as cm
from app.decks import claims as deck_claims

RUN = fixture()["runs"]["A"]
NO_FILE = {"target_date": "2021", "period_text": "FY2021"}      # before the first month of the file
FY23 = {"target_date": "2023", "period_text": "FY2023"}      # file revenue FY2023: 187,701.05


def row(snippet="Turnover", value=190000, results=None, extra_settings=None, inputs=None, run=RUN, **candidate):
    c = {"id": "x1", "status": "approved", "claim_type": "revenue", "value": value, "value_high": None, "unit": None,
         "currency": "EUR", "snippet": snippet, "label_from": None, "file": "deck.pptx", "order": 0,
         "sources": [{"file": "deck.pptx", "slide": 3}], **FY23, **candidate}
    if inputs:
        c["claim_inputs"] = {"x1": inputs}
    deck_claims.resolve_period(c, run["fiscal_year_end"])
    s = {"fiscal_year_end": 12, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}, **(extra_settings or {})}
    return cm.build_register([c], results or engine_results(tuple(run["files"]), run["as_of_month"]), s)[0]


ASKS = (None, "ask", "python", "Unverified", cm.ASK_REASON)


def _asks(r):
    return (r["metric"], r["turnover_state"], r["turnover_set_by"], r["evidence_label"], r["reason"])


@pytest.mark.parametrize("snippet, value, extra", [
    ("Turnover €190,000 in FY2023", 190_000, {}),                                      # within tolerance of the file (187,701)
    ("GMV €900,000 in FY2023", 900_000, {}), ("GMV €280,000 in FY2023", 280_000, {}),  # above tolerance: 4.8x, 1.5x
    ("Turnover €100,000 in FY2023", 100_000, {}),                                      # below tolerance
    ("GMV €900,000–1,000,000 FY2023", 900_000, {"value_high": 1_000_000}),             # a range above, inside, within, below
    ("GMV €150,000–250,000 FY2023", 150_000, {"value_high": 250_000}),
    ("GMV €100,000–190,000 FY2023", 100_000, {"value_high": 190_000}),
    ("GMV €50,000–100,000 FY2023", 50_000, {"value_high": 100_000}),
    ("SMB turnover €3,800 FY2023", 3_800, {}),                                         # within tolerance of the SMB segment
    ("SMB turnover €500,000 FY2023", 500_000, {}),
    ("GMV $210,000 FY2023", 210_000, {"currency": "USD", "extra_settings": {"fx": {"EUR": 1.0, "USD": 0.9}}}),
])
def test_no_turnover_claim_is_revenue_before_the_analyst_answers_whatever_the_revenue_file_says(snippet, value, extra):
    """Amended 2026-10-09 (George, decision 2): the register asks too. Before, a figure within tolerance of the file was
    Revenue and Verified, one below it Revenue and Contradicted; now every turnover claim is Unverified until the click."""
    r = row(snippet, value=value, **extra)
    assert _asks(r) == ASKS, snippet
    assert r["turnover_note"] == "Revenue or volume? Confirm below" and r["observed_value"] is None and r["gap"] is None
    assert r["turnover_suggested"] is None, "the file never pre-selects an answer"


def test_once_the_analyst_answers_revenue_the_claim_is_tested_as_revenue_against_the_file():
    answer = {"turnover_as": "revenue", "turnover_reason": "file_confirms"}
    within = row("Turnover €190,000 in FY2023", inputs=answer)
    assert (within["metric"], within["evidence_label"], within["turnover_note"], within["turnover_set_by"]) == \
        ("Revenue", "Verified", "Gross revenue (turnover)", "analyst")
    assert within["observed_source"]
    below = row("Turnover €100,000 in FY2023", value=100_000, inputs=answer)
    assert (below["metric"], below["evidence_label"]) == ("Revenue", "Contradicted")
    rng = row("GMV €100,000–190,000 FY2023", value=100_000, value_high=190_000, inputs=answer)     # tested at the nearest end
    assert rng["evidence_label"] == "Verified"
    segment = row("SMB turnover €3,800 FY2023", value=3_800, inputs=answer)
    assert (segment["segment"], segment["evidence_label"]) == ("SMB", "Verified")


def test_a_turnover_claim_in_another_currency_with_no_rate_says_fx_rate_needed():
    fx = {"EUR": 1.0}
    for text in ("GMV $900,000 FY2023", "GMV $190,000 FY2023"):
        r = row(text, value=900_000 if "900" in text else 190_000, currency="USD", extra_settings={"fx": fx, "deck_take_rate": True})
        assert (r["turnover_state"], r["evidence_label"], r["reason"]) == ("ask", "Unverified", "FX rate needed: USD→EUR"), text
        assert r["turnover_suggested"] is None, "a file covers the period: the take rate pre-selects nothing"
    # no file covers the period: the take-rate pre-selection still applies, the row still asks
    r = row("GMV $900,000", value=900_000, currency="USD", extra_settings={"fx": fx, "deck_take_rate": True}, **NO_FILE)
    assert (r["turnover_state"], r["turnover_suggested"], r["evidence_label"]) == ("ask", "volume", "Unverified")


@pytest.mark.parametrize("term", ["TPV", "GMV", "trading volume", "payment volume", "Transaction volume", "turnover"])
def test_every_term_is_ambiguous_and_never_defaults_to_revenue_without_a_file(term):
    r = row(f"{term} €5M", value=5_000_000, **NO_FILE)
    assert (r["metric"], r["evidence_label"], r["turnover_state"]) == (None, "Unverified", "ask")


def test_no_period_asks_even_with_a_file():
    r = row("Turnover €190,000", target_date=None, period_text=None)
    assert (r["metric"], r["turnover_state"], r["evidence_label"]) == (None, "ask", "Unverified")


def test_deck_take_rate_mention_pre_selects_volume_and_the_row_still_asks():
    """Amended 2026-10-09 (George, decision 2): before, the row read as Volume until answered; now Volume is only
    pre-selected and the row is Unverified until the analyst clicks."""
    r = row("GMV €5M", value=5_000_000, extra_settings={"deck_take_rate": True}, **NO_FILE)
    assert _asks(r) == ASKS and r["turnover_suggested"] == "volume" and r["deck_revenue_note"] is None
    assert row("GMV €5M", value=5_000_000, **NO_FILE)["turnover_suggested"] is None


def test_the_analyst_answer_wins_over_the_file_and_over_the_deck():
    r = row("Turnover €190,000", inputs={"turnover_as": "volume", "turnover_reason": "deck_says_processed_volume"})
    assert (r["metric"], r["turnover_set_by"], r["turnover_reason"], r["evidence_label"]) == \
        ("Transaction volume", "analyst", "deck_says_processed_volume", "Unsupported")
    r = row("GMV €900,000", value=900000, inputs={"turnover_as": "revenue", "turnover_reason": "deck_says_gross_revenue"})
    assert (r["metric"], r["evidence_label"], r["turnover_set_by"]) == ("Revenue", "Contradicted", "analyst")
    r = row("GMV €900,000–1,000,000", value=900000, value_high=1_000_000, inputs={"turnover_as": "revenue", "turnover_reason": "file_confirms"})
    assert (r["metric"], r["evidence_label"]) == ("Revenue", "Contradicted")


def test_an_audit_answer_is_reused_for_the_same_term_and_period_only():
    key = cm.turnover_key({"snippet": "GMV", "period_start": "2023-01-01", "period_end": "2023-12-31"})
    saved = {key: {"as": "volume", "reason": "other"}}
    r = row("GMV €900,000", value=900000, extra_settings={"turnover_choices": saved})
    assert (r["metric"], r["turnover_set_by"], r["turnover_reason"]) == ("Transaction volume", "analyst", "other")
    other = row("GMV €900,000", value=900000, target_date="2022", period_text="FY2022", extra_settings={"turnover_choices": saved})
    assert other["turnover_set_by"] == "python"


def test_volume_is_never_matched_to_engine_revenue_even_when_the_figures_agree():
    r = row("Turnover", value=187701, inputs={"turnover_as": "volume", "turnover_reason": "other"})
    assert r["observed_value"] is None and r["evidence_label"] == "Unsupported" and r["gap"] is None


def test_implied_take_rate_is_revenue_over_volume_cited_to_both_sources_and_never_verified():
    r = row("GMV", value=1_877_010.5, inputs={"turnover_as": "volume", "turnover_reason": "other"})
    assert r["implied_take_rate"] == pytest.approx(0.1, abs=1e-6)
    assert "revenue:" in r["implied_take_rate_source"] and "volume: deck.pptx" in r["implied_take_rate_source"]
    assert r["evidence_label"] != "Verified"
    assert row("GMV", value=1e6, inputs={"turnover_as": "volume"}, **NO_FILE)["implied_take_rate"] is None


def test_plain_revenue_arr_and_mrr_claims_are_not_turnover_claims():
    for text in ("Revenue €190,000", "ARR €190,000", "MRR €15,000"):
        r = row(text)
        assert r["turnover_state"] is None and r["turnover_note"] is None


def test_only_take_rate_counts_as_the_volume_default():
    assert cm.mentions_take_rate({"blocks": [{"text": "Our Take Rate is 2%"}]})
    assert cm.mentions_take_rate([{"cells": ["take-rates", "1%"]}])
    for text in ("Commission", "spread", "fees", "subscription fees", "sales commission", "feeds the pipeline", "revenue"):
        assert not cm.mentions_take_rate([text]), text


def test_a_saas_deck_with_fees_or_commission_does_not_turn_turnover_into_volume():
    """Reproduced: 'Turnover €5M FY2027' read Unsupported (Volume) on any deck that said fees, commission or spread."""
    r = row("Turnover €5M FY2027", value=5_000_000, target_date="2027", period_text="FY2027",
            extra_settings={"deck_take_rate": cm.mentions_take_rate(["subscription fees", "sales commission", "spread"])})
    assert (r["turnover_state"], r["evidence_label"]) == ("ask", "Unverified")


@pytest.mark.parametrize("text", ["GMV €5M", "TPV $2bn", "Payment volume €1M", "Trading volume €1M", "Transaction volume €1M", "Turnover €1M"])
def test_the_deck_parser_reads_every_turnover_term_as_a_revenue_family_claim(text):
    families = {family for family, rx in deck_claims._KEYWORDS if rx.search(text)}
    assert "revenue" in families


# --- the deck's own revenue figure for the same period (claim-matching.md section 11, deck hint) ---------------------

def _pair(turnover=550508, revenue=150000, revenue_currency="EUR", revenue_label="Revenue", **settings):
    def claim(id, snippet, value, currency, page):
        c = {"id": id, "status": "approved", "claim_type": "revenue", "value": value, "value_high": None, "unit": None,
             "currency": currency, "snippet": snippet, "label_from": None, "file": "deck.pdf", "order": 0,
             "target_date": "2027", "period_text": "FY2027", "sources": [{"file": "deck.pdf", "page": page}]}
        deck_claims.resolve_period(c, 12)
        return c
    claims = [claim("t", "Turnover", turnover, "EUR", 17), claim("r", revenue_label, revenue, revenue_currency, 19)]
    s = {"fiscal_year_end": 12, "as_of_month": None, "reporting_currency": "EUR", "fx": {"EUR": 1.0}, **settings}
    rows = cm.build_register(claims, engine_results(tuple(RUN["files"]), RUN["as_of_month"]), s)
    return {r["claim_id"]: r for r in rows}


def test_revenue_below_turnover_in_the_deck_preselects_volume_and_still_asks():
    t = _pair()["t"]
    assert t["turnover_suggested"] == "volume"
    assert t["deck_revenue_note"] == "Deck revenue for the same period: 150,000 EUR (page 19); implied take rate 27%, derived, not verified"
    assert (t["turnover_state"], t["turnover_note"], t["evidence_label"]) == ("ask", "Revenue or volume? Confirm below", "Unverified")
    assert t["metric"] is None and t["implied_take_rate"] is None


@pytest.mark.parametrize("kwargs", [
    {"revenue": 540000},                       # within tolerance of the turnover figure
    {"revenue": 600000},                       # above it
    {"revenue_currency": "USD"},               # another currency is never compared
    {"revenue_label": "Turnover"},             # turnover is not revenue
])
def test_no_deck_hint_without_a_single_lower_revenue_figure_in_the_same_currency(kwargs):
    t = _pair(**kwargs)["t"]
    assert (t["turnover_suggested"], t["deck_revenue_note"]) == (None, None)


def test_the_revenue_row_never_gets_the_suggestion():
    rows = _pair()
    assert rows["r"]["turnover_suggested"] is None and rows["r"]["deck_revenue_note"] is None
