"""An approved AI-read claim is tested like any other; value at stake from Target ARR and Target date; the top-5 proposal; the reason
texts of a claim with no period and of two data gaps; the growth basis default (docs/specs/claim-matching.md, chat-upload.md)."""
import copy

import pytest

from test_claim_matching import RUNS, results_for, run_claim

import growth_engine
from app import claim_matching as cm
from app import verdict as vd
from app.decks import claims as deck_claims

TARGET = {"target_arr": 5_000_000, "target_date": "2025-12-31"}
AI = {"origin": "ai", "ai_status": "unverified", "ai_label": "AI suggestion, not verified"}
NRR = {"claim_type": "retention", "snippet": "NRR", "unit": "%", "currency": None, "target_date": "2024-02"}


def results_a():
    return copy.deepcopy(results_for(RUNS["A"]))


# --- 1. an approved AI-read claim is analyst-confirmed ---------------------------------------------------------------------

def test_an_approved_ai_claim_within_tolerance_is_verified_and_outside_it_is_contradicted():
    inside = run_claim({**NRR, **AI, "value": 112})
    assert (inside["evidence_label"], inside["deck_reading"]) == ("Verified", "AI suggestion, not verified")
    assert "not verified" not in inside["reason"] and "analyst edits" not in inside["reason"]
    outside = run_claim({**NRR, **AI, "value": 120})
    assert (outside["evidence_label"], outside["deck_status"]) == ("Unverified", "differs"), "deck-actuals.md: a past period is management data, not a claim"


def test_an_approved_ai_claim_that_beats_the_data_is_a_verified_beat():
    revenue = {"claim_type": "revenue", "snippet": "Revenue", "currency": "EUR", "target_date": "2024-02", **AI}
    observed = run_claim({**revenue, "value": 1})["observed_value"]
    row = run_claim({**revenue, "value": observed * 0.8})
    assert (row["evidence_label"], row["deck_status"]) == ("Unverified", "differs"), "deck-actuals.md: either way beyond tolerance, the deck differs from the file"


# --- 2. value at stake ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("claim, expected, marked", [
    ({"claim_type": "arr", "snippet": "ARR", "value": 600_000, "target_date": "2024-02"}, 600_000, None),
    # a short period annualised says so, with its period and multiplier (claim-groups.md section 6)
    ({"claim_type": "mrr", "snippet": "MRR", "value": 50_000, "target_date": "2024-02"}, 600_000, None),   # MRR times 12 is the metric's definition, not a run-rate
    ({"claim_type": "arr", "snippet": "ARR", "value": 9_000_000, "target_date": "2024-02"}, 5_000_000, None),     # capped at Target ARR
    ({"claim_type": "revenue", "snippet": "Revenue", "value": 300_000, "target_date": "2024-Q1"}, 1_200_000, "run-rate: 2024-Q1 × 4"),
    ({"claim_type": "revenue", "snippet": "Revenue", "value": 1_200_000, "target_date": "2023"}, 1_200_000, None),
])
def test_value_at_stake_is_the_claimed_arr_equivalent_capped_at_target_arr(claim, expected, marked):
    row = run_claim({"currency": "EUR", **claim}, **TARGET)
    assert (row["value_at_stake_arr"], row["vas_reason"]) == (expected, marked)


def test_value_at_stake_of_a_rate_is_the_rate_times_current_arr_and_of_a_count_the_count_times_acv():
    results = results_a()
    arr, acv = results["arr"]["value"], results["acv_path"]["acv"]
    churn = run_claim({"claim_type": "churn", "snippet": "Gross revenue churn", "unit": "%", "currency": None, "value": 10,
                       "target_date": "2024-02"}, results=results, **TARGET)
    assert churn["value_at_stake_arr"] == pytest.approx(arr * 0.10)
    customers = run_claim({"claim_type": "customers", "snippet": "Customers", "unit": "customers", "currency": None, "value": 100,
                           "target_date": "2024-02"}, results=results, **TARGET)
    assert customers["value_at_stake_arr"] == pytest.approx(100 * acv)


@pytest.mark.parametrize("extra, reason", [
    ({}, "not yet computed: Target ARR and Target date empty"),
    ({"target_arr": 5_000_000}, "not yet computed: Target date empty"),
    ({"target_date": "2025-12-31"}, "not yet computed: Target ARR empty"),
    ({"target_arr": 0, "target_date": "2025-12-31"}, "not yet computed: Target ARR empty"),
])
def test_value_at_stake_waits_only_for_the_empty_target_field_and_names_it(extra, reason):
    row = run_claim({"claim_type": "arr", "snippet": "ARR", "value": 600_000, "currency": "EUR", "target_date": "2024-02"}, **extra)
    assert (row["value_at_stake_arr"], row["vas_reason"]) == (None, reason)


def test_a_contradicted_claim_has_value_at_stake_too_and_an_untested_one_has_none():
    arr = {"claim_type": "arr", "snippet": "ARR", "currency": "EUR", "target_date": "2024-02"}
    observed = run_claim({**arr, "value": 1}, **TARGET)["observed_value"]
    row = run_claim({**arr, "value": observed * 1.3}, **TARGET)
    assert row["evidence_label"] == "Contradicted" and row["value_at_stake_arr"] == pytest.approx(min(observed * 1.3, 5_000_000))
    funds = run_claim({"claim_type": "use_of_funds", "snippet": "Use of funds", "unit": "%", "currency": None, "value": 40}, **TARGET)
    assert funds["value_at_stake_arr"] is None and funds["vas_reason"] == "no ARR link: untested claim"


# --- 3. the top-5 proposal ------------------------------------------------------------------------------------------------

def row(i, claim_type, vas=None, value=100.0, **extra):
    base = dict.fromkeys(cm.FIELDS)
    base.update(claim_id=f"r{i}", rank=i, claim_type=claim_type, evidence_label="Unverified", claimed_value=value, value_at_stake_arr=vas,
                overlaps_with=[], gate_needed=True)
    base.update(extra)
    return base


@pytest.mark.parametrize("excluded", ["market", "pricing", "use_of_funds", "other", "people", "product"])
def test_the_proposal_leaves_out_market_pricing_use_of_funds_other_people_and_product(excluded):
    rows = [row(1, excluded, vas=9e9), row(2, "revenue", vas=1)]
    assert vd.proposal(rows) == ["r2"]


def test_the_proposal_ranks_testable_plan_claims_by_value_at_stake_then_by_claim_value():
    types = ["revenue", "arr", "mrr", "churn", "nrr", "revenue_growth", "sales", "customers"]
    rows = [row(i + 1, t, vas=v, value=c) for i, (t, v, c) in enumerate(zip(
        types, [None, 500, 500, 900, 100, None, 700, 300], [50, 10, 20, 5, 5, 80, 5, 5]))]
    # VaS 900, 700, then the 500 pair by claim value (mrr 20 before arr 10), then 300; the claims with no VaS follow
    assert vd.proposal(rows) == ["r4", "r7", "r3", "r2", "r8"]
    assert vd.proposal(rows[:2] + [row(9, "revenue", vas=None, value=70)])[:3] == ["r2", "r9", "r1"]


# --- 4. reason texts ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("claim_type, snippet, unit, currency", [
    ("nrr", "NRR", "x", None), ("gross_margin", "Gross margin", "x", None), ("customers", "Customers", "%", None)])
def test_a_claim_whose_type_has_an_engine_metric_but_no_period_reads_period_missing(claim_type, snippet, unit, currency):
    row = run_claim({"claim_type": claim_type, "snippet": snippet, "unit": unit, "currency": currency, "value": 5, "target_date": None})
    assert (row["evidence_label"], row["reason"]) == ("Unverified", "period missing; set it with Edit")


def test_a_claim_with_a_period_and_no_metric_stays_unverified_no_metric():
    row = run_claim({"claim_type": "sales", "snippet": "Sales cycle 60", "unit": None, "currency": None, "value": 60, "target_date": "2024-02"})
    assert (row["evidence_label"], row["reason"]) == ("Unverified", "no metric")


def _engine(rev, pnl, config, yearly=None):
    import pandas as pd
    return growth_engine.compute_all_raw(rev, pd.DataFrame(), pnl, config, {}, yearly=yearly)


def test_the_cac_gap_of_a_yearly_pnl_and_the_arr_gap_of_a_monthly_total_report_read_as_the_file_is():
    import pandas as pd
    config = {"recognition": {"file": "r.xlsx", "sheet": "S", "file_type": "monthly_revenue_report", "basis": "recognised", "periods": 0,
                              "excluded_columns": [], "currency_confirmed": True, "series": [], "rows": []}}
    yearly = {"file": "p.xlsx", "sheet": "P", "actual": [], "rows": []}
    res = _engine(pd.DataFrame(), pd.DataFrame(), config, yearly)
    gaps = {m["metric"]: m["reason"] for m in res["missing_data"]}
    assert gaps["CAC payback"] == "P&L is yearly; CAC payback needs monthly S&M, revenue and cost of revenue"
    assert gaps["ARR / MRR"] == "revenue file is a monthly total report with no recurring split"
    plain = _engine(pd.DataFrame(), pd.DataFrame(), {})
    plain_gaps = {m["metric"]: m["reason"] for m in plain["missing_data"]}
    assert plain_gaps["CAC payback"] == "P&L not provided" and plain_gaps["ARR / MRR"] == "No usable recurring revenue rows"


# --- 5. growth basis default ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, basis", [
    ("Revenue grew 40% from 2023", "yoy"), ("Annual revenue growth of 40%", "yoy"), ("Revenue up 40% YoY", "yoy"),
    ("Revenue up 40% Y2Y", "yoy"), ("Revenue up 4% MoM", "mom"), ("Users grow 4% per month", "mom"), ("Monthly growth of 4%", "mom"),
    ("Revenue grew 40%", "unknown")])
def test_the_growth_basis_defaults_from_the_claim_text(text, basis):
    assert deck_claims.growth_basis(text) == basis


def test_a_parser_or_model_basis_of_unknown_does_not_hide_the_words_and_the_analyst_override_stays():
    claim = {"claim_type": "revenue_growth", "value": 15, "unit": "%", "currency": None, "target_date": "2024-01", "period_text": "Jan 2024",
             "snippet": "Revenue grew 15% YoY in Jan 2024", "growth_basis": "unknown"}
    assert run_claim(claim)["growth_basis"] == "yoy"
    assert run_claim({**claim, "claim_inputs": {"x1": {"growth_basis": "mom"}}})["growth_basis"] == "mom"
