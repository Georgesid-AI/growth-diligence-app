"""Add claim (docs/specs/deck-parser.md section 6): a claim the analyst enters from a slide or page the parser could not read.
Source document and page are required; the claim is tagged origin "analyst", sits in the register and the CSV marked
analyst-entered, and is matched and labelled by the same code as every other claim."""
import copy
import csv
import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from claim_matching_support import engine_results  # noqa: E402
from test_claim_matching import RUNS, candidates_for  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import decks  # noqa: E402

AUDIT, DECK = "audit-ac", "deck-1"
RUN = RUNS["A"]
# The figures of the parser's claim c01 (Revenue 200,000 EUR in Feb 2024), typed in by hand.
BODY = {"claim_type": "revenue", "value": 200000, "currency": "EUR", "target_date": "2024-02", "deck_id": DECK, "page": 3,
        "metric": "ARR"}


@pytest.fixture()
def api(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT, "reporting_currency": "EUR", "fiscal_year_end": 12, "as_of_month": None,
                              "results": copy.deepcopy(engine_results())})
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "fx": {}})
    db[decks.TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": DECK, "file": "testco_board.pptx", "page_unit": "slide",
                                           "pages": 12, "uploaded_at": "2026-10-01", "blocks": []})
    for n, c in enumerate(candidates_for(RUN)):
        db[decks.CANDIDATES_COLLECTION].docs.append({**c, "audit_id": AUDIT, "order": n})
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


def _add(client, **over):
    return client.post(f"/api/audits/{AUDIT}/decks/candidates", json={**BODY, **over})


def _register(client):
    r = client.get(f"/api/audits/{AUDIT}/claims")
    assert r.status_code == 200, r.text
    return r.json()["register"]


def test_an_added_claim_is_stored_approved_tagged_analyst_and_cites_its_deck_and_page(api):
    client, db = api
    r = _add(client)
    assert r.status_code == 200, r.text
    c = r.json()
    assert (c["origin"], c["status"], c["snippet"], c["file"], c["deck_id"]) == ("analyst", "approved", "Added by analyst", "testco_board.pptx", DECK)
    assert c["sources"] == [{"file": "testco_board.pptx", "slide": 3, "kind": "analyst"}], "a deck of slides cites a slide"
    assert (c["period_start"], c["period_end"]) == ("2024-02-01", "2024-02-29"), "the period resolves like any other claim's"
    assert any(x["id"] == c["id"] for x in db[decks.CANDIDATES_COLLECTION].docs)


def test_the_source_document_and_the_page_are_required_and_must_exist(api):
    client, db = api
    before = len(db[decks.CANDIDATES_COLLECTION].docs)
    no_page = {k: v for k, v in BODY.items() if k != "page"}
    no_deck = {k: v for k, v in BODY.items() if k != "deck_id"}
    no_metric = {k: v for k, v in BODY.items() if k != "metric"}
    assert client.post(f"/api/audits/{AUDIT}/decks/candidates", json=no_page).status_code == 422
    assert client.post(f"/api/audits/{AUDIT}/decks/candidates", json=no_deck).status_code == 422
    assert client.post(f"/api/audits/{AUDIT}/decks/candidates", json=no_metric).status_code == 422, "no default metric"
    assert _add(client, metric="Win rate").status_code == 400, "a % metric for an amount"
    assert _add(client, metric="Net happiness").status_code == 400
    assert _add(client, page=0).status_code == 422
    assert _add(client, page=13).status_code == 400, "the deck has 12 slides"
    assert _add(client, deck_id="not-a-deck").status_code == 400
    assert _add(client, value_high=1).status_code == 400, "a range does not run backwards"
    assert len(db[decks.CANDIDATES_COLLECTION].docs) == before, "a refused claim is not stored"
    assert _add(client, page=12, value_high=250000).status_code == 200, "a range is one claim"


def test_it_is_matched_and_labelled_by_the_same_code_as_a_parser_claim_with_the_same_fields(api):
    client, db = api
    new = _add(client).json()
    twin = {k: v for k, v in new.items() if k not in ("origin", "id", "claim_inputs")}      # as the parser would store it
    db[decks.CANDIDATES_COLLECTION].docs.append({**twin, "id": "twin", "claim_inputs": {"twin": {"metric": "ARR"}}})
    rows = {r["claim_id"]: r for r in _register(client)}
    mine, parsers = rows[new["id"]], rows["twin"]
    assert (mine["deck_reading"], parsers["deck_reading"]) == ("analyst-entered", "parser")
    assert {k: v for k, v in mine.items() if k not in ("claim_id", "deck_reading", "rank", "overlaps_with")} == \
           {k: v for k, v in parsers.items() if k not in ("claim_id", "deck_reading", "rank", "overlaps_with")}
    assert mine["page_ref"] == "slide 3" and mine["deck_file"] == "testco_board.pptx"


def test_the_chosen_metric_is_the_analysts_and_the_claim_is_tested_like_the_parsers_c01_at_once(api):
    client, _ = api
    new = _add(client).json()
    rows = {x["claim_id"]: x for x in _register(client)}
    mine, c01 = rows[new["id"]], rows["c01"]
    assert (mine["metric"], mine["metric_set_by"]) == ("ARR", "analyst")
    for field in ("evidence_label", "gap", "gap_kind", "observed_value", "observed_source", "tolerance", "period_start", "period_end"):
        assert mine[field] == c01[field], field
    assert mine["evidence_label"] == "Verified"


def test_a_later_edit_keeps_it_marked_analyst_entered(api):
    client, _ = api
    new = _add(client).json()
    r = client.put(f"/api/audits/{AUDIT}/decks/candidates/{new['id']}", json={"value": 210000})
    assert r.status_code == 200 and r.json()["status"] == "edited"
    assert next(x for x in _register(client) if x["claim_id"] == new["id"])["deck_reading"] == "analyst-entered"


def test_the_csv_marks_the_claim_analyst_entered(api):
    client, _ = api
    new = _add(client).json()
    r = client.get(f"/api/audits/{AUDIT}/claims.csv")
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert {x["claim_id"]: x["deck_reading"] for x in rows if x["row_type"] == "claim"}[new["id"]] == "analyst-entered"
    assert "deck_reading" in cm.FIELDS, "no new column: the existing field carries the mark"


def test_the_deck_list_shows_confidence_analyst_entered_and_the_group_of_its_type(api):
    client, _ = api
    new = _add(client).json()
    r = client.get(f"/api/audits/{AUDIT}/decks")
    assert r.status_code == 200, r.text
    c = next(x for x in r.json()["candidates"] if x["id"] == new["id"])
    assert c["confidence"]["text"] == "Analyst-entered" and c["group"] == 1
    assert next(x for x in r.json()["candidates"] if x["id"] == "c01")["confidence"]["text"] != "Analyst-entered"


def test_removing_the_deck_removes_the_claims_added_from_it(api):
    client, db = api
    new = _add(client).json()
    assert client.delete(f"/api/audits/{AUDIT}/decks/{DECK}").status_code == 200
    assert all(x["id"] != new["id"] for x in db[decks.CANDIDATES_COLLECTION].docs)
