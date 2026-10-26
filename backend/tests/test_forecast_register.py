"""Forecast claims in the register (docs/specs/forecast-and-payback.md sections 2 and 3; design note section 3).

Actual or forecast comes from the source classification, never from the period alone; a forecast is Unverified however far its figure is from the
history, and carries the calculation lines instead of a repeated disclaimer. Fixture company: synthetic figures, a 36-month series.
"""
import pytest

from forecast_support import NOTE, claim, forecast, long_results, row_of

from app import claim_matching as cm
from app import verdict as verdict_mod

# --- 1. actual or forecast: the source classification ------------------------------------------------------------------------------

def test_a_period_after_the_data_alone_is_missing_coverage_not_a_forecast():
    for basis in ("actual", None):
        row = row_of(claim("Revenue €2.1M in FY2026", 2_073_600, "FY2026", "2026", basis=basis))
        assert row["figure_type"] == "actual" and row["evidence_label"] == "Unverified"
        assert row["reason"].startswith("claim period not in supplied data"), row["reason"]
        assert row["calc_lines"] == [] and row["gap_kind"] != "to go", "no forecast calculation, no 'to go'"


def test_a_projection_for_a_period_after_the_data_is_a_forecast():
    row = row_of(forecast())
    assert row["figure_type"] == "target" and row["evidence_label"] == "Unverified"
    assert row["calc_lines"] and row["calc_lines"][0].startswith("Required growth: 20.0% a year")
    arr = row_of(claim("ARR €1.7M target by Dec 2025", 1_728_000, "Dec 2025", "2025-12", claim_type="arr", basis="projection"))
    assert arr["gap_kind"] == "to go", "the existing 'to go' gap stays for a forecast that has a latest figure"


def test_a_scenario_basis_for_a_period_after_the_data_is_a_forecast():
    row = row_of(claim("Revenue €2.1M in FY2026", 2_073_600, "FY2026", "2026", basis="scenario"))
    assert row["figure_type"] == "target" and row["calc_lines"]


def test_a_target_cue_in_the_claims_words_is_a_forecast_with_no_basis():
    row = row_of(claim("Target revenue €2.1M in FY2026", 2_073_600, "FY2026", "2026"))
    assert row["figure_type"] == "target" and row["calc_lines"]


def test_the_analysts_figure_type_wins_over_the_basis_in_both_directions():
    assert row_of(forecast(figure_type="actual"))["calc_lines"] == [], "the analyst says it is an actual: missing coverage"
    row = row_of(claim("Revenue €2.1M in FY2026", 2_073_600, "FY2026", "2026", basis="actual", figure_type="target"))
    assert row["figure_type"] == "target" and row["calc_lines"], "the analyst says it is a plan: a forecast"


def test_a_projection_for_a_period_in_the_data_stays_an_actual_with_the_existing_flag():
    c = claim("Revenue €1.4M in FY2024", 1_440_000, "FY2024", "2024", basis="projection")
    row = row_of(c)
    assert row["figure_type"] == "actual" and row["calc_lines"] == []
    assert cm.basis_conflict(c, "2024-12") is True


# --- 2. no verification of future outcomes ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [2_073_600, 100_000, 50_000_000, 1_440_000])
def test_a_forecast_is_unverified_however_far_the_figure_is_from_the_history(value):
    row = row_of(forecast(value))
    assert row["evidence_label"] == "Unverified"
    assert row["gap_kind"] in ("to go", None), "never a miss or a beat"
    text = " ".join([row["reason"], row["gloss"] or "", *row["calc_lines"], *row["calc_details"]]).lower()
    for word in ("beat", "verified:", "contradicted", " pass", " fail"):
        assert word not in text, word


def test_the_row_reason_is_the_calculation_not_a_repeated_disclaimer():
    row = row_of(forecast())
    assert row["reason"] == "Forecast: required growth 20.0% a year against 20.0% historical"
    assert not hasattr(cm, "FORECAST_AFTER_DATA") and not hasattr(cm, "forecast_after_data")
    for field in ("reason", "gloss", "vas_reason", "period_note"):
        assert "cannot be tested" not in str(row[field] or "") and NOTE not in str(row[field] or "")
    assert not any(NOTE in line for line in row["calc_lines"] + row["calc_details"]), "the note is shown once, never on a row"


def test_a_forecast_whose_calculation_is_unavailable_says_why_in_its_reason():
    row = row_of(forecast(), results=long_results("2022-06"))        # six months of history: no complete year
    assert row["evidence_label"] == "Unverified" and row["reason"] == "Forecast: no complete 12 months of actual revenue"
    assert row["calc_lines"][0] == "Required growth: not calculated – no complete 12 months of actual revenue"


def test_a_forecast_of_a_metric_with_no_comparison_has_a_reason_and_no_calculation():
    row = row_of(claim("NRR 120% in FY2026", 120, "FY2026", "2026", claim_type="retention", unit="%", currency=None, basis="projection"))
    assert row["metric"] == "NRR (12-month)" and row["evidence_label"] == "Unverified"
    assert row["reason"] == "Forecast: no comparison is calculated for this metric" and row["calc_lines"] == []


def test_the_forecast_note_is_one_sentence_shown_once_whenever_a_forecast_appears():
    rows = [row_of(forecast()), row_of(forecast(3_000_000, id="x2"))]
    assert verdict_mod.FORECAST_NOTE == NOTE
    assert verdict_mod.has_forecast(rows) is True
    assert verdict_mod.has_forecast([row_of(claim("Revenue €1.4M in FY2024", 1_440_000, "FY2024", "2024", basis="actual"))]) is False
    assert verdict_mod.has_forecast([]) is False


# --- 3. the calculation in the register -----------------------------------------------------------------------------------------------

def test_the_lines_name_the_base_the_comparator_the_difference_and_the_details_hold_the_inputs():
    row = row_of(forecast())
    text = " | ".join(row["calc_lines"])
    assert "FY2024" in text and "24 months" in text and "Historical growth: 20.0% (FY2023 → FY2024)" in text
    assert "Difference: +0.0 percentage points (required less historical)" in text
    assert any("base €1,440,000 for FY2024" in d for d in row["calc_details"]) and "required annual growth" in row["calc_details"][0]


def test_a_range_is_shown_as_a_range():
    row = row_of(claim("Revenue €1.7M to €2.2M in FY2025", 1_728_000, "FY2025", "2025", basis="projection", value_high=2_160_000))
    assert row["calc_lines"][0].startswith("Required growth: 20.0% to 50.0% a year")
    assert row["evidence_label"] == "Unverified"


def test_arr_is_set_against_the_latest_observation_of_arr_and_customers_against_customers():
    row = row_of(claim("ARR €1.7M target by Dec 2025", 1_728_000 * 1.0, "Dec 2025", "2025-12", claim_type="arr", basis="projection"))
    assert row["metric"] == "ARR" and row["calc_lines"][0].startswith("Required growth: 20.0% a year")
    assert any("base" in d and "2024-12" in d for d in row["calc_details"])
    row = row_of(claim("180 customers by Dec 2025", 180, "Dec 2025", "2025-12", claim_type="customers", currency=None, basis="projection"))
    assert row["metric"] == "Customer count" and row["calc_lines"][0].startswith("Required growth: 50.0% a year")


def test_a_part_year_of_actuals_keeps_the_remaining_amount_labelled_a_calculation():
    c = claim("Revenue €1.8M in FY2025", 1_800_000, "FY2025", "2025", basis="projection")
    results = long_results("2024-12")
    for key in ("revenue_series", "mrr_series"):
        extra = [{"month": f"2025-{m:02d}", "total": 130_000.0, "Enterprise": 78_000.0, "Mid-Market": 39_000.0, "SMB": 13_000.0} for m in range(1, 6)]
        results[key]["data"] += extra
        results[key]["months"] += [d["month"] for d in extra]
    results["as_of_month"] = "2025-05"
    row = row_of(c, last="2025-05", results=results)
    assert any(line.startswith("Remaining to reach the target: €1,150,000 (calculation: 5 of 12 months actual") for line in row["calc_lines"])


def test_a_claim_in_another_currency_without_a_saved_rate_is_not_calculated():
    row = row_of(claim("Revenue £1.7M in FY2026", 1_728_000, "FY2026", "2026", currency="GBP", basis="projection"))
    assert row["reason"].startswith("FX rate needed") and row["calc_lines"] == []


def test_a_population_that_differs_is_named_as_the_reason_a_growth_is_not_calculated():
    c = claim("180 registered users in FY2026", 180, "FY2026", "2026", claim_type="customers", currency=None, basis="projection", population="registered")
    row = row_of(c)
    assert row["evidence_label"] == "Unverified"
    assert row["calc_lines"][0].startswith("Required growth: not calculated – population differs")


def test_the_calculation_lists_survive_the_baseline_csv_round_trip():
    rows = [row_of(forecast())]
    text = verdict_mod.baseline_csv(rows, [], [], None)
    parsed, _, _ = verdict_mod.parse_baseline(text)
    assert parsed[0]["calc_lines"] == rows[0]["calc_lines"] and parsed[0]["calc_details"] == rows[0]["calc_details"]
    assert verdict_mod.rewrite_baseline(parsed, [], None) == text, "the same bytes"
    assert cm.FIELDS[-2:] == ("calc_lines", "calc_details") or {"calc_lines", "calc_details"} <= set(cm.FIELDS)


# --- 4. an actual after the data is missing coverage for every metric kind (Opus review M1) -------------------------------------------

@pytest.mark.parametrize("metric_periods", [False, True])
def test_an_actual_ARR_after_the_data_reads_not_covered(metric_periods):
    results = long_results()
    if metric_periods:
        results["metric_periods"] = {"mrr_series": {"first": "2022-01", "last": "2024-12", "missing": []}}
    for basis in ("actual", None):
        row = row_of(claim("ARR €1.7M in Dec 2025", 1_728_000, "Dec 2025", "2025-12", claim_type="arr", basis=basis), results=results)
        assert row["evidence_label"] == "Unverified" and row["reason"].startswith("claim period not in supplied data: after "), row["reason"]


def test_an_actual_win_rate_after_the_data_reads_not_covered():
    results = long_results()
    row = row_of(claim("Win rate 30% in Dec 2025", 30, "Dec 2025", "2025-12", claim_type="sales", unit="%", currency=None, basis="actual"),
                 results=results)
    assert row["metric"] == "Win rate" and row["evidence_label"] == "Unverified"
    assert row["reason"].startswith("claim period not in supplied data: after "), row["reason"]


def test_an_actual_acv_and_segment_nrr_after_the_data_read_not_covered():
    acv = row_of(claim("ACV €30k in Dec 2025", 30_000, "Dec 2025", "2025-12", claim_type="sales", unit=None, basis="actual"))
    assert acv["metric"] == "ACV" and acv["reason"].startswith("claim period not in supplied data: after "), acv["reason"]
    nrr = row_of(claim("Enterprise NRR 120% in Dec 2025", 120, "Dec 2025", "2025-12", claim_type="retention", unit="%", currency=None,
                       basis="actual", segment="Enterprise"))
    assert nrr["metric"] == "NRR (12-month)" and nrr["reason"].startswith("claim period not in supplied data: after "), nrr["reason"]


# --- 5. the turnover path and _observe take the forecast flag, never infer it from the period (Opus review L1) -------------------------------

def test_observe_does_not_infer_a_forecast_from_the_period():
    import inspect
    results = long_results()
    figures = cm._Figures(results, "ARR", cm.WHOLE)
    after = cm._mi("2025-12")
    got = cm._observe(figures, cm.METRICS["ARR"], "ARR", after - 11, after, cm._mi("2024-12"))
    assert isinstance(got[0], str) and got[0].startswith("Unverified|claim period not in supplied data: after "), got
    assert inspect.signature(cm._observe).parameters["forecast"].default is False
    assert inspect.signature(cm._file_revenue).parameters["forecast"].default is inspect.Parameter.empty


def test_the_turnover_path_passes_the_classification_to_observe(monkeypatch):
    seen = []
    real = cm._observe
    monkeypatch.setattr(cm, "_observe", lambda *a, **k: seen.append(k.get("forecast")) or real(*a, **k))
    results = long_results()
    assert cm._file_revenue(results, cm.WHOLE, cm._mi("2024-01"), cm._mi("2024-12"), cm._mi("2024-12"), False)[0] == 1_440_000
    assert cm._file_revenue(results, cm.WHOLE, cm._mi("2025-01"), cm._mi("2025-12"), cm._mi("2024-12"), True) == (None, None)
    assert cm._file_revenue(results, cm.WHOLE, cm._mi("2025-01"), cm._mi("2025-12"), cm._mi("2024-12"), False) == (None, None)
    assert seen == [False, False], "the flag goes to _observe as given; a forecast never reaches it"
