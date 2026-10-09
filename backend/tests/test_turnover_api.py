"""PUT /audits/{id}/claims/{claim_id}/turnover (docs/specs/claim-matching.md section 11): what it writes and what it refuses."""
import copy
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from claim_matching_support import engine_results, fixture  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import decks  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402

AUDIT = "audit-turn"
RUN = fixture()["runs"]["A"]
SENTINEL = "Zephyr Holdings GMV EUR 900,000"


def turnover_candidate(cid="g1", **over):
    c = {"audit_id": AUDIT, "id": cid, "status": "approved", "claim_type": "revenue", "value": 900_000, "value_high": None,
         "unit": None, "currency": "EUR", "snippet": SENTINEL, "label_from": None, "file": "deck.pptx", "order": 0,
         "sources": [{"file": "deck.pptx", "slide": 3}], "target_date": "2023", "period_text": "FY2023", **over}
    deck_claims.resolve_period(c, RUN["fiscal_year_end"])
    return c


@pytest.fixture()
def api(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT, "reporting_currency": "EUR", "fiscal_year_end": 12, "as_of_month": None,
                              "results": copy.deepcopy(engine_results(tuple(RUN["files"]), RUN["as_of_month"]))})
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "fx": {}})
    db[decks.CANDIDATES_COLLECTION].docs.append(turnover_candidate())
    db[decks.CANDIDATES_COLLECTION].docs.append(turnover_candidate("plain", snippet="Revenue EUR 190,000"))
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


def put(client, claim_id="g1", body=None, audit=AUDIT):
    return client.put(f"/api/audits/{audit}/claims/{claim_id}/turnover",
                      json=body if body is not None else {"as": "volume", "reason": "deck_says_processed_volume"})


def row(body, claim_id="g1"):
    return next(r for r in body["register"] if r["claim_id"] == claim_id)


def test_an_unanswered_turnover_claim_asks(api):
    client, _ = api
    assert row(client.get(f"/api/audits/{AUDIT}/claims").json())["turnover_state"] == "ask"


def test_the_answer_is_written_on_the_claim_and_on_the_audit_under_a_hash_and_the_register_follows(api):
    client, db = api
    done = put(client)
    assert done.status_code == 200, done.text
    got = row(done.json())
    assert (got["turnover_state"], got["turnover_set_by"], got["turnover_reason"], got["metric"]) == \
        ("volume", "analyst", "deck_says_processed_volume", "Transaction volume")
    candidate = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "g1")
    assert candidate["claim_inputs"] == {"g1": {"turnover_as": "volume", "turnover_reason": "deck_says_processed_volume"}}
    audit = next(a for a in db["audits"].docs if a["id"] == AUDIT)
    key = cm.turnover_key(turnover_candidate())
    assert list(audit["turnover_choices"]) == [key]
    assert {k: v for k, v in audit["turnover_choices"][key].items() if k != "saved_at"} == \
        {"as": "volume", "reason": "deck_says_processed_volume"} and audit["turnover_choices"][key]["saved_at"]
    # data boundary (rule 14, 17): neither the audit nor the stored answer holds a word of the deck
    assert "Zephyr" not in json.dumps(audit["turnover_choices"], default=str) and "GMV" not in json.dumps(candidate["claim_inputs"])
    assert "Zephyr" not in json.dumps({k: v for k, v in audit.items() if k != "results"}, default=str)


def test_the_answer_can_be_changed_and_a_second_claim_of_the_same_term_and_period_reuses_it(api):
    client, db = api
    put(client)
    db[decks.CANDIDATES_COLLECTION].docs.append(turnover_candidate("g2"))
    body = client.get(f"/api/audits/{AUDIT}/claims").json()
    assert (row(body, "g2")["turnover_state"], row(body, "g2")["turnover_set_by"]) == ("volume", "analyst")
    changed = put(client, body={"as": "revenue", "reason": "file_confirms"})
    assert row(changed.json())["turnover_state"] == "revenue"
    assert next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "g1")["claim_inputs"]["g1"]["turnover_as"] == "revenue"


@pytest.mark.parametrize("body", [
    {"as": "volume", "reason": "deck_says_gross_revenue"},      # contradictory pairs
    {"as": "revenue", "reason": "deck_says_processed_volume"},
    {"as": "maybe", "reason": "other"}, {"as": "volume", "reason": "because"}, {"as": "volume"}, {"reason": "other"},
    {"as": "volume", "reason": "other", "note": "free text"}, {"as": "volume", "reason": ""}, {},
])
def test_a_contradictory_or_open_answer_is_refused_and_nothing_is_written(api, body):
    client, db = api
    assert put(client, body=body).status_code == 422
    assert "turnover_choices" not in db["audits"].docs[0]
    assert "claim_inputs" not in next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "g1")


@pytest.mark.parametrize("body", [{"as": "volume", "reason": "other"}, {"as": "volume", "reason": "deck_says_processed_volume"},
                                  {"as": "revenue", "reason": "deck_says_gross_revenue"}, {"as": "revenue", "reason": "file_confirms"}])
def test_the_consistent_pairs_are_accepted(api, body):
    client, _ = api
    assert put(client, body=body).status_code == 200


def test_a_claim_that_is_not_a_turnover_claim_gets_400(api):
    client, db = api
    assert put(client, "plain").status_code == 400
    assert "turnover_choices" not in db["audits"].docs[0]


def test_an_unknown_claim_or_audit_gets_404(api):
    client, _ = api
    assert put(client, "nope").status_code == 404
    assert put(client, audit="nope").status_code == 404


def test_an_audit_that_is_not_computed_gets_409(api):
    client, db = api
    db["audits"].docs[0]["results"] = None
    assert put(client).status_code == 409
    assert "turnover_choices" not in db["audits"].docs[0]


def test_get_claims_reads_the_deck_for_take_rate_only(api):
    """_deck_take_rate through GET /claims: the volume default applies with 'take rate' in the deck, not with fees or commission."""
    client, db = api
    db[decks.CANDIDATES_COLLECTION].docs[0].update(target_date="2021", period_text="FY2021")   # no file covers the period
    deck_claims.resolve_period(db[decks.CANDIDATES_COLLECTION].docs[0], RUN["fiscal_year_end"])
    decks_coll = db[decks.TEXT_COLLECTION]
    assert row(client.get(f"/api/audits/{AUDIT}/claims").json())["turnover_state"] == "ask"
    for text, expected in (("We earn fees and sales commission", "ask"), ("Our take rate is 2%", "volume")):
        decks_coll.docs[:] = [{"audit_id": AUDIT, "id": "d1", "blocks": [{"text": text}]}]
        assert row(client.get(f"/api/audits/{AUDIT}/claims").json())["turnover_state"] == expected, text
