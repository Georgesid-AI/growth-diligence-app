"""Claim-review conclusion (docs/specs/claim-review-conclusion.md; plan of 15 Oct 2026, section 1 and 7.1).

The outcome describes the five selected claims, never a recommendation; the contradictions outside the five and the computed reasons
stand beside it, on the screen and in the memo. The five-words scan and the two required judgment fields are retired (docs/design/
simplified-flow.md section 6). Python only, no network, no model.
"""
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_claim_register_api import AUDIT  # noqa: E402

from app import decks  # noqa: E402

HEADING = "Claim-review conclusion — assessment of the five selected claims"
SCOPE = "This assesses the five claims selected by the app by value at stake; the analyst may change the selection. It is not an investment recommendation."
SELECTED = ["c01", "c21", "c23", "c27", "c31"]          # five Verified claims with a stated period
UNSELECTED_CONTRADICTED = "c05"                          # ARR €240,000 for FY2023: 198,142.68 observed


def _only(db, ids):
    col = db[decks.CANDIDATES_COLLECTION]
    col.docs[:] = [c for c in col.docs if c.get("id") in ids]


def _confirmed(client):
    r = client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"top5": SELECTED})
    assert r.status_code == 200, r.text
    return r.json()


def test_plan_1_five_verified_selected_claims_and_one_contradicted_unselected_show_supported_and_the_contradiction_in_one_block(register_api):
    client, db = register_api
    _only(db, SELECTED + [UNSELECTED_CONTRADICTED])
    body = _confirmed(client)
    block = body["verdict"]
    assert block["heading"] == HEADING
    assert block["outcome"] == "Selected claims supported" and block["outcome_code"] == "supported"
    assert block["scope_sentence"] == SCOPE
    others = block["other_contradictions"]
    assert [o["claim_id"] for o in others] == [UNSELECTED_CONTRADICTED], "the contradiction sits in the same block"
    assert others[0]["metric"] == "ARR, FY2023" and others[0]["gap"] == "€41,857 lower (miss)"
    assert "revenue.csv" in others[0]["source"] and "slide 7" in others[0]["source"]

    # the memo: the same block in its summary
    memo = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert memo.status_code == 200, memo.text
    summary = memo.text.split("## Summary")[1].split("## Deal thesis")[0]
    assert HEADING in summary and "Verdict: Selected claims supported – All 5 selected claims are Verified." in summary
    assert SCOPE in summary
    assert re.search(r"Other contradictions:\n- ARR(?: \(see glossary\))?, FY2023: €41,857 lower \(miss\)", summary), summary
    assert "Reasons:\n- #" in summary and "Unresolved questions:" in summary, "computed, not typed"


def test_no_other_contradiction_reads_none_found_among_tested_claims(register_api):
    client, db = register_api
    _only(db, SELECTED)
    block = _confirmed(client)["verdict"]
    assert block["other_contradictions"] == [] and block["other_contradictions_text"] == "None found among tested claims."


def test_the_reasons_and_unresolved_questions_are_computed_and_the_memo_needs_no_judgment(register_api):
    """simplified-flow.md: the computed block replaces the judgment fields; nothing is typed, nothing is refused."""
    client, db = register_api
    _only(db, SELECTED)
    body = _confirmed(client)
    assert "judgment" not in body["ic_inputs"] and body["unresolved_questions"] is not None
    memo = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert memo.status_code == 200, memo.text
    summary = memo.text.split("## Summary")[1].split("## Deal thesis")[0]
    assert "Reasons:\n- #" in summary and "Unresolved questions:" in summary and "Analyst note:" not in summary
    assert client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"note": "Agree."}).status_code == 200
    again = client.get(f"/api/audits/{AUDIT}/memo.md").text
    assert "Analyst note: Agree." in again.split("## Deal thesis")[0]
