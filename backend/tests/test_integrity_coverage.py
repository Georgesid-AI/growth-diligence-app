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


def test_the_testco_run_is_insufficient_coverage_with_three_of_five_completed():
    ig = _integrity()
    assessed = ig.assess(engine_results(), deck_count=1, candidates=[])
    statuses = {r["check"]: r["status"] for r in assessed["coverage"]}
    assert [r["check"] for r in assessed["coverage"]] == CHECKS
    assert statuses == {"Revenue reconciliation": ig.COMPLETED, "Gaps in customer data": ig.COMPLETED,
                        "Quarter-end clustering": ig.NOT_AVAILABLE, "Smoothness": ig.NOT_AVAILABLE,
                        "Benford on transactions": ig.NOT_APPLICABLE, "Deck-vs-deck figures": ig.COMPLETED}
    rec = next(r for r in assessed["results"] if r["check"] == "Revenue reconciliation")
    assert rec["result"] == "Red", "TestCo's window is beyond tolerance: the hard blocker"
    assert assessed["conclusion"] == "Insufficient assessment coverage (3 of 5)"


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
    assert "Insufficient assessment coverage (3 of 5)" in row and "Completed 3 of 5 applicable checks" in row
    assert "Data integrity conclusion: Insufficient assessment coverage (3 of 5)" in row
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
    gaps = lambda results: next(r for r in ig.assess(results, deck_count=0, candidates=[])["results"] if r["check"] == "Gaps in customer data")
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
    deck = lambda cands: next(r for r in ig.assess({}, deck_count=2, candidates=cands)["results"] if r["check"] == "Deck-vs-deck figures")
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
    assert out["memo_sentence"] == "Insufficient assessment coverage is not a finding about the company: 3 of the 5 applicable checks could not be completed."
