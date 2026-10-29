"""P&L lines: what each mapped line feeds (docs/design/pnl-lines.md, sections 1-8).

The fixture is an anonymised yearly P&L shaped like the real one: FY 2019 to FY 2024, as-of month Dec 2021, an OPEX total written positive
over department totals written negative (a sign gap), a yearly growth row, result lines below EBITDA. Synthetic figures (rule 15).
Every test runs on the pure functions and the register; nothing reaches a model or a database.
"""
import copy
from pathlib import Path

import pytest

import growth_engine as ge
from claim_matching_support import engine_results  # noqa: F401  (shared fixture module import order)
from forecast_support import claim, long_results, payback_claim, settings

from app import claim_groups as cg
from app import claim_matching as cm
from app import integrity
from app import run_audit as ra
from app import verdict as vd
from app import column_rules as cr
from app.structures import pnl_lines as pl
from app.structures import sheet as sh
from schemas import metrics

FIXTURE = "yearly_pnl_lines.csv"
MAPPING = Path(__file__).resolve().parent / "fixtures" / "mapping"
META = {"file": FIXTURE, "sheet": "CSV"}
AS_OF = "2021-12"
SOURCE = (MAPPING / FIXTURE).read_bytes()


def stmt_map(content: bytes = SOURCE) -> dict:
    s = cr.read_workbook(content, FIXTURE)[0]
    return sh.build(sh.read(s.grid, s.fmt, 12))


def edit(old: str, new: str) -> bytes:
    assert old.encode() in SOURCE, f"fixture row not found: {old}"
    return SOURCE.replace(old.encode(), new.encode())


def view(content: bytes = SOURCE) -> dict:
    return {line["label"]: line for line in sh.view(stmt_map(content), 12, 1000)["lines"]}


def analysis(content: bytes = SOURCE, fye: int = 12) -> dict:
    return pl.analyse(stmt_map(content), fye, 1000, META, AS_OF)


def results_for(content: bytes = SOURCE, fye: int = 12) -> dict:
    fed = sh.feed(stmt_map(content), fye, 1000, META, AS_OF)
    r = long_results(AS_OF)
    r["yearly_basis"] = ge.compute_yearly_basis(fed["yearly"], r, r["revenue_series"])
    r["pnl_lines"] = ge.compute_pnl_lines(fed["lines"], META)
    return r


def years(content: bytes = SOURCE) -> dict:
    return {y["period"]: y for y in results_for(content)["yearly_basis"]["years"]}


# --- 1. every mapped line has a use, assigned by its mapped role -----------------------------------------------------------------------

def test_every_mapped_line_shows_a_use_and_none_reads_not_used():
    lines = view()
    mapped = [x for x in lines.values() if x["role"] not in sh.NOT_LINES]
    assert mapped and all(x["use"] in pl.USES for x in mapped), {x["label"]: x["use"] for x in mapped if x["use"] not in pl.USES}
    assert not any("not used" in str(x["use"]).lower() for x in lines.values())


def test_the_uses_follow_the_roles_of_the_real_file():
    lines = view()
    use = {k: v["use"] for k, v in lines.items()}
    assert use["Revenue (Recognised)"] == "series" and use["Product A"] == "series" and use["EBITDA"] == "series"
    assert use["OPEX total"] == "sum check" and use["Research & Development"] == "sum check"
    assert use["Revenue growth rate"] == use["Gross margin %"] == use["OPEX %"] == use["EBITDA %"] == "recompute check"
    assert use["Gross Margin"] == use["EBT"] == use["Net income"] == "recompute check"
    assert {use[k] for k in ("Interest income / costs", "Other income: venture capital", "Other income: grants",
                             "Depreciation & amortization", "Tax paid", "RnD Tax credits")} == {"excluded"}


def test_a_use_comes_from_the_role_never_from_the_label():
    m = stmt_map()
    before = {x["row"]: x["use"] for x in sh.view(m, 12, 1000)["lines"]}
    renamed = copy.deepcopy(m)
    for line in renamed["lines"]:
        line["label"] = f"Line {line['row']}"
    after = {x["row"]: x["use"] for x in sh.view(renamed, 12, 1000)["lines"]}
    assert after == before, "the same roles through other labels give the same uses"


# --- 2. periods ------------------------------------------------------------------------------------------------------------------------

def test_the_growth_rate_row_reads_yearly_and_a_margin_row_has_no_period():
    lines = view()
    assert lines["Revenue growth rate"]["period"] == "yearly"
    assert lines["Gross margin %"]["period"] is None and lines["OPEX %"]["period"] is None and lines["EBITDA %"]["period"] is None


def test_a_monthly_growth_row_reads_monthly():
    s = cr.read_workbook((MAPPING / "monthly_kpi.csv").read_bytes(), "monthly_kpi.csv")[0]
    lines = {x["label"]: x for x in sh.view(sh.build(sh.read(s.grid, s.fmt, 12)), 12, 1)["lines"]}
    assert lines["MRR growth % MoM"]["period"] == "monthly"


def test_a_period_converts_only_in_code_with_the_formula_and_the_word_annualised():
    got = pl.annualise(0.02, "month")
    assert got["label"] == "annualised" and got["value"] == pytest.approx(1.02 ** 12 - 1) and "^12" in got["formula"]
    assert pl.annualise(0.1, "quarter")["value"] == pytest.approx(1.1 ** 4 - 1)
    assert pl.annualise(0.4, "year") is None, "a yearly rate is not converted"


def test_columns_after_the_as_of_month_are_plan_whatever_the_header_says_and_a_budget_column_is_plan_before_it():
    plan = {c["period"] for c in analysis(edit("Line,FY 2019,FY 2020,FY 2021,FY 2022,FY 2023,FY 2024",
                                              "Line,FY 2019,FY 2020,FY 2021,FY 2022 Actual,FY 2023,FY 2024"))["plan"]}
    assert plan == {"FY 2022 Actual", "FY 2023", "FY 2024"}, "FY 2022 Actual ends after the as-of month"
    budget = {c["period"] for c in analysis(edit("FY 2021,FY 2022,FY 2023,FY 2024", "FY 2021 Budget,FY 2022,FY 2023,FY 2024"))["plan"]}
    assert "FY 2021 Budget" in budget, "a column marked budget is plan even before the as-of month"


# --- 3. integrity findings -------------------------------------------------------------------------------------------------------------

def test_the_sign_finding_says_sign_differs_with_the_two_amounts_not_a_sum_gap():
    found = [f for f in analysis()["findings"] if f["line"] == "OPEX total"]
    assert {f["period"] for f in found} == {"FY 2019", "FY 2020", "FY 2021", "FY 2022", "FY 2023", "FY 2024"}
    fy21 = next(f for f in found if f["period"] == "FY 2021")
    assert fy21["kind"] == "sign" and fy21["gap"] is None
    assert fy21["text"] == "OPEX total: sign differs from its lines in FY 2021 (total 1,500,000, lines -1,500,000)"
    assert "3,000,000" not in fy21["text"] and fy21["cell"] == "D12"


def test_a_total_and_its_lines_of_one_sign_raise_no_finding_whatever_the_convention():
    negative = analysis(edit("OPEX total,600,940,1500,2080,2760,3520", "OPEX total,-600,-940,-1500,-2080,-2760,-3520"))["findings"]
    assert [f for f in negative if f["line"] == "OPEX total"] == [], "total and lines both negative: the sum check compares by size"


def test_a_total_that_differs_from_its_lines_by_more_than_the_sign_stays_a_sum_finding():
    found = [f for f in analysis(edit("OPEX total,600,940,1500,", "OPEX total,600,940,1700,"))["findings"] if f["period"] == "FY 2021"]
    assert [f["kind"] for f in found if f["line"] == "OPEX total"] == ["sum"]


def test_a_clean_file_has_no_finding_but_the_sign_gap():
    assert {f["line"] for f in analysis()["findings"]} == {"OPEX total"}


def test_a_total_beyond_the_money_tolerance_is_a_finding_and_within_it_is_not():
    off = analysis(edit("Cloud processing and database,-100,-190,-330", "Cloud processing and database,-100,-170,-330"))["findings"]
    found = next(f for f in off if f["line"] == "Cost of Goods Sold")
    assert (found["kind"], found["period"], found["gap"]) == ("sum", "FY 2020", -20_000)
    near = analysis(edit("Product A,300,550,900,", "Product A,300,550,901,"))["findings"]
    assert not [f for f in near if f["line"] == "Revenue (Recognised)"], "1 in 1,500 is inside 0.5%"


def test_the_growth_row_recomputes_within_the_rate_tolerance():
    assert not [f for f in analysis()["findings"] if f["line"] == "Revenue growth rate"]
    near = analysis(edit("0.875,0.6,0.5", "0.875,0.605,0.5"))["findings"]
    assert not [f for f in near if f["line"] == "Revenue growth rate"], "half a point is inside ±1 point and is not shown"
    far = [f for f in analysis(edit("0.875,0.6,0.5", "0.875,0.65,0.5"))["findings"] if f["line"] == "Revenue growth rate"]
    assert len(far) == 1 and far[0]["kind"] == "recompute" and far[0]["period"] == "FY 2022"
    assert far[0]["unit"] == "points" and far[0]["gap"] == pytest.approx(5.0) and "5.0 points" in far[0]["text"]


GROWTH_OPEX = "OPEX growth %,,0.5667,0.5957,0.3867,0.3269,0.2754\n"
GROWTH_CUSTOMERS = "Customers,10,20,30,40,50,60\nCustomer growth %,,1.0,0.5,0.3333,0.25,0.2\n"


def test_a_growth_row_is_recomputed_against_its_own_base_line_at_the_columns_period():
    opex = analysis(edit("OPEX %,", GROWTH_OPEX + "OPEX %,"))
    assert not [f for f in opex["findings"] if f["line"] == "OPEX growth %"], "OPEX growth is OPEX 940 / 600 - 1, not a share of revenue"
    assert view(edit("OPEX %,", GROWTH_OPEX + "OPEX %,"))["OPEX growth %"]["period"] == "yearly"
    customers = analysis(edit("OPEX %,", GROWTH_CUSTOMERS + "OPEX %,"))
    assert not [f for f in customers["findings"] if f["line"] == "Customer growth %"], "customer growth is not revenue growth"
    assert view(edit("OPEX %,", GROWTH_CUSTOMERS + "OPEX %,"))["Customer growth %"]["period"] == "yearly"


def test_a_growth_row_that_differs_from_the_growth_of_its_base_is_a_finding():
    wrong = GROWTH_OPEX.replace("0.5957", "0.7957")
    found = [f for f in analysis(edit("OPEX %,", wrong + "OPEX %,"))["findings"] if f["line"] == "OPEX growth %"]
    assert [(f["period"], f["unit"]) for f in found] == [("FY 2021", "points")] and found[0]["gap"] == pytest.approx(20.0, abs=0.1)
    assert "recomputed 59.6%" in found[0]["text"]


def test_a_growth_row_that_names_no_line_of_the_file_is_not_checked_against_revenue():
    assert not [f for f in analysis(edit("OPEX %,", "Net adds growth %,,0.9,0.9,0.9,0.9,0.9\nOPEX %,"))["findings"] if f["line"] == "Net adds growth %"]


def test_opex_and_opex_percent_both_written_negative_raise_no_finding():
    both = edit("OPEX %,1.5,1.175,1.0,0.8667,0.7667,0.704", "OPEX %,-1.5,-1.175,-1.0,-0.8667,-0.7667,-0.704")
    both = both.replace(b"OPEX total,600,940,1500,2080,2760,3520", b"OPEX total,-600,-940,-1500,-2080,-2760,-3520")
    assert not [f for f in analysis(both)["findings"] if f["line"] in ("OPEX total", "OPEX %")]
    wrong = analysis(edit("OPEX %,1.5,1.175,1.0,", "OPEX %,-1.5,-1.175,-1.3,"))["findings"]
    assert [f["period"] for f in wrong if f["line"] == "OPEX %"] == ["FY 2021"], "a real gap in size is still found"


def test_margin_rows_and_result_lines_are_recomputed_from_the_money_rows():
    margin = [f for f in analysis(edit("0.74,0.75,0.7611,0.77", "0.74,0.75,0.7911,0.77"))["findings"] if f["line"] == "Gross margin %"]
    assert [f["period"] for f in margin] == ["FY 2023"]
    ebt = [f for f in analysis(edit("EBT,-278,497,-325", "EBT,-278,497,-335"))["findings"] if f["line"] == "EBT"]
    assert [(f["period"], f["gap"]) for f in ebt] == [("FY 2021", -10_000)]
    money = [f for f in analysis(edit("Gross Margin,280,580,1110", "Gross Margin,280,580,1010"))["findings"] if f["line"] == "Gross Margin"]
    assert [f["period"] for f in money] == ["FY 2021"]


def test_the_checks_use_the_apps_tolerances():
    assert sh.TOLERANCE == 0.005 and cm.RATE_TOLERANCE_PP == 1.0 == pl.rate_tolerance_points()


def test_the_findings_are_in_the_stored_block_each_with_its_cell_and_in_the_integrity_view():
    r = results_for()
    assert metrics.PnlLines.model_validate(r["pnl_lines"]).findings
    first = r["pnl_lines"]["findings"][0]
    assert first["source"]["row_numbers"] == [12] and first["source"]["rule"].endswith("cell B12")
    shown = integrity.assess(r, 0, [])["statement_findings"]
    assert shown and shown[0]["text"] == first["text"] and "yearly_pnl_lines.csv" in shown[0]["source"]
    assert integrity.assess({}, 0, [])["statement_findings"] == []


# --- 4. plan cells ---------------------------------------------------------------------------------------------------------------------

def test_fy2022_to_fy2024_revenue_cells_are_plan_claims_with_implied_growth_next_to_observed():
    plan = {c["period"]: c for c in analysis()["plan"] if c["metric"] == "Revenue"}
    assert list(plan) == ["FY 2022", "FY 2023", "FY 2024"]
    fy22 = plan["FY 2022"]
    assert fy22["source_text"] == "File CSV!E3 (plan)" and fy22["value"] == 2_400_000 and fy22["cell"] == "E3"
    assert fy22["measure"] == "growth" and fy22["implied"] == pytest.approx(0.6) and fy22["observed"] == pytest.approx(0.875)
    assert fy22["gap_points"] == pytest.approx(-27.5) and fy22["compared"] == "FY 2021 → FY 2022 against FY 2020 → FY 2021"
    assert plan["FY 2023"]["implied"] == pytest.approx(0.5), "a later plan year grows from the plan year before it"
    assert (fy22["period_start"], fy22["period_end"]) == ("2022-01", "2022-12")


def test_gross_margin_and_ebitda_are_tested_as_a_share_of_revenue_and_costs_as_growth():
    plan = {(c["metric"], c["period"]): c for c in analysis()["plan"]}
    assert plan[("Gross margin", "FY 2022")]["measure"] == "share of revenue" and plan[("Gross margin", "FY 2022")]["observed"] == pytest.approx(0.74)
    assert plan[("EBITDA", "FY 2022")]["implied"] == pytest.approx(-280 / 2400)
    assert plan[("S&M expense", "FY 2022")]["value"] == 770_000, "Sales + Marketing, less the internal events"
    assert plan[("Operating expenses", "FY 2022")]["measure"] == "growth"


def test_a_plan_claim_enters_the_register_unverified_with_its_source_and_a_value_at_stake():
    r = results_for()
    rows = cm.build_register([], r, settings(AS_OF, target_arr=10_000_000, target_date="2027-12-31"))
    plan = {(x["claim_type"], x["period"]): x for x in rows if x["deck_reading"] == cm.PLAN_READING}
    rev = plan[("revenue", "FY 2022")]
    assert rev["evidence_label"] == "Unverified" and rev["page_ref"] == "File CSV!E3 (plan)"
    assert all(x["evidence_label"] == "Unverified" for x in plan.values()), "never Verified or Contradicted"
    assert rev["value_at_stake_arr"] == 2_400_000 and rev["figure_type"] == "target"
    assert "Implied growth FY 2021 → FY 2022: 60.0%" in rev["calc_lines"][1] and "Gap: -27.5 points" in rev["calc_lines"]
    assert not any(x["value_at_stake_arr"] for x in plan.values() if x["claim_type"] in ("cost_of_revenue", "s_and_m", "opex")), "a cost has no ARR link"


def test_plan_rows_carry_the_claim_type_of_their_line_and_are_never_rivals_for_one_year():
    r = results_for()
    rows = cm.build_register([], r, settings(AS_OF, target_arr=10_000_000, target_date="2027-12-31"))
    plan = [x for x in rows if x["deck_reading"] == cm.PLAN_READING]
    assert {x["claim_type"] for x in plan} == {"revenue", "cost_of_revenue", "s_and_m", "opex", "gross_profit", "ebitda"}
    assert len(plan) == 18 and "costs" not in {x["claim_type"] for x in plan}
    assert not [x for x in plan if x["group_role"] is not None], "no 'choose the one to use' card from plan rows"
    assert not [x for x in plan if cg.is_ineligible(x)]
    assert all(x["rank"] for x in plan) and len({x["rank"] for x in plan}) == len(plan), "every plan row is ranked"


def test_confirming_the_forecast_table_folds_its_rows_into_the_plan_rows_and_keeps_the_ranking():
    r = results_for()
    cells = {(c["metric"], c["period"]): c["cell"] for c in r["pnl_lines"]["plan"]}
    table = []
    for n, (metric, ctype) in enumerate((("Revenue", "revenue"), ("Gross margin", "gross_profit"), ("EBITDA", "ebitda")), 1):
        for period, year in (("FY 2022", "2022"), ("FY 2023", "2023"), ("FY 2024", "2024")):
            cell = cells[(metric, period)]
            table.append(claim(f"{metric} {period}", 1.0, period.replace(" ", ""), year, claim_type=ctype, id=f"f{n}{year}", origin=cm.FORECAST_FILE,
                               basis="projection", sources=[{"file": FIXTURE, "sheet": "CSV", "cell": cell}]))
    st = settings(AS_OF, target_arr=10_000_000, target_date="2027-12-31")
    before, after = cm.build_register([], r, st), cm.build_register(table, r, st)
    plan = [x for x in after if x["deck_reading"] == cm.PLAN_READING]
    assert len(plan) == 18 and not [x for x in after if x["deck_reading"] == cm.FORECAST_READING], "one claim, not two"
    revenue = next(x for x in plan if x["claim_type"] == "revenue" and x["period"] == "FY 2022")
    assert revenue["page_ref"] == "File CSV!E3 (plan), CSV!E3 (forecast table)"
    assert vd.proposal(after) == vd.proposal(before) and len(vd.proposal(after)) == 5, "the top five is populated"


def test_a_plan_rows_id_is_its_sheet_line_and_period_so_a_shifted_column_keeps_it():
    def plan_ids(content):
        r = results_for(content)
        return {(x["claim_type"], x["period"]): (x["claim_id"], x["page_ref"]) for x in cm.build_register([], r, settings(AS_OF))
                if x["deck_reading"] == cm.PLAN_READING}
    shifted = b"\n".join(row.replace(b",", b",,", 1) if row else row for row in SOURCE.split(b"\n"))      # one empty column inserted after the labels
    before, after = plan_ids(SOURCE), plan_ids(shifted)
    assert before[("revenue", "FY 2024")][0] == after[("revenue", "FY 2024")][0] == "plan:CSV:revenue:FY2024"
    assert before[("revenue", "FY 2024")][1] == "File CSV!G3 (plan)" and after[("revenue", "FY 2024")][1] == "File CSV!H3 (plan)", "the cell moved"
    assert {k: v[0] for k, v in before.items()} == {k: v[0] for k, v in after.items()}


def test_a_deck_forecast_within_tolerance_makes_one_claim_with_two_sources():
    r = results_for()
    deck = claim("Revenue of €2.3M in FY2022", 2_300_000, "FY2022", "2022", basis="projection")
    rows = cm.build_register([deck], r, settings(AS_OF))
    revenue = [x for x in rows if x["claim_type"] == "revenue"]
    assert [x["period"] for x in revenue if x["period"] in ("FY2022", "FY 2022")] == ["FY2022"], "the plan row of FY 2022 is merged away"
    one = next(x for x in revenue if x["period"] == "FY2022")
    assert "slide 3" in one["page_ref"] and "File CSV!E3 (plan)" in one["page_ref"]
    assert any("within" in line for line in one["calc_lines"])


def test_a_deck_forecast_beyond_tolerance_is_flagged_plan_in_file_differs_from_plan_in_deck():
    r = results_for()
    deck = claim("Revenue of €2.0M in FY2022", 2_000_000, "FY2022", "2022", basis="projection")
    rows = cm.build_register([deck], r, settings(AS_OF))
    plan = next(x for x in rows if x["deck_reading"] == cm.PLAN_READING and x["claim_type"] == "revenue" and x["period"] == "FY 2022")
    assert plan["reason"] == f"{cm.PLAN_DIFFERS}: file €2,400,000, deck €2,000,000 (+20%)"
    assert plan in vd.flagged_rows(rows), "listed under Worth flagging"
    assert any(x["claim_id"] == "x1" for x in rows), "the deck claim stays"
    assert not [x for x in vd.flagged_rows(rows) if x["claim_id"] == "x1"]


def test_a_deck_percentage_is_compared_with_the_plans_implied_percentage_not_its_money_figure():
    r = results_for()
    deck = claim("EBITDA margin 7% in FY2024", 7, "FY2024", "2024", claim_type="ebitda", currency=None, unit="%", basis="projection")
    rows = cm.build_register([deck], r, settings(AS_OF))
    one = next(x for x in rows if x["claim_id"] == "x1")
    assert any("6.6%" in line and "within ±1 pp" in line for line in one["calc_lines"]), one["calc_lines"]
    assert not [x for x in rows if x["claim_id"] == "plan:CSV:ebitda:FY2024"], "within tolerance: one claim, two sources"
    assert not [x for x in vd.flagged_rows(rows) if x["claim_type"] == "ebitda"] and "File CSV!G" in one["page_ref"]
    far = claim("EBITDA margin 12% in FY2024", 12, "FY2024", "2024", claim_type="ebitda", currency=None, unit="%", basis="projection")
    plan = next(x for x in cm.build_register([far], r, settings(AS_OF)) if x["claim_id"] == "plan:CSV:ebitda:FY2024")
    assert plan["reason"] == f"{cm.PLAN_DIFFERS}: file implied share of revenue 6.6%, deck 12.0% (-5.4 points)"


def test_a_deck_money_figure_is_compared_with_the_plans_money_figure():
    r = results_for()
    deck = claim("EBITDA of €330k in FY2024", 330_000, "FY2024", "2024", claim_type="ebitda", basis="projection")
    rows = cm.build_register([deck], r, settings(AS_OF))
    assert not [x for x in rows if x["claim_id"] == "plan:CSV:ebitda:FY2024"] and "within" in " ".join(next(x for x in rows if x["claim_id"] == "x1")["calc_lines"])


def test_a_cost_forecast_of_the_deck_is_not_compared_with_a_plan_line():
    r = results_for()
    deck = claim("S&M of €0.8M in FY2022", 800_000, "FY2022", "2022", claim_type="costs", basis="projection")
    rows = cm.build_register([deck], r, settings(AS_OF))
    assert not [x for x in rows if x["reason"] and x["reason"].startswith(cm.PLAN_DIFFERS)]


# --- 5. every deck-to-yearly match goes through yearly_year -------------------------------------------------------------------------

def test_a_deck_year_matches_only_a_column_ending_in_the_same_month():
    r = results_for(fye=6)
    plan_years = {c["period"]: (c["period_start"], c["period_end"]) for c in r["pnl_lines"]["plan"]}
    assert plan_years["FY 2022"] == ("2021-07", "2022-06")
    year, why = cm.yearly_year(r, cm._mi("2022-01"), cm._mi("2022-12"), plan=True)
    assert year is None and why and "not covered" in why.lower(), "a calendar 2022 is no column ending in June"
    year, why = cm.yearly_year(r, cm._mi("2021-07"), cm._mi("2022-06"), plan=True)
    assert year["period"] == "FY 2022" and why is None
    actual, why = cm.yearly_year(r, cm._mi("2020-07"), cm._mi("2021-06"))
    assert actual["period"] == "FY 2021" and why is None, "the actual years go through the same rule"


def test_a_deck_forecast_of_another_year_end_is_never_compared_with_the_plan_column():
    r = results_for(fye=6)
    deck = claim("Revenue of €2.4M in FY2022", 2_400_000, "FY2022", "2022", basis="projection")      # calendar year 2022 (year-end Dec)
    rows = cm.build_register([deck], r, settings(AS_OF))
    one = next(x for x in rows if x["claim_id"] == "x1")
    assert any("not covered" in line.lower() for line in one["calc_lines"])
    assert [x for x in rows if x["deck_reading"] == cm.PLAN_READING and x["period"] == "FY 2022"], "the plan row is kept: nothing was merged"


# --- 6. yearly CAC payback -------------------------------------------------------------------------------------------------------------

def test_the_yearly_cac_payback_leaves_internal_events_out_of_sm_and_is_labelled_yearly_revenue_based():
    y = years()["FY 2021"]
    assert y["sm_expense"] == 540_000, "Sales 300 + Marketing 260 less internal events 20, in thousands"
    assert y["new_revenue"] == 700_000 and y["gross_margin_pct"] == 0.74
    assert y["cac_payback_months"] == round(12 * 540_000 / (700_000 * 0.74), 2) == 12.51
    assert y["cac_payback_label"] == "yearly, revenue-based"
    assert y["sm_scope"] == "sales and marketing"
    assert metrics.YearlyBasis.model_validate(results_for()["yearly_basis"])


def test_the_register_words_the_yearly_payback_in_months_labelled_yearly_revenue_based():
    r = results_for()
    deck = payback_claim("CAC payback 12.5 months in FY2021: sales and marketing spend over revenue growth, gross margin adjusted", 12.5, 2021)
    row = cm.build_register([deck], r, settings(AS_OF))[0]
    first = row["calc_lines"][0]
    assert first.startswith("CAC payback FY 2021: 12.5 months (yearly, revenue-based) = 12 × S&M €540,000 ÷ (revenue growth €700,000")
    assert row["evidence_label"] == "Verified" and row["observed_value"] == 12.51


def test_internal_events_are_read_from_the_mapped_role_not_counted_in_sm():
    lines = stmt_map()["lines"]
    events = next(x for x in lines if x["label"] == "internal events")
    assert events["meaning"] == "opex" and events["parent_row"] == 19
    assert [x["row"] for x in sh.excluded_parts(next(x for x in lines if x["row"] == 19), lines, "sm_expense")] == [23]
    renamed = copy.deepcopy(stmt_map())
    for line in renamed["lines"]:
        if line["row"] == 23:
            line["label"] = "Staff gatherings"
    fed = sh.feed(renamed, 12, 1000, META, AS_OF)
    assert next(y for y in fed["yearly"]["actual"] if y["period"] == "FY 2021")["fields"]["sm_expense"]["value"] == 540_000


# --- 7. the contract -------------------------------------------------------------------------------------------------------------------

def test_the_contract_moves_to_13_and_results_stored_under_12_read_stale():
    assert metrics.CONTRACT_VERSION == 13
    assert ra.results_stale({"results": {"contract_version": 12}}) and ra.STALE_LABEL == "Stale – re-run audit"
    assert not ra.results_stale({"results": {"contract_version": 13}})


def test_the_pnl_lines_block_is_declared_and_validated():
    assert "pnl_lines" in metrics.MetricsPayload.model_fields
    block = results_for()["pnl_lines"]
    assert metrics.PnlLines.model_validate(block).plan and block["source"]["rule"]
    with pytest.raises(Exception):
        metrics.PnlLines.model_validate({**block, "surprise": 1})
