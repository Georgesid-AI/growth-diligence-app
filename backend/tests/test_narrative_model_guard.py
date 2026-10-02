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
