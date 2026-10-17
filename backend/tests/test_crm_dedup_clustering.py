"""CRM de-duplication and quarter-end clustering (docs/specs/crm-dedup-clustering.md).

Rows of one deal repeated with the same deal ID, stage and dates are counted once in every deal figure and flagged; the share of
won deals closed in the last 10 days of a quarter is the integrity check's result. Python only, no network, no model.
"""
import copy
import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("motor")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import contract_fixtures as cf  # noqa: E402
import growth_engine as ge  # noqa: E402
import server  # noqa: E402
from app import integrity as ig  # noqa: E402
from claim_matching_support import engine_results  # noqa: E402
from test_claim_register_api import AUDIT  # noqa: E402

CFG = {"reporting_currency": "EUR", "target_arr": 1_000_000, "target_date": "2026-12-31", "fx": {"EUR": 1.0},
       "billing_terms": {}, "default_l": 1, "as_of_month": None}
SOURCES = {"revenue": {"file": "revenue.csv", "sheet": "Sheet1"}, "crm": {"file": "crm.csv", "sheet": "Deals"}}
HEADERS = ("Deal ID", "Created", "Close Date", "Stage", "Amount")
CRM_MAP = {"deal_id": "Deal ID", "created_date": "Created", "close_date": "Close Date", "stage": "Stage", "amount": "Amount"}
NO_ID_MAP = {k: v for k, v in CRM_MAP.items() if k != "deal_id"}


def _revenue():
    """Three customers billed monthly through 2024: the as-of month defaults to 2024-12, so no deal below is cut."""
    rows = [(f"C{c}", f"{m}-01", 1000, "EUR") for c in range(3) for m in pd.period_range("2023-01", "2024-12", freq="M")]
    df = pd.DataFrame(rows, columns=["customer_id", "invoice_date", "amount", "currency"])
    df["_row"] = range(2, len(df) + 2)
    return df


def _run(rows, mapping=CRM_MAP):
    """The engine over CRM rows (deal ID, created, close, stage, amount) read as an upload reads them: sheet rows from 2."""
    deals = server.normalize([dict(zip(HEADERS, r)) for r in rows], "crm", mapping)
    return server.sanitize(ge.compute_all(_revenue(), deals, None, CFG, SOURCES))


def _won(dates, prefix="W"):
    """One won deal per close date, created 30 days before it."""
    return [(f"{prefix}{i}", (pd.Timestamp(d) - pd.Timedelta(days=30)).date().isoformat(), d, "Closed Won", 1000)
            for i, d in enumerate(dates)]


def _row(results, check="Quarter-end clustering"):
    """(coverage row, Block A row or None, the whole assessment) of one check."""
    assessed = ig.assess(results, deck_count=0, candidates=[])
    return (next(r for r in assessed["coverage"] if r["check"] == check),
            next((r for r in assessed["results"] if r["check"] == check), None), assessed)


# Ten closes in the last 10 days of a calendar quarter (September has 30 days: the 21st is inside), and fifteen that are not:
# the 21st of March is the 11th day from the end, and a late day in a month that ends no quarter does not count.
LATE = ["2023-03-25", "2023-06-28", "2023-09-21", "2023-12-31", "2024-03-22", "2024-06-30", "2024-09-28", "2024-12-24",
        "2023-03-30", "2024-06-25"]
NOT_LATE = ["2023-03-21", "2023-02-27", "2023-11-29", "2023-12-21", "2024-06-20"] + [f"2024-{m:02d}-05" for m in range(1, 11)]


# --- section 1: de-duplication -----------------------------------------------------------------------------------------------

def test_line_item_repeats_count_the_deal_once_and_the_flag_shows_the_counts():
    rows = [("D1", "2024-01-10", "2024-02-20", "Closed Won", 100),       # one deal exported as three line items;
            ("D1", "2024-01-10", "2024-02-20", "closed won ", 200),      # the stage as the engine reads it
            ("D1", "2024-01-10", "2024-02-20", "Closed Won", 300),
            ("L1", "2024-01-10", "2024-03-01", "Closed Lost", 50),
            ("L2", "2024-01-15", "2024-03-05", "Closed Lost", 50),
            ("", "2024-01-15", "2024-03-05", "Closed Lost", 50),           # a blank deal ID is never a repeat
            ("", "2024-01-15", "2024-03-05", "Closed Lost", 50)]
    results = _run(rows)
    assert (results["win_rate"]["won"], results["win_rate"]["lost"]) == (1, 4), "the deal counts once, blank IDs stay"
    assert results["sales_cycle"]["n"] == 1 and results["sales_cycle"]["median_days"] == 41
    assert results["anomalies"]["deals_duplicate_id"] == {"rows": 3, "distinct_ids": 1, "collapsed": 2, "rows_list": [2, 3, 4]}


def test_the_same_deal_id_with_a_different_stage_or_date_keeps_every_row_and_is_flagged():
    rows = [("D2", "2024-01-10", "2024-02-20", "Closed Won", 100),
            ("D2", "2024-01-10", "2024-02-20", "Closed Lost", 100),
            ("D3", "2024-01-10", "2024-02-20", "Closed Won", 100),
            ("D3", "2024-01-10", "2024-03-20", "Closed Won", 100)]
    results = _run(rows)
    assert (results["win_rate"]["won"], results["win_rate"]["lost"]) == (3, 1)
    assert results["anomalies"]["deals_duplicate_id"] == {"rows": 4, "distinct_ids": 2, "collapsed": 0, "rows_list": [2, 3, 4, 5]}


def test_without_a_mapped_deal_id_nothing_is_collapsed_and_the_flag_reads_zero():
    rows = [("D1", "2024-01-10", "2024-02-20", "Closed Won", 100)] * 2
    results = _run(rows, NO_ID_MAP)
    assert results["win_rate"]["won"] == 2
    assert results["anomalies"]["deals_duplicate_id"] == {"rows": 0, "distinct_ids": 0, "collapsed": 0, "rows_list": []}


def test_a_deal_figure_read_from_another_upload_counts_repeats_once():
    """Compute before Missing (growth_engine.can_compute) runs the same calculation on another file: the same collapse applies."""
    rows = [("D1", "2024-01-10", "2024-02-20", "Closed Won", 100)] * 3 + [("L1", "2024-01-10", "2024-03-01", "Closed Lost", 50)]
    frame = server.normalize([dict(zip(HEADERS, r)) for r in rows], "crm", CRM_MAP)
    assert (ge._run_analysis("win_rate", frame, {"as_of": None})["won"], ge._run_analysis("sales_cycle", frame, {"as_of": None})["n"]) == (1, 1)


def test_the_collapse_runs_after_the_as_of_cut():
    """D1 closed after the as-of month: it is cut, so its repeats are neither counted nor flagged; D2's are."""
    rows = [("D1", "2024-01-10", "2024-02-20", "Closed Won", 100), ("D1", "2024-01-10", "2024-02-20", "Closed Won", 100),
            ("D2", "2024-01-02", "2024-01-20", "Closed Won", 100), ("D2", "2024-01-02", "2024-01-20", "Closed Won", 100)]
    deals = server.normalize([dict(zip(HEADERS, r)) for r in rows], "crm", CRM_MAP)
    results = server.sanitize(ge.compute_all(_revenue(), deals, None, {**CFG, "as_of_month": "2024-01"}, SOURCES))
    assert results["win_rate"]["won"] == 1 and results["win_rate"]["excluded_after_as_of"] == 2
    assert results["anomalies"]["deals_duplicate_id"] == {"rows": 2, "distinct_ids": 1, "collapsed": 1, "rows_list": [4, 5]}


# --- section 2: quarter-end clustering -----------------------------------------------------------------------------------------

def test_forty_percent_of_won_deals_in_the_last_ten_days_of_a_quarter_is_red_and_cites_the_deals_rows():
    results = _run(_won(LATE) + _won(NOT_LATE, "N"))
    row, ran, _ = _row(results)
    assert (row["status"], row["result"], row["reason"]) == (ig.COMPLETED, "Red", None)
    assert ran == {"check": "Quarter-end clustering", "result": "Red",
                   "finding": "40% of 25 won deals closed in the last 10 days of a quarter (chance: 11%)",
                   "source": "crm.csv · Deals · rows 2–26 (25 rows)"}


def test_an_even_spread_of_close_dates_is_green():
    dates = [(pd.Timestamp("2023-01-03") + pd.Timedelta(days=9 * i)).date().isoformat() for i in range(40)]
    row, ran, _ = _row(_run(_won(dates)))
    assert row["status"] == ig.COMPLETED and ran["result"] == "Green"
    assert ran["finding"] == "10% of 40 won deals closed in the last 10 days of a quarter (chance: 11%)"


def test_eight_won_deals_are_not_applicable_and_out_of_the_requests_and_the_count():
    """George, 17 Oct 2026 (follow-up to PR 123): below 20 won deals the row reads Not applicable – fewer than 20 won deals (N); it is
    no data request and leaves the denominator, so it is neither completed nor missing."""
    results = _run(_won(LATE[:4] + NOT_LATE[:4]) + [(f"L{i}", "2024-01-10", "2024-03-01", "Closed Lost", 50) for i in range(30)])
    row, ran, assessed = _row(results)
    assert (row["status"], row["reason"], row["result"]) == (ig.NOT_APPLICABLE, "Fewer than 20 won deals (8)", None)
    assert ran is None, "a check that did not complete is not in Block A"
    assert not [r for r in assessed["data_requests"] if r.startswith("Quarter-end clustering")]
    assert "Quarter-end clustering" not in assessed["blocked"]
    statuses = {r["check"]: r["status"] for r in assessed["coverage"]}
    assert assessed["applicable"] == sum(1 for s in statuses.values() if s != ig.NOT_APPLICABLE) == 4
    nineteen = _row(_closes(19, 0))[0]
    assert (nineteen["status"], nineteen["reason"]) == (ig.NOT_APPLICABLE, "Fewer than 20 won deals (19)")


def test_line_item_repeats_that_would_push_a_green_file_to_amber_are_collapsed():
    """20 deals, 3 closing at a quarter end (15%, Green). Each of the three repeated as two more line items: read row by row
    that is 9 of 26 (35%, Amber); collapsed it stays 3 of 20."""
    late = _won(LATE[:3])
    rows = late * 3 + _won(NOT_LATE + ["2024-11-05", "2024-12-05"], "N")
    assert len(rows) == 26
    collapsed = _row(_run(rows))[1]
    assert (collapsed["result"], collapsed["finding"]) == (
        "Green", "15% of 20 won deals closed in the last 10 days of a quarter (chance: 11%)")
    row_by_row = _row(_run(rows, NO_ID_MAP))[1]
    assert (row_by_row["result"], row_by_row["finding"]) == (
        "Amber", "35% of 26 won deals closed in the last 10 days of a quarter (chance: 11%)"), "the fixture is Amber uncollapsed"
    assert _run(rows)["anomalies"]["deals_duplicate_id"] == {"rows": 9, "distinct_ids": 3, "collapsed": 6,
                                                             "rows_list": [2, 3, 4, 5, 6, 7, 8, 9, 10]}


def test_quarters_follow_the_fiscal_year_end():
    results = _run(_won(LATE) + _won(NOT_LATE, "N"))
    assert ig.clustering(results, fiscal_year_end=6)["result"] == "Red", "a June year-end has the calendar quarters"
    january = ig.clustering(results, fiscal_year_end=1)
    assert (january["result"], january["finding"]) == (
        "Green", "0% of 25 won deals closed in the last 10 days of a quarter (chance: 11%)"), "quarters end in Jan, Apr, Jul, Oct"
    row = next(r for r in ig.assess(results, deck_count=0, candidates=[], fiscal_year_end=1)["results"]
               if r["check"] == "Quarter-end clustering")
    assert row["result"] == "Green"


def _closes(n, late, late_month="2024-03"):
    """Stored won-deal counts: `late` of `n` won deals closing in the last 10 days of `late_month`, the rest in February."""
    by_month = [{"month": "2024-02", "won": n - late, "last_10_days": n - late}, {"month": late_month, "won": late, "last_10_days": late}]
    return {"won_deal_closes": {"by_month": by_month, "source": {"file": "crm.csv", "sheet": "Deals", "rows": "rows 2–9"}}}


@pytest.mark.parametrize("n, late, result", [
    (100, 19, "Green"), (100, 20, "Amber"), (100, 35, "Amber"), (100, 36, "Red"),
    (37, 13, "Amber"),          # 35.1% reads 35%: the band is read from the percent shown
    (20, 0, "Green"),           # 20 won deals complete the check
])
def test_the_bands_are_green_below_20_amber_from_20_to_35_and_red_above(n, late, result):
    """February's closes are all in its last 10 days, and February ends no calendar quarter: they never count."""
    row, ran, _ = _row(_closes(n, late))
    assert row["status"] == ig.COMPLETED and ran["result"] == result


def test_no_crm_or_no_close_date_is_blocked_with_the_data_request():
    for results in ({}, {"won_deal_closes": None}, engine_results(("revenue", "pnl"))):
        row, ran, assessed = _row(results)
        assert (row["status"], row["reason"], ran) == (ig.BLOCKED, "CRM file mapped (stage, close date)", None)
        assert "Quarter-end clustering: CRM file mapped (stage, close date)" in assessed["data_requests"]
    rows = [("D1", "2024-01-10", "2024-02-20", "Closed Won", 100)]
    assert _run(rows, {k: v for k, v in CRM_MAP.items() if k != "close_date"})["won_deal_closes"] is None


def test_the_stored_block_holds_counts_by_month_and_no_amount():
    results = _run(_won(LATE[:2]) + [("L1", "2024-01-10", "2023-03-29", "Closed Lost", 50),        # lost: not read
                                     ("X1", "2024-01-10", "2023-06-29", "Closed Won", 50)])       # closes before created
    block = results["won_deal_closes"]
    assert block["by_month"] == [{"month": "2023-03", "won": 1, "last_10_days": 1}, {"month": "2023-06", "won": 1, "last_10_days": 1}]
    assert block["source"]["row_numbers"] == [2, 3] and block["source"]["file"] == "crm.csv"
    assert "amount" not in str(block).lower() and "1000" not in str(block["by_month"])


# --- sample_data -----------------------------------------------------------------------------------------------------------------

def test_sample_data_is_unchanged_and_its_clustering_is_green():
    results = engine_results()
    assert results["anomalies"]["deals_duplicate_id"] == {"rows": 0, "distinct_ids": 0, "collapsed": 0, "rows_list": []}
    sc, wr = results["sales_cycle"], results["win_rate"]
    assert (sc["median_days"], sc["n"], sc["iqr"], sc["source"]["rows"]) == (58.5, 36, [39.0, 74.0], "rows 2–121 (112 rows)")
    assert (wr["won"], wr["lost"], wr["win_rate_pct"], wr["excluded_after_as_of"]) == (36, 54, 0.4, 8)
    row, ran, _ = _row(results)
    assert row["status"] == ig.COMPLETED
    assert (ran["result"], ran["finding"]) == ("Green", "14% of 36 won deals closed in the last 10 days of a quarter (chance: 11%)")


def test_the_memo_leaves_fewer_than_20_won_deals_out_of_the_requests_and_still_exports():
    """integrity-coverage.md section 3: a Not applicable check is never a request, so Appendix B does not list the clustering check
    below 20 won deals; the memo still exports."""
    from app import ic_memo as im
    from test_ic_memo import inputs
    stored = copy.deepcopy(engine_results())        # cached: never changed in place
    deals = server.normalize([dict(zip(HEADERS, r)) for r in _won(LATE + NOT_LATE[:5])], "crm", CRM_MAP)
    stored["won_deal_closes"] = server.sanitize(ge.compute_all(_revenue(), deals, None, CFG, SOURCES))["won_deal_closes"]
    assert stored["won_deal_closes"]["source"]["rows"] == "rows 2–16 (15 rows)"
    text = im.build_memo(**inputs(stored=stored))
    assert "Quarter-end clustering" not in text.split("## Appendix B")[1].split("## Appendix C")[0]
    row = next(line for line in text.split("\n") if line.startswith("| Data reliability"))
    assert "Completed 4 of 4 applicable checks" in row, "the check leaves the denominator"


def test_the_endpoint_reads_the_audits_fiscal_year_end(register_api):
    client, db = register_api
    finding = lambda: next(r for r in client.get(f"/api/audits/{AUDIT}/integrity").json()["results"]  # noqa: E731
                           if r["check"] == "Quarter-end clustering")["finding"]
    assert finding().startswith("14% of 36 won deals")
    db["audits"].docs[0]["fiscal_year_end"] = 2
    assert finding().startswith("17% of 36 won deals"), "quarters ending in Feb, May, Aug and Nov"


# --- follow-up to PR 123: the repeated rows on screen, in the xlsx and in the memo's count ----------------------------------------

REPEATS = {"rows": 9, "distinct_ids": 3, "collapsed": 6, "rows_list": [2, 3, 4]}


def test_the_xlsx_anomalies_sheet_lists_crm_rows_sharing_a_deal_id_after_the_deals_closed_before_created():
    import openpyxl
    stored = cf.stored(anomalies=cf.anomalies(deals_duplicate_id=REPEATS))
    wb = openpyxl.load_workbook(server.build_export_workbook({"company_name": "Acme"}, stored))
    rows = [tuple(c.value for c in r) for r in wb["Anomalies"].iter_rows(min_row=2)]
    labels = [r[0] for r in rows]
    at = labels.index("Deals close-before-created (excluded)")
    assert rows[at + 1] == ("CRM rows sharing a deal ID", 6, "3 distinct deal IDs")


def test_the_memo_anomaly_count_adds_the_collapsed_rows_as_the_screen_lists_them():
    from app import ic_memo as im
    assert im.anomaly_count(cf.stored(anomalies=cf.anomalies(deals_duplicate_id=REPEATS))) == 6
    assert im.anomaly_count(cf.stored(anomalies=cf.anomalies())) == 0
