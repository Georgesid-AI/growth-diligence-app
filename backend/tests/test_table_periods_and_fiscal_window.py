"""Two findings on a real audit, pinned on synthetic data only (CLAUDE.md rules 13 and 15):

A a deck table with four quarter columns and two rows ("Sales (Annual Contracted Value)", "Recognised Revenue") gives, per row, N figures
with N periods, each the period of its own column header; the contracted row is Contract value, never Revenue · B a claim whose date is
the bare year ("2021") reads the 12 months of that fiscal year from three years of actuals, whatever year the other two are."""
import copy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import server  # noqa: E402
from test_claim_matching import RUNS, results_for, run_claim, settings  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app.decks import claims  # noqa: E402

QUARTERS = ("Q1 2021", "Q2 2021", "Q3 2021", "Q4 2021")
ACV = (120000, 156000, 130000, 140000)
REV = (100000, 125000, 127000, 148000)
EXPECTED = [("Q1 2021", "2021-01-01", "2021-03-31"), ("Q2 2021", "2021-04-01", "2021-06-30"),
            ("Q3 2021", "2021-07-01", "2021-09-30"), ("Q4 2021", "2021-10-01", "2021-12-31")]


def cell(r, c, text):
    return {"page": 5, "kind": "table", "table": 1, "row": r, "col": c, "text": text}


TITLE = {"page": 5, "kind": "text", "text": "2021 COMPARISON SALES vs RECOGNISED REVENUE", "bbox": [0.1, 0.1, 0.6, 0.13], "box": 1,
         "title": True}


def money(v):
    return f"€ {v:,.2f}"


def table(one_cell: bool):
    """Header row of four quarters, then the two rows: a figure per cell (pptx) or the four figures in one cell (borderless PDF)."""
    def row(r, label, values):
        return [cell(r, 1, label), *([cell(r, 2, " ".join(map(money, values)))] if one_cell
                                     else [cell(r, c + 2, money(v)) for c, v in enumerate(values)])]
    header = [cell(1, 2, " ".join(QUARTERS))] if one_cell else [cell(1, c + 2, q) for c, q in enumerate(QUARTERS)]
    return [TITLE, *header, *row(2, "Sales (Annual Contracted Value)", ACV), *row(3, "Recognised Revenue", REV)]


@pytest.mark.parametrize("one_cell", [False, True])
def test_a_each_figure_of_a_row_takes_the_period_of_its_own_quarter_and_the_acv_row_is_contract_value(one_cell):
    found = claims.detect_candidates(table(one_cell), "deck.pdf")
    rows = {tuple(i["value"] for i in c["by_period"]): c for c in found if c.get("by_period")}
    assert set(rows) == {ACV, REV}
    for values, c in rows.items():
        assert [(i["period_text"], i["period_start"], i["period_end"]) for i in c["by_period"]] == EXPECTED
    for r in range(len(found)):
        found[r].update(id=f"k{r}", status="approved")
    run = RUNS["A"]
    register = cm.build_register(found, results_for(run), settings(run))
    metrics = {x["claimed_value"]: x["metric"] for x in register if x["claimed_value"]}
    assert {metrics[v] for v in ACV} == {cm.CONTRACT_VALUE}, "contracted value is never engine revenue"
    assert {metrics[v] for v in REV} == {"Revenue"}


# ---------------------------------------------------------------------------
# B. A bare-year date over three years of actuals
# ---------------------------------------------------------------------------
YEARS = (2019, 2020, 2021)
MONTHLY = {y: 1000 * (y - 2018) for y in YEARS}                 # a different level per year, so a wrong year shows


def three_years():
    r = copy.deepcopy(results_for(RUNS["A"]))
    months = [f"{y}-{m:02d}" for y in YEARS for m in range(1, 13)]
    r["as_of_month"] = "2021-12"
    r["revenue_series"].update(months=months, data=[{"month": m, "total": MONTHLY[int(m[:4])]} for m in months])
    r["metric_periods"]["revenue_series"] = {"first": "2019-01", "last": "2021-12", "missing": []}
    return r


@pytest.mark.parametrize("year", YEARS)
def test_b_a_fiscal_year_claim_with_a_bare_year_reads_that_years_twelve_months(year):
    row = run_claim({"claim_type": "revenue", "snippet": f"FY{year} revenue", "value": 1, "target_date": str(year),
                     "period_text": str(year)}, results=three_years(), as_of_month="2021-12")
    assert (row["period_start"], row["period_end"]) == (f"{year}-01-01", f"{year}-12-31")
    assert row["observed_value"] == 12 * MONTHLY[year]
    assert row["observed_at"] == f"{year}-01 to {year}-12"


def test_b_without_a_fiscal_year_end_setting_the_year_is_the_calendar_year():
    """The audit's setting missing or empty falls back to December (server._fiscal_year_end), never to another month or to a crash."""
    assert [server._fiscal_year_end(a) for a in (None, {}, {"fiscal_year_end": None})] == [12, 12, 12]
    assert claims.period_range("2021") == ("2021-01-01", "2021-12-31")
    assert claims.period_range("2021", 3) == ("2020-04-01", "2021-03-31")
