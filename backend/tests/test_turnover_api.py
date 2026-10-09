"""PUT /audits/{id}/claims/{claim_id}/turnover (docs/specs/claim-matching.md section 11): what it writes and what it refuses."""
import copy
import json
from pathlib import Path

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


def test_a_pending_claim_can_be_answered_before_the_audit_is_computed(api):
    """The deck list asks in the claim's own row (section 11 point 8): the answer needs neither an approval nor results."""
    client, db = api
    db["audits"].docs[0]["results"] = None
    db[decks.CANDIDATES_COLLECTION].docs[0]["status"] = "pending"
    done = put(client)
    assert done.status_code == 200 and done.json() == {"register": []}
    assert next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "g1")["claim_inputs"]["g1"]["turnover_as"] == "volume"
    assert list(db["audits"].docs[0]["turnover_choices"]) == [cm.turnover_key(turnover_candidate())]


def test_a_rejected_claim_cannot_be_answered(api):
    client, db = api
    db[decks.CANDIDATES_COLLECTION].docs[0]["status"] = "rejected"
    assert put(client).status_code == 404
    assert "turnover_choices" not in db["audits"].docs[0]


def test_get_claims_reads_the_deck_for_take_rate_only(api):
    """_deck_take_rate through GET /claims: the volume default applies with 'take rate' in the deck, not with fees or commission."""
    client, db = api
    db[decks.CANDIDATES_COLLECTION].docs[0].update(target_date="2021", period_text="FY2021")   # no file covers the period
    deck_claims.resolve_period(db[decks.CANDIDATES_COLLECTION].docs[0], RUN["fiscal_year_end"])
    decks_coll = db[decks.TEXT_COLLECTION]
    assert row(client.get(f"/api/audits/{AUDIT}/claims").json())["turnover_state"] == "ask"
    for text, expected in (("We earn fees and sales commission", None), ("Our take rate is 2%", "volume")):
        decks_coll.docs[:] = [{"audit_id": AUDIT, "id": "d1", "blocks": [{"text": text}]}]
        got = row(client.get(f"/api/audits/{AUDIT}/claims").json())
        assert (got["turnover_state"], got["turnover_suggested"]) == ("ask", expected), text


# --- the reported case: 05-zero2hero.pdf, every claim still to review (claim-matching.md section 11 points 7 and 8) -------

DECKS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "decks" / "decks"
ZERO2HERO = "05-zero2hero.pdf"


@pytest.fixture()
def zero2hero(api):
    """The public test deck uploaded as in the browser: p17 Turnover (£/year) FY2021–FY2023 278,085 / 415,107 / 550,508 GBP,
    p19 table 1 Revenue FY2022 130,550 and FY2023 150,000 GBP, all to review. The revenue file starts in 2023-01: it has no
    period to compare with FY2021 and FY2022, and covers FY2023. A GBP rate is saved."""
    pytest.importorskip("pdfplumber")
    client, db = api
    db["audits"].docs[0]["fx"] = {"GBP": 1.17}
    db[decks.CANDIDATES_COLLECTION].docs[:] = []
    r = client.post(f"/api/audits/{AUDIT}/decks/upload", files={"file": (ZERO2HERO, (DECKS / ZERO2HERO).read_bytes())})
    assert r.status_code == 200, r.text
    return client, db


def _listed(client):
    return client.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]


def _turnover_rows(candidates):
    return {c["value"]: c for c in candidates if c["value"] in (278085, 415107, 550508)}


def test_zero2hero_turnover_rows_ask_revenue_or_volume_in_the_list_before_approval(zero2hero):
    """Reproduced (Emergent after PR #83): the three turnover rows read Revenue, To review, and no question was asked, because
    the question and the deck hint were read for approved claims only."""
    client, _ = zero2hero
    listed = _listed(client)
    rows = _turnover_rows(listed)
    assert sorted(rows) == [278085, 415107, 550508] and all(c["status"] == "pending" for c in rows.values())
    view = {value: c["turnover"] for value, c in rows.items()}
    assert all(len(v) == 1 and (v[0]["turnover_state"], v[0]["turnover_set_by"]) == ("ask", "python") for v in view.values())
    # deck revenue below turnover beyond tolerance, from the pending p19 table: Volume pre-selected, still to be confirmed
    assert (view[415107][0]["turnover_suggested"], view[415107][0]["deck_revenue_note"]) == (
        "volume", "Deck revenue for the same period: 130,550 GBP (page 19); implied take rate 31%, derived, not verified")
    assert (view[550508][0]["turnover_suggested"], view[550508][0]["deck_revenue_note"]) == (
        "volume", "Deck revenue for the same period: 150,000 GBP (page 19); implied take rate 27%, derived, not verified")
    assert (view[278085][0]["turnover_suggested"], view[278085][0]["deck_revenue_note"]) == (None, None), "no FY2021 revenue in the deck"
    # the revenue file starts in 2023: FY2021 and FY2022 have no period to compare; FY2023 is compared (and asks: above tolerance)
    assert [view[v][0]["file_note"] for v in (278085, 415107, 550508)] == [cm.NO_FILE_PERIOD, cm.NO_FILE_PERIOD, None]
    revenue_row = next(c for c in listed if c.get("by_period") and c["by_period"][0]["value"] == 130550)
    assert revenue_row["turnover"] is None, "the revenue table row is not a turnover claim"


def test_zero2hero_answer_in_the_list_is_kept_when_the_claim_is_approved(zero2hero):
    client, db = zero2hero
    turnover = _turnover_rows(_listed(client))[550508]
    assert put(client, turnover["id"], {"as": "volume", "reason": "deck_says_processed_volume"}).status_code == 200
    answered = _turnover_rows(_listed(client))[550508]["turnover"][0]
    assert (answered["turnover_state"], answered["turnover_set_by"], answered["turnover_note"]) == ("volume", "analyst", "Transaction volume")
    assert answered["turnover_suggested"] is None
    assert client.put(f"/api/audits/{AUDIT}/decks/candidates/{turnover['id']}", json={"status": "approved"}).status_code == 200
    got = row(client.get(f"/api/audits/{AUDIT}/claims").json(), turnover["id"])
    assert (got["turnover_state"], got["turnover_set_by"], got["metric"]) == ("volume", "analyst", "Transaction volume")


def test_zero2hero_the_register_hint_reads_the_pending_revenue_table(zero2hero):
    """Section 11 point 7 (amended 2026-10-09, George): an approved turnover claim is hinted from a revenue figure still to
    review; a rejected one gives no hint."""
    client, db = zero2hero
    turnover = _turnover_rows(_listed(client))[550508]
    client.put(f"/api/audits/{AUDIT}/decks/candidates/{turnover['id']}", json={"status": "approved"})
    got = row(client.get(f"/api/audits/{AUDIT}/claims").json(), turnover["id"])
    assert (got["turnover_state"], got["turnover_suggested"], got["evidence_label"]) == ("ask", "volume", "Unverified")
    revenue = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if (c.get("by_period") or [{}])[0].get("value") == 130550)
    client.put(f"/api/audits/{AUDIT}/decks/candidates/{revenue['id']}", json={"status": "rejected"})
    got = row(client.get(f"/api/audits/{AUDIT}/claims").json(), turnover["id"])
    assert (got["turnover_suggested"], got["deck_revenue_note"]) == (None, None)
