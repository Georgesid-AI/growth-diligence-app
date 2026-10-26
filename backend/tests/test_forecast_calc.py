"""Forecast diagnostics (docs/specs/forecast-and-payback.md section 3; docs/design/claim-review-simplified-design.md section 3).

The acceptance table of the design note, for this scope: like-duration bases, insufficient history, missing periods, zero and negative inputs,
ranges, remaining target, and no verification of future outcomes. Pure Python over synthetic series; fixture companies only.
"""
import re

import pytest

from app import forecast_calc as fc

EUR = lambda v: f"€{v:,.0f}"        # noqa: E731


def m(text):
    return fc.mi(text)


def months(first, last, value):
    """{month index: value} for every month from `first` to `last`; `value` is a number or a function of the month index."""
    return {i: (value(i) if callable(value) else value) for i in range(m(first), m(last) + 1)}


def run(metric="Revenue", series=None, last=None, start="2026-01", end="2026-12", low=1.0, high=None, fye=12, **kw):
    series = series if series is not None else {}
    last = m(last) if isinstance(last, str) else last
    return fc.diagnose(metric=metric, series=series, last=last, start=m(start), end=m(end), low=low, high=high, fye=fye, money=EUR, **kw)


def lines_of(found):
    return " | ".join(found["lines"])


# 2023: 100,000 a month (1.2M a year); 2024: 120,000 a month (1.44M a year): FY2024 grew 20% on FY2023.
TWO_YEARS = {**months("2023-01", "2023-12", 100_000), **months("2024-01", "2024-12", 120_000)}


# --- 1. like-duration bases ------------------------------------------------------------------------------------------------------

def test_an_annual_forecast_is_set_against_the_latest_complete_actual_fiscal_year_with_its_window_named():
    found = run(series=TWO_YEARS, last="2024-12", start="2026-01", end="2026-12", low=2_073_600)
    assert found["reason"] is None
    assert found["base"] == {"value": 1_440_000, "window": "FY2024", "start": "2024-01", "end": "2024-12", "elapsed": 24}
    assert found["required"] == {"low": pytest.approx(0.2), "high": None}, "(2,073,600 / 1,440,000) ^ (12 / 24) - 1"
    assert found["historical"] == {"kind": "annual", "value": pytest.approx(0.2), "windows": ["FY2023", "FY2024"]}
    assert found["difference"] == {"low": pytest.approx(0.0), "high": None}
    text = lines_of(found)
    assert "Required growth: 20.0% a year" in text and "FY2024" in text and "24 months" in text
    assert "Historical growth: 20.0% (FY2023 → FY2024)" in text
    assert "Difference: +0.0 percentage points (required less historical)" in text


def test_the_required_growth_is_the_compound_annual_rate_over_the_elapsed_months():
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=1_728_000)       # 1.44M x 1.2 in 12 months
    assert found["base"]["elapsed"] == 12 and found["required"]["low"] == pytest.approx(0.2)
    found = run(series=TWO_YEARS, last="2024-12", start="2027-01", end="2027-12", low=1_440_000 * 1.5 ** 3)     # 36 months, +50% a year
    assert found["base"]["elapsed"] == 36 and found["required"]["low"] == pytest.approx(0.5)


def test_the_gap_to_the_historical_growth_is_in_percentage_points_and_carries_no_verdict():
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=1_440_000 * 1.5)
    assert found["difference"]["low"] == pytest.approx(30.0), "required 50% less historical 20%"
    text = lines_of(found)
    assert "Difference: +30.0 percentage points (required less historical)" in text
    for word in ("beat", "pass", "fail", "ahead", "behind", "achievable", "on track", "verified"):
        assert not re.search(rf"(?i)\b{word}\b", text), f"a calculation is a number, not a verdict: {word!r}"


def test_a_forecast_below_the_historical_growth_shows_a_negative_difference():
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=1_440_000 * 1.1)
    assert found["difference"]["low"] == pytest.approx(-10.0)
    assert "Difference: -10.0 percentage points" in lines_of(found)


def test_with_no_complete_fiscal_year_the_complete_trailing_12_months_are_the_base_and_the_window_is_named():
    series = months("2023-03", "2024-02", 100_000)                  # twelve months, none a complete December year
    found = run(series=series, last="2024-02", start="2025-01", end="2025-12", low=1_800_000)
    assert found["base"] == {"value": 1_200_000, "window": "2023-03 to 2024-02", "start": "2023-03", "end": "2024-02", "elapsed": 22}
    assert found["required"]["low"] == pytest.approx((1_800_000 / 1_200_000) ** (12 / 22) - 1)
    assert "2023-03 to 2024-02" in lines_of(found) and "22 months" in lines_of(found)


def test_the_latest_complete_fiscal_year_is_preferred_to_a_later_trailing_window():
    series = {**TWO_YEARS, **months("2025-01", "2025-05", 130_000)}      # five months of 2025 are in the data
    found = run(series=series, last="2025-05", start="2026-01", end="2026-12", low=2_000_000)
    assert found["base"]["window"] == "FY2024" and found["base"]["elapsed"] == 24


def test_a_march_year_end_names_and_aligns_its_fiscal_years():
    series = {**months("2022-04", "2023-03", 100_000), **months("2023-04", "2024-03", 120_000)}     # FY2023 and FY2024
    found = run(series=series, last="2024-03", start="2025-04", end="2026-03", low=1_440_000 * 1.21, fye=3)
    assert found["base"]["window"] == "FY2024" and found["base"]["start"] == "2023-04" and found["base"]["end"] == "2024-03"
    assert found["base"]["elapsed"] == 24 and found["required"]["low"] == pytest.approx(0.1)
    assert found["historical"]["windows"] == ["FY2023", "FY2024"]


def test_a_quarter_is_set_against_the_same_quarter_of_an_earlier_year_never_an_annual_total():
    series = {**months("2023-01", "2023-12", 100_000), **months("2024-01", "2024-12", 110_000)}
    found = run(series=series, last="2024-12", start="2025-04", end="2025-06", low=363_000)          # Q2 2025
    assert found["base"]["start"] == "2024-04" and found["base"]["end"] == "2024-06" and found["base"]["value"] == 330_000
    assert found["base"]["elapsed"] == 12 and found["required"]["low"] == pytest.approx(0.1)
    assert found["historical"]["windows"] == ["2023-04 to 2023-06", "2024-04 to 2024-06"] and found["historical"]["value"] == pytest.approx(0.1)
    assert 1_320_000 not in (found["base"]["value"],), "the annual total is never the base of a quarter"


def test_a_quarter_moves_back_a_year_at_a_time_to_the_latest_year_that_holds_all_its_months():
    series = {**months("2022-04", "2022-06", 100_000), **months("2023-01", "2023-03", 90_000), **months("2024-01", "2024-12", 120_000)}
    series.pop(m("2024-05"))                                             # Q2 2024 has a hole: not complete
    found = run(series=series, last="2024-12", start="2025-04", end="2025-06", low=420_000)
    assert found["base"]["start"] == "2022-04" and found["base"]["elapsed"] == 36 and found["base"]["value"] == 300_000


def test_a_quarter_with_no_actual_quarter_of_an_earlier_year_shows_the_target_and_the_missing_comparator():
    series = months("2024-07", "2024-12", 100_000)                       # only the second half of one year; the annual total does not exist
    found = run(series=series, last="2024-12", start="2025-04", end="2025-06", low=330_000)
    assert found["required"] is None and found["base"] is None
    assert found["reason"] == "no actual revenue for the same quarter of an earlier year (missing comparator: 2024-04 to 2024-06)"
    text = lines_of(found)
    assert "Required growth: not calculated – no actual revenue for the same quarter of an earlier year" in text
    assert "€330,000" in text and "2025-04 to 2025-06" in text, "the target is shown"


def test_a_month_is_set_against_the_same_calendar_month_of_an_earlier_year():
    series = {**months("2023-01", "2023-12", 100_000), **months("2024-01", "2024-12", 120_000)}
    found = run(series=series, last="2024-12", start="2025-09", end="2025-09", low=144_000)
    assert found["base"]["start"] == found["base"]["end"] == "2024-09" and found["base"]["elapsed"] == 12
    assert found["required"]["low"] == pytest.approx(0.2) and found["historical"]["value"] == pytest.approx(0.2)


def test_a_balance_is_set_against_the_latest_observation_with_the_elapsed_months_to_the_endpoint():
    arr = {**months("2023-01", "2023-12", 1_000_000), **months("2024-01", "2024-12", 1_200_000)}
    found = run(metric="ARR", series=arr, last="2024-12", start="2026-12", end="2026-12", low=1_728_000)
    assert found["base"] == {"value": 1_200_000, "window": "2024-12", "start": "2024-12", "end": "2024-12", "elapsed": 24}
    assert found["required"]["low"] == pytest.approx(0.2)
    assert found["historical"] == {"kind": "annual", "value": pytest.approx(0.2), "windows": ["2023-12", "2024-12"]}


@pytest.mark.parametrize("metric", ["MRR", "Customer count"])
def test_mrr_and_customers_follow_the_same_rule_as_arr(metric):
    series = {**months("2023-01", "2023-12", 100), **months("2024-01", "2024-12", 150)}
    found = run(metric=metric, series=series, last="2024-12", start="2025-12", end="2025-12", low=225)
    assert found["base"]["value"] == 150 and found["base"]["elapsed"] == 12
    assert found["required"]["low"] == pytest.approx(0.5) and found["historical"]["value"] == pytest.approx(0.5)


def test_the_claims_own_year_is_never_the_base():
    found = run(series=TWO_YEARS, last="2024-12", start="2024-01", end="2024-12", low=1_728_000)
    assert found["base"]["window"] == "FY2023" and found["base"]["elapsed"] == 12, "a base starts before the claim's period"


# --- 2. insufficient history and missing periods ------------------------------------------------------------------------------------

def test_without_a_window_before_the_base_the_annual_comparator_is_missing_and_the_reason_names_it():
    series = months("2024-01", "2024-12", 120_000)
    found = run(series=series, last="2024-12", start="2025-01", end="2025-12", low=1_728_000)
    assert found["required"]["low"] == pytest.approx(0.2) and found["historical"] is None and found["difference"] is None
    assert found["historical_reason"] == "insufficient history: no complete 12 months before FY2024"
    assert "Historical growth: not available – insufficient history: no complete 12 months before FY2024" in lines_of(found)


def test_a_hole_in_the_window_before_the_base_makes_that_comparator_unavailable_and_names_the_months():
    series = {**months("2023-01", "2023-12", 100_000), **months("2024-01", "2024-12", 120_000)}
    series.pop(m("2023-05"))
    found = run(series=series, last="2024-12", start="2025-01", end="2025-12", low=1_728_000)
    assert found["base"]["window"] == "FY2024" and found["historical"] is None
    assert found["historical_reason"] == "insufficient history: months missing in the comparator window FY2023: 2023-05"


def test_a_hole_in_a_fiscal_year_makes_it_incomplete_so_the_latest_complete_year_is_used():
    series = {**months("2022-01", "2022-12", 80_000), **months("2023-01", "2023-12", 100_000), **months("2024-01", "2024-12", 120_000)}
    series.pop(m("2024-05"))
    found = run(series=series, last="2024-12", start="2025-01", end="2025-12", low=1_500_000)
    assert found["base"]["window"] == "FY2023" and found["base"]["elapsed"] == 24
    assert found["historical"]["windows"] == ["FY2022", "FY2023"]


def test_no_complete_twelve_months_gives_no_growth_and_names_the_months_missing():
    series = months("2024-01", "2024-12", 120_000)
    series.pop(m("2024-05"))
    found = run(series=series, last="2024-12", start="2025-01", end="2025-12", low=1_728_000)
    assert found["required"] is None
    assert found["reason"] == "no complete 12 months of actual revenue"
    assert "Required growth: not calculated – no complete 12 months of actual revenue" in lines_of(found)


def test_a_pace_indicator_is_named_apart_with_its_dates_and_interval_and_has_no_difference():
    series = months("2023-01", "2024-02", lambda i: 100_000 * 1.02 ** (i - m("2023-01")))      # 14 observations over 13 months elapsed
    found = run(series=series, last="2024-02", start="2025-01", end="2025-12", low=2_400_000)
    pace = found["pace"]
    assert pace["start"] == "2023-01" and pace["end"] == "2024-02" and pace["elapsed"] == 13 and pace["observations"] == 14
    assert pace["value"] == pytest.approx(1.02 ** 12 - 1, rel=1e-6) and pace["limited"] is False
    assert found["historical"] is None and found["difference"] is None, "a pace indicator is not annual growth: no difference in points"
    text = lines_of(found)
    assert "Pace indicator (monthly endpoint growth, not annual growth)" in text and "2023-01 to 2024-02" in text
    assert "13 months elapsed, 14 observations" in text


def test_a_history_under_twelve_elapsed_months_is_marked_limited_and_observations_are_not_elapsed_time():
    series = {m("2024-01"): 100.0, m("2024-03"): 102.0, m("2024-06"): 110.0, m("2024-09"): 115.0, m("2024-11"): 118.0}
    found = run(metric="Customer count", series=series, last="2024-11", start="2025-12", end="2025-12", low=200)
    pace = found["pace"]
    assert pace["elapsed"] == 10 and pace["observations"] == 5 and pace["limited"] is True
    text = lines_of(found)
    assert "10 months elapsed, 5 observations" in text and "history limited: under 12 months" in text


def test_a_history_of_twelve_elapsed_months_is_not_marked_limited():
    series = months("2023-01", "2024-01", lambda i: 100 + (i - m("2023-01")))                # 13 observations, 12 months elapsed
    found = run(metric="Customer count", series=series, last="2024-01", start="2025-12", end="2025-12", low=200)
    assert found["historical"] is not None, "the balance twelve months earlier exists: an annual comparator"
    series = months("2023-02", "2024-01", lambda i: 100 + (i - m("2023-02")))                # 12 observations, 11 elapsed: no annual comparator
    found = run(metric="Customer count", series=series, last="2024-01", start="2025-12", end="2025-12", low=200)
    assert found["historical"] is None and found["pace"]["elapsed"] == 11 and found["pace"]["limited"] is True


def test_a_balance_without_the_observation_twelve_months_earlier_names_it():
    arr = {**months("2023-01", "2023-10", 1_000_000), **months("2024-01", "2024-12", 1_200_000)}
    found = run(metric="ARR", series=arr, last="2024-12", start="2025-12", end="2025-12", low=1_440_000)
    assert found["historical"] is None and found["historical_reason"] == "insufficient history: no observation of ARR at 2023-12"
    assert found["pace"] is not None and found["pace"]["observations"] == 22 and found["pace"]["elapsed"] == 23


def test_no_observation_at_all_gives_no_calculation():
    found = run(metric="ARR", series={}, last=None, start="2025-12", end="2025-12", low=1_440_000)
    assert found["required"] is None and found["reason"] == "no actual observation of ARR"


def test_a_series_of_one_month_has_no_pace_indicator():
    found = run(metric="ARR", series={m("2024-12"): 1_200_000.0}, last="2024-12", start="2025-12", end="2025-12", low=1_440_000)
    assert found["required"]["low"] == pytest.approx(0.2) and found["pace"] is None and found["historical"] is None


# --- 3. zero and negative inputs ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("series_value, low, reason", [
    (0, 1_000_000, "base not positive"),
    (-5_000, 1_000_000, "base not positive"),
    (100_000, 0, "forecast not positive"),
    (100_000, -1_000_000, "forecast not positive"),
])
def test_a_zero_or_negative_base_or_forecast_gives_a_specific_reason_and_never_a_number(series_value, low, reason):
    series = months("2023-01", "2024-12", series_value)
    found = run(series=series, last="2024-12", start="2025-01", end="2025-12", low=low)
    assert found["required"] is None and found["reason"] == reason
    assert f"Required growth: not calculated – {reason}" in lines_of(found)
    assert not re.search(r"\d+\.\d%", lines_of(found).split("Required growth")[1].split("|")[0]), "no growth figure is printed"


def test_elapsed_months_that_are_not_positive_give_a_specific_reason():
    arr = months("2023-01", "2024-12", 1_000_000)
    found = run(metric="ARR", series=arr, last="2024-12", start="2024-12", end="2024-12", low=1_100_000)
    assert found["required"] is None and found["reason"] == "elapsed months not positive"


def test_a_comparator_over_a_zero_or_negative_window_is_unavailable_with_its_reason():
    series = {**months("2023-01", "2023-12", 0), **months("2024-01", "2024-12", 120_000)}
    found = run(series=series, last="2024-12", start="2025-01", end="2025-12", low=1_728_000)
    assert found["required"]["low"] == pytest.approx(0.2) and found["historical"] is None
    assert found["historical_reason"] == "comparator base not positive"
    series = {**months("2023-01", "2023-12", -10_000), **months("2024-01", "2024-12", 120_000)}
    assert run(series=series, last="2024-12", start="2025-01", end="2025-12", low=1_728_000)["historical_reason"] == "comparator base not positive"


def test_a_period_that_is_not_a_year_a_quarter_or_a_month_is_not_calculated():
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-06", low=900_000)
    assert found["required"] is None and found["reason"] == "period is not a year, a quarter or a month"


# --- 4. ranges ---------------------------------------------------------------------------------------------------------------------

def test_a_range_is_shown_as_a_range_with_both_ends_calculated():
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=1_728_000, high=2_160_000)
    assert found["required"] == {"low": pytest.approx(0.2), "high": pytest.approx(0.5)}
    assert found["difference"] == {"low": pytest.approx(0.0), "high": pytest.approx(30.0)}
    text = lines_of(found)
    assert "Required growth: 20.0% to 50.0% a year" in text and "€1,728,000–€2,160,000" in text
    assert "Difference: +0.0 to +30.0 percentage points (required less historical)" in text


def test_a_range_is_never_reduced_to_the_end_that_compares_best():
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=1_440_000 * 1.1, high=1_440_000 * 1.5)
    assert found["required"]["low"] == pytest.approx(0.1) and found["required"]["high"] == pytest.approx(0.5)
    assert found["difference"]["low"] == pytest.approx(-10.0) and found["difference"]["high"] == pytest.approx(30.0)


def test_a_range_with_an_end_that_is_not_positive_calculates_no_growth():
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=-10, high=2_160_000)
    assert found["required"] is None and found["reason"] == "low end of the forecast range not positive"
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=1_728_000, high=0)
    assert found["required"] is None and found["reason"] == "low end of the forecast range not positive"
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=-5, high=0)
    assert found["reason"] == "both ends of the forecast range not positive"
    assert "Required growth: not calculated – both ends of the forecast range not positive" in lines_of(found)
    assert run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=0)["reason"] == "forecast not positive", "a single figure"


def test_a_range_given_in_either_order_reads_low_then_high():
    found = run(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=2_160_000, high=1_728_000)
    assert found["required"]["low"] == pytest.approx(0.2) and found["required"]["high"] == pytest.approx(0.5)


# --- 5. remaining target -----------------------------------------------------------------------------------------------------------

def test_when_actuals_cover_part_of_the_forecast_year_the_remaining_amount_is_kept_and_labelled_a_calculation():
    series = {**TWO_YEARS, **months("2025-01", "2025-05", 130_000)}
    found = run(series=series, last="2025-05", start="2025-01", end="2025-12", low=1_800_000)
    assert found["remaining"] == {"value": 1_150_000, "actual": 650_000, "months": 5}
    assert "Remaining to reach the target: €1,150,000 (calculation: 5 of 12 months actual, €650,000 to date)" in lines_of(found)


def test_no_remaining_amount_when_no_month_of_the_period_is_in_the_data():
    found = run(series=TWO_YEARS, last="2024-12", start="2026-01", end="2026-12", low=2_000_000)
    assert found["remaining"] is None and "Remaining" not in lines_of(found)


def test_a_hole_inside_the_part_year_gives_no_remaining_amount():
    series = {**TWO_YEARS, **months("2025-01", "2025-05", 130_000)}
    series.pop(m("2025-03"))
    found = run(series=series, last="2025-05", start="2025-01", end="2025-12", low=1_800_000)
    assert found["remaining"] is None


def test_the_remaining_amount_of_a_balance_is_the_target_less_the_latest_observation():
    arr = months("2023-01", "2024-12", 1_000_000)
    found = run(metric="ARR", series=arr, last="2024-12", start="2025-12", end="2025-12", low=1_300_000)
    assert found["remaining"] == {"value": 300_000, "actual": 1_000_000, "months": 1}
    assert "Remaining to reach the target: €300,000 (calculation: target less the latest observation, 2024-12)" in lines_of(found)


# --- 6. the text ------------------------------------------------------------------------------------------------------------------

SCENARIOS = [
    dict(series=TWO_YEARS, last="2024-12", start="2026-01", end="2026-12", low=2_073_600),
    dict(series=TWO_YEARS, last="2024-12", start="2025-01", end="2025-12", low=1_728_000, high=2_160_000),
    dict(series=months("2024-01", "2024-12", 120_000), last="2024-12", start="2025-01", end="2025-12", low=1_728_000),
    dict(series=months("2024-07", "2024-12", 100_000), last="2024-12", start="2025-04", end="2025-06", low=330_000),
    dict(series=months("2023-01", "2024-12", 0), last="2024-12", start="2025-01", end="2025-12", low=1),
    dict(series={**TWO_YEARS, **months("2025-01", "2025-05", 130_000)}, last="2025-05", start="2025-01", end="2025-12", low=1_800_000),
]


@pytest.mark.parametrize("case", SCENARIOS, ids=range(len(SCENARIOS)))
def test_the_lines_are_flat_text_without_a_semicolon_a_disclaimer_or_a_verdict_word(case):
    found = run(**case)
    assert found["lines"] and all(isinstance(line, str) for line in found["lines"] + found["details"])
    for line in found["lines"] + found["details"]:
        assert "; " not in line, "a list field is joined by '; ' in the baseline CSV"
        assert "unverified" not in line.lower() and "future outcome" not in line.lower(), "the one forecast note is shown once, never on a row"
        assert not re.search(r"(?i)\b(beat|pass|fail)\b", line)


def test_the_details_hold_the_formula_and_every_input_with_its_window():
    found = run(series=TWO_YEARS, last="2024-12", start="2026-01", end="2026-12", low=2_073_600)
    details = " | ".join(found["details"])
    assert "required annual growth = (forecast ÷ base) ^ (12 ÷ elapsed months) − 1" in details
    assert "forecast €2,073,600 for FY2026 (2026-01 to 2026-12)" in details and "base €1,440,000 for FY2024 (2024-01 to 2024-12)" in details
    assert "elapsed 24 months" in details and "comparator FY2023 €1,200,000 → FY2024 €1,440,000" in details


def test_the_calculation_depends_only_on_its_inputs():
    one = run(series=TWO_YEARS, last="2024-12", start="2026-01", end="2026-12", low=2_073_600)
    two = run(series=dict(reversed(list(TWO_YEARS.items()))), last="2024-12", start="2026-01", end="2026-12", low=2_073_600)
    assert one == two


def test_a_balance_forecast_names_its_endpoint_month_not_a_twelve_month_window():
    arr = months("2023-01", "2024-12", 1_000_000)
    found = run(metric="ARR", series=arr, last="2024-12", start="2025-01", end="2025-12", low=1_500_000)
    text = lines_of(found)
    assert "for 2025-12 against" in text and "2025-01 to 2025-12" not in text and "Target" not in text
    assert not any("2025-01 to 2025-12" in d for d in found["details"]) and any("forecast €1,500,000 for 2025-12" in d for d in found["details"])
    shown = fc.unavailable("population differs", "180", m("2025-01"), m("2025-12"), 12, flow=False)
    assert shown["lines"][1] == "Target: 180 for 2025-12"
    assert fc.unavailable("population differs", "180", m("2025-01"), m("2025-12"))["lines"][1] == "Target: 180 for FY2025"
