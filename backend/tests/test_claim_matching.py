"""Claim matching: approved claims tested against the computed metrics (docs/specs/claim-matching.md).

The fixture is synthetic: TestCo claims on sample_data/ (section 9). Every fixture row gives its label, gap,
gloss and rank; every label class and every metric of table 2a has at least one row. Python only: the matching
module reads stored results and the register's rows, never a model.
"""
import copy

import pytest

from claim_matching_support import engine_results, fixture

from app import claim_matching as cm
from app.decks import claims as deck_claims

FIX = fixture()
RUNS = FIX["runs"]
METRICS_2A = ("Revenue", "ARR", "MRR", "Customer count", "New MRR", "NRR (12-month)", "Gross revenue churn", "ACV",
              "Median sales cycle", "Win rate", "Gross margin", "CAC payback")
LABELS = ("Verified", "Contradicted", "Unverified", "Unsupported")


def settings(run, **extra):
    return {"fiscal_year_end": run["fiscal_year_end"], "as_of_month": run["as_of_month"],
            "reporting_currency": run["reporting_currency"], "fx": {"EUR": 1.0}, **extra}


def results_for(run):
    return engine_results(tuple(run["files"]), run["as_of_month"])


def candidates_for(run):
    """The run's candidates as the register stores them: period resolved for the year-end, the analyst's inputs on the row."""
    by_id = {}
    for entry in run["claims"]:
        c = by_id.setdefault(entry["candidate"]["id"], copy.deepcopy(entry["candidate"]))
        if entry["analyst"]:
            c.setdefault("claim_inputs", {})[entry["claim_id"]] = dict(entry["analyst"])
    out = list(by_id.values())
    for c in out:
        deck_claims.resolve_period(c, run["fiscal_year_end"])
        for item in c.get("by_period") or ():
            deck_claims.resolve_period(item, run["fiscal_year_end"])
    return out


def register(run):
    return cm.build_register(candidates_for(run), results_for(run), settings(run))


def row_of(rows, claim_id):
    return next(r for r in rows if r["claim_id"] == claim_id)


def run_claim(candidate, run="A", **extra):
    """One synthetic claim over a fixture run's data; its row."""
    r = RUNS[run]
    c = {"id": "x1", "status": "approved", "claim_type": "revenue", "value": 1, "value_high": None, "unit": None,
         "currency": "EUR", "target_date": None, "period_text": None, "snippet": "", "label_from": None,
         "file": "deck.pptx", "order": 0, "sources": [{"file": "deck.pptx", "slide": 3}], **candidate}
    deck_claims.resolve_period(c, r["fiscal_year_end"])
    return cm.build_register([c], extra.pop("results", None) or results_for(r), settings(r, **extra))[0]


ALL = [(name, e) for name, r in RUNS.items() for e in r["claims"]]


# --- section 9: the fixture ------------------------------------------------------------------------------------------

def test_the_fixture_covers_every_label_class_and_every_metric_of_table_2a():
    expected = [e["expect"] for _, e in ALL]
    assert {x["label"] for x in expected} == set(LABELS)
    assert {x["metric"] for x in expected if x.get("metric")} == set(METRICS_2A)


@pytest.mark.parametrize("name, entry", ALL, ids=[f"run{n}-claim{e['n']}-{e['claim_id']}" for n, e in ALL])
def test_fixture_row_gives_its_label_gap_gloss_and_rank(name, entry):
    row = row_of(register(RUNS[name]), entry["claim_id"])
    e = entry["expect"]
    assert row["evidence_label"] == e["label"], row["reason"]
    if "reason" in e:
        assert e["reason"].lower() in row["reason"].lower(), row["reason"]
    for key, field in (("metric", "metric"), ("segment", "segment"), ("observed_at", "observed_at"), ("kind", "gap_kind"),
                       ("note", "period_note"), ("gloss", "gloss"), ("tolerance", "tolerance"), ("direction", "direction"),
                       ("deck_reading", "deck_reading"), ("rank", "rank")):
        if key in e:
            assert row[field] == e[key], f"{field}: {row[field]!r}"
    if "observed" in e:
        assert row["observed_value"] == (pytest.approx(e["observed"], abs=0.005) if e["observed"] is not None else None)
    if e.get("gap") is not None:
        assert row["gap"] == pytest.approx(e["gap"], abs=0.005)
        assert row["gap_normalised"] == pytest.approx(e["norm"], abs=1e-5)
    elif "observed" in e and e["observed"] is None:
        assert row["gap"] is None and row["gap_normalised"] is None and row["gap_kind"] is None and row["gloss"] is None


@pytest.mark.parametrize("name", sorted(RUNS))
def test_the_register_comes_in_rank_order_and_ranks_run_from_one(name):
    rows = register(RUNS[name])
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert len(rows) == len({r["claim_id"] for r in rows}) == len(RUNS[name]["claims"])


def test_a_table_row_gives_one_claim_per_value_by_period():
    rows = register(RUNS["A"])
    assert {r["claim_id"] for r in rows} >= {"c19#1", "c19#2"} and "c19" not in {r["claim_id"] for r in rows}


def test_forecasts_and_untested_rows_rank_after_every_row_with_a_gap_and_keep_register_order():
    rows = register(RUNS["A"])
    kinds = [r["gap_kind"] for r in rows]
    # misses first, then beats and zero gaps (a beat counts as 0), then the rest: forecast and untested rows
    first_rest = next(i for i, r in enumerate(rows) if r["gap_kind"] == "to go" or r["observed_value"] is None)
    assert all(r["gap"] is not None and r["gap_kind"] != "to go" for r in rows[:first_rest])
    misses = [r["gap_normalised"] for r in rows[:first_rest] if r["gap_kind"] == "miss"]
    assert misses == sorted(misses, reverse=True) and len(misses) == 10
    assert kinds[:10] == ["miss"] * 10
    assert [r["claim_id"] for r in rows[first_rest:]] == [
        "c09", "c10", "c12", "c14", "c15", "c16", "c17", "c18", "c19#1", "c26", "c29", "c30", "c33", "c34"]


def test_a_beat_beyond_tolerance_is_contradicted_but_never_ranks_as_a_miss():
    rows = register(RUNS["A"])
    beat = row_of(rows, "c08")
    assert (beat["evidence_label"], beat["gap_kind"], beat["gap_normalised"]) == ("Contradicted", "beat", -0.25)
    assert beat["rank"] > row_of(rows, "c27")["rank"]          # a 1.2% miss ranks above a 25% beat


# --- section 2: matching ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("claim, metric", [
    ({"claim_type": "revenue", "snippet": "Revenue of €1M"}, "Revenue"),
    # Turnover, GMV and TPV are not proposed as revenue: section 11 asks (tests/test_turnover.py)
    ({"claim_type": "revenue", "label_from": "Revenue"}, "Revenue"),
    ({"claim_type": "revenue", "snippet": "Recurring revenue €1M"}, None),
    ({"claim_type": "revenue", "snippet": "Bookings €1M"}, None),
    ({"claim_type": "revenue", "snippet": "ARR €1M"}, "ARR"),
    ({"claim_type": "revenue", "snippet": "Annual recurring revenue €1M"}, "ARR"),
    ({"claim_type": "revenue", "snippet": "MRR €1M"}, "MRR"),
    ({"claim_type": "revenue", "snippet": "Monthly recurring revenue €1M"}, "MRR"),
    ({"claim_type": "revenue", "snippet": "New MRR €1M"}, "New MRR"),
    ({"claim_type": "revenue", "snippet": "ARR €1M"}, "ARR"),
    ({"claim_type": "revenue", "snippet": "Revenue €1M", "currency": None}, None),                  # no currency: not an amount
    ({"claim_type": "revenue_growth", "snippet": "Revenue growth 30%", "unit": "%", "currency": None}, None),
    ({"claim_type": "growth", "snippet": "ARR growth 30%", "unit": "%", "currency": None}, None),
    ({"claim_type": "customers", "snippet": "40 customers", "unit": "customers", "currency": None}, "Customer count"),
    ({"claim_type": "customers", "snippet": "40 customers", "unit": "%", "currency": None}, None),
    ({"claim_type": "users", "snippet": "40 users", "unit": "users", "currency": None}, None),
    ({"claim_type": "retention", "snippet": "NRR 110%", "unit": "%", "currency": None}, "NRR (12-month)"),
    ({"claim_type": "retention", "snippet": "Net retention 110%", "unit": "%", "currency": None}, "NRR (12-month)"),
    ({"claim_type": "retention", "snippet": "Net revenue retention 110%", "unit": "%", "currency": None}, "NRR (12-month)"),
    ({"claim_type": "retention", "snippet": "Revenue churn 5%", "unit": "%", "currency": None}, "Gross revenue churn"),
    ({"claim_type": "retention", "snippet": "Gross churn 5%", "unit": "%", "currency": None}, "Gross revenue churn"),
    ({"claim_type": "retention", "snippet": "Retention 90%", "unit": "%", "currency": None}, None),
    ({"claim_type": "retention", "snippet": "Churn 5%", "unit": "%", "currency": None}, None),
    ({"claim_type": "sales", "snippet": "ACV €40K", "currency": "EUR"}, "ACV"),
    ({"claim_type": "sales", "snippet": "Sales cycle 60 days", "unit": "days", "currency": None}, "Median sales cycle"),
    ({"claim_type": "sales", "snippet": "Win rate 40%", "unit": "%", "currency": None}, "Win rate"),
    ({"claim_type": "sales", "snippet": "CAC payback 12 months", "unit": "months", "currency": None}, "CAC payback"),
    ({"claim_type": "sales", "snippet": "Pipeline €2M", "currency": "EUR"}, None),
    ({"claim_type": "gross_margin", "snippet": "Gross margin 70%", "unit": "%", "currency": None}, "Gross margin"),
    ({"claim_type": "gross_profit", "snippet": "Gross profit €1M", "currency": "EUR"}, None),
    ({"claim_type": "ebitda", "snippet": "EBITDA €1M", "currency": "EUR"}, None),
    ({"claim_type": "sales", "snippet": "Win rate 40%", "unit": "customers", "currency": None}, None),    # a win rate in customers
])
def test_the_metric_is_proposed_from_claim_type_keyword_and_unit(claim, metric):
    row = run_claim({"value": 40, **claim})
    assert (row["metric"], row["metric_set_by"]) == (metric, "python")
    if metric is None:
        assert (row["evidence_label"], row["observed_value"]) == ("Unsupported", None) and "no metric" in row["reason"]


def test_the_analyst_may_set_the_metric_or_none_and_python_does_not_overrule_it():
    base = {"claim_type": "revenue", "snippet": "Bookings €1M", "value": 200000, "target_date": "2024-02", "period_text": "Feb 2024"}
    row = run_claim({**base, "claim_inputs": {"x1": {"metric": "ARR"}}})
    assert (row["metric"], row["metric_set_by"], row["evidence_label"]) == ("ARR", "analyst", "Verified")
    row = run_claim({**base, "snippet": "ARR €1M", "claim_inputs": {"x1": {"metric": "none"}}})
    assert (row["metric"], row["metric_set_by"], row["evidence_label"]) == (None, "analyst", "Unsupported")


def test_a_metric_the_analyst_picks_in_another_unit_than_the_claim_is_unsupported():
    row = run_claim({"claim_type": "sales", "snippet": "Win rate", "unit": "%", "currency": None, "value": 40,
                     "claim_inputs": {"x1": {"metric": "ARR"}}})
    assert (row["evidence_label"], row["metric_set_by"]) == ("Unsupported", "analyst") and "unit" in row["reason"]


@pytest.mark.parametrize("snippet, segment, by", [
    ("Enterprise ARR €1M", "Enterprise", "python"), ("enterprise ARR €1M", "Enterprise", "python"),
    ("mid-market ARR €1M", "Mid-Market", "python"), ("SMB ARR €1M", "SMB", "python"),
    ("Enterprise and SMB ARR €1M", "Whole company", "python"),         # two segments named: the whole company
    ("Enterprises ARR €1M", "Whole company", "python"),                 # not a whole word
    ("ARR €1M", "Whole company", "python"),
])
def test_a_segment_is_proposed_when_the_snippet_names_exactly_one(snippet, segment, by):
    row = run_claim({"claim_type": "revenue", "snippet": snippet, "target_date": "2024-02", "period_text": "Feb 2024"})
    assert (row["segment"], row["segment_set_by"]) == (segment, by)


def test_the_label_borrowed_from_a_header_names_the_segment_too():
    row = run_claim({"claim_type": "revenue", "snippet": "ARR €1M", "label_from": "Mid-Market", "target_date": "2024-02"})
    assert row["segment"] == "Mid-Market"


def test_the_analyst_may_set_a_segment_the_engine_has():
    row = run_claim({"claim_type": "revenue", "snippet": "ARR €1M", "target_date": "2024-02", "value": 3_900 * 12,
                     "claim_inputs": {"x1": {"segment": "Mid-Market"}}})
    assert (row["segment"], row["segment_set_by"], row["observed_value"]) == ("Mid-Market", "analyst", pytest.approx(3983.33 * 12, abs=0.1))


def test_an_unknown_segment_is_not_in_the_data():
    row = run_claim({"claim_type": "revenue", "snippet": "ARR €1M", "target_date": "2024-02",
                     "claim_inputs": {"x1": {"segment": "Public sector"}}})
    assert row["evidence_label"] == "Unsupported" and "segment not in the data" in row["reason"]


@pytest.mark.parametrize("snippet, claim_type, unit, currency", [
    ("Enterprise gross churn 5%", "retention", "%", None), ("Enterprise gross margin 70%", "gross_margin", "%", None),
    ("Enterprise new MRR €1K", "revenue", None, "EUR"), ("Enterprise CAC payback 12 months", "sales", "months", None)])
def test_a_segment_on_a_metric_the_engine_does_not_split_is_unsupported(snippet, claim_type, unit, currency):
    row = run_claim({"claim_type": claim_type, "snippet": snippet, "unit": unit, "currency": currency})
    assert (row["evidence_label"], row["segment"]) == ("Unsupported", "Enterprise") and "not computed by segment" in row["reason"]


@pytest.mark.parametrize("unit, value, claimed_days", [("days", 60, 60), ("weeks", 8, 56), ("week", 1, 7), ("months", 2, 60.88)])
def test_durations_convert_at_7_days_a_week_and_30_44_a_month(unit, value, claimed_days):
    row = run_claim({"claim_type": "sales", "snippet": "Sales cycle", "unit": unit, "currency": None, "value": value})
    assert row["metric"] == "Median sales cycle"
    assert row["gap"] == pytest.approx(58.5 - claimed_days, abs=0.005) and row["claimed_value"] == value
    assert row["unit"] == unit


def test_a_gap_below_half_a_working_week_reads_under_a_working_week():
    row = run_claim({"claim_type": "sales", "snippet": "Sales cycle", "unit": "weeks", "currency": None, "value": 8})
    assert row["gloss"] == "2.5 days longer, under a working week (miss)" and row["evidence_label"] == "Verified"


def test_a_year_is_twelve_months_of_30_44_days():
    row = run_claim({"claim_type": "sales", "snippet": "Sales cycle", "unit": "years", "currency": None, "value": 0.2})
    assert (row["metric"], row["unit"]) == ("Median sales cycle", "years")
    assert row["gap"] == pytest.approx(58.5 - 0.2 * 12 * 30.44, abs=0.005)           # 0.2 years = 73.056 days


def test_a_claim_in_years_for_a_months_metric_is_tested_at_twelve_months_a_year():
    results = copy.deepcopy(results_for(RUNS["A"]))
    results["cac_payback"] = {"default_l": 1, "headline_quarter": "2023-Q3", "source": {"file": "pnl.csv", "sheet": "CSV", "rows": "r", "rule": "x"},
                              "quarters": {"2023-Q3": {"gross_margin_pct": 78.0, "partial": False, "L1": {"months": 12.0, "reason": None}}}}
    row = run_claim({"claim_type": "sales", "snippet": "CAC payback", "unit": "years", "currency": None, "value": 1, "target_date": "2023-Q3"},
                    results=results)
    assert (row["observed_value"], row["gap"], row["evidence_label"], row["gloss"]) == (12.0, 0.0, "Verified", "as claimed")


@pytest.mark.parametrize("unit, snippet, claim_type", [("hours", "Sales cycle", "sales"), (None, "Sales cycle 60", "sales"),
                                                       (None, "ACV 40", "sales"), (None, "ARR 200", "revenue")])
def test_hours_and_claims_with_no_unit_stay_unmatched(unit, snippet, claim_type):
    row = run_claim({"claim_type": claim_type, "snippet": snippet, "unit": unit, "currency": None, "value": 60})
    assert (row["metric"], row["evidence_label"]) == (None, "Unsupported") and "no metric" in row["reason"]


# --- table 2b: periods -------------------------------------------------------------------------------------------------

def test_a_period_before_the_data_or_cut_by_its_start_is_unverified_and_the_reason_names_the_missing_months():
    full = run_claim({"claim_type": "revenue", "snippet": "Revenue €1M", "target_date": "2022"})
    assert (full["evidence_label"], full["observed_value"]) == ("Unverified", None) and "first month, 2023-01" in full["reason"]
    run = RUNS["A"]
    c = {"id": "x1", "status": "approved", "claim_type": "revenue", "value": 1, "currency": "EUR", "snippet": "Revenue",
         "target_date": "2023", "sources": []}
    deck_claims.resolve_period(c, 3)                                   # a March year-end: FY2023 starts April 2022
    row = cm.build_register([c], results_for(run), settings(run, fiscal_year_end=3))[0]
    assert (row["evidence_label"], row["observed_value"]) == ("Unverified", None)
    assert "2022-04 to 2022-12" in row["reason"], "the months the data lacks are named"


def test_a_gap_inside_the_period_names_its_months_too():
    results = copy.deepcopy(results_for(RUNS["A"]))
    series = results["revenue_series"]
    series["data"] = [d for d in series["data"] if d["month"] not in ("2023-05", "2023-06", "2023-09")]
    series["months"] = [d["month"] for d in series["data"]]
    row = run_claim({"claim_type": "revenue", "snippet": "Revenue", "value": 1, "target_date": "2023"}, results=results)
    assert row["evidence_label"] == "Unverified" and "2023-05 to 2023-06, 2023-09" in row["reason"]


def test_a_quarter_metric_needs_one_calendar_quarter_of_the_engine():
    for target in ("2023-H2", "2023", "2023-11"):
        row = run_claim({"claim_type": "gross_margin", "snippet": "Gross margin", "unit": "%", "currency": None,
                         "target_date": target})
        assert (row["evidence_label"], row["observed_value"]) == ("Unsupported", None) and "calendar quarter" in row["reason"], target


def test_with_a_march_year_end_every_fiscal_quarter_is_a_calendar_quarter():
    run = RUNS["C"]
    c = {"id": "x1", "status": "approved", "claim_type": "gross_margin", "value": 78, "unit": "%", "snippet": "Gross margin",
         "target_date": "2024-Q3", "sources": []}
    deck_claims.resolve_period(c, 3)
    row = cm.build_register([c], results_for(run), settings(run))[0]
    assert (row["observed_at"], row["evidence_label"]) == ("2023-Q4", "Verified") and row["period_start"] == "2023-10-01"


def test_an_as_of_metric_is_tested_only_for_a_period_ending_in_the_as_of_month():
    ended = run_claim({"claim_type": "sales", "snippet": "Win rate", "unit": "%", "currency": None, "value": 40, "target_date": "2023-Q4"})
    assert (ended["evidence_label"], ended["observed_value"]) == ("Unsupported", None) and "period" in ended["reason"]
    now = run_claim({"claim_type": "sales", "snippet": "Win rate", "unit": "%", "currency": None, "value": 40, "target_date": "2024-02"})
    assert (now["evidence_label"], now["observed_value"], now["period_note"]) == ("Verified", 40.0, None)


def test_a_figure_with_no_period_is_tested_at_the_as_of_figure_and_marked():
    for metric_text, claim_type, unit, cur in (("ARR", "revenue", None, "EUR"), ("MRR", "revenue", None, "EUR"),
                                               ("NRR", "retention", "%", None), ("Gross revenue churn", "retention", "%", None)):
        row = run_claim({"claim_type": claim_type, "snippet": f"{metric_text} 1", "unit": unit, "currency": cur})
        assert row["period_note"] == "no period stated" and row["observed_at"] == "2024-02", metric_text
    cac = run_claim({"claim_type": "gross_margin", "snippet": "Gross margin", "unit": "%", "currency": None, "value": 78})
    assert (cac["observed_at"], cac["period_note"], cac["observed_value"]) == ("2023-Q4", "no period stated", 78.0)


def test_revenue_is_a_sum_so_with_no_period_it_is_unverified_not_unsupported():
    row = run_claim({"claim_type": "revenue", "snippet": "Revenue €1M"})
    assert (row["evidence_label"], row["observed_value"], row["reason"]) == ("Unverified", None, "no period stated")
    assert row["period_note"] == "no period stated"


def test_a_sum_over_a_period_entirely_in_the_future_has_no_figure_to_date():
    row = run_claim({"claim_type": "revenue", "snippet": "Revenue €9M", "value": 9_000_000, "target_date": "2026"})
    assert (row["evidence_label"], row["observed_value"], row["gap_kind"]) == ("Unverified", None, None)
    assert "forecast" in row["reason"]


def test_a_forecast_of_a_quarter_figure_shows_the_latest_complete_quarter():
    row = run_claim({"claim_type": "gross_margin", "snippet": "Gross margin", "unit": "%", "currency": None, "value": 80,
                     "target_date": "2025-Q2"})
    assert (row["evidence_label"], row["observed_value"], row["observed_at"], row["gap_kind"]) == ("Unverified", 78.0, "2023-Q4", "to go")
    assert row["gloss"] == "2.0 points lower (to go by Jun 2025)"


def test_an_engine_not_computable_reason_is_the_unsupported_reason():
    row = run_claim({"claim_type": "sales", "snippet": "CAC payback", "unit": "months", "currency": None, "value": 12,
                     "target_date": "2023-Q1"})
    assert row["evidence_label"] == "Unsupported" and "no P&L for 2022-Q4" in row["reason"]


def test_a_metric_with_no_result_is_unverified_when_the_engine_names_a_missing_file_else_unsupported():
    results = copy.deepcopy(results_for(RUNS["A"]))
    results["cac_payback"] = None
    results["missing_data"] = [{"metric": "CAC payback", "reason": "P&L not provided",
                                "unlocked_by": "Upload P&L with month, S&M expense, revenue, cost of revenue", "file": "pnl"}]
    row = run_claim({"claim_type": "gross_margin", "snippet": "Gross margin", "unit": "%", "currency": None, "value": 78}, results=results)
    assert row["evidence_label"] == "Unverified" and "Missing: Upload P&L" in row["reason"]
    results["missing_data"] = []
    row = run_claim({"claim_type": "gross_margin", "snippet": "Gross margin", "unit": "%", "currency": None, "value": 78}, results=results)
    assert (row["evidence_label"], row["reason"]) == ("Unsupported", "not computed")


def test_cac_payback_is_tested_at_the_default_lag_and_the_headline_quarter():
    results = copy.deepcopy(results_for(RUNS["A"]))
    results["cac_payback"] = {"default_l": 1, "headline_quarter": "2023-Q3", "partial_quarter_excluded": None,
                              "source": {"file": "pnl.csv", "sheet": "CSV", "rows": "rows 2–15", "rule": "CAC payback"},
                              "quarters": {"2023-Q3": {"gross_margin_pct": 78.0, "partial": False, "L0": {"months": 5.0},
                                                       "L1": {"months": 14.0, "reason": None}},
                                           "2023-Q4": {"gross_margin_pct": 78.0, "partial": False,
                                                       "L1": {"months": None, "reason": "new MRR is zero"}}}}
    stated = run_claim({"claim_type": "sales", "snippet": "CAC payback", "unit": "months", "currency": None, "value": 12,
                        "target_date": "2023-Q3"}, results=results)
    assert (stated["observed_value"], stated["gap"], stated["gap_kind"], stated["evidence_label"]) == (14.0, 2.0, "miss", "Contradicted")
    assert stated["gloss"] == "2.0 months longer (miss)" and stated["direction"] == "lower"
    bare = run_claim({"claim_type": "sales", "snippet": "CAC payback", "unit": "months", "currency": None, "value": 14}, results=results)
    assert (bare["observed_at"], bare["observed_value"], bare["evidence_label"], bare["period_note"]) == ("2023-Q3", 14.0, "Verified", "no period stated")
    weeks = run_claim({"claim_type": "sales", "snippet": "CAC payback", "unit": "weeks", "currency": None, "value": 60,
                       "target_date": "2023-Q3"}, results=results)
    assert weeks["gap"] == pytest.approx(14 - 60 * 7 / 30.44, abs=0.005) and weeks["claimed_value"] == 60


def test_another_currency_is_converted_at_the_audits_fx_rate():
    row = run_claim({"claim_type": "revenue", "snippet": "ARR $210,000", "currency": "USD", "value": 210000, "target_date": "2024-02"},
                    fx={"EUR": 1.0, "USD": 0.9})
    assert row["claimed_value"] == 210000 and row["currency"] == "USD"
    assert row["gap"] == pytest.approx(189000 - 202125.48, abs=0.005) and row["gap_kind"] == "beat"
    assert row["evidence_label"] == "Contradicted" and row["gloss"] == "€13,125 higher (beat)"


# --- section 3 and 4: gap, gloss, tolerance --------------------------------------------------------------------------

@pytest.mark.parametrize("unit, value, gap_text", [
    ("%", 78.0, "as claimed"), ("%", 85, "7.0 points lower (miss)"), ("%", 77.5, "0.5 points higher (beat)")])
def test_percent_gloss(unit, value, gap_text):
    row = run_claim({"claim_type": "gross_margin", "snippet": "Gross margin", "unit": unit, "currency": None, "value": value,
                     "target_date": "2023-Q4"})
    assert row["gloss"] == gap_text


def test_tolerance_is_five_percent_of_the_claim_or_one_point_and_the_boundary_is_verified():
    assert cm.within_tolerance("ARR", 212700 - 202125.48, 212700) is True
    assert cm.within_tolerance("ARR", 213000 - 202125.48, 213000) is False
    assert cm.within_tolerance("Win rate", 1.0, 41) is True and cm.within_tolerance("Win rate", 1.01, 41) is False
    assert cm.within_tolerance("Win rate", -1.0, 39) is True
    assert cm.tolerance_text("Win rate") == "±1 pp" and cm.tolerance_text("ARR") == "±5%"


def test_a_range_is_tested_at_the_end_nearest_the_observed_value():
    base = {"claim_type": "revenue", "snippet": "ARR", "target_date": "2024-02"}
    outside_high = run_claim({**base, "value": 150000, "value_high": 180000})
    assert outside_high["gap"] == pytest.approx(180000 - 202125.48, abs=0.005) and outside_high["evidence_label"] == "Contradicted"
    outside_low = run_claim({**base, "value": 210000, "value_high": 230000})
    assert outside_low["gap"] == pytest.approx(210000 - 202125.48, abs=0.005) and outside_low["evidence_label"] == "Verified"
    inside = run_claim({**base, "value": 190000, "value_high": 210000})
    assert (inside["gap"], inside["gap_normalised"], inside["gap_kind"], inside["claimed_high"]) == (0.0, 0.0, None, 210000)


def test_a_range_on_a_lower_is_better_metric_uses_the_same_nearest_end():
    row = run_claim({"claim_type": "sales", "snippet": "Sales cycle", "unit": "days", "currency": None, "value": 30, "value_high": 50})
    assert row["gap"] == pytest.approx(8.5) and row["gap_kind"] == "miss"


def test_a_zero_claim_has_no_normalised_gap():
    row = run_claim({"claim_type": "retention", "snippet": "Gross churn", "unit": "%", "currency": None, "value": 0, "target_date": "2024-02"})
    assert row["gap"] == 0.0 and row["gap_normalised"] is None and row["evidence_label"] == "Verified"


@pytest.mark.parametrize("gap, gloss", [
    (4.0, "4.0 days longer, one working week (miss)"), (3.5, "3.5 days longer, one working week (miss)"),
    (3.4, "3.4 days longer, under a working week (miss)"), (13.5, "13.5 days longer, two working weeks (miss)"),
    (150.0, "150.0 days longer, 21 working weeks (miss)")])
def test_the_days_gloss_names_the_working_weeks_rounded(gap, gloss):
    assert cm.gloss("days", "miss", gap, None, None, None) == gloss


def test_one_gloss_rule_for_every_metric_direction_in_plain_words_kind_in_brackets():
    g = cm.gloss
    # the direction is the observed figure against the claimed one, whichever way the metric is better
    assert g("days", "beat", -1.5, None, "lower", None) == "1.5 days shorter (beat)"
    assert g("days", "miss", 7.0, None, "lower", None) == "7.0 days longer, one working week (miss)"
    assert g("months", "miss", 3.0, None, "lower", None) == "3.0 months longer (miss)"
    assert g("months", "beat", -3.0, None, "lower", None) == "3.0 months shorter (beat)"
    assert g("%", "miss", 3.0, None, "higher", None) == "3.0 points lower (miss)"
    assert g("%", "miss", 3.0, None, "lower", None) == "3.0 points higher (miss)"
    assert g("%", "beat", -5.0, None, "higher", None) == "5.0 points higher (beat)"
    assert g("%", "beat", -0.68, None, "higher", None) == "0.7 points higher (beat)"
    assert g("%", "beat", -5.0, None, "lower", None) == "5.0 points lower (beat)"
    assert g("%", "to go", 17.0, None, "higher", "Dec 2026") == "17.0 points lower (to go by Dec 2026)"
    assert g("currency", "miss", 41857.32, "EUR", "higher", None) == "€41,857 lower (miss)"
    assert g("currency", "beat", -2125.48, "EUR", "higher", None) == "€2,125 higher (beat)"
    assert g("currency", "to go", 4797874.52, "EUR", "higher", "Dec 2026") == "€4.8M lower (to go by Dec 2026)"
    assert g("currency", "miss", 1500.0, "USD", "higher", None) == "$1,500 lower (miss)"
    assert g("currency", "miss", 1500.0, "CHF", "higher", None) == "CHF 1,500 lower (miss)"
    assert g("count", "miss", 1.0, None, "higher", None) == "1 customer fewer (miss)"
    assert g("count", "miss", 3.0, None, "higher", None) == "3 customers fewer (miss)"
    assert g("count", "beat", -1.0, None, "higher", None) == "1 customer more (beat)"
    assert g("count", "to go", 3.0, None, "higher", "Dec 2026") == "3 customers fewer (to go by Dec 2026)"
    # a to-go is claimed - observed: negative, the observed figure is above the claim
    assert g("days", "to go", -13.5, None, "lower", "Dec 2026") == "13.5 days longer, two working weeks (to go by Dec 2026)"
    assert g("days", "to go", 13.5, None, "lower", "Dec 2026") == "13.5 days shorter (to go by Dec 2026)"


@pytest.mark.parametrize("unit, kind, direction", [("days", "miss", "lower"), ("%", "beat", "higher"), ("currency", "to go", "higher"),
                                                   ("count", "miss", "higher"), ("months", "beat", "lower")])
def test_a_gap_of_zero_is_as_claimed_in_every_unit(unit, kind, direction):
    assert cm.gloss(unit, kind, 0.0, "EUR", direction, "Dec 2026") == "as claimed"


def test_a_deck_reading_that_is_an_ai_suggestion_stays_unverified_until_the_analyst_edits_the_claim():
    base = {"claim_type": "retention", "snippet": "NRR", "unit": "%", "currency": None, "value": 112, "target_date": "2024-02",
            "origin": "ai", "ai_status": "unverified", "ai_label": "AI suggestion, not verified"}
    row = run_claim(base)
    assert (row["evidence_label"], row["deck_reading"], row["observed_value"]) == ("Unverified", "AI suggestion, not verified", 112.68)
    edited = run_claim({**base, "status": "edited", "ai_status": None, "ai_label": None, "parsed": {"value": 112}})
    assert (edited["evidence_label"], edited["deck_reading"], edited["status"]) == ("Verified", "edited", "edited")
    unchanged = run_claim({**base, "status": "edited", "ai_status": None, "ai_label": None, "parsed": {"value": 112}})
    assert unchanged["evidence_label"] == "Verified", "an edit clears the label even when the value is unchanged"
    verified = run_claim({**base, "ai_status": "verified", "ai_label": "Verified"})
    assert (verified["evidence_label"], verified["deck_reading"]) == ("Verified", "Verified")
    parser = run_claim({k: v for k, v in base.items() if k not in ("origin", "ai_status", "ai_label")})
    assert parser["deck_reading"] == "parser"


def test_an_ai_suggestion_with_no_figure_keeps_its_unsupported_reason():
    row = run_claim({"claim_type": "market", "snippet": "TAM", "value": 5, "origin": "ai", "ai_status": "unverified",
                     "ai_label": "AI suggestion, not verified"})
    assert (row["evidence_label"], row["deck_reading"]) == ("Unsupported", "AI suggestion, not verified")


# --- section 5: gate -----------------------------------------------------------------------------------------------------

def test_the_app_proposes_no_gate_date(as_of=None):
    """verdict-and-memo.md section 3: the date starts empty, so the default of claim-matching section 5 is gone."""
    assert not hasattr(cm, "gate_date")
    assert all(r["gate_date"] is None for r in register(RUNS["A"]))


def test_no_gate_is_proposed_a_row_has_no_sentence_and_no_default_threshold_until_the_analyst_fills_it():
    rows = register(RUNS["A"])
    assert all(r["gate_sentence"] is None and r["gate_threshold"] is None and r["gate_saved"] is False for r in rows)
    row = row_of(rows, "c01")
    assert (row["gate_threshold"], row["gate_budget_decision"], row["gate_date"], row["gate_saved"]) == (None, None, None, False)
    assert row["claimed_value"] == 200000 and row["observed_value"] == 202125.48, "claimed and observed sit beside the empty field"


def test_the_analysts_gate_is_saved_only_when_threshold_and_budget_decision_are_filled():
    inputs = {"gate_threshold": 195000.0, "gate_budget_decision": "the Series B hiring plan", "gate_date": "2024-06-30"}
    base = {"claim_type": "revenue", "snippet": "ARR", "value": 200000, "target_date": "2024-02", "period_text": "Feb 2024"}
    full = run_claim({**base, "claim_inputs": {"x1": inputs}})
    assert (full["gate_saved"], full["gate_threshold"], full["gate_date"]) == (True, 195000.0, "2024-06-30")
    assert full["gate_sentence"] == ("Before the Series B hiring plan, ARR must be at least €195,000 by 2024-06-30. "
                                     "Observed €202,125 (2024-02); claimed €200,000 (Feb 2024).")
    for missing in ("gate_threshold", "gate_budget_decision", "gate_date"):
        half = run_claim({**base, "claim_inputs": {"x1": {k: v for k, v in inputs.items() if k != missing}}})
        assert half["gate_saved"] is False and half["gate_sentence"] is None, missing
    assert run_claim(base)["gate_saved"] is False


def test_a_saved_gate_on_a_lower_is_better_metric_says_at_most_and_a_forecast_row_can_carry_one():
    sales = run_claim({"claim_type": "sales", "snippet": "Sales cycle", "unit": "days", "currency": None, "value": 45,
                       "claim_inputs": {"x1": {"gate_threshold": 50, "gate_budget_decision": "the SDR hires",
                                                                      "gate_date": "2024-03-31"}}})
    assert sales["gate_sentence"] == ("Before the SDR hires, Median sales cycle must be at most 50.0 days by 2024-03-31. "
                                      "Observed 58.5 days (2024-02); claimed 45.0 days (no period stated).")
    forecast = run_claim({"claim_type": "revenue", "snippet": "ARR", "value": 5_000_000, "target_date": "2026",
                          "claim_inputs": {"x1": {"gate_threshold": 1_000_000, "gate_budget_decision": "the plan",
                                                                     "gate_date": "2024-03-31"}}})
    assert forecast["gate_sentence"].startswith("Before the plan, ARR must be at least €1,000,000 by 2024-03-31. Observed €202,125 (2024-02)")


# --- section 6: the register's fields ----------------------------------------------------------------------------

def test_a_register_row_has_exactly_the_fields_of_section_6_and_the_verdict_spec_in_order():
    section_6 = ("claim_id deck_file page_ref claim_type status deck_reading claimed_value claimed_high claim_direction unit "
                 "currency claimed_converted claimed_converted_high fx_rate fx_date period "
                 "period_start period_end period_note segment segment_set_by metric metric_set_by direction observed_value "
                 "observed_at observed_source gap gap_normalised gap_kind gloss evidence_label reason tolerance rank "
                 "value_at_stake_arr shortfall overlaps_with evidence_analysis evidence_source_key gate_sentence gate_threshold "
                 "gate_budget_decision gate_date gate_saved gate_metric_name gate_direction key_gate gate_needed as_of_month "
                 "as_of_defaulted turnover_state turnover_note turnover_set_by turnover_reason implied_take_rate "
                 "implied_take_rate_source").split()
    assert list(register(RUNS["A"])[0]) == section_6 == list(cm.FIELDS)


def test_a_register_row_carries_the_claim_the_source_and_the_as_of_month_not_the_deck_text():
    rows = register(RUNS["A"])
    row = row_of(rows, "c01")
    assert (row["deck_file"], row["claim_type"], row["status"], row["deck_reading"]) == ("testco_board.pptx", "revenue", "approved", "parser")
    assert (row["claimed_value"], row["claimed_high"], row["currency"], row["period"], row["period_start"], row["period_end"]) == (
        200000, None, "EUR", "Feb 2024", "2024-02-01", "2024-02-29")
    assert (row["segment"], row["segment_set_by"], row["metric_set_by"], row["direction"]) == ("Whole company", "python", "python", "higher")
    assert row["observed_source"] == {"file": "revenue.csv", "sheet": "CSV", "rows": row["observed_source"]["rows"],
                                      "rule": "ARR = current-month recurring MRR × 12"}
    assert row["observed_source"]["rows"].startswith("rows 2")
    assert (row["as_of_month"], row["as_of_defaulted"], row["value_at_stake_arr"]) == ("2024-02", True, None)
    assert row_of(rows, "c19#2")["page_ref"] == "slide 7" and row_of(rows, "c19#2")["period"] == "Y/E 23"
    assert run_claim({"sources": [{"slide": 4}, {"slide": 9}, {"page": 12}]})["page_ref"] == "slide 4, slide 9, p12"


def test_the_as_of_month_set_on_the_audit_is_not_defaulted():
    run = RUNS["A"]
    row = cm.build_register(candidates_for(run), results_for(run), settings(run, as_of_month="2024-02"))[0]
    assert row["as_of_defaulted"] is False


def test_no_deck_text_reaches_a_register_row():
    run = RUNS["A"]
    sentinel = "DECKTEXT Jane Doe"
    cands = candidates_for(run)
    for c in cands:
        c["snippet"] = f"{c['snippet']} {sentinel}"
        c["label_from"] = sentinel
        c["date_from"] = sentinel
        c["sources"] = [{**s, "text": sentinel} for s in c["sources"]]
    rows = cm.build_register(cands, results_for(run), settings(run))
    assert sentinel not in repr(rows) and "snippet" not in rows[0] and "label_from" not in rows[0]


def test_the_matching_does_not_change_the_candidates_or_the_results():
    run = RUNS["A"]
    cands, results = candidates_for(run), copy.deepcopy(results_for(run))
    before = copy.deepcopy(cands)
    cm.build_register(cands, results, settings(run))
    assert cands == before and results == results_for(run)


def test_no_results_gives_an_empty_register():
    assert cm.build_register(candidates_for(RUNS["A"]), None, settings(RUNS["A"])) == []


# --- verdict-and-memo.md section 2: value at stake, overlaps, evidence ------------------------------------------------------------------

def test_value_at_stake_is_never_estimated_and_the_shortfall_is_the_normalised_gap_of_a_miss_only():
    rows = register(RUNS["A"])
    assert all(r["value_at_stake_arr"] is None for r in rows)
    for r in rows:
        assert r["shortfall"] == (r["gap_normalised"] if r["gap_kind"] == "miss" else None), r["claim_id"]
    assert row_of(rows, "c06")["shortfall"] == 0.3 and row_of(rows, "c01")["shortfall"] is None     # a beat has none
    assert row_of(rows, "c09")["shortfall"] is None, "a forecast's gap is to go, not a miss"


def test_two_rows_overlap_on_the_same_metric_or_arr_and_mrr_a_shared_segment_and_a_shared_month():
    rows = register(RUNS["A"])
    arr_feb = {r["claim_id"] for r in rows if r["metric"] == "ARR" and r["observed_at"] == "2024-02" and r["segment"] == cm.WHOLE}
    assert {"c01", "c23", "c24", "c21", "c25", "c09"} <= arr_feb
    for claim_id in arr_feb:
        assert set(row_of(rows, claim_id)["overlaps_with"]) == arr_feb - {claim_id}, claim_id
    assert row_of(rows, "c05")["overlaps_with"] == ["c19#2"], "ARR Dec 2023 against the table row's Y/E 23 value"
    assert "c02" in row_of(rows, "c06")["overlaps_with"], "Whole company overlaps Enterprise"


def test_overlap_is_symmetric_and_a_row_with_no_observed_figure_overlaps_nothing():
    rows = register(RUNS["A"])
    by_id = {r["claim_id"]: r for r in rows}
    for r in rows:
        for other in r["overlaps_with"]:
            assert r["claim_id"] in by_id[other]["overlaps_with"], (r["claim_id"], other)
        if r["observed_value"] is None:
            assert r["overlaps_with"] == [], r["claim_id"]
    assert row_of(rows, "c14")["overlaps_with"] == []


def test_overlap_needs_the_same_metric_a_shared_month_and_compatible_segments():
    run = RUNS["A"]
    base = {"claim_type": "revenue", "snippet": "ARR", "value": 200000, "target_date": "2024-02", "period_text": "Feb 2024"}

    def pair(second, **extra):
        a = {**base, "id": "a", "status": "approved", "claim_type": "revenue", "currency": "EUR", "file": "d.pptx", "order": 0,
             "sources": [{"file": "d.pptx", "slide": 1}], "unit": None, "value_high": None, "label_from": None}
        b = {**a, **second, "id": "b", "order": 1}
        for c in (a, b):
            deck_claims.resolve_period(c, run["fiscal_year_end"])
        return {r["claim_id"]: r for r in cm.build_register([a, b], results_for(run), settings(run))}

    assert pair({})["a"]["overlaps_with"] == ["b"]
    assert pair({"snippet": "MRR", "value": 17000})["a"]["overlaps_with"] == ["b"], "ARR is MRR x 12"
    assert pair({"snippet": "Revenue", "value": 17000, "target_date": "2024-02"})["a"]["overlaps_with"] == [], "revenue is another metric"
    assert pair({"target_date": "2023-12", "period_text": "Dec 2023"})["a"]["overlaps_with"] == [], "no shared month"
    assert pair({"snippet": "ARR Enterprise"})["a"]["overlaps_with"] == ["b"], "Whole company overlaps a segment"


def test_every_row_with_a_figure_names_its_analysis_and_the_source_key_it_was_read_from():
    rows = register(RUNS["A"])
    expected = {
        "c01": ("Monthly MRR by Segment", "mrr_series.data.total"), "c02": ("Sales cycle", "sales_cycle.by_segment.Enterprise.median_days"),
        "c03": ("Win rate", "win_rate.win_rate_pct"), "c04": ("NRR", "nrr.series.nrr_pct"),
        "c07": ("CAC Payback by Quarter", "cac_payback.quarters.2023-Q4.gross_margin_pct"),
        "c08": ("Customers", "customers_series.data.total"), "c27": ("Revenue by month", "revenue_series.data.total"),
    }
    for claim_id, (analysis, key) in expected.items():
        r = row_of(rows, claim_id)
        assert (r["evidence_analysis"], r["evidence_source_key"]) == (analysis, key), claim_id
        assert r["observed_source"] and r["observed_at"], "the hover shows file, sheet, rows and rule"
    d = register(RUNS["D"])
    keys = {r["metric"]: r["evidence_source_key"] for r in d if r["evidence_source_key"] and not r["evidence_source_key"] == "missing_data"
            and r["segment"] == cm.WHOLE}
    assert keys["New MRR"].startswith("new_mrr_by_quarter.") and keys["New MRR"].endswith(".new_mrr")
    assert keys["Gross revenue churn"] == "gross_churn.series.churn_pct" and keys["ACV"] == "acv_path.acv"
    assert keys["MRR"] == "mrr_series.data.total"
    segment = [r for r in d if r["segment"] != cm.WHOLE and r["evidence_source_key"]]
    assert segment and all(r["segment"] in r["evidence_source_key"] for r in segment)


def test_a_missing_reason_names_the_missing_data_item_and_a_row_with_no_figure_names_nothing():
    rows = register(RUNS["B"])
    missing = [r for r in rows if r["reason"].startswith("Missing:")]
    assert missing
    for r in missing:
        assert r["evidence_source_key"] == "missing_data" and r["evidence_analysis"] == "Sales cycle & win rate"
    none = [r for r in register(RUNS["A"]) if r["observed_value"] is None and not r["reason"].startswith("Missing:")]
    assert none and all(r["evidence_analysis"] is None and r["evidence_source_key"] is None for r in none)


# --- 2026-10-08: both figures of a claim in another currency, and a direction with no figure -----------------------------

def test_a_claim_in_another_currency_is_converted_at_the_saved_rate_and_shows_both_figures():
    row = run_claim({"claim_type": "revenue", "snippet": "ARR £150,000", "currency": "GBP", "value": 150000, "value_high": 160000,
                     "target_date": "2024-02"}, fx={"EUR": 1.0, "GBP": 1.14})
    assert (row["claimed_value"], row["currency"], row["fx_rate"], row["fx_date"]) == (150000, "GBP", 1.14, "2024-02-29")
    assert (row["claimed_converted"], row["claimed_converted_high"]) == (pytest.approx(171000), pytest.approx(182400))
    assert row["claimed_converted"] / row["claimed_value"] == row["fx_rate"], "matched at the converted figure"
    assert row["evidence_label"] in ("Verified", "Contradicted") and row["observed_value"] is not None
    same = run_claim({"claim_type": "revenue", "snippet": "ARR €150,000", "currency": "EUR", "value": 150000,
                      "target_date": "2024-02"})
    assert (same["claimed_converted"], same["fx_rate"], same["fx_date"]) == (None, None, None), "the audit's currency"


@pytest.mark.parametrize("period", ["2024-02", "2026", None])
def test_a_claim_with_no_saved_rate_is_unverified_with_fx_rate_needed_whatever_its_period(period):
    row = run_claim({"claim_type": "revenue", "snippet": "ARR $210,000", "currency": "USD", "value": 210000,
                     "target_date": period})
    assert (row["evidence_label"], row["reason"]) == ("Unverified", "FX rate needed: USD→EUR")
    assert (row["fx_rate"], row["claimed_converted"], row["observed_value"]) == (None, None, None)


def test_a_direction_with_no_figure_is_unverified_and_never_verified_or_contradicted():
    for direction in ("positive", "negative"):
        row = run_claim({"claim_type": "ebitda", "snippet": f"{direction.title()} EBITDA", "currency": None, "value": None,
                         "claim_direction": direction, "target_date": "2024-02"})
        assert (row["evidence_label"], row["claim_direction"], row["claimed_value"]) == ("Unverified", direction, None)
        assert "no figure" in row["reason"]
    # Even where a metric exists for the type, a direction is not tested against a figure.
    row = run_claim({"claim_type": "revenue", "snippet": "Positive ARR", "currency": None, "value": None,
                     "claim_direction": "positive", "target_date": "2024-02"})
    assert row["evidence_label"] == "Unverified" and row["observed_value"] is None
    # A figure typed over it ends the direction: it is tested like any claim.
    typed = run_claim({"claim_type": "revenue", "snippet": "ARR", "currency": "EUR", "value": 200000,
                       "claim_direction": "positive", "target_date": "2024-02"})
    assert typed["claim_direction"] is None and typed["evidence_label"] == "Verified"
