"""The page reader's closed metric list grows by seven words (George, 2026-10-23; engine contract 7): arr, mrr, churn, nrr, market_share,
pricing, use_of_funds. Each maps to a register claim type (decks.claims.PAGE_CLAIM_TYPE) and so to a group of the claims list. Contract 8 (the
same day) makes arr, mrr, churn and nrr types of their own and adds cac_payback (test_recurring_claim_types.py). Synthetic pages only."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from test_page_check import claim, grid, line  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402
from app.llm import schemas  # noqa: E402
from app.structures import checker  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402
from schemas import metrics  # noqa: E402

NEW = ("arr", "mrr", "churn", "nrr", "market_share", "pricing", "use_of_funds")
TYPE_AND_GROUP = {"arr": ("arr", 1), "mrr": ("mrr", 1), "churn": ("churn", 3), "nrr": ("nrr", 3),
                  "market_share": ("market", 5), "pricing": ("pricing", 10), "use_of_funds": ("use_of_funds", 8)}


def test_the_closed_metric_list_holds_the_seven_new_words_in_the_model_class_and_the_json_schema():
    assert set(NEW) <= set(schemas.PAGE_METRICS) and "other" in schemas.PAGE_METRICS
    assert len(set(schemas.PAGE_METRICS)) == len(schemas.PAGE_METRICS)
    assert set(NEW).isdisjoint(schemas.CLAIM_METRICS), "the structure reads keep their lists"
    base = dict(value=1.0, value_high=None, unit="USD", unit_other=None, period=None, basis="actual", scenario="none",
                value_cell="p1r1c1", label_cell=None, period_cell=None)
    for metric in NEW:
        assert schemas.PageClaim.model_validate({"metric": metric, **base}).metric == metric
    with pytest.raises(ValueError):
        schemas.PageClaim.model_validate({"metric": "ndr", **base})
    sent = schemas.page_claims_output_schema()["properties"]["claims"]["items"]["properties"]["metric"]["enum"]
    assert sent == list(schemas.PAGE_METRICS) and set(NEW) <= set(sent)


@pytest.mark.parametrize("metric", NEW)
def test_each_new_metric_maps_to_a_register_claim_type_and_its_group(metric):
    claim_type, group = TYPE_AND_GROUP[metric]
    assert deck_claims.PAGE_CLAIM_TYPE.get(metric, metric) == claim_type
    assert deck_claims.type_group(claim_type) == group
    assert deck_claims.claim_group({"claim_type": claim_type}) == group
    assert deck_claims.claim_group({"claim_type": claim_type, "scenario": "best"}) == deck_claims.SCENARIO_GROUP


def test_the_other_metrics_map_to_themselves():
    assert all(m not in deck_claims.PAGE_CLAIM_TYPE for m in deck_claims.CLAIM_TYPES)


def test_pricing_and_use_of_funds_are_collapsed_groups_listed_after_market_size_and_before_other():
    assert deck_claims.GROUPS[10] == "pricing" and set(deck_claims.COLLAPSED_GROUPS) == {8, 9, 10}
    assert 10 <= max(deck_claims.GROUPS), "Approve all accepts the group"
    assert deck_claims.PRICING == "pricing" and deck_claims.PRICING not in deck_claims.CLAIM_TYPES


def test_a_page_row_carries_the_register_claim_type_not_the_models_word():
    page = grid([line(1, "Annual recurring revenue", 1), line(2, "$2.4M", 1), line(3, "Net revenue retention", 2), line(4, "112%", 2)])
    deck = {"file": "deck.pdf", "page_unit": "page", "blocks": []}
    for cell, metric, value, unit, expected in (("r2c1", "arr", 2_400_000, "USD", "arr"), ("r4c1", "nrr", 112, "%", "nrr")):
        item, = checker.check(page, [claim(cell, value, metric=metric, unit=unit)], 12)["items"]
        assert pipeline.row_from_claim(item, page, deck, 12)["claim_type"] == expected
    far = pipeline.row_out_of_range(claim("p9r1c1", 99, metric="market_share", unit="%"), 9, deck)
    assert far["claim_type"] == "market"
    assert pipeline.row_out_of_range(claim("p9r1c1", 99, metric="pricing", unit="USD"), 9, deck)["claim_type"] == "pricing"


def test_pricing_is_a_money_type_with_an_optional_period_and_no_engine_metric_to_test_it_against():
    assert "pricing" in cm.MONEY_TYPES and "pricing" in cm.PERIOD_OPTIONAL_TYPES and "pricing" in cm.UNTESTED_TYPES
    assert cm.UNTESTED_TYPES["pricing"].startswith("pricing:")


def test_the_engine_contract_is_9():
    assert metrics.CONTRACT_VERSION == 15
    assert metrics.DECK_CLAIM_FIELDS == ("basis", "scenario", "flags"), "contracts 7 and 8 change the metric list, not the claim fields"


def test_a_pricing_claim_with_no_period_goes_through_the_register_unverified_with_its_closed_reason():
    from test_claim_matching import run_claim
    row = run_claim({"claim_type": "pricing", "snippet": "$49 per seat", "value": 49, "currency": "USD", "target_date": None, "origin": "ai",
                     "ai_status": "unverified", "ai_label": "AI suggestion, not verified"})
    assert row["evidence_label"] == "Unverified" and row["reason"] == cm.PRICING_NOTE
