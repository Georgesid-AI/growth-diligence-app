"""Data integrity, results and assessment coverage (docs/specs/integrity-coverage.md; plan of 15 Oct 2026, section 2 and 7.1).

Block A lists the checks that ran with their result; Block B lists all six checks of the method with their status; the overall
conclusion is Python's, by a fixed rule, and needs at least 4 applicable checks completed with the revenue reconciliation among
them. Python only, no network, no model.
"""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import engine_results  # noqa: E402
from test_claim_register_api import AUDIT, api  # noqa: E402,F401  (the fixture)
from test_ic_memo import inputs  # noqa: E402

CHECKS = ["Revenue reconciliation", "Gaps in customer data", "Quarter-end clustering", "Smoothness", "Benford on transactions",
          "Deck-vs-deck figures"]


def _integrity():
    from app import integrity
    return integrity


def _rows(*statuses):
    """Coverage rows for the six checks, in order: (status, result) pairs."""
    return [{"check": name, "status": status, "result": result} for name, (status, result) in zip(CHECKS, statuses)]


def test_plan_2_1_two_checks_completed_and_green_four_blocked_is_insufficient_assessment_coverage_2_of_6():
    ig = _integrity()
    rows = _rows((ig.COMPLETED, "Green"), (ig.COMPLETED, "Green"), (ig.BLOCKED, None), (ig.BLOCKED, None), (ig.BLOCKED, None),
                 (ig.BLOCKED, None))
    out = ig.overall(rows)
    assert out["conclusion"] == "Insufficient assessment coverage (2 of 6)"
    assert out["code"] == "insufficient" and (out["completed"], out["applicable"]) == (2, 6)
    assert "Reliable" not in out["conclusion"]


def test_plan_2_2_benford_not_applicable_is_not_counted_in_y():
    ig = _integrity()
    rows = _rows((ig.COMPLETED, "Green"), (ig.COMPLETED, "Green"), (ig.NOT_AVAILABLE, None), (ig.NOT_AVAILABLE, None),
                 (ig.NOT_APPLICABLE, None), (ig.COMPLETED, "Green"))
    assert ig.overall(rows)["applicable"] == 5
    assessed = ig.assess(engine_results(), deck_count=1, candidates=[])
    benford = next(r for r in assessed["coverage"] if r["check"] == "Benford on transactions")
    assert benford["status"] == ig.NOT_APPLICABLE
    assert benford["reason"] == "No transaction-level file: the app ingests revenue by customer and month, not transactions."
    assert assessed["applicable"] == 5


def test_plan_2_3_a_check_blocked_by_missing_company_data_is_in_the_data_request_list():
    ig = _integrity()
    no_pnl = engine_results(("revenue", "crm"))
    assessed = ig.assess(no_pnl, deck_count=1, candidates=[])
    rec = next(r for r in assessed["coverage"] if r["check"] == "Revenue reconciliation")
    assert rec["status"] == ig.BLOCKED and rec["reason"] == "P&L with a revenue line, overlapping the revenue file's months"
    assert "Revenue reconciliation: P&L with a revenue line, overlapping the revenue file's months" in assessed["data_requests"]
    assert all(r["check"] != "Revenue reconciliation" for r in assessed["results"]), "a check that did not run is not in Block A"


def test_plan_2_3_the_memo_lists_the_blocked_check_under_requests():
    from app import ic_memo as im
    text = im.build_memo(**inputs(stored=engine_results(("revenue", "crm"))))       # no P&L: the reconciliation is blocked
    appendix_b = text.split("## Appendix B")[1].split("## Appendix C")[0]
    assert "- Revenue reconciliation: P&L with a revenue line, overlapping the revenue file's months" in appendix_b


def test_the_testco_run_completes_four_of_five_and_reads_material_concerns_from_its_red_reconciliation():
    ig = _integrity()
    assessed = ig.assess(engine_results(), deck_count=1, candidates=[])
    statuses = {r["check"]: r["status"] for r in assessed["coverage"]}
    assert [r["check"] for r in assessed["coverage"]] == CHECKS
    assert statuses == {"Revenue reconciliation": ig.COMPLETED, "Gaps in customer data": ig.COMPLETED,
                        "Quarter-end clustering": ig.NOT_AVAILABLE, "Smoothness": ig.COMPLETED,
                        "Benford on transactions": ig.NOT_APPLICABLE, "Deck-vs-deck figures": ig.COMPLETED}
    rec = next(r for r in assessed["results"] if r["check"] == "Revenue reconciliation")
    assert rec["result"] == "Red", "TestCo's window is beyond tolerance: the hard blocker"
    assert (assessed["conclusion"], assessed["completed_text"]) == ("Material concerns", "Completed 4 of 5 applicable checks")


@pytest.mark.parametrize("results, code", [
    (["Green", "Green", "Green", "Green"], "reliable"),
    (["Green", "Amber", "Green", "Green"], "needs_clarification"),
    (["Red", "Green", "Green", "Green"], "material_concerns"),
])
def test_four_completed_with_the_reconciliation_give_a_conclusion(results, code):
    ig = _integrity()
    rows = _rows(*[(ig.COMPLETED, r) for r in results], (ig.NOT_APPLICABLE, None), (ig.COMPLETED, "Green"))
    assert ig.overall(rows)["code"] == code


def test_four_completed_without_the_reconciliation_stay_insufficient():
    ig = _integrity()
    rows = _rows((ig.BLOCKED, None), (ig.COMPLETED, "Green"), (ig.COMPLETED, "Green"), (ig.COMPLETED, "Green"),
                 (ig.NOT_APPLICABLE, None), (ig.COMPLETED, "Green"))
    assert ig.overall(rows)["conclusion"] == "Insufficient assessment coverage (4 of 5)"


def test_the_endpoint_returns_both_blocks_and_the_conclusion(api):  # noqa: F811
    client, _ = api
    r = client.get(f"/api/audits/{AUDIT}/integrity")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [row["check"] for row in body["coverage"]] == CHECKS
    assert body["conclusion"].startswith("Insufficient assessment coverage")
    assert body["completed_text"] == f"Completed {body['completed']} of {body['applicable']} applicable checks"
    assert client.get("/api/audits/nope/integrity").status_code == 404


def test_the_memo_scorecard_reads_the_conclusion_and_never_the_narratives_verdict():
    from app import ic_memo as im
    from test_ic_memo import data_step
    text = im.build_memo(**inputs(narratives=[data_step("data_integrity", verdict="Reliable", headline="Reliable: the files agree.")]))
    row = next(line for line in text.split("\n") if line.startswith("| Data reliability"))
    assert "Material concerns" in row and "Completed 4 of 5 applicable checks" in row
    assert "Data integrity conclusion: Material concerns" in row
    assert "Data integrity verdict" not in text and "Reliable: the files agree." not in row


# --- section 1: the result of each completed check -----------------------------------------------------------------------------

def _rec(blocker, months):
    return {"revenue_reconciliation": {"available": True, "first": "2024-01", "last": "2024-03", "tolerance_pct": 0.02, "gap_pct": 0.01,
                                       "blocker": blocker, "by_month": [{"month": m, "gap_pct": g} for m, g in months],
                                       "source": {"revenue_file": {"file": "revenue.csv", "sheet": "CSV", "rows": "rows 2–9"},
                                                  "pnl": {"file": "pnl.csv", "sheet": "CSV", "rows": "rows 2–4"}}}}


@pytest.mark.parametrize("blocker, months, result", [
    (False, [("2024-01", 0.01), ("2024-02", -0.02)], "Green"),
    (False, [("2024-01", 0.01), ("2024-02", -0.05)], "Amber"),
    (True, [("2024-01", 0.30)], "Red"),
])
def test_the_reconciliation_is_green_amber_or_red_by_the_window_and_its_months(blocker, months, result):
    ig = _integrity()
    row = next(r for r in ig.assess(_rec(blocker, months), deck_count=0, candidates=[])["results"] if r["check"] == "Revenue reconciliation")
    assert row["result"] == result
    assert row["finding"] == "Revenue file and P&L differ by 1% over 2024-01–2024-03"
    assert row["source"] == "revenue.csv · CSV · rows 2–9; pnl.csv · CSV · rows 2–4"


def test_gaps_in_customer_data_is_amber_on_a_resumed_customer_or_a_line_without_a_customer_id():
    ig = _integrity()
    clean = {"anomalies": {"revenue_gap_then_resume": [], "revenue_missing_customer_id": {"count": 0}, "source": {"file": "revenue.csv"}}}
    found = {"anomalies": {"revenue_gap_then_resume": [{"customer": "C1"}], "revenue_missing_customer_id": {"count": 2},
                           "source": {"file": "revenue.csv"}}}
    gaps = lambda results: next(r for r in ig.assess(results, deck_count=0, candidates=[])["results"] if r["check"] == "Gaps in customer data")  # noqa: E731
    assert gaps(clean)["result"] == "Green"
    assert (gaps(found)["result"], gaps(found)["finding"]) == (
        "Amber", "1 customers whose revenue stops for over two months and resumes; 2 revenue lines without a customer ID")


def _cand(cid, deck, page, value, **over):
    c = {"id": cid, "status": "approved", "claim_type": "revenue", "value": value, "value_high": None, "currency": "EUR", "unit": None,
         "target_date": "2023", "period_start": "2023-01-01", "period_end": "2023-12-31", "snippet": "Revenue", "label_from": None,
         "date_from": None, "file": deck, "sources": [{"file": deck, "slide": page}]}
    c.update(over)
    return c


def test_deck_vs_deck_compares_the_figures_of_every_deck_and_names_the_first_pair():
    ig = _integrity()
    deck = lambda cands: next(r for r in ig.assess({}, deck_count=2, candidates=cands)["results"] if r["check"] == "Deck-vs-deck figures")  # noqa: E731
    assert deck([_cand("a", "board.pptx", 3, 1_000_000), _cand("b", "plan.pdf", 5, 1_000_000)])["result"] == "Green"
    differ = [_cand("a", "board.pptx", 3, 1_000_000), _cand("b", "plan.pdf", 5, 1_200_000)]
    row = deck(differ)
    assert row["result"] == "Amber" and row["finding"].startswith("2 deck figures differ from another of the same type, label and stated period")
    assert "board.pptx · slide 3 and plan.pdf · slide 5" in row["finding"]
    assert differ[0].get("inconsistencies") is None, "the stored candidates are not changed"
    assert deck([_cand("a", "board.pptx", 3, 1_000_000), _cand("b", "plan.pdf", 5, 1_200_000, date_from="FY2023 heading")])["result"] == "Green", \
        "a borrowed date is not compared"
    assert deck([_cand("a", "board.pptx", 3, 1_000_000), _cand("b", "plan.pdf", 5, 1_200_000, status="rejected")])["result"] == "Green", \
        "a rejected figure is no claim"


def test_with_no_deck_the_deck_check_is_blocked_and_requested():
    ig = _integrity()
    out = ig.assess(engine_results(), deck_count=0, candidates=[])
    row = next(r for r in out["coverage"] if r["check"] == "Deck-vs-deck figures")
    assert (row["status"], row["reason"]) == (ig.BLOCKED, "At least one board deck")
    assert out["blocked"] == ["Deck-vs-deck figures"] and out["data_requests"] == ["Deck-vs-deck figures: At least one board deck"]
    assert out["memo_sentence"] == "Insufficient assessment coverage is not a finding about the company: 2 of the 5 applicable checks could not be completed."


# --- smoothness (docs/specs/smoothness.md) -----------------------------------------------------------------------------------------

def _series(totals, first="2023-01", status="Complete"):
    """Stored results holding a revenue series of monthly totals starting at `first` (the one input the check reads)."""
    y, m = int(first[:4]), int(first[5:])
    months = []
    for _ in totals:
        months.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    data = [{"month": mo, "total": t} for mo, t in zip(months, totals)]
    return {"revenue_series": {"months": months, "segments": [], "data": data,
                               "source": {"file": "revenue.csv", "sheet": "CSV", "rows": "rows 2–71 (70 rows)"}},
            "source_period": {"month": months[-1], "status": status, "complete_by": None, "evidence_to": months[-1]}}


def _smooth(results):
    ig = _integrity()
    assessed = ig.assess(results, deck_count=0, candidates=[])
    row = next(r for r in assessed["coverage"] if r["check"] == "Smoothness")
    return assessed, row, next((r for r in assessed["results"] if r["check"] == "Smoothness"), None)


NOISY = [100, 108, 103, 121, 118, 131, 127, 149, 141, 160, 158, 181, 170, 196, 189, 214]


def test_a_series_growing_exactly_one_percent_a_month_is_amber_and_the_finding_names_the_window():
    totals = [10000 * 1.01 ** i for i in range(24)]
    assessed, row, ran = _smooth(_series(totals))
    assert row["status"] == "Completed" and row["reason"] is None and row["result"] == "Amber"
    assert ran["result"] == "Amber"
    assert ran["finding"] == ("Month-on-month revenue growth varies by 0.0 points (standard deviation) over 2023-12–2024-12; "
                              "below 0.5 points is unusually smooth (provisional threshold, 3 synthetic series)")
    assert ran["source"] == "revenue.csv · CSV · rows 2–71 (70 rows)"


def test_a_series_with_ordinary_noise_is_green():
    _, row, ran = _smooth(_series(NOISY + [210, 230, 224, 251]))
    assert row["result"] == "Green" and ran["result"] == "Green"
    assert ran["finding"].startswith("Month-on-month revenue growth varies by ") and "unusually smooth" not in ran["finding"]
    assert ran["finding"].endswith("(provisional threshold, 3 synthetic series)")


def test_twelve_months_or_a_gap_that_leaves_fewer_than_thirteen_consecutive_months_is_blocked_and_requested():
    ig = _integrity()
    short = _series(NOISY[:12])
    gap = _series(NOISY + [210, 230])
    gap["revenue_series"]["data"][5]["total"] = 0        # a month with no revenue splits the run: 12 months remain
    for results in (short, gap, {}):
        assessed, row, ran = _smooth(results)
        assert row["status"] == ig.BLOCKED and ran is None
        assert row["reason"] == "Revenue file with at least 13 consecutive months of revenue"
        assert "Smoothness: Revenue file with at least 13 consecutive months of revenue" in assessed["data_requests"]


def test_a_possibly_partial_last_month_is_not_read():
    smooth = [10000 * 1.01 ** i for i in range(15)]
    partial = _series(smooth + [90000], status="Possibly partial")        # a spike in the unfinished last month
    complete = _series(smooth + [90000], status="Complete")
    assert _smooth(partial)[1]["result"] == "Amber", "the spike is left out"
    assert _smooth(complete)[1]["result"] == "Green", "ticked complete, the same month is read"


def test_with_smoothness_four_of_five_applicable_checks_can_complete_and_clustering_stays_not_available():
    ig = _integrity()
    stored = engine_results()
    assessed = ig.assess(stored, deck_count=1, candidates=[])
    statuses = {r["check"]: r["status"] for r in assessed["coverage"]}
    assert statuses["Smoothness"] == ig.COMPLETED and statuses["Quarter-end clustering"] == ig.NOT_AVAILABLE
    assert (assessed["completed"], assessed["applicable"]) == (4, 5)
    assert assessed["code"] != "insufficient"
    assert next(r for r in assessed["results"] if r["check"] == "Smoothness")["result"] == "Amber", "TestCo grows exactly 1% a month"


def test_the_memo_labels_the_smoothness_threshold_as_provisional():
    from app import ic_memo as im
    row = next(line for line in im.build_memo(**inputs()).split("\n") if line.startswith("| Data reliability"))
    assert "Smoothness: Amber (provisional threshold, 3 synthetic series)." in row
