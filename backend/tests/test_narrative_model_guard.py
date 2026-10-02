"""Narrative model setting and the numeric guard on signed figures. Stub only - no real API calls."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.llm import gateway  # noqa: E402
from app.llm.schemas import Narrative  # noqa: E402


# --- model setting ---------------------------------------------------------
def test_narrative_model_defaults_to_sonnet_5_5(monkeypatch):
    monkeypatch.delenv("NARRATIVE_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert gateway.run_model() == "claude-sonnet-5-5"


def test_narrative_model_is_read_from_narrative_model_env(monkeypatch):
    monkeypatch.setenv("NARRATIVE_MODEL", "claude-opus-5-5")
    assert gateway.run_model() == "claude-opus-5-5"
    assert gateway.estimate_cost_usd("claude-opus-5-5", 1_000_000, 1_000_000) == pytest.approx(24.00)
    assert gateway.estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.00)


# --- numeric guard -----------------------------------------------------------
# The engine's segment projection for a shrinking segment, as the model receives it.
COMPUTED = {"metrics": {"segment_paths": {
    "stage_one": {"segments": {"SMB": {"nrr_pct": 76.0, "nrr_base_customers": 65, "start_arr": 324_787.5,
                                       "projected_arr": 246_838.13, "change_arr": -77_949.37}}},
    "landed": {"12": {"segments": {"SMB": {"new_customers": 89}}}},
}}}
SENTENCE = ("SMB has NRR of 76% on 65 base customers. In the segment projection its ARR falls by 77,949 EUR, "
            "yet it supplies the largest share of new customers (89 in the last 12 months).")


def _narrative(text):
    return Narrative(headline="Segment mix", what_this_means=text)


def test_a_negative_engine_figure_written_as_a_fall_is_verified():
    payload = gateway.build_outbound(COMPUTED, {})
    assert "-77,949" in str(payload), "fixture: the engine figure is signed"
    assert gateway.numeric_guard(_narrative(SENTENCE), payload).all == []


def test_the_guard_is_not_widened_beyond_the_sign():
    payload = gateway.build_outbound(COMPUTED, {})
    # a figure the model worked out itself (start - projected, rounded differently) stays unverified
    assert gateway.numeric_guard(_narrative("ARR falls by 77,950 EUR."), payload).all == ["77950"]
    # a positive engine figure never licenses its negative
    assert gateway.numeric_guard(_narrative("NRR moved -76% on -65 customers."), payload).all == ["-76", "-65"]


@pytest.mark.parametrize("text", ["ARR falls by 77,949 EUR.", "ARR declines 77,949 EUR.", "ARR is down 77,949 EUR.",
                                  "A loss of 77,949 EUR of ARR."])
def test_a_dropped_minus_sign_passes_with_decline_wording(text):
    payload = gateway.build_outbound(COMPUTED, {})
    assert gateway.numeric_guard(_narrative(text), payload).all == []


@pytest.mark.parametrize("text", ["ARR grows by 77,949 EUR.", "ARR changes by 77,949 EUR.",
                                  "ARR falls, then rises by 77,949 EUR."])
def test_a_dropped_minus_sign_without_decline_wording_is_flagged(text):
    payload = gateway.build_outbound(COMPUTED, {})
    assert gateway.numeric_guard(_narrative(text), payload).soft == ["77949"]


def test_decline_wording_counts_only_in_its_own_sentence():
    payload = gateway.build_outbound(COMPUTED, {})
    text = "SMB ARR falls at 76% NRR. The projection changes by 77,949 EUR."
    assert gateway.numeric_guard(_narrative(text), payload).all == ["77949"]


def test_a_dropped_minus_sign_in_the_headline_still_needs_decline_wording():
    payload = gateway.build_outbound(COMPUTED, {})
    flagged = Narrative(headline="SMB ARR grows by 77,949 EUR", what_this_means="")
    assert gateway.numeric_guard(flagged, payload).hard == ["77949"]
    assert gateway.numeric_guard(Narrative(headline="SMB ARR drops 77,949 EUR", what_this_means=""), payload).all == []


@pytest.mark.parametrize("text", ["NRR grows to 76% on 65 base customers.", "SMB had 89 new customers.",
                                  "NRR falls to 76% on 65 base customers, with 89 new customers."])
def test_positive_figures_are_unaffected_by_direction_words(text):
    payload = gateway.build_outbound(COMPUTED, {})
    assert gateway.numeric_guard(_narrative(text), payload).all == []
