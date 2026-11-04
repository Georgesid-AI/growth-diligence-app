"""A cost role mapped as part rows with no total row (S&M as 8 lines) is the sum of its parts; the Data gaps table names, for every yearly P&L
row, the data that resolves it. Synthetic maps only."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from test_memo_cleanup_4f import MONTHS_41, YEARS  # noqa: E402,F401
from test_role_engine import file_of, metric, row, run, series, sheet  # noqa: E402

from app import report_text, role_engine, verdict  # noqa: E402

PLAN_YEARS = ["2026", "2027", "2028"]
PARTS = ["Sales", "HR costs", "Marketing", "Events", "Tools", "Travel", "Agencies", "Other"]
BASE = [10, 20, 30, 40, 50, 60, 70, 120]            # sums to 400
ACTUAL_K, PLAN_K = [1, 1.25, 1.5], [1.75, 2, 2.25]


def both(n, role, actual, plan, **kw):
    r = row(n, role, actual, YEARS, basis="yearly", **kw)
    r["plan_series"] = series(plan, PLAN_YEARS, first_row=n, col0=6)
    return r


def part_rows(role="sales_marketing", first=10, parent=None):
    out = []
    for i, (name, base) in enumerate(zip(PARTS, BASE)):
        r = both(first + i, role, [base * k for k in ACTUAL_K], [base * k for k in PLAN_K], segment=name)
        if parent:
            r["parent_row"] = parent
        out.append(r)
    return out


def pnl(sm_rows=None, with_split=True):
    rows = [both(4, "revenue", [1_000, 1_500, 2_400], [3_000, 3_600, 4_200]),
            both(5, "cost_of_revenue", [300, 450, 600], [700, 800, 900]),
            both(6, "opex", [700, 800, 1_000], [1_000, 1_160, 1_320])]
    rows += part_rows() if sm_rows is None else sm_rows
    if with_split:
        rows += [row(30, "rnd", [200, 240, 280], PLAN_YEARS, basis="yearly", plan=True), row(31, "ga", [100, 120, 140], PLAN_YEARS, basis="yearly", plan=True)]
    return [file_of("pnl", [sheet("P&L", rows, granularity="yearly")])]


def test_s_and_m_as_part_rows_with_no_total_is_the_sum_of_the_parts():
    r = run(pnl())
    sm = metric(r, "sm_share")
    assert sm["status"] == "computed" and sm["period"] == "2025"
    assert sm["value"] == pytest.approx(600 / 2_400)
    cells = set(sm["source"]["cells"])
    assert {f"D{n}" for n in range(10, 18)} <= cells and "D4" in cells, "every summed cell is cited"
    cac = metric(r, "yearly_cac_payback")
    assert cac["status"] == "computed" and cac["value"] == pytest.approx(12 * 600 / ((2_400 - 1_500) * 0.75), rel=1e-3)
    assert {f"D{n}" for n in range(10, 18)} <= set(cac["source"]["cells"]), "CAC cites every summed S&M cell"


def test_the_rnd_ga_estimate_fires_on_summed_parts():
    r = run(pnl())
    rnd, ga = metric(r, "rnd_expense"), metric(r, "ga_expense")
    for m in (rnd, ga):
        assert m["estimate"] is True and m["status"] == "computed", m["reason"]
    assert rnd["value"] == pytest.approx((1_000 - 600) * 2 / 3) and ga["value"] == pytest.approx((1_000 - 600) / 3)
    assert {f"D{n}" for n in range(10, 18)} <= set(rnd["source"]["cells"])


def test_a_part_whose_parent_is_mapped_to_the_role_with_a_value_is_skipped():
    total = both(9, "sales_marketing", [400, 500, 600], [700, 800, 900])
    r = run(pnl([total, *part_rows(parent=9)]))
    sm = metric(r, "sm_share")
    assert sm["value"] == pytest.approx(600 / 2_400) and sm["source"]["cells"].count("D9") == 1
    assert not {f"D{n}" for n in range(10, 18)} & set(sm["source"]["cells"]), "total and parts never both"


def test_no_reason_says_segment_rows_the_calculation_uses_one_total_row():
    for files in (pnl(), pnl(with_split=False)):
        text = " ".join(str(m["reason"]) for m in run(files)["role_metrics"]["metrics"])
        assert "segment rows" not in text and "uses one total row" not in text
    only_segments = [file_of("f", [sheet("S", [row(4, "customers", [5, 6], YEARS[:2], basis="yearly", segment="EU", unit="count")], granularity="yearly")])]
    assert "uses one total row" not in (report_text.missing_reason(role_engine.build_table(only_segments), ("customers",), None) or "")


def test_a_part_row_set_without_an_actual_split_gives_its_own_estimate_reason():
    r = run(pnl(with_split=False))
    rnd = metric(r, "rnd_expense")
    assert rnd["status"] != "computed" and rnd["reason"].startswith("No estimate: ")


@pytest.mark.parametrize("name", ["S&M share of revenue", "R&D share of revenue", "G&A share of revenue", "R&D expense", "G&A expense", "CAC payback (yearly)"])
def test_every_yearly_pnl_gap_names_the_data_that_resolves_it(name):
    # S&M mapped in plan years only, no R&D/G&A: every yearly row fails with a reason
    rows = [both(4, "revenue", [1_000, 1_500, 2_400], [3_000, 3_600, 4_200]), both(6, "opex", [700, 800, 1_000], [1_000, 1_160, 1_320]),
            row(10, "sales_marketing", [500, 600, 700], PLAN_YEARS, basis="yearly", plan=True)]
    files = [file_of("pnl", [sheet("P&L", rows, granularity="yearly")])]
    table = role_engine.build_table(files)
    results = report_text.apply_reasons(run(files), table)
    gaps = {g["item"]: g for g in verdict.data_gaps(results, [], [], table=table)}
    assert name in gaps, sorted(gaps)
    assert gaps[name]["requested"].strip(), name
    assert "P&L" in gaps[name]["requested"] and gaps[name]["requested"][0].isupper()


# ---------------------------------------------------------------------------
# A cost role the engine could not compute names the cells of every row it sums, never "()"
# ---------------------------------------------------------------------------
def test_a_cost_role_of_part_rows_the_engine_cannot_compute_names_the_cells_of_every_part():
    # S&M parts hold 2026 only: no period at or before the as-of month is shared with revenue, so the engine gives no value
    parts = [row(10 + i, "sales_marketing", [base], ["2026"], basis="yearly", segment=name) for i, (name, base) in enumerate(zip(PARTS, BASE))]
    files = [file_of("pnl", [sheet("P&L", [row(4, "revenue", [1_000, 1_500, 2_400, 3_000], YEARS + ["2026"], basis="yearly"), *parts], granularity="yearly")])]
    table = role_engine.build_table(files)
    reason = report_text.missing_reason(table, ["revenue", "sales_marketing"], "the revenue row and the sales_marketing row share no period at or before the as-of month")
    assert "()" not in reason, reason
    assert "S&M row read (P&L!B10, B11, B12, B13, B14, B15, B16, B17)" in reason, reason


# ---------------------------------------------------------------------------
# The total-row guard: a row that equals the sum of the other rows of the role (within 1 %) is the total; its parts are not counted twice
# ---------------------------------------------------------------------------
TOTAL_NOTE = "8 rows summed to the total row; parts not counted twice"


def unlinked_total(values=(400, 500, 600), plan=(700, 800, 900)):
    return both(9, "sales_marketing", list(values), list(plan))


def test_an_unlinked_total_row_is_read_as_the_total_and_its_parts_are_skipped():
    table = role_engine.build_table(pnl([unlinked_total(), *part_rows()]))
    rec = role_engine.cost_row(table, "sales_marketing", "yearly")
    assert rec["actual"]["2025"] == (600, "D9") and rec["actual"]["2023"] == (400, "B9"), "the total's cell, not the parts'"
    assert rec["note"] == TOTAL_NOTE
    plan = role_engine.sum_role(table, "sales_marketing", "yearly", key="plan")
    assert plan["plan"]["2026"] == (700, "F9") and plan["note"] == TOTAL_NOTE, "the plan series is read on its own"


def test_the_guard_needs_three_rows_of_the_role():
    rows = [both(9, "rnd", [100, 100, 100], [1, 1, 1]), both(10, "rnd", [100, 100, 100], [1, 1, 1])]
    table = role_engine.build_table(pnl(sm_rows=rows))
    rec = role_engine.cost_row(table, "rnd", "yearly")
    assert rec["actual"]["2025"] == (200, "D9+D10") and not rec.get("note"), "two equal rows are two rows, never a total and its part"


def test_the_guard_reads_within_one_percent_and_not_beyond():
    close = [unlinked_total((403, 504, 605)), *part_rows()]                                   # 0.7 % above the parts
    rec = role_engine.cost_row(role_engine.build_table(pnl(close)), "sales_marketing", "yearly")
    assert rec["actual"]["2025"] == (605, "D9") and rec["note"] == TOTAL_NOTE
    far = [unlinked_total((410, 510, 610)), *part_rows()]                                     # 1.7 % above the parts in 2025
    rec = role_engine.cost_row(role_engine.build_table(pnl(far)), "sales_marketing", "yearly")
    assert rec["actual"]["2025"] == (1_210, "D9+" + "+".join(f"D{n}" for n in range(10, 18))) and not rec.get("note")


def test_the_guard_needs_one_row_that_is_the_sum_and_no_other():
    rows = [both(9, "rnd", [10, 10, 10], [1, 1, 1]), both(10, "rnd", [10, 10, 10], [1, 1, 1]), both(11, "rnd", [0, 0, 0], [0, 0, 0])]
    rec = role_engine.cost_row(role_engine.build_table(pnl(sm_rows=rows)), "rnd", "yearly")
    assert rec["actual"]["2025"] == (20, "D9+D10+D11") and not rec.get("note"), "two rows each equal the others' sum: no total is read"


def test_the_guard_runs_before_the_parent_rule_on_every_row_of_the_role():
    """A total that links 2 of its 8 parts: the guard reads all 9 rows, the total equals the sum of the other 8 within 1 %, so the total alone is
    read; the 6 unlinked parts are not added to it and the total's cell is cited once."""
    parts = part_rows()
    parts[0]["parent_row"] = parts[1]["parent_row"] = 9
    rec = role_engine.cost_row(role_engine.build_table(pnl([unlinked_total(), *parts])), "sales_marketing", "yearly")
    assert rec["actual"]["2025"] == (600, "D9") and rec["note"] == TOTAL_NOTE
    sm = metric(run(pnl([unlinked_total(), *parts])), "sm_share")
    assert sm["value"] == pytest.approx(600 / 2_400) and sm["source"]["cells"].count("D9") == 1
    assert not {f"D{n}" for n in range(10, 18)} & set(sm["source"]["cells"]), "no part is added to the total"


def test_a_forecast_row_with_a_segment_label_enters_the_plan_like_any_other_plan_row():
    """Plan S&M as 8 `forecast` rows of the sm_expense line, each with a segment label and no total: the plan S&M share of every plan year is the
    parts' sum over plan revenue, and every part cell is cited."""
    rows = [both(4, "revenue", [1_000, 1_500, 2_400], [3_000, 3_600, 4_200]), both(5, "cost_of_revenue", [300, 450, 600], [700, 800, 900]),
            both(6, "opex", [700, 800, 1_000], [1_000, 1_160, 1_320])]
    for i, (name, base) in enumerate(zip(PARTS, BASE)):
        r = row(10 + i, "forecast", [base * k for k in PLAN_K], PLAN_YEARS, basis="yearly", actual_plan="plan", plan=True, segment=name)
        r["metric"] = "sm_expense"
        r["plan_series"] = series([base * k for k in PLAN_K], PLAN_YEARS, first_row=10 + i, col0=6)
        rows.append(r)
    r = run([file_of("pnl", [sheet("P&L", rows, granularity="yearly")])])
    trend = {row_["metric"]: row_ for row_ in r["role_metrics"]["pnl_trend"]["rows"]}
    plan = {v["period"]: v for v in trend["sm_share"]["values"] if v["kind"] == "plan"}
    assert sorted(plan) == PLAN_YEARS, "every plan year has a plan S&M share"
    assert plan["2026"]["value"] == pytest.approx(700 / 3_000) and plan["2028"]["value"] == pytest.approx(900 / 4_200)
    assert set(plan["2026"]["cells"]) == {"F4", *(f"F{n}" for n in range(10, 18))}, plan["2026"]["cells"]
    view = role_engine.plan_view(role_engine.build_table([file_of("pnl", [sheet("P&L", rows, granularity="yearly")])]))
    assert role_engine.sum_role(view, "sales_marketing", "yearly", key="plan")["plan"]["2027"] == (800, "+".join(f"G{n}" for n in range(10, 18)))


def test_the_total_cell_is_cited_and_the_note_is_in_the_method_text_of_the_share_the_payback_and_the_estimate():
    r = run(pnl([unlinked_total(), *part_rows()]))
    sm = metric(r, "sm_share")
    assert sm["value"] == pytest.approx(600 / 2_400) and sm["source"]["cells"].count("D9") == 1
    assert not {f"D{n}" for n in range(10, 18)} & set(sm["source"]["cells"]) and sm["source"]["rule"].endswith("; " + TOTAL_NOTE), sm["source"]["rule"]
    cac = metric(r, "yearly_cac_payback")
    assert cac["status"] == "computed" and "D9" in cac["source"]["cells"] and not {f"D{n}" for n in range(10, 18)} & set(cac["source"]["cells"])
    assert TOTAL_NOTE in cac["source"]["rule"], cac["source"]["rule"]
    rnd = metric(r, "rnd_expense")
    assert rnd["estimate"] is True and rnd["value"] == pytest.approx((1_000 - 600) * 2 / 3), rnd["reason"]
    assert "D9" in rnd["source"]["cells"] and not {f"D{n}" for n in range(10, 18)} & set(rnd["source"]["cells"])
    assert TOTAL_NOTE not in rnd["source"]["rule"] and "Checks passed: (a)" in rnd["source"]["rule"], "the S&M total-row note is not R&D's"


def test_without_the_guard_an_unlinked_plan_total_would_fail_check_a():
    """The plan S&M of the estimate: with the total and its parts both summed, S&M + R&D + G&A would be twice OPEX − R&D − G&A and check (a)
    would fail; the guard reads the total alone and the check passes."""
    r = run(pnl([unlinked_total(), *part_rows()]))
    assert metric(r, "ga_expense")["status"] == "computed" and "check (a)" not in str(metric(r, "ga_expense")["reason"])
    for m in run(pnl([unlinked_total(plan=(1_400, 1_600, 1_800)), *part_rows()]))["role_metrics"]["metrics"]:
        if m["metric"] == "ga_expense":
            assert m["status"] != "computed" and "check (a) failed" in m["reason"], "a plan total that is not the parts' sum is summed with them, and the check says so"
