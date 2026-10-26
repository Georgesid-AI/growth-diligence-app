"""The conclusion when annual conflicts are open and no other claim can be tested (docs/specs/forecast-and-payback.md section 7).

Insufficient evidence with "n conflicts open", never "No testable claims", in the verdict and in the memo. Fixture company: synthetic figures,
in-memory Mongo, no network.
"""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_claim_groups_api import AUDIT, get  # noqa: E402

from app import verdict as verdict_mod  # noqa: E402

ONE = [("c1", 187_700, "2023"), ("c6", 250_000, "2023")]
TWO = [*ONE, ("c8", 120_000, "2022"), ("c9", 100_000, "2022")]
NO_TESTABLE = "No testable claims found"


def test_one_open_conflict_and_nothing_else_reads_insufficient_evidence_with_the_count(claims_for):
    client, _ = claims_for(ONE)
    ver = get(client, "/verdict")["verdict"]
    assert (ver["status"], ver["outcome"], ver["outcome_code"]) == ("ok", "Insufficient evidence", "insufficient")
    assert ver["rule"] == "No claim can be tested yet; 1 conflict open." and ver["message"] is None
    assert ver["five"] == [] and ver["reasons"] == [] and len(ver["conflicts"]) == 1 and ver["open_questions"] == 1
    assert NO_TESTABLE not in str(ver)


def test_several_open_conflicts_are_counted_in_the_plural(claims_for):
    client, _ = claims_for(TWO)
    ver = get(client, "/verdict")["verdict"]
    assert ver["rule"] == "No claim can be tested yet; 2 conflicts open." and ver["outcome_code"] == "insufficient"
    assert len(ver["conflicts"]) == 2


def test_the_conflicts_are_not_counted_twice_on_the_rule_line(claims_for):
    client, _ = claims_for(ONE)
    ver = get(client, "/verdict")["verdict"]
    assert "question" not in ver["rule"], "an open conflict is an open question already; the rule line names it once"


def test_the_memo_summary_reads_the_same_conclusion_and_lists_the_conflicts(claims_for):
    client, _ = claims_for(ONE)
    memo = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert memo.status_code == 200, memo.text
    summary = memo.text.split("## Summary")[1].split("## Deal thesis")[0]
    assert "Verdict: Insufficient evidence – No claim can be tested yet; 1 conflict open." in summary
    assert "Unresolved conflicts:" in summary and "No figure chosen." in summary
    assert NO_TESTABLE not in memo.text


def test_a_register_with_no_claim_and_no_conflict_still_reads_no_testable_claims(claims_for):
    client, _ = claims_for([])
    ver = get(client, "/verdict")["verdict"]
    assert ver["status"] == "no_verdict" and ver["message"].startswith(NO_TESTABLE) and ver["outcome"] is None


def test_choosing_a_figure_ends_the_special_case(claims_for):
    client, _ = claims_for(ONE)
    body = get(client, "/claims")
    review = body["reviews"][0]
    identity = next(c["identity"] for c in review["candidates"] if c["claim_id"] == "c1")
    assert client.put(f"/api/audits/{AUDIT}/claim-groups/{review['id']}", json={"choice": identity}).status_code == 200
    ver = get(client, "/verdict")["verdict"]
    assert [f["claim_id"] for f in ver["five"]] == ["c1"]
    assert "No claim can be tested yet" not in (ver["rule"] or "")


def test_the_function_reads_the_conflicts_it_is_given_and_an_empty_register_without_them_is_unchanged():
    conflict = {"id": "q1", "state": "open", "text": "Revenue FY2023: two figures", "reason": "x", "metric": "Revenue", "period": "FY2023", "candidates": []}
    results = {"reporting_currency": "EUR"}
    ver = verdict_mod.verdict([], results, None, 1, [conflict])
    assert ver["outcome"] == "Insufficient evidence" and ver["rule"] == "No claim can be tested yet; 1 conflict open." and ver["conflicts"][0]["id"] == "q1"
    none = verdict_mod.verdict([], results, None, 0, [])
    assert none["status"] == "no_verdict" and none["message"] == verdict_mod.W10_NO_CLAIMS
    assert verdict_mod.verdict([], None, None, 0, [conflict])["message"] == verdict_mod.W10_NOT_COMPUTED, "not computed stays first"
