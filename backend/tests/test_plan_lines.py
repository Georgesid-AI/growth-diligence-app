"""Commit 3: the yearly P&L trend table and the templated comparison lines of "What the plan assumes" (docs/design/pnl-lines.md).
A synthetic P&L (revenue, cost of revenue, S&M and OPEX for 2023-25; the plan for 2026-27 as forecast rows and plan cells); no client data."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from test_memo_role_metrics import build  # noqa: E402
from test_role_engine import file_of, row, run, sheet  # noqa: E402

from app import plan_lines  # noqa: E402

YEARS, PLAN = ["2023", "2024", "2025"], ["2026", "2027"]


def pnl(cogs=(300, 450, 600), plan_sm=(1_200, 1_500), plan_rnd=(600, 700), plan_ga=(400, 500), plan_opex=(2_200, 2_700), extra=()):
    def plan(n, role, values, metric=None):
        return {**row(n, role, list(values), PLAN, basis="yearly", actual_plan="plan", plan=True), **({"metric": metric} if metric else {})}
    rows = [row(4, "revenue", [1_000, 1_500, 2_400], YEARS, basis="yearly"), row(5, "cost_of_revenue", list(cogs), YEARS, basis="yearly"),
            row(6, "sales_marketing", [300, 400, 900], YEARS, basis="yearly"), row(7, "opex", [800, 1_100, 1_900], YEARS, basis="yearly"),
            plan(10, "forecast", (3_000, 4_000), "revenue"), plan(11, "forecast", (900, 1_400), "cost_of_revenue"),
            plan(12, "sales_marketing", plan_sm), plan(13, "rnd", plan_rnd), plan(14, "ga", plan_ga), plan(15, "opex", plan_opex), *extra]
    return [file_of("pnl", [sheet("P&L", rows, granularity="yearly")])]


def texts(maps, ccy="EUR"):
    return [item["text"] for item in plan_lines.lines(run(maps), ccy)]


def line(maps, start):
    found = [item for item in plan_lines.lines(run(maps), "EUR") if item["text"].startswith(start)]
    return found[0] if found else None


def test_a_rising_line_reads_the_plan_assumes_template_with_the_cells_of_both_values():
    found = line(pnl(), "Plan assumes revenue")
    assert found["text"] == "Plan assumes revenue rises from 2,400 EUR (2025) to 4,000 EUR (2027)."
    assert found["cells"] == ["D4", "C10"], "the actual cell and the plan cell it was built from"


def test_a_falling_line_reads_falls():
    assert line(pnl(), "Plan assumes gross margin")["text"] == "Plan assumes gross margin falls from 75% (2025) to 65% (2027)."


def test_a_stable_line_reads_holds_within_two_points_for_a_share():
    # S&M share 37.5% in 2025 and in 2027 (1,500 ÷ 4,000)
    assert line(pnl(), "Plan holds")["text"] == "Plan holds S&M share of revenue at about 38% (2025) through 2027."
    near = line(pnl(plan_sm=(1_200, 1_560), plan_opex=(2_200, 2_760)), "Plan holds")          # 39.0 %: 1.5 points above 37.5 %
    assert near is not None, "within ±2 points is stable"
    far = pnl(plan_sm=(1_200, 1_600), plan_opex=(2_200, 2_800))                                  # 40.0 %: 2.5 points
    assert line(far, "Plan holds") is None
    assert line(far, "Plan assumes S&M share")["text"] == "Plan assumes S&M share of revenue rises from 38% (2025) to 40% (2027)."


def test_money_is_stable_within_five_percent():
    assert _stable("money", 2_400, 2_520) and not _stable("money", 2_400, 2_521)
    assert _stable("rate", 0.375, 0.395) and not _stable("rate", 0.375, 0.396)
    assert plan_lines.MONEY_STABLE == 0.05 == __import__("app.claim_matching", fromlist=["x"]).AMOUNT_TOLERANCE


def _stable(unit, a, b):
    return plan_lines._stable(unit, a, b)


def test_the_trend_reads_rose_fell_or_moved_between_over_the_actual_years():
    assert line(pnl(), "Revenue rose")["text"] == "Revenue rose from 1,000 EUR (2023) to 2,400 EUR (2025)."
    assert line(pnl(), "Gross margin rose")["text"] == "Gross margin rose from 70% (2023) to 75% (2025)."
    flat = pnl(cogs=(300, 435, 696))                         # 70 %, 71 %, 71 %
    assert line(flat, "Gross margin moved")["text"] == "Gross margin moved between 70% and 71% over 2023–2025."
    assert line(flat, "Gross margin rose") is None


def test_an_estimate_carries_the_label_in_the_line_and_the_table_and_has_no_trend_line():
    maps = pnl()
    assert line(maps, "Plan assumes R&D")["text"] == "Plan assumes R&D share of revenue falls from 25% (2025, estimate) to 18% (2027)."
    assert line(maps, "R&D share of revenue rose") is None and line(maps, "R&D share of revenue fell") is None
    header, rows = plan_lines.table(run(maps)["role_metrics"]["pnl_trend"], "EUR")
    assert header == ["Metric", "2023", "2024", "2025", "2026 (plan)", "2027 (plan)"]
    by = {r[0]: r for r in rows}
    assert by["R&D share of revenue"][3] == "25%, estimate" and by["R&D share of revenue"][5] == "18%", "the plan values are not estimates"
    assert by["Revenue"][1:] == ["1,000 EUR", "1,500 EUR", "2,400 EUR", "3,000 EUR", "4,000 EUR"]


def test_a_missing_input_gives_no_line_and_a_dash_in_the_table():
    r = run(pnl())
    assert not [t for t in texts(pnl()) if "EBITDA" in t], "no EBITDA row: no line"
    assert plan_lines.table(r["role_metrics"]["pnl_trend"], "EUR")[1][-1] == ["EBITDA margin", "—", "—", "—", "—", "—"]
    ebitda = row(16, "ebitda", [100, 150, 400], YEARS, basis="yearly")
    assert [t for t in texts(pnl(extra=[ebitda])) if t.startswith("EBITDA margin")] == ["EBITDA margin rose from 10% (2023) to 17% (2025)."], "only actual years: no plan EBITDA"


def test_a_failed_estimate_check_gives_no_r_and_d_or_g_and_a_line_and_no_estimate_in_the_table():
    bad = pnl(plan_opex=(2_200, 3_000))                         # check (a) fails in 2027
    assert not [t for t in texts(bad) if "R&D" in t or "G&A" in t]
    rows = {r[0]: r for r in plan_lines.table(run(bad)["role_metrics"]["pnl_trend"], "EUR")[1]}
    assert rows["R&D share of revenue"][1:4] == ["—", "—", "—"] and rows["R&D share of revenue"][5] == "18%"


def test_plan_to_date_reads_behind_ahead_or_on_plan_with_the_five_percent_tolerance():
    base = {"period": "2026-06", "actual": 0, "plan": 0, "source": {"file": "f", "sheet": "s", "cells": ["S4", "S9"]}}
    ahead = plan_lines.plan_to_date_line({**base, "variance": 75.0, "variance_pct": 0.68}, "EUR")
    assert ahead["text"] == "Revenue is 75 EUR (68%) ahead of plan to June 2026." and ahead["beyond_tolerance"] and ahead["cells"] == ["S4", "S9"]
    behind = plan_lines.plan_to_date_line({**base, "variance": -1_200.0, "variance_pct": -0.123}, "EUR")
    assert behind["text"] == "Revenue is 1,200 EUR (12%) behind plan to June 2026."
    on = plan_lines.plan_to_date_line({**base, "variance": 5.0, "variance_pct": 0.05}, "EUR")
    assert on["text"] == "Revenue is on plan to June 2026." and not on["beyond_tolerance"]
    assert plan_lines.plan_to_date_line({**base, "variance": 5.0, "variance_pct": None}, "EUR") is None


def test_a_reconciliation_that_differs_reads_the_template_and_one_that_agrees_gives_no_line():
    sources = [{"kind": "file", "file": "pnl", "where": "P&L!D4", "value": 2_400.0}, {"kind": "deck", "file": "deck.pdf", "where": "page 4", "value": 1_500.0}]
    differs = {"metric": "revenue", "period": "2025", "status": "differs", "gap": 900.0, "gap_pct": 0.375, "sources": sources}
    got = plan_lines.reconciliation_lines([differs, {**differs, "period": "2024", "status": "agrees"}, {**differs, "status": "agrees_rounded"}], "EUR")
    assert [item["text"] for item in got] == ["Revenue 2025 differs across sources by 900 EUR (38%): pnl P&L!D4 2,400 EUR; deck.pdf page 4 1,500 EUR."]


def test_every_line_is_built_from_a_template_of_this_module_and_carries_cells():
    for item in plan_lines.lines(run(pnl()), "EUR"):
        assert item["cells"] and item["kind"] in ("plan_vs_past", "trend")


# --- the memo ---------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def memo_text():
    return build(run(pnl()), pnl())


def test_the_block_sits_directly_after_the_scorecard_with_the_trend_table_and_the_lines(memo_text):
    after = memo_text.split("## Scorecard")[1]
    scorecard, block = after.split("## What the plan assumes")
    assert "## " not in scorecard, "directly after the Scorecard: no section between"
    block = block.split("\n## ")[0]
    assert "| Metric | 2023 | 2024 | 2025 | 2026 (plan) | 2027 (plan) |" in block
    assert "| R&D share of revenue | 30%, estimate |" in block
    assert "- Plan assumes revenue rises from 2,400 EUR (2025) to 4,000 EUR (2027).[^" in block
    assert "- Revenue rose from 1,000 EUR (2023) to 2,400 EUR (2025).[^" in block


def test_the_cells_of_every_trend_value_are_in_appendix_c_and_the_footnotes(memo_text):
    appendix = memo_text.split("## Appendix C")[1].split("## Appendix D")[0]
    assert "Yearly P&L trend" in appendix and "| Revenue | 2027 (plan) | 4,000 EUR | pnl · P&L!C10 |" in appendix
    assert "| R&D share of revenue | 2025 | 25%, estimate |" in appendix
    assert "What the plan assumes · pnl · P&L · D4" in memo_text.split("Footnotes")[-1]


def test_a_plan_to_date_gap_beyond_tolerance_is_in_the_block_and_in_worth_flagging():
    from test_memo_role_metrics import reading_maps, reading_results
    text = build(reading_results(), reading_maps())
    line_ = "Revenue is 75 EUR (68%) ahead of plan to June 2026."
    block = text.split("## What the plan assumes")[1].split("\n## ")[0]
    flagged = text.split("## Worth flagging")[1].split("\n## ")[0]
    assert f"- {line_}" in block and f"- {line_}" in flagged
    assert "- Revenue 2025 differs across sources by 900 EUR (38%): " in block


def test_the_memo_text_has_no_glossary_pointer_and_no_internal_field_name_in_the_key_evidence_column(memo_text):
    body = memo_text.split("## Appendix B")[0]
    assert "(see glossary)" not in memo_text
    score = [item for item in body.split("## Scorecard")[1].split("\n## ")[0].splitlines() if item.startswith("| ") and "Key evidence" not in item]
    for item in score:
        evidence = item.rsplit("|", 2)[-2]
        for field in ("revenue_reconciliation", "gross_churn", "cac_payback", "acv_path", "nrr", "anomalies"):
            assert field not in evidence, (field, item)
