"""The engine on the map (docs/design/read-check-review.md section 16; PR 4 step a).

Synthetic maps only: every input is a stored map row with its stored series, as the reading writes them (app/series.py). The engine reads them by
role. A metric runs when the rows it needs exist, otherwise it says "needs a <role> row" and never "no S&M line" or the like. No network, no
MongoDB, no company's figures."""
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import growth_engine as ge  # noqa: E402
from app import role_engine as re_  # noqa: E402
from schemas import metrics  # noqa: E402

MONTHS = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 7)]


def series(values, periods, first_row=4, col0=2):
    refs = [f"{chr(64 + col0 + i)}{first_row}" if col0 + i <= 26 else f"A{chr(64 + col0 + i - 26)}{first_row}" for i in range(len(periods))]
    return {"periods": list(periods), "values": list(values), "refs": refs}


def row(n, role, values, periods, *, basis="monthly", actual_plan="actual", segment=None, plan=False, unit="money"):
    out = {"row": n, "role": role, "basis": basis, "actual_plan": actual_plan, "segment": segment, "unit": unit, "evidence": "x",
           "cells": f"B{n}:Z{n}"}
    cells = series(values, periods, first_row=n)
    out["plan_series" if plan else "series"] = cells
    return out


def sheet(name, rows, granularity="monthly"):
    return {"sheet": name, "header_row": 1, "label_col": "A", "first_period_col": "B", "last_period_col": "Z", "granularity": granularity, "rows": rows}


def file_of(name, sheets, rejected=(), cannot=()):
    return {"file": name, "file_map": {"map_version": 1, "kind": "sheet", "sheets": sheets, "figures": []}, "rejected": list(rejected), "cannot": list(cannot)}


def run(files, as_of="2026-06", deck=None, fye=12):
    table = re_.build_table(files)
    cfg = {"reporting_currency": "EUR", "target_arr": 1_000_000, "target_date": "2027-12-31", "fx": {"EUR": 1.0}, "as_of_month": as_of,
           "roles": {"table": table, "deck": deck or [], "fye": fye}}
    return ge.compute_all(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), cfg, {})


def metric(results, name, label=None):
    found = [m for m in results["role_metrics"]["metrics"] if m["metric"] == name and (label is None or (m["label"] or "").endswith(label))]
    assert found, f"{name} not in role_metrics"
    return found[0]


def monthly_report(plan_rows=()):
    n = len(MONTHS)
    actual = MONTHS[:18]                       # to 2026-06
    rows = [
        row(4, "revenue", [100 + 5 * i for i in range(18)], actual),
        row(5, "arr", [(100 + 5 * i) * 12 for i in range(18)], actual),
        row(6, "mrr", [100 + 5 * i for i in range(18)], actual),
        row(7, "churn_rate", [0.02] * 17 + [0.03], actual, basis="rate", unit="rate"),
        row(8, "customers", [50 + i for i in range(18)], actual, unit="count"),
        *plan_rows,
    ]
    assert n == 18
    return [file_of("monthly report", [sheet("Report", rows)])]


def test_a_monthly_report_gives_every_metric_it_has_rows_for():
    r = run(monthly_report())
    arr = r["arr"]
    assert arr["month"] == "2026-06" and arr["value"] == (100 + 5 * 17) * 12, "ending ARR from the arr row at the as-of month"
    assert r["mrr_series"]["months"][-1] == "2026-06" and len(r["mrr_series"]["data"]) == 18
    assert r["customers_series"]["data"][-1]["total"] == 67
    assert r["revenue_series"]["data"][0] == {"month": "2025-01", "total": 100.0}
    assert metric(r, "monthly_churn")["value"] == 0.03 and metric(r, "monthly_churn")["period"] == "2026-06"
    assert metric(r, "customers")["value"] == 67
    assert metric(r, "growth", "month on month")["value"] == pytest.approx(185 / 180 - 1)
    assert metric(r, "growth", "year on year")["value"] == pytest.approx(185 / 125 - 1)
    assert r["source_period"]["month"] == "2026-06" and r["metric_periods"]["arr"]["last"] == "2026-06"


def test_a_metric_without_its_row_says_which_role_it_needs():
    only_revenue = [file_of("f", [sheet("S", [row(4, "revenue", [10, 11, 12], MONTHS[:3])])])]
    r = run(only_revenue, as_of="2025-03")
    for name, text in (("monthly_churn", "needs a churn_rate row"), ("customers", "needs a customers row"), ("plan_to_date", "needs a forecast row"),
                       ("mrr_series", "needs an mrr row"), ("ending_arr", "needs an arr row or an mrr row"), ("cash", "needs a cash row"),
                       ("headcount", "needs a headcount row"), ("sm_share", "needs a sales_marketing row")):
        m = metric(r, name)
        assert m["status"] == "needs_row" and m["reason"] == text, (name, m["reason"])
    text = " ".join(str(v) for m in r["role_metrics"]["metrics"] for v in (m["reason"],)) + " " + " ".join(i["reason"] for i in r["missing_data"])
    assert "no S&M line" not in text and "no usable" not in text.lower()


def test_plan_to_date_compares_the_same_month_of_a_monthly_plan():
    plan = row(9, "forecast", [90 + 6 * i for i in range(24)], [f"{2025 + i // 12}-{i % 12 + 1:02d}" for i in range(24)], actual_plan="plan", plan=True,
               basis="monthly")
    r = run(monthly_report([plan]))
    p = r["role_metrics"]["plan_to_date"]
    assert p["basis"] == "month" and p["period"] == "2026-06"
    assert p["actual"] == 185 and p["plan"] == 90 + 6 * 17 and p["variance"] == 185 - (90 + 6 * 17)
    assert p["variance_pct"] == pytest.approx(p["variance"] / p["plan"])


def test_a_cumulative_plan_is_compared_with_the_actual_accumulated_over_the_same_span():
    periods = [f"2026-{m:02d}" for m in range(1, 13)]
    cumulative, total = [], 0
    for i in range(12):
        total += 110
        cumulative.append(total)
    plan = row(9, "forecast", cumulative, periods, actual_plan="plan", plan=True, basis="cumulative_to_date")
    r = run(monthly_report([plan]))
    p = r["role_metrics"]["plan_to_date"]
    assert p["basis"] == "cumulative_to_date"
    assert p["actual"] == sum(100 + 5 * i for i in range(12, 18)), "actual 2026-01 to 2026-06, the plan row's own span"
    assert p["plan"] == 6 * 110


def test_a_full_year_plan_is_never_compared_with_actual_to_date():
    plan = row(9, "forecast", [1_500], ["2026"], actual_plan="plan", plan=True, basis="yearly")
    plan_sheet = sheet("Plan", [plan], granularity="yearly")
    files = monthly_report() + [file_of("plan", [plan_sheet])]
    r = run(files)
    assert r["role_metrics"]["plan_to_date"] is None
    m = metric(r, "plan_to_date")
    assert m["status"] == "needs_row" and "full-year plan" in m["reason"]


def yearly_pnl(with_sm=True, with_cogs=True):
    years = ["2023", "2024", "2025"]
    rows = [row(4, "revenue", [1_000, 1_500, 2_400], years, basis="yearly")]
    if with_cogs:
        rows.append(row(5, "cost_of_revenue", [300, 450, 600], years, basis="yearly"))
    if with_sm:
        rows.append(row(6, "sales_marketing", [400, 500, 900], years, basis="yearly"))
    return [file_of("pnl", [sheet("P&L", rows, granularity="yearly")])]


def test_a_yearly_pnl_gives_yearly_revenue_margin_share_and_a_payback_labelled_yearly():
    r = run(yearly_pnl(), as_of="2026-06")
    year = r["yearly_basis"]["years"][-1]
    assert year["period"] == "2025" and year["revenue"] == 2_400
    assert year["gross_margin_pct"] == pytest.approx((2_400 - 600) / 2_400)
    assert year["sm_pct_revenue"] == pytest.approx(900 / 2_400)
    assert year["cac_payback_months"] == pytest.approx(12 * 900 / ((2_400 - 1_500) * 0.75), abs=0.01)
    assert year["cac_payback_label"] == "yearly, revenue-based"
    assert metric(r, "yearly_revenue")["value"] == 2_400 and metric(r, "yearly_revenue")["label"] == "yearly"
    assert metric(r, "gross_margin")["value"] == pytest.approx(0.75)
    assert metric(r, "sm_share")["value"] == pytest.approx(900 / 2_400) and metric(r, "sm_share")["label"] == "yearly"
    payback = metric(r, "yearly_cac_payback")
    assert payback["label"] == "yearly, revenue-based" and payback["unit"] == "months"


def test_a_yearly_payback_without_its_cost_rows_names_the_role():
    r = run(yearly_pnl(with_sm=False))
    assert metric(r, "yearly_cac_payback")["reason"] == "needs a sales_marketing row"
    assert r["yearly_basis"]["years"][-1]["cac_payback_reason"] == "needs a sales_marketing row"
    r = run(yearly_pnl(with_cogs=False))
    assert metric(r, "gross_margin")["reason"] == "needs a cost_of_revenue row"
    assert metric(r, "yearly_cac_payback")["reason"] == "needs a cost_of_revenue row"


def test_a_row_the_checks_rejected_is_no_input():
    files = monthly_report()
    files[0]["rejected"] = ["row:Report:8"]
    r = run(files)
    assert metric(r, "customers")["status"] == "needs_row" and r["customers_series"]["data"] == []


def test_a_split_without_a_total_row_is_not_a_total():
    files = [file_of("f", [sheet("S", [row(4, "customers", [5, 6], MONTHS[:2], segment="EU", unit="count")])])]
    assert metric(run(files, as_of="2025-02"), "customers")["status"] == "needs_row"


def test_the_total_row_is_chosen_before_a_split():
    rows = [row(4, "customers", [1, 2], MONTHS[:2], segment="EU", unit="count"), row(5, "customers", [10, 20], MONTHS[:2], unit="count")]
    assert metric(run([file_of("f", [sheet("S", rows)])], as_of="2025-02"), "customers")["value"] == 20


def test_nothing_after_the_as_of_month_is_an_actual_input():
    r = run(monthly_report(), as_of="2026-03")
    assert r["arr"]["month"] == "2026-03" and r["mrr_series"]["months"][-1] == "2026-03"
    assert metric(r, "customers")["period"] == "2026-03"


def test_the_same_metric_and_period_across_a_file_the_pnl_and_the_deck_are_reconciled():
    monthly = [file_of("report", [sheet("Report", [row(4, "revenue", [100] * 12, [f"2025-{m:02d}" for m in range(1, 13)])])])]
    pnl = [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1_200], ["2025"], basis="yearly")], granularity="yearly")])]
    deck = [{"metric": "revenue", "period": "2025", "value": 1_500.0, "currency": "EUR", "actual_plan": "actual", "file": "deck", "page": 4}]
    r = run(monthly + pnl, as_of="2026-06", deck=deck)
    rec = [x for x in r["role_metrics"]["reconciliation"] if x["metric"] == "revenue" and x["period"] == "2025"]
    assert len(rec) == 1
    assert {s["kind"] for s in rec[0]["sources"]} == {"file", "deck"} and len(rec[0]["sources"]) == 3
    assert rec[0]["status"] == "differs" and rec[0]["gap"] == 300
    agree = run(monthly + pnl, as_of="2026-06", deck=[{**deck[0], "value": 1_200.0}])
    assert agree["role_metrics"]["reconciliation"][0]["status"] == "agrees"


def test_a_plan_deck_figure_or_another_currency_is_not_compared():
    monthly = [file_of("report", [sheet("Report", [row(4, "revenue", [100] * 12, [f"2025-{m:02d}" for m in range(1, 13)])])])]
    pnl = [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1_200], ["2025"], basis="yearly")], granularity="yearly")])]
    plan = {"metric": "revenue", "period": "2025", "value": 9.0, "currency": "EUR", "actual_plan": "plan", "file": "deck", "page": 1}
    r = run(monthly + pnl, deck=[plan])
    assert all(len(x["sources"]) == 2 for x in r["role_metrics"]["reconciliation"])


def test_customer_level_and_crm_metrics_still_say_they_need_their_files():
    r = run(monthly_report())
    reasons = {i["metric"]: i["reason"] for i in r["missing_data"]}
    assert "customer-level revenue lines" in reasons["NRR (12-month)"] and "customer-level revenue lines" in reasons["Gross revenue churn"]
    assert reasons["Sales cycle & win rate"] == "needs CRM deals"
    assert "ARR / MRR" not in reasons


def test_the_engine_output_passes_the_contract_and_carries_the_version():
    r = run(monthly_report() + yearly_pnl())
    assert r["contract_version"] == metrics.CONTRACT_VERSION == 16
    metrics.MetricsPayload.model_validate(r)
    assert metrics.safe_problems(r) == []


def test_without_an_as_of_month_nothing_on_the_map_is_computed():
    r = run(monthly_report(), as_of=None)
    assert "role_metrics" not in r or r["role_metrics"] is None


def test_the_scope_of_the_s_and_m_row_is_read_from_its_label_and_only_the_closed_word_is_kept():
    files = yearly_pnl()
    files[0]["labels"] = {"P&L:6": "Marketing expenses"}
    year = run(files)["yearly_basis"]["years"][-1]
    assert year["sm_scope"] == "marketing only"
    assert "Marketing" not in str(year), "the label itself is not in the result"
    files[0]["labels"] = {"P&L:6": "Sales and marketing"}
    assert run(files)["yearly_basis"]["years"][-1]["sm_scope"] == "sales and marketing"
    assert run(yearly_pnl())["yearly_basis"]["years"][-1]["sm_scope"] == "unknown"


def test_a_monthly_plan_row_is_the_plan_to_date_even_when_a_yearly_plan_row_has_the_longer_series():
    """Section 16: plan to date compares actual to the as-of month with the plan row to the same month. A yearly P&L beside the monthly
    report may carry a longer plan series (FY2026–FY2030); it is a full-year plan and never the row compared."""
    monthly_plan = row(9, "forecast", [90 + 6 * i for i in range(3)], ["2026-04", "2026-05", "2026-06"], actual_plan="plan", plan=True)
    yearly_plan = row(9, "forecast", [1_500, 1_900, 2_400, 3_000, 3_600], ["2026", "2027", "2028", "2029", "2030"], actual_plan="plan", plan=True,
                      basis="yearly")
    files = monthly_report([monthly_plan]) + [file_of("pnl", [sheet("Plan", [yearly_plan], granularity="yearly")])]
    p = run(files)["role_metrics"]["plan_to_date"]
    assert p is not None and p["basis"] == "month" and p["period"] == "2026-06"
    assert p["actual"] == 185 and p["plan"] == 90 + 6 * 2


def test_a_forecast_row_of_a_cost_line_is_never_the_revenue_plan():
    """The P&L's plan rows carry the metric of their line (forecast of cost of revenue, of S&M): only a revenue plan is compared with revenue."""
    cost_plan = {**row(9, "forecast", [40 + i for i in range(24)], [f"{2025 + i // 12}-{i % 12 + 1:02d}" for i in range(24)], actual_plan="plan",
                      plan=True), "metric": "cost_of_revenue"}
    r = run(monthly_report([cost_plan]))
    m = metric(r, "plan_to_date")
    assert r["role_metrics"]["plan_to_date"] is None and m["status"] == "needs_row" and m["reason"] == "needs a forecast row"
    revenue_plan = {**row(10, "forecast", [100] * 18, MONTHS, actual_plan="plan", plan=True), "metric": "revenue"}
    p = run(monthly_report([cost_plan, revenue_plan]))["role_metrics"]["plan_to_date"]
    assert p["plan"] == 100 and p["actual"] == 185


def test_a_plan_row_on_another_sheet_is_cited_with_its_sheet():
    plan = row(3, "forecast", [100] * 18, MONTHS, actual_plan="plan", plan=True)
    files = [file_of("f", [sheet("Actuals", [row(4, "revenue", [100 + 5 * i for i in range(18)], MONTHS)]), sheet("Budget", [plan])])]
    p = run(files)["role_metrics"]["plan_to_date"]
    assert p["source"]["sheet"] == "Actuals" and p["source"]["cells"] == ["S4", "Budget!S3"]


# ---------------------------------------------------------------------------
# PR 4b: the sign of the cost rows, S&M over several rows or in plan years only, the sheet's own gross margin row, growth by year
# ---------------------------------------------------------------------------
YEARS = ["2023", "2024", "2025"]


def pnl_with(*extra, costs_sign=-1, sm_rows=None, labels=None):
    rows = [row(4, "revenue", [1_000, 1_500, 2_400], YEARS, basis="yearly"),
            row(5, "cost_of_revenue", [costs_sign * v for v in (300, 450, 600)], YEARS, basis="yearly")]
    rows += sm_rows if sm_rows is not None else [row(6, "sales_marketing", [costs_sign * v for v in (400, 500, 900)], YEARS, basis="yearly")]
    rows += list(extra)
    f = file_of("pnl", [sheet("P&L", rows, granularity="yearly")])
    f["labels"] = labels or {}
    return [f]


def test_cost_rows_that_carry_the_opposite_sign_to_revenue_are_used_in_absolute_values():
    r = run(pnl_with(costs_sign=-1))
    year = r["yearly_basis"]["years"][-1]
    assert year["gross_margin_pct"] == pytest.approx(0.75), "(2400 − |−600|) ÷ 2400, never (2400 + 600) ÷ 2400"
    assert year["sm_pct_revenue"] == pytest.approx(900 / 2_400) and year["sm_expense"] == 900
    assert year["cac_payback_months"] == pytest.approx(12 * 900 / ((2_400 - 1_500) * 0.75), abs=0.01)
    for name in ("gross_margin", "sm_share", "yearly_cac_payback"):
        m = metric(r, name)
        assert m["status"] == "computed" and "costs shown as negative" in (m["detail"] or ""), name
    assert metric(r, "gross_margin")["value"] == pytest.approx(0.75)
    same = run(pnl_with(costs_sign=1))
    assert metric(same, "gross_margin")["value"] == pytest.approx(0.75)
    assert all("negative" not in (metric(same, n)["detail"] or "") for n in ("gross_margin", "sm_share", "yearly_cac_payback"))


@pytest.mark.parametrize("sign", [1, -1])
def test_gross_margin_never_exceeds_100_percent_whatever_sign_the_cost_rows_carry(sign):
    r = run(pnl_with(costs_sign=sign))
    for y in r["yearly_basis"]["years"]:
        assert y["gross_margin_pct"] is None or y["gross_margin_pct"] <= 1
    assert metric(r, "gross_margin")["value"] <= 1


def test_the_other_cost_shares_use_absolute_values_too():
    rnd = row(7, "rnd", [-200, -250, -480], YEARS, basis="yearly")
    r = run(pnl_with(rnd))
    m = metric(r, "rnd_share")
    assert m["value"] == pytest.approx(480 / 2_400) and m["detail"] == "costs shown as negative"


def test_every_sales_marketing_row_is_summed():
    sm = [row(6, "sales_marketing", [150, 200, 500], YEARS, basis="yearly"), row(7, "sales_marketing", [250, 300, 400], YEARS, basis="yearly")]
    r = run(pnl_with(sm_rows=sm, costs_sign=1, labels={"P&L:6": "Sales", "P&L:7": "Marketing"}))
    year = r["yearly_basis"]["years"][-1]
    assert year["sm_expense"] == 900 and year["sm_scope"] == "sales and marketing"
    assert metric(r, "sm_share")["value"] == pytest.approx(900 / 2_400)
    assert metric(r, "sm_share")["source"]["cells"][:2] == ["D6", "D7"], "both rows' cells are cited"


def test_a_sub_row_of_a_total_s_and_m_row_is_not_added_to_it():
    total = row(6, "sales_marketing", [400, 500, 900], YEARS, basis="yearly")
    child = {**row(7, "sales_marketing", [300, 400, 700], YEARS, basis="yearly"), "parent_row": 6}
    r = run(pnl_with(sm_rows=[total, child], costs_sign=1))
    assert r["yearly_basis"]["years"][-1]["sm_expense"] == 900


def test_s_and_m_that_exists_only_in_plan_years_says_so_and_not_that_a_row_is_needed():
    plan = {**row(6, "sales_marketing", [1_000, 1_200], ["2026", "2027"], basis="yearly", actual_plan="plan", plan=True)}
    opex = row(8, "opex", [800, 1_100, 1_900], YEARS, basis="yearly")
    r = run(pnl_with(opex, sm_rows=[plan], costs_sign=1))
    text = "S&M split only in plan years; actual years carry OPEX total only"
    assert metric(r, "sm_share")["reason"] == text
    assert metric(r, "yearly_cac_payback")["reason"] == text
    assert r["yearly_basis"]["years"][-1]["cac_payback_reason"] == "needs a sales_marketing row", "the legacy block keeps its own words"
    none = run(pnl_with(sm_rows=[], costs_sign=1))
    assert metric(none, "sm_share")["reason"] == "needs a sales_marketing row"


def test_the_sheets_own_gross_margin_row_is_compared_with_the_computed_margin():
    own = {**row(9, "margin_rate", [0.70, 0.70, 0.62], YEARS, basis="rate", unit="rate"), "metric": "gross_margin"}
    r = run(pnl_with(own, costs_sign=1))
    detail = metric(r, "gross_margin")["detail"]
    assert "62%" in detail and "75%" in detail and "difference 13%" in detail
    agree = {**own, **row(9, "margin_rate", [0.75, 0.75, 0.75], YEARS, basis="rate", unit="rate"), "metric": "gross_margin"}
    assert metric(run(pnl_with(agree, costs_sign=1)), "gross_margin")["detail"] is None


def test_growth_by_year_from_a_monthly_row_and_a_yearly_row_with_the_cells():
    r = run(monthly_report())
    years = r["role_metrics"]["growth_by_year"]
    assert [y["period"] for y in years] == [] or all(y["source"]["cells"] for y in years)
    full = [file_of("f", [sheet("R", [row(4, "revenue", [100] * 12 + [150] * 12, [f"{2024 + i // 12}-{i % 12 + 1:02d}" for i in range(24)])])])]
    y = run(full, as_of="2025-12")["role_metrics"]["growth_by_year"]
    assert len(y) == 1 and y[0]["period"] == "2025" and y[0]["value"] == 1_800 and y[0]["prior"] == 1_200
    assert y[0]["growth"] == pytest.approx(0.5) and len(y[0]["source"]["cells"]) == 4
    yearly = run(pnl_with(costs_sign=1))["role_metrics"]["growth_by_year"]
    assert [(x["period"], round(x["growth"], 3)) for x in yearly] == [("2024", 0.5), ("2025", 0.6)]


def test_the_reconciliation_compares_a_year_of_monthly_revenue_with_a_yearly_row_even_when_the_row_says_monthly():
    monthly = [file_of("report", [sheet("Report", [row(4, "revenue", [100] * 12, [f"2025-{m:02d}" for m in range(1, 13)])])])]
    pnl = [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1_150], ["2025"], basis="monthly")], granularity="yearly")])]
    rec = [x for x in run(monthly + pnl)["role_metrics"]["reconciliation"] if x["period"] == "2025"]
    assert len(rec) == 1 and rec[0]["status"] == "differs" and rec[0]["gap"] == 50


def test_the_missing_metrics_have_one_reason_each_and_the_data_gaps_table_carries_the_same_text():
    from app import verdict
    r = run(yearly_pnl(with_sm=False))
    reasons = {m["metric"]: m["reason"] for m in r["role_metrics"]["metrics"] if m["status"] != "computed"}
    top = {x["metric"]: x["reason"] for x in re_.missing_reasons(r["role_metrics"])}
    assert top == {re_.NAMES[k]: v for k, v in reasons.items() if k != "ending_arr"}, "one line, one reason, per missing metric"
    gaps = {g["item"]: g for g in verdict.data_gaps(r, [], [])}
    assert top and set(top) <= set(gaps)
    for name, reason in top.items():
        assert reason in gaps[name]["why"], (name, reason, gaps[name]["why"])
    assert top["S&M share of revenue"] == "needs a sales_marketing row"


def test_the_integrity_block_reads_the_yearly_revenue_reconciliation_of_the_map():
    from app import integrity
    monthly = [file_of("report", [sheet("Report", [row(4, "revenue", [100] * 12, [f"2025-{m:02d}" for m in range(1, 13)])])])]
    pnl = [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1_300], ["2025"], basis="yearly")], granularity="yearly")])]
    deck = [{"metric": "revenue", "period": "2025", "value": 1_200.0, "currency": "EUR", "actual_plan": "actual", "file": "deck", "page": 7}]
    bad = integrity.assess(run(monthly + pnl, deck=deck), 1, [])
    row_ = next(x for x in bad["results"] if x["check"] == "Revenue reconciliation")
    assert row_["result"] == "Red" and "1 of 1 years differ" in row_["finding"] and "page 7" in row_["source"]
    good = integrity.assess(run(monthly + [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1_200], ["2025"], basis="yearly")], granularity="yearly")])]), 0, [])
    assert next(x for x in good["results"] if x["check"] == "Revenue reconciliation")["result"] == "Green"
