"""Claim groups through the API (docs/specs/claim-groups.md sections 4 to 7): edit and Undo, the saved choice, the conclusion, the banner and the memo.

A fixture audit of a synthetic company on the sample revenue file (FY2023 revenue 187,701 in four quarters), in-memory Mongo, no network.
"""
import copy
import logging

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import test_llm_gateway as t  # noqa: E402
from claim_matching_support import engine_results  # noqa: E402

from app import decks  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402

AUDIT = "audit-groups"
DECK = "testco_board.pptx"
BASE = [("c1", 187_700, "2023"), ("c2", 44_845, "2023-Q1"), ("c3", 46_204, "2023-Q2"), ("c4", 47_604, "2023-Q3"), ("c5", 49_047, "2023-Q4")]
OFFSETTING = [("c1", 187_700, "2023"), ("c2", 44_845, "2023-Q1"), ("c3", 46_204, "2023-Q2"), ("c4", 52_000, "2023-Q3"), ("c5", 44_651, "2023-Q4")]


def cand(cid, value, label, claim_type="revenue", **over):
    c = {"audit_id": AUDIT, "id": cid, "deck_id": "d1", "status": "approved", "claim_type": claim_type, "value": value, "value_high": None,
         "unit": None, "currency": "EUR", "target_date": label, "period_text": label, "snippet": f"Revenue EUR {value}", "label_from": None,
         "file": DECK, "order": int(cid[1:]), "basis": "actual", "sources": [{"file": DECK, "slide": int(cid[1:])}], **over}
    return deck_claims.resolve_period(c, 12)


def make_db(claims):
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT, "reporting_currency": "EUR", "fiscal_year_end": 12, "as_of_month": None, "target_arr": 5_000_000,
                              "target_date": "2026-12-31", "results": copy.deepcopy(engine_results())})
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "fx": {}})
    db[decks.CANDIDATES_COLLECTION].docs.extend(cand(*c) for c in claims)
    return db


@pytest.fixture()
def client_for(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    def build(claims):
        db = make_db(claims)
        monkeypatch.setattr(server, "db", db)
        return TestClient(server.app, raise_server_exceptions=False), db
    return build


def get(client, path=""):
    r = client.get(f"/api/audits/{AUDIT}{path}")
    assert r.status_code == 200, r.text
    return r.json()


def edit(client, cid, body):
    r = client.put(f"/api/audits/{AUDIT}/decks/candidates/{cid}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def roles(body):
    return {r["claim_id"]: r["group_role"] for r in body["register"]}


# --- edit and Undo --------------------------------------------------------------------------------------------------------------

def test_the_claims_endpoint_returns_the_register_the_groups_and_the_two_counts(client_for):
    client, _ = client_for(BASE)
    body = get(client, "/claims")
    assert roles(body) == {"c1": "total", "c2": "part", "c3": "part", "c4": "part", "c5": "part"}
    assert body["counts"] == {"items": 1, "claims": 5, "groups": 1}
    assert [g["total"] for g in body["groups"]] == ["c1"] and body["reviews"] == [] and body["conflicts"] == []


def test_an_edit_that_breaks_the_reconciliation_dissolves_the_group_and_restoring_the_value_forms_it_again(client_for):
    client, _ = client_for(BASE)
    edit(client, "c4", {"value": 60_000})
    body = get(client, "/claims")
    assert roles(body) == {f"c{i}": None for i in range(1, 6)} and body["groups"] == []
    total = next(r for r in body["register"] if r["claim_id"] == "c1")
    assert total["relationship"].startswith("Quarters sum to €200,096"), "a note says why, where it is useful"
    edit(client, "c4", {"value": 47_604})
    assert roles(get(client, "/claims"))["c1"] == "total"


def test_excluding_a_part_dissolves_the_group_and_undo_restores_it(client_for):
    client, _ = client_for(BASE)
    edit(client, "c3", {"status": "rejected"})
    body = get(client, "/claims")
    assert {r["claim_id"] for r in body["register"]} == {"c1", "c2", "c4", "c5"} and body["groups"] == []
    assert next(r for r in body["register"] if r["claim_id"] == "c1")["relationship"] == "Quarters: 3 of 4 stated; kept as independent claims"
    edit(client, "c3", {"undo": True})
    body = get(client, "/claims")
    assert body["counts"] == {"items": 1, "claims": 5, "groups": 1}


def test_a_part_moved_to_another_segment_leaves_the_group_and_the_total_keeps_every_part_it_has(client_for):
    client, _ = client_for(BASE)
    r = client.put(f"/api/audits/{AUDIT}/claims/c2", json={"segment": "Enterprise"})
    assert r.status_code == 200, r.text
    assert get(client, "/claims")["groups"] == []


# --- the conclusion, the banner and the memo -----------------------------------------------------------------------------------------

def test_a_verified_total_with_a_contradicted_part_gives_not_supported_in_the_verdict_and_the_banner(client_for):
    client, _ = client_for(OFFSETTING)
    body = get(client, "/claims")
    labels = {r["claim_id"]: r["evidence_label"] for r in body["register"]}
    assert labels["c1"] == "Verified" and labels["c4"] == "Contradicted" and roles(body)["c4"] == "part"
    ver = get(client, "/verdict")["verdict"]
    assert ver["outcome_code"] == "not_supported" and ver["five"][0]["group"]["contradicted"] == ["c4"]
    blockers = get(client, "/blockers")["blockers"]
    assert [b["claim_id"] for b in blockers if b["kind"] == "claim_contradicted"] == ["c4"]
    assert "Top-5 claim contradicted: revenue 52,000 EUR" in next(b for b in blockers if b["kind"] == "claim_contradicted")["text"]
    summary = client.get(f"/api/audits/{AUDIT}/memo.md").text.split("## Summary")[1].split("## Deal thesis")[0]
    assert "Verdict: Selected claims not supported" in summary and "2023-Q3" in summary
    assert "Grouping: 1 items are shown for 5 claims" in summary


def test_the_memo_appendix_lists_every_claim_with_its_relationship(client_for):
    client, _ = client_for(BASE)
    memo = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert memo.status_code == 200, memo.text
    appendix = memo.text.split("## Appendix A")[1].split("## Appendix B")[0]
    assert "| Relationship |" in appendix and appendix.count("Part of the annual total for") == 4 and "Annual total: quarters reconcile" in appendix


# --- conflict resolution --------------------------------------------------------------------------------------------------------------

CONFLICT = [*BASE, ("c6", 250_000, "2023")]


def conflict_body(client):
    body = get(client, "/claims")
    assert len(body["reviews"]) == 1 and body["reviews"][0]["state"] == "open"
    return body, body["reviews"][0]


def choose(client, review, claim_id):
    identity = next(c["identity"] for c in review["candidates"] if c["claim_id"] == claim_id)
    r = client.put(f"/api/audits/{AUDIT}/claim-groups/{review['id']}", json={"choice": identity})
    return r


def test_an_ambiguous_total_is_listed_with_candidates_sources_and_the_hint_and_counts_as_an_open_question(client_for):
    client, _ = client_for(CONFLICT)
    body, review = conflict_body(client)
    assert sorted(c["claim_id"] for c in review["candidates"]) == ["c1", "c6"]
    assert {c["claim_id"]: c["hint"] for c in review["candidates"]}["c1"].startswith("quarters sum to")
    assert all(c["source"].startswith(DECK) for c in review["candidates"]) and body["groups"] == []
    ver = get(client, "/verdict")
    assert ver["verdict"]["open_questions"] == 1 and "1 question open." in ver["verdict"]["rule"]
    assert [c["state"] for c in ver["verdict"]["conflicts"]] == ["open"]
    assert not {"c1", "c6"} & {r["claim_id"] for r in ver["verdict"]["five"]}, "no single figure can enter the five while none is chosen"


def test_the_conflict_is_in_the_memo_summary_even_when_nothing_is_chosen(client_for):
    client, _ = client_for(CONFLICT)
    memo = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert memo.status_code == 200, memo.text
    summary = memo.text.split("## Summary")[1].split("## Deal thesis")[0]
    assert "Unresolved conflicts:" in summary and "No figure chosen." in summary and "€250,000" in summary


def test_choosing_a_total_saves_a_hash_bound_choice_and_selects_nothing_else(client_for):
    client, db = client_for(CONFLICT)
    _, review = conflict_body(client)
    r = choose(client, review, "c1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reviews"] == [] and [c["state"] for c in body["conflicts"]] == ["chosen"]
    assert roles(body)["c1"] == "total" and roles(body)["c6"] == "alternative"
    other = next(x for x in body["register"] if x["claim_id"] == "c6")
    assert other["segment"] == "Whole company", "the passed-over figure is not made a segment"
    assert other["evidence_label"] == "Contradicted" and "not a segment" in other["relationship"], \
        "its label is the data's verdict on it (250,000 against 187,701 observed), not a consequence of being passed over"
    stored = db["audits"].docs[0]["group_choices"]
    assert list(stored) == [review["id"]]
    saved = stored[review["id"]]
    assert set(saved) == {"kind", "chosen", "context", "saved_at"} and len(saved["chosen"]) == 16 and len(saved["context"]) == 16
    text = str(db["audits"].docs[0]["group_choices"])
    for needle in (DECK, "187700", "250000", "slide"):
        assert needle not in text, f"{needle!r} was stored with the choice"


def test_the_conflict_stays_in_the_conclusion_after_a_figure_is_chosen(client_for):
    client, _ = client_for(CONFLICT)
    _, review = conflict_body(client)
    choose(client, review, "c1")
    ver = get(client, "/verdict")["verdict"]
    assert [c["state"] for c in ver["conflicts"]] == ["chosen"] and "Preferred: €187,700" in ver["conflicts"][0]["text"]
    assert ver["open_questions"] == 1, "a conflict that stays unresolved stays a card on the Audit page"


def test_a_choice_survives_repeated_reads_and_a_new_audit_run_and_expires_after_an_edit_of_a_candidate(client_for):
    client, db = client_for(CONFLICT)
    _, review = conflict_body(client)
    choose(client, review, "c1")
    for _ in range(3):
        assert [c["state"] for c in get(client, "/claims")["conflicts"]] == ["chosen"]
    db["audits"].docs[0]["results"] = copy.deepcopy(engine_results())      # a run again: same results, the claims untouched
    assert [c["state"] for c in get(client, "/claims")["conflicts"]] == ["chosen"]
    edit(client, "c6", {"value": 260_000})
    body = get(client, "/claims")
    assert [c["state"] for c in body["conflicts"]] == ["open"] and len(body["reviews"]) == 1, "an edited candidate is a new question"
    edit(client, "c6", {"value": 250_000})
    assert [c["state"] for c in get(client, "/claims")["conflicts"]] == ["chosen"], "a choice binds to the context, so the same context holds it"


def test_a_choice_survives_an_unrelated_claim_and_expires_when_a_candidate_is_excluded_or_added(client_for):
    client, db = client_for(CONFLICT)
    _, review = conflict_body(client)
    choose(client, review, "c1")
    db[decks.CANDIDATES_COLLECTION].docs.append(cand("c9", 12, "2022", claim_type="churn", unit="%", currency=None))
    assert [c["state"] for c in get(client, "/claims")["conflicts"]] == ["chosen"]
    db[decks.CANDIDATES_COLLECTION].docs.append(cand("c8", 300_000, "2023"))
    assert [c["state"] for c in get(client, "/claims")["conflicts"]] == ["open"], "a third annual figure is a new question"
    edit(client, "c8", {"status": "rejected"})
    assert [c["state"] for c in get(client, "/claims")["conflicts"]] == ["chosen"]


def test_excluding_the_alternative_with_a_reason_resolves_the_conflict_and_undo_brings_it_back(client_for):
    client, db = client_for(CONFLICT)
    _, review = conflict_body(client)
    choose(client, review, "c1")
    edit(client, "c6", {"status": "rejected", "reason": "deck_context"})
    assert next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "c6")["excluded_reason"] == "deck_context"
    body = get(client, "/claims")
    assert body["conflicts"] == [] and roles(body)["c1"] == "total" and get(client, "/verdict")["verdict"]["open_questions"] == 0
    edit(client, "c6", {"undo": True})
    assert [c["state"] for c in get(client, "/claims")["conflicts"]] == ["chosen"]


def test_scoping_the_alternative_resolves_the_conflict_without_a_choice(client_for):
    client, _ = client_for(CONFLICT)
    conflict_body(client)
    from app import claim_matching
    segments = claim_matching.data_segments(engine_results())
    r = client.put(f"/api/audits/{AUDIT}/claims/c6", json={"segment": segments[0]})
    assert r.status_code == 200, r.text
    body = get(client, "/claims")
    assert body["conflicts"] == [] and roles(body)["c1"] == "total" and roles(body)["c6"] is None


def test_undoing_a_choice_asks_the_question_again_and_changes_no_claim(client_for):
    client, db = client_for(CONFLICT)
    _, review = conflict_body(client)
    choose(client, review, "c1")
    before = copy.deepcopy(db[decks.CANDIDATES_COLLECTION].docs)
    r = client.delete(f"/api/audits/{AUDIT}/claim-groups/{review['id']}")
    assert r.status_code == 200, r.text
    assert [c["state"] for c in r.json()["conflicts"]] == ["open"] and "group_choices" in db["audits"].docs[0]
    assert db[decks.CANDIDATES_COLLECTION].docs == before, "a choice is an analyst decision on the audit; no claim was edited"
    assert client.delete(f"/api/audits/{AUDIT}/claim-groups/{review['id']}").status_code == 404


def test_a_choice_the_server_did_not_offer_is_refused(client_for):
    client, db = client_for(CONFLICT)
    _, review = conflict_body(client)
    assert client.put(f"/api/audits/{AUDIT}/claim-groups/{review['id']}", json={"choice": "0123456789abcdef"}).status_code == 400
    assert client.put(f"/api/audits/{AUDIT}/claim-groups/nope", json={"choice": review["candidates"][0]["identity"]}).status_code == 404
    assert client.put(f"/api/audits/{AUDIT}/claim-groups/{review['id']}", json={"choice": "x", "extra": 1}).status_code == 422
    assert "group_choices" not in db["audits"].docs[0]


def test_a_choice_needs_computed_results(client_for):
    client, db = client_for(CONFLICT)
    _, review = conflict_body(client)
    db["audits"].docs[0].pop("results")
    assert client.put(f"/api/audits/{AUDIT}/claim-groups/{review['id']}", json={"choice": review["candidates"][0]["identity"]}).status_code == 409


def test_the_choice_of_a_set_of_parts_is_saved_and_undone_the_same_way(client_for):
    client, _ = client_for([*BASE, ("c6", 93_000, "2023-H1"), ("c7", 94_700, "2023-H2")])
    body = get(client, "/claims")
    review = body["reviews"][0]
    assert review["kind"] == "partition" and body["groups"] == []
    r = client.put(f"/api/audits/{AUDIT}/claim-groups/{review['id']}", json={"choice": "half"})
    assert r.status_code == 200, r.text
    assert [g["partition"] for g in r.json()["groups"]] == ["half"] and r.json()["reviews"] == []
    assert r.json()["groups"][0]["chosen"] == [review["id"]]
    assert client.put(f"/api/audits/{AUDIT}/claim-groups/{review['id']}", json={"choice": "decade"}).status_code in (400, 404)
    undone = client.delete(f"/api/audits/{AUDIT}/claim-groups/{review['id']}")
    assert undone.json()["groups"] == [] and len(undone.json()["reviews"]) == 1


# --- logs --------------------------------------------------------------------------------------------------------------------------

def test_a_choice_logs_the_run_and_a_closed_word_only(client_for, caplog):
    client, _ = client_for(CONFLICT)
    _, review = conflict_body(client)
    with caplog.at_level(logging.INFO):
        choose(client, review, "c1")
        client.delete(f"/api/audits/{AUDIT}/claim-groups/{review['id']}")
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("group choice")]
    assert lines == [f"group choice saved: run_id={AUDIT} kind=total", f"group choice undone: run_id={AUDIT} kind=total"]
    text = caplog.text
    for needle in (DECK, "187700", "250000", review["candidates"][0]["identity"], review["candidates"][1]["identity"], review["context"]):
        assert needle not in text
