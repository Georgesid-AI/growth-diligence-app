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
