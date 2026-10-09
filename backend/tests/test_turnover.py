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


def test_turnover_within_tolerance_of_the_file_revenue_is_gross_revenue_matched_as_before():
    r = row("Turnover €190,000 in FY2023")
    assert (r["metric"], r["evidence_label"], r["turnover_state"], r["turnover_note"]) == \
        ("Revenue", "Verified", "revenue", "Gross revenue (turnover)")
    assert r["turnover_set_by"] == "python" and r["observed_source"]


def test_turnover_above_three_times_the_file_revenue_asks_instead_of_contradicting():
    r = row("GMV €900,000 in FY2023", value=900000)
    assert (r["metric"], r["evidence_label"], r["turnover_state"]) == (None, "Unverified", "ask")
    assert r["turnover_note"] == "Looks like transaction volume, not revenue" and "confirm Revenue or Volume" in r["reason"]


def test_turnover_between_tolerance_and_three_times_is_an_ordinary_revenue_claim_with_the_control():
    r = row("Turnover €280,000 in FY2023", value=280000)       # 1.5x
    assert (r["metric"], r["evidence_label"], r["turnover_state"]) == ("Revenue", "Contradicted", "revenue")


def test_exactly_three_times_is_not_flagged():
    r = row("Turnover", value=3 * 187701.05)
    assert r["turnover_state"] == "revenue"


@pytest.mark.parametrize("term", ["TPV", "GMV", "trading volume", "payment volume", "Transaction volume", "turnover"])
def test_every_term_is_ambiguous_and_never_defaults_to_revenue_without_a_file(term):
    r = row(f"{term} €5M", value=5_000_000, **NO_FILE)
    assert (r["metric"], r["evidence_label"], r["turnover_state"]) == (None, "Unverified", "ask")


def test_no_period_asks_even_with_a_file():
    r = row("Turnover €190,000", target_date=None, period_text=None)
    assert (r["metric"], r["turnover_state"], r["evidence_label"]) == (None, "ask", "Unverified")


def test_deck_take_rate_mention_reads_the_row_as_volume_until_answered():
    r = row("GMV €5M", value=5_000_000, extra_settings={"deck_take_rate": True}, **NO_FILE)
    assert (r["metric"], r["turnover_state"], r["turnover_set_by"]) == ("Transaction volume", "volume", "python")
    assert (r["evidence_label"], r["observed_value"]) == ("Unsupported", None) and "no engine volume source" in r["reason"]


def test_the_analyst_answer_wins_over_the_file_and_over_the_deck():
    r = row("Turnover €190,000", inputs={"turnover_as": "volume", "turnover_reason": "deck_says_processed_volume"})
    assert (r["metric"], r["turnover_set_by"], r["turnover_reason"], r["evidence_label"]) == \
        ("Transaction volume", "analyst", "deck_says_processed_volume", "Unsupported")
    r = row("GMV €900,000", value=900000, inputs={"turnover_as": "revenue", "turnover_reason": "deck_says_gross_revenue"})
    assert (r["metric"], r["evidence_label"], r["turnover_set_by"]) == ("Revenue", "Contradicted", "analyst")


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


def test_take_rate_words_in_a_deck():
    assert cm.mentions_take_rate({"blocks": [{"text": "Our Take Rate is 2%"}]})
    assert cm.mentions_take_rate([{"cells": ["Commission", "1%"]}])
    assert cm.mentions_take_rate(["spread"]) and cm.mentions_take_rate(["fees"])
    assert not cm.mentions_take_rate(["feeds the pipeline", "revenue"])


@pytest.mark.parametrize("text", ["GMV €5M", "TPV $2bn", "Payment volume €1M", "Trading volume €1M", "Transaction volume €1M", "Turnover €1M"])
def test_the_deck_parser_reads_every_turnover_term_as_a_revenue_family_claim(text):
    families = {family for family, rx in deck_claims._KEYWORDS if rx.search(text)}
    assert "revenue" in families
