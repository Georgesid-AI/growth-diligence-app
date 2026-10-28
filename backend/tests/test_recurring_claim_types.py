"""ARR, MRR, Churn, NRR and CAC payback are claim types of their own (George, 2026-10-23; engine contract 8; docs/specs/claim-matching.md,
amended 2026-10-23). The page reader's words arr, mrr, churn, nrr and the new cac_payback map to them, no longer to Revenue or Retention;
the type decides the engine metric, not a keyword in the snippet. Synthetic claims over the fixture runs; Python only."""
import copy
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from test_claim_matching import RUNS, results_for, run_claim  # noqa: E402
from test_page_check import claim, grid, line  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402
from app.llm import schemas  # noqa: E402
from app.structures import checker  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402
from schemas import metrics  # noqa: E402

NEW = ("arr", "mrr", "churn", "nrr", "cac_payback")
METRIC = {"arr": "ARR", "mrr": "MRR", "churn": "Gross revenue churn", "nrr": "NRR (12-month)", "cac_payback": "CAC payback"}
LABELS = {"arr": "ARR", "mrr": "MRR", "churn": "Churn", "nrr": "NRR", "cac_payback": "CAC payback"}
GROUP = {"arr": 1, "mrr": 1, "churn": 3, "nrr": 3, "cac_payback": 3}


def with_cac(results):
    """Run A holds no P&L, so no CAC payback: the same block the matching tests use."""
    results = copy.deepcopy(results)
    results["cac_payback"] = {"default_l": 1, "headline_quarter": "2023-Q3", "partial_quarter_excluded": None,
                              "source": {"file": "pnl.csv", "sheet": "CSV", "rows": "rows 2–15", "rule": "CAC payback"},
                              "quarters": {"2023-Q3": {"gross_margin_pct": 78.0, "partial": False, "L1": {"months": 14.0, "reason": None}},
                                           "2023-Q1": {"gross_margin_pct": 78.0, "partial": False, "L1": {"months": 9.0, "reason": None}}}}
    results.setdefault("metric_periods", {})["cac_payback"] = {"first": "2023-01", "last": "2023-09", "missing": []}
    return results


def row(kind, value, period, unit=None, currency=None, snippet="", **more):
    """One claim of a new type; the snippet names no keyword by default, so only the type can say the metric."""
    return run_claim({"claim_type": kind, "value": value, "unit": unit, "currency": currency, "target_date": period, "snippet": snippet},
                     **more)


# --- 1. the types and the page reader's words ------------------------------------------------------------------------------

def test_the_five_types_are_register_types_of_their_own_and_the_page_words_map_to_them():
    assert deck_claims.RECURRING_TYPES == NEW
    assert set(NEW) <= set(deck_claims.ANALYST_TYPES) and set(deck_claims.CLAIM_TYPES) < set(deck_claims.ANALYST_TYPES)
    assert deck_claims.PAGE_CLAIM_TYPE == {"market_share": "market"}, "arr, mrr, churn, nrr are no longer folded into Revenue or Retention"
    assert "cac_payback" in schemas.PAGE_METRICS and len(set(schemas.PAGE_METRICS)) == len(schemas.PAGE_METRICS)
    assert "cac_payback" not in schemas.CLAIM_METRICS, "the structure reads keep their list"
    sent = schemas.page_claims_output_schema()["properties"]["claims"]["items"]["properties"]["metric"]["enum"]
    assert "cac_payback" in sent
    for metric in NEW:
        assert deck_claims.PAGE_CLAIM_TYPE.get(metric, metric) == metric
    assert "months_to_profitability" in deck_claims.CLAIM_TYPES, "Months to profitability stays its own type"


@pytest.mark.parametrize("kind", NEW)
def test_each_type_has_its_group_and_a_scenario_still_goes_to_scenarios(kind):
    assert deck_claims.type_group(kind) == deck_claims.claim_group({"claim_type": kind}) == GROUP[kind]
    assert deck_claims.claim_group({"claim_type": kind, "scenario": "worst"}) == deck_claims.SCENARIO_GROUP
    assert deck_claims.type_name(kind) == LABELS[kind]


def test_a_page_row_carries_its_own_type_for_arr_mrr_churn_nrr_and_payback():
    page = grid([line(1, "ARR", 1), line(2, "$2.4M", 1), line(3, "Net revenue retention", 2), line(4, "112%", 2),
                 line(5, "Payback", 3), line(6, "14 months", 3), line(7, "Churn", 4), line(8, "8%", 4), line(9, "MRR", 5), line(10, "$200K", 5)])
    deck = {"file": "deck.pdf", "page_unit": "page", "blocks": []}
    for cell, metric, value, unit in (("r2c1", "arr", 2_400_000, "USD"), ("r4c1", "nrr", 112, "%"), ("r6c1", "cac_payback", 14, "months"),
                                      ("r8c1", "churn", 8, "%"), ("r10c1", "mrr", 200_000, "USD")):
        item, = checker.check(page, [claim(cell, value, metric=metric, unit=unit)], 12)["items"]
        assert pipeline.row_from_claim(item, page, deck, 12)["claim_type"] == metric
    far = pipeline.row_out_of_range(claim("p9r1c1", 14, metric="cac_payback", unit="months"), 9, deck)
    assert far["claim_type"] == "cac_payback"


def test_the_amount_types_need_a_currency_and_the_rates_do_not():
    assert {"arr", "mrr"} <= set(cm.MONEY_TYPES) and not {"churn", "nrr", "cac_payback"} & set(cm.MONEY_TYPES)
    assert row("arr", 200000, "2024-02")["required_unknown"] == ["currency"]
    assert row("nrr", 113, "2024-02", unit="%")["required_unknown"] == []


# --- 2. matching: the type names the engine's figure ---------------------------------------------------------------------

@pytest.mark.parametrize("kind, unit, currency", [("arr", None, "EUR"), ("mrr", None, "EUR"), ("churn", "%", None), ("nrr", "%", None),
                                                  ("cac_payback", "months", None)])
def test_the_type_alone_proposes_the_metric(kind, unit, currency):
    assert cm.propose_metric(kind, "currency" if currency else unit, "a line with no keyword") == METRIC[kind]


def test_arr_is_tested_against_the_engines_ending_arr_for_the_period_with_the_revenue_tolerance():
    within = row("arr", 205000, "2024-02", currency="EUR")
    assert within["metric"] == "ARR" and within["observed_value"] == pytest.approx(202125.48, abs=0.01)
    assert (within["evidence_label"], within["observed_at"]) == ("Verified", "2024-02") and within["tolerance"] == "±5%"
    beat = row("arr", 150000, "2024-02", currency="EUR")
    assert (beat["evidence_label"], beat["gap_kind"]) == ("Verified", "beat") and beat["reason"].startswith(cm.BEAT_PREFIX)
    miss = row("arr", 240000, "2024-02", currency="EUR")
    assert (miss["evidence_label"], miss["gap_kind"]) == ("Contradicted", "miss")


def test_mrr_is_tested_against_the_engines_ending_mrr():
    within = row("mrr", 17000, "2024-02", currency="EUR")
    assert within["metric"] == "MRR" and within["observed_value"] == pytest.approx(16843.79, abs=0.01) and within["evidence_label"] == "Verified"
    assert row("mrr", 20000, "2024-02", currency="EUR")["evidence_label"] == "Contradicted"
    assert row("mrr", 12000, "2024-02", currency="EUR")["evidence_label"] == "Verified"


def test_nrr_is_tested_against_the_twelve_month_nrr_within_one_point():
    within = row("nrr", 113, "2024-02", unit="%")
    assert within["metric"] == "NRR (12-month)" and within["observed_value"] == pytest.approx(112.68) and within["evidence_label"] == "Verified"
    assert within["tolerance"] == "±1 pp"
    assert row("nrr", 120, "2024-02", unit="%")["evidence_label"] == "Contradicted"
    assert row("nrr", 105, "2024-02", unit="%")["reason"].startswith(cm.BEAT_PREFIX)


def test_churn_is_tested_against_gross_revenue_churn_lower_is_better():
    results = copy.deepcopy(results_for(RUNS["A"]))
    for point in results["gross_churn"]["series"]:
        point["churn_pct"] = 0.08
    miss = row("churn", 5, "2024-02", unit="%", results=results)
    assert miss["metric"] == "Gross revenue churn" and miss["direction"] == "lower"
    assert (miss["observed_value"], miss["gap_kind"], miss["evidence_label"]) == (8.0, "miss", "Contradicted")
    assert row("churn", 8.5, "2024-02", unit="%", results=results)["evidence_label"] == "Verified"
    beat = row("churn", 12, "2024-02", unit="%", results=results)
    assert (beat["gap_kind"], beat["evidence_label"]) == ("beat", "Verified")


def test_cac_payback_is_tested_against_the_engines_months_for_the_quarter():
    results = with_cac(results_for(RUNS["A"]))
    miss = row("cac_payback", 12, "2023-Q3", unit="months", results=results)
    assert miss["metric"] == "CAC payback" and (miss["observed_value"], miss["observed_at"]) == (14.0, "2023-Q3")
    assert (miss["evidence_label"], miss["gap_kind"], miss["gloss"]) == ("Contradicted", "miss", "2.0 months longer (miss)")
    assert row("cac_payback", 14.5, "2023-Q3", unit="months", results=results)["evidence_label"] == "Verified"
    beat = row("cac_payback", 20, "2023-Q3", unit="months", results=results)
    assert (beat["evidence_label"], beat["gap_kind"]) == ("Verified", "beat") and beat["reason"].startswith(cm.BEAT_PREFIX)


def test_a_month_the_engine_has_no_value_for_is_unverified_and_the_reason_names_it():
    results = copy.deepcopy(results_for(RUNS["A"]))
    results["mrr_series"]["data"] = [d for d in results["mrr_series"]["data"] if d["month"] != "2023-06"]
    results["metric_periods"]["mrr_series"]["missing"] = ["2023-06"]
    for kind, currency in (("arr", "EUR"), ("mrr", "EUR")):
        got = row(kind, 100000, "2023-06", currency=currency, results=results)
        assert got["evidence_label"] == "Unverified" and "2023-06" in got["reason"], got["reason"]
        assert got["months_missing"] == ["2023-06"] and got["gap"] is None
    for kind, period in (("nrr", "2022-05"), ("churn", "2022-05")):
        got = row(kind, 100, period, unit="%")
        assert got["evidence_label"] == "Unverified" and "2024-01" in got["reason"], (kind, got["reason"])


def test_a_quarter_the_engine_has_no_value_for_names_its_months():
    results = with_cac(results_for(RUNS["A"]))
    got = row("cac_payback", 12, "2023-Q2", unit="months", results=results)
    assert got["evidence_label"] == "Unverified" and "2023-04 to 2023-06" in got["reason"], got["reason"]
    assert got["months_missing"] == ["2023-04", "2023-05", "2023-06"] and got["observed_value"] is None


def test_a_claim_of_the_old_types_still_reads_its_keyword_and_a_contract_value_is_still_not_computed():
    old = run_claim({"claim_type": "revenue", "value": 205000, "currency": "EUR", "target_date": "2024-02", "snippet": "ARR €205,000"})
    assert old["metric"] == "ARR" and old["evidence_label"] == "Verified"
    contract = row("arr", 205000, "2024-02", currency="EUR", snippet="Contracted ARR €205,000")
    assert contract["metric"] == "Contract value" and contract["evidence_label"] == "Unverified"
    assert row("arr", 205000, "2024-02", currency="EUR", snippet="New MRR €205,000")["metric"] == "ARR", "the type decides, not the snippet"


def test_arr_and_mrr_overlap_and_the_names_read_in_a_sentence():
    from app import verdict
    got = row("cac_payback", 12, "2023-Q3", unit="weeks", currency=None)
    assert verdict.claim_name({**got, "metric": None}).startswith("CAC payback")
    assert verdict.claim_name({**got, "metric": None, "claim_type": "nrr", "period": None}) == "NRR"


# --- 3. the contract (the Uber page 20 fixture, 4 claims and 1 flag, stays pinned by test_checker.py) ----------------------------------------------------------------------------------------

def test_the_engine_contract_is_9():
    assert metrics.CONTRACT_VERSION == 13 and metrics.DECK_CLAIM_FIELDS == ("basis", "scenario", "flags")

