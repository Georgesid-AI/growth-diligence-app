"""Annual payback with an explicit basis (docs/specs/forecast-and-payback.md section 4; design note section 5).

The acceptance table of the design note, for this scope: matching and mismatching payback definitions, the net-new-ARR and revenue proxies,
missing years or costs, an invalid denominator, and correctly scoped data requests. Fixture company: synthetic figures.
"""
import copy

import pytest

import growth_engine as ge
from forecast_support import arr_series, payback_claim, payback_results, row_of, yearly_input

from app import claim_matching as cm
from app import payback_definition as pd_
from app import verdict as vd
from schemas import metrics

BASIS = "yearly basis, not monthly"
MATCHING_REVENUE = "CAC payback 24 months in FY2024: sales and marketing spend over revenue growth, gross margin adjusted"
MATCHING_ARR = "CAC payback 16 months in FY2024: sales and marketing spend over net new ARR, gross margin adjusted"


def years(block):
    return {y["period"]: y for y in block["years"]}


def block(yearly=None, mrr=None):
    return payback_results(yearly, mrr)["yearly_basis"]


# --- 1. the engine: two named proxies ------------------------------------------------------------------------------------------------

def test_both_proxies_are_calculated_and_named_with_their_denominators():
    y = years(block())["FY2024"]
    assert y["new_revenue"] == 240_000 and y["cac_payback_months"] == 24.0, "12 x 336,000 / (240,000 x 0.70): the revenue-growth proxy"
    assert (y["arr_prior_year_end"], y["arr_year_end"], y["net_new_arr"]) == (1_080_000, 1_440_000, 360_000)
    assert y["cac_payback_net_new_arr_months"] == 16.0, "12 x 336,000 / (360,000 x 0.70): the net-new-ARR proxy"
    assert y["cac_payback_net_new_arr_reason"] is None and y["cac_payback_reason"] is None
    assert (y["period_start"], y["period_end"], y["sm_expense"], y["sm_scope"]) == ("2024-01", "2024-12", 336_000, "sales and marketing")
    assert y["basis"] == BASIS
    assert "net new ARR" in y["source"]["rule"] and "revenue growth" in y["source"]["rule"] and "gross margin" in y["source"]["rule"]


def test_the_proxies_are_independent_of_each_other():
    y = years(block())["FY2023"]
    assert y["cac_payback_months"] == round(12 * 300_000 / (200_000 * 0.7), 2) == 25.71
    assert y["cac_payback_net_new_arr_months"] == round(12 * 300_000 / (240_000 * 0.7), 2) == 21.43


def test_the_block_validates_against_the_contract_and_the_contract_moves_to_10():
    found = metrics.YearlyBasis.model_validate(block())
    assert found.years[-1].net_new_arr == 360_000
    assert metrics.CONTRACT_VERSION == 15, "15 added the file map (no engine block); 14 added the pnl_lines block and cac_payback_label; 13 added revenue_cells to the yearly-basis years (deck-actuals.md); 12 moved for the one as-of month; the optional fields of section 4.5 came earlier"


def test_a_marketing_only_line_is_calculated_and_named_never_total_sm():
    y = years(block(yearly_input("marketing only")))["FY2024"]
    assert y["sm_scope"] == "marketing only" and y["cac_payback_months"] == 24.0
    assert "marketing only" in y["source"]["rule"], "the figure's own citation names the scope of its numerator"


# --- 2. missing years or costs, an invalid denominator --------------------------------------------------------------------------------

def test_a_year_with_no_prior_year_has_a_reason_for_each_proxy():
    y = years(block())["FY2022"]
    assert y["cac_payback_months"] is None and y["cac_payback_reason"] == "no revenue for the year before"
    assert y["cac_payback_net_new_arr_months"] is None and y["cac_payback_net_new_arr_reason"] == "no ARR for the year-end before"


def test_no_s_and_m_line_gives_no_proxy_and_the_reason():
    y = years(block(yearly_input(sm=(250_000, 300_000, None))))["FY2024"]
    assert (y["cac_payback_months"], y["cac_payback_reason"]) == (None, "no S&M line")
    assert (y["cac_payback_net_new_arr_months"], y["cac_payback_net_new_arr_reason"]) == (None, "no S&M line")
    assert y["sm_expense"] is None and y["sm_scope"] is None


@pytest.mark.parametrize("sm", [0, -5_000])
def test_s_and_m_that_is_not_positive_gives_no_proxy(sm):
    y = years(block(yearly_input(sm=(250_000, 300_000, sm))))["FY2024"]
    assert y["cac_payback_months"] is None and y["cac_payback_reason"] == "S&M not positive"
    assert y["cac_payback_net_new_arr_reason"] == "S&M not positive"


def test_no_arr_series_leaves_the_revenue_proxy_and_names_what_is_missing():
    y = years(block(mrr={"months": [], "segments": [], "data": [], "source": {}}))["FY2024"]
    assert y["cac_payback_months"] == 24.0
    assert y["cac_payback_net_new_arr_months"] is None and y["cac_payback_net_new_arr_reason"] == "no ARR series (revenue file)"
    assert y["arr_year_end"] is None and y["net_new_arr"] is None


def test_a_net_new_arr_that_is_not_positive_is_an_invalid_denominator_with_its_reason():
    y = years(block(mrr=arr_series((70_000, 90_000, 80_000))))["FY2024"]
    assert y["net_new_arr"] == -120_000
    assert (y["cac_payback_net_new_arr_months"], y["cac_payback_net_new_arr_reason"]) == (None, "net new ARR not positive")
    assert y["cac_payback_months"] == 24.0, "the other proxy is unaffected"


def test_a_revenue_growth_that_is_not_positive_is_an_invalid_denominator_with_its_reason():
    y = years(block(yearly_input(revenue=(1_000_000, 1_200_000, 1_100_000))))["FY2024"]
    assert (y["cac_payback_months"], y["cac_payback_reason"]) == (None, "new revenue not positive")
    margin = (1_100_000 - 432_000) / 1_100_000
    assert y["cac_payback_net_new_arr_months"] == pytest.approx(12 * 336_000 / (360_000 * margin), abs=0.01), "the other proxy is unaffected"


def test_a_gross_margin_that_is_not_positive_gives_no_proxy():
    y = years(block(yearly_input(cost=(300_000, 360_000, 1_440_000))))["FY2024"]
    assert y["cac_payback_reason"] == "gross margin not positive or missing"
    assert y["cac_payback_net_new_arr_reason"] == "gross margin not positive or missing"


def test_the_monthly_timing_request_is_named_apart_in_the_blocks_missing_list():
    missing = block()["missing"]
    assert [m["metric"] for m in missing if m["metric"].startswith("CAC payback")] == ["CAC payback (monthly timing)"]


# --- 3. the numerator's scope --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("labels, scope", [
    (["Sales and marketing"], "sales and marketing"), (["S&M"], "sales and marketing"), (["Sales & marketing expenses"], "sales and marketing"),
    (["Sales", "Marketing"], "sales and marketing"), (["Marketing"], "marketing only"), (["Advertising"], "marketing only"),
    (["Marketing expenses"], "marketing only"), (["Sales expenses"], "sales only"), (["Sales costs"], "sales only"),
    (["Commercial costs"], "unknown"), ([], "unknown"),
])
def test_the_scope_of_an_s_and_m_line_is_read_from_its_labels(labels, scope):
    from app.structures import sheet as sh
    assert sh.sm_scope(labels) == scope


def test_a_bare_sales_line_in_a_cost_section_is_total_s_and_m_as_the_statement_rules_read_it():
    from app.structures import sheet as sh
    assert sh.sm_scope(["Sales"]) == "sales and marketing", "chat-upload.md section 26 rule 4: Sales alone in a cost section is S&M"


# --- 4. the claim's definition -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("12 x sales and marketing over net new ARR at gross margin", {"denominator": "net new ARR", "margin": "gross margin", "cost": "sales and marketing"}),
    ("S&M spend over revenue growth, gross-margin adjusted", {"denominator": "revenue growth", "margin": "gross margin", "cost": "sales and marketing"}),
    ("marketing spend only over net-new ARR, margin adjusted", {"denominator": "net new ARR", "margin": "gross margin", "cost": "marketing only"}),
    ("CAC payback of 18 months", {"denominator": None, "margin": None, "cost": None}),
    ("payback on new ARR", {"denominator": "gross new ARR", "margin": None, "cost": None}),
    ("revenue-based payback, unadjusted, fully loaded", {"denominator": None, "margin": "none", "cost": None}),
    ("blended CAC payback on net new ARR", {"denominator": "net new ARR", "margin": None, "cost": None}),
])
def test_the_definition_is_read_from_the_claims_own_words_and_unstated_is_unknown(text, expected):
    assert pd_.claimed_definition(text) == expected


def test_a_part_the_claim_does_not_state_is_never_assumed_equal():
    proxy = {"denominators": ("net new ARR", "revenue growth"), "margin": "gross margin", "cost": "sales and marketing"}
    assert pd_.compare(pd_.claimed_definition("12 x S&M over net new ARR at gross margin"), proxy) is None
    for text in ("S&M over net new ARR", "over net new ARR at gross margin", "S&M at gross margin", "payback"):
        assert pd_.compare(pd_.claimed_definition(text), proxy).startswith("definition not compared: "), text


def test_fully_loaded_and_blended_are_no_cost_basis_so_such_a_claim_is_not_compared():
    proxy = {"denominators": ("net new ARR", "revenue growth"), "margin": "gross margin", "cost": "sales and marketing"}
    for text in ("fully loaded CAC payback over net new ARR at gross margin", "blended CAC payback over net new ARR at gross margin"):
        got = pd_.compare(pd_.claimed_definition(text), proxy)
        assert got is not None and got.startswith("definition not compared: ") and "cost basis" in got, text


# --- 5. the claim against the annual figures -----------------------------------------------------------------------------------------

def test_a_matching_definition_is_tested_against_the_matching_proxy_as_any_claim():
    row = row_of(payback_claim(MATCHING_REVENUE, 24), results=payback_results())
    assert (row["metric"], row["evidence_label"], row["observed_value"], row["observed_at"]) == ("CAC payback", "Verified", 24.0, "FY2024 (annual)")
    assert row["evidence_analysis"] == "Yearly basis (P&L summary)" and row["evidence_source_key"] == "yearly_basis.years.cac_payback_months"
    assert row["observed_source"]["file"] == "pnl.xlsx" and row["observed_citation"]
    row = row_of(payback_claim(MATCHING_ARR, 16), results=payback_results())
    assert (row["evidence_label"], row["observed_value"], row["evidence_source_key"]) == ("Verified", 16.0, "yearly_basis.years.cac_payback_net_new_arr_months")


def test_a_matching_definition_that_misses_is_contradicted_by_the_ordinary_rules():
    row = row_of(payback_claim(MATCHING_ARR, 12), results=payback_results())
    assert (row["evidence_label"], row["observed_value"], row["gap_kind"]) == ("Contradicted", 16.0, "miss")


def test_the_two_proxies_are_listed_for_the_claim_in_its_calculation_lines():
    row = row_of(payback_claim(MATCHING_ARR, 16), results=payback_results())
    text = " | ".join(row["calc_lines"])
    assert "CAC payback FY2024: 24 months (yearly, revenue-based) =" in text and "Annual payback FY2024 (net-new-ARR proxy): 16 months" in text
    assert "S&M scope: sales and marketing" in text and "Claim definition: net new ARR, gross margin, sales and marketing" in text
    assert all("; " not in line for line in row["calc_lines"] + row["calc_details"])
    assert any("12 × S&M" in d for d in row["calc_details"])


@pytest.mark.parametrize("text, reason", [
    ("CAC payback 16 months in FY2024", "definition not compared: the claim does not state its denominator, gross margin treatment, cost basis"),
    ("CAC payback 16 months in FY2024, sales and marketing over net new ARR",
     "definition not compared: the claim does not state its gross margin treatment"),
    ("CAC payback 16 months in FY2024, net new ARR at gross margin", "definition not compared: the claim does not state its cost basis"),
    ("CAC payback 16 months in FY2024, sales and marketing at gross margin", "definition not compared: the claim does not state its denominator"),
    ("CAC payback 16 months in FY2024, sales and marketing over gross new ARR at gross margin",
     "definition not compared: the claim uses gross new ARR; the annual calculation offers net new ARR and revenue growth"),
    ("CAC payback 16 months in FY2024, marketing spend over net new ARR at gross margin",
     "definition not compared: the claim states marketing only; the S&M line holds sales and marketing"),
    ("CAC payback 16 months in FY2024, sales and marketing over net new ARR, revenue-based unadjusted",
     "definition not compared: the claim is not gross margin adjusted; the annual calculation is"),
])
def test_a_claim_whose_definition_differs_or_is_not_stated_is_not_compared_with_any_figure(text, reason):
    row = row_of(payback_claim(text, 16), results=payback_results())
    assert row["evidence_label"] == "Unverified" and row["reason"] == reason
    assert row["observed_value"] is None and row["gap"] is None, "no differently defined figure is put against the claim"
    assert row["calc_lines"], "both annual figures are still listed"


def test_a_marketing_only_ledger_is_not_compared_with_a_total_s_and_m_claim_and_the_reverse_matches():
    results = payback_results(yearly_input("marketing only"))
    row = row_of(payback_claim(MATCHING_ARR, 16), results=results)
    assert row["reason"] == "definition not compared: the claim states sales and marketing; the S&M line holds marketing only"
    claim = "CAC payback 16 months in FY2024: marketing spend over net new ARR, gross margin adjusted"
    assert row_of(payback_claim(claim, 16), results=results)["evidence_label"] == "Verified"


def test_a_line_of_unknown_scope_is_never_assumed_to_be_total_s_and_m():
    row = row_of(payback_claim(MATCHING_ARR, 16), results=payback_results(yearly_input("unknown")))
    assert row["evidence_label"] == "Unverified" and row["reason"] == "definition not compared: the scope of the S&M line is not known"


def test_the_period_must_be_the_fiscal_year_of_the_annual_figure():
    row = row_of(payback_claim(MATCHING_REVENUE, 24, 2023), results=payback_results())
    assert row["observed_value"] == 25.71 and row["observed_at"] == "FY2023 (annual)", "each claim reads its own year"
    row = row_of(payback_claim(MATCHING_REVENUE, 24, 2025), results=payback_results())
    assert row["evidence_label"] == "Unverified" and row["observed_value"] is None


def test_a_year_with_no_value_for_the_matching_proxy_says_why_and_never_falls_back_to_the_other():
    results = payback_results(mrr=arr_series((70_000, 90_000, 80_000)))
    row = row_of(payback_claim(MATCHING_ARR, 16), results=results)
    assert row["evidence_label"] == "Unverified" and row["reason"] == "annual payback not calculated for FY2024: net new ARR not positive"
    assert row["observed_value"] is None
    assert "CAC payback FY2024: 24 months (yearly, revenue-based) =" in " | ".join(row["calc_lines"])


def test_a_calendar_quarter_claim_keeps_the_monthly_path():
    c = payback_claim("CAC payback 12 months in Q4 2024", 12)
    c["target_date"], c["period_text"] = "2024-Q4", "Q4 2024"
    from app.decks import claims as deck_claims
    deck_claims.resolve_period(c, 12)
    row = row_of(c, results=payback_results())
    assert row["reason"].startswith("Missing:") and row["calc_lines"] == []


def test_a_payback_plan_for_a_year_after_the_data_is_a_forecast_not_an_annual_comparison():
    row = row_of(payback_claim(MATCHING_ARR, 12, 2026, basis="projection"), results=payback_results())
    assert row["figure_type"] == "target" and row["evidence_label"] == "Unverified"
    assert row["reason"] == "Forecast: no comparison is calculated for this metric" and row["calc_lines"] == []


def test_a_claim_with_no_yearly_basis_block_keeps_the_existing_reading_of_an_annual_period():
    results = copy.deepcopy(payback_results())
    results["yearly_basis"] = None
    row = row_of(payback_claim(MATCHING_ARR, 16), results=results)
    assert row["evidence_label"] == "Unverified" and row["calc_lines"] == []


# --- 6. correctly scoped data requests ------------------------------------------------------------------------------------------------

def gap_claims(rows, results):
    gaps = vd.data_gaps(results, rows, [])
    return next(g for g in gaps if g["item"] == "CAC payback")["claims"]


def test_the_claim_the_annual_figure_answers_leaves_the_monthly_p_and_l_request():
    results = payback_results()
    answered = row_of(payback_claim(MATCHING_ARR, 16), results=results)
    assert answered["evidence_source_key"] != cm.MISSING_KEY and not answered["reason"].startswith("Missing:")
    assert gap_claims([answered], results) == [], "the request for a monthly P&L does not block the claim the annual figure answers"
    gaps = vd.data_gaps(results, [answered], [])
    assert [g["item"] for g in gaps] == ["CAC payback"], "the request itself stays: quarterly timing needs a monthly P&L"


def test_a_year_without_an_annual_figure_keeps_the_request_and_names_the_specific_reason():
    results = payback_results()
    row = row_of(payback_claim(MATCHING_REVENUE, 24, 2022), results=results)
    assert row["reason"] == "annual payback not calculated for FY2022: no revenue for the year before"
    assert gap_claims([row], results) == [row["claim_id"]]


def test_a_definition_the_annual_figures_do_not_answer_keeps_the_request():
    results = payback_results()
    row = row_of(payback_claim("CAC payback 16 months in FY2024, sales and marketing over gross new ARR at gross margin", 16), results=results)
    assert row["reason"].startswith("definition not compared")
    assert gap_claims([row], results) == [row["claim_id"]]


def test_monthly_timing_keeps_the_request():
    results = payback_results()
    c = payback_claim("CAC payback 12 months in Q4 2024", 12)
    c["target_date"], c["period_text"] = "2024-Q4", "Q4 2024"
    from app.decks import claims as deck_claims
    deck_claims.resolve_period(c, 12)
    row = row_of(c, results=results)
    assert gap_claims([row], results) == [row["claim_id"]]


def test_the_baseline_csv_carries_the_annual_claim_and_reads_back():
    row = row_of(payback_claim(MATCHING_ARR, 16), results=payback_results())
    text = vd.baseline_csv([row], [], [], None)
    parsed, _, _ = vd.parse_baseline(text)
    assert parsed[0]["calc_lines"] == row["calc_lines"] and parsed[0]["observed_value"] == 16.0
    assert vd.rewrite_baseline(parsed, [], None) == text


def test_the_compute_function_is_pure():
    one = ge.compute_yearly_basis(yearly_input(), {"mrr_series": arr_series()}, None)
    two = ge.compute_yearly_basis(yearly_input(), {"mrr_series": arr_series()}, None)
    assert one == two
