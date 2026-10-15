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

# Committed before the code (docs/specs/integrity-coverage.md): strict expected failures until the code PR removes this mark.
pytestmark = pytest.mark.xfail(strict=True, reason="docs/specs/integrity-coverage.md: not built yet")

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
