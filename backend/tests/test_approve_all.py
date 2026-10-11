"""POST /audits/{id}/decks/candidates/approve-all (docs/specs/chat-upload.md section 17): one call approves the claims to review of
one category; it skips what a single Approve would refuse and what fails to save, and records the approval as Approve does."""
import copy
import csv
import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from claim_matching_support import engine_results, fixture  # noqa: E402

from app import decks  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402

AUDIT = "audit-all"
RUN = fixture()["runs"]["A"]
URL = f"/api/audits/{AUDIT}/decks/candidates/approve-all"
REVENUE, CUSTOMERS, CHANNELS, FUNDS, OTHER = (deck_claims.type_group(x) for x in
                                              ("revenue", "customers", "acquisition_channels", "use_of_funds", "other"))


def claim(cid, claim_type="revenue", **over):
    c = {"audit_id": AUDIT, "id": cid, "deck_id": "d1", "status": "pending", "claim_type": claim_type, "value": 1000, "value_high": None,
         "unit": None, "currency": "EUR", "snippet": f"Revenue EUR 1,000 ({cid})", "label_from": None, "file": "deck.pptx", "order": 0,
         "sources": [{"file": "deck.pptx", "slide": 3}], "target_date": "2023", "period_text": "FY2023", **over}
    deck_claims.resolve_period(c, RUN["fiscal_year_end"])
    return c


@pytest.fixture()
def api(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT, "reporting_currency": "EUR", "fiscal_year_end": 12, "as_of_month": None,
                              "results": copy.deepcopy(engine_results(tuple(RUN["files"]), RUN["as_of_month"]))})
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "fx": {}})
    docs = db[decks.CANDIDATES_COLLECTION].docs
    docs += [claim("r1"), claim("r2", value=2000), claim("r3", status="rejected"), claim("r4", status="approved"),
             claim("c1", "customers", value=40, currency=None, unit="count", snippet="40 customers"),
             claim("a1", "acquisition_channels", value=30000, currency=None, unit="count", snippet="Telegram(30K)", channel="Telegram",
                   target_date=None, period_text=None),
             claim("a2", "acquisition_channels", value=3000, currency=None, unit="count", snippet="Twitter(3K)", channel="Twitter",
                   target_date=None, period_text=None, deck_id="d2"),
             claim("f1", "use_of_funds", value=40, currency=None, unit="%", snippet="Hiring (40%)", target_date=None, period_text=None),
             claim("o1", "other", value=7, currency=None, snippet="7 things", target_date=None, period_text=None),
             claim("e1", "revenue", value=5, status="pending", parsed={"claim_type": "revenue", "value": 4})]
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


def status(db, cid):
    return next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == cid)["status"]


def test_one_call_approves_every_claim_to_review_of_the_category_and_nothing_else(api):
    client, db = api
    r = client.post(URL, json={"group": REVENUE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["approved"], body["skipped"]) == (3, 0) and sorted(body["approved_ids"]) == ["e1", "r1", "r2"]
    assert [status(db, c) for c in ("r1", "r2", "r3", "r4", "e1")] == ["approved", "approved", "rejected", "approved", "edited"], \
        "a rejected claim stays rejected; a claim carrying the parser's values is approved as Approve does: edited"
    assert [status(db, c) for c in ("c1", "a1", "a2", "f1", "o1")] == ["pending"] * 5, "other categories are untouched"


def test_the_deck_tab_limits_the_call_to_that_decks_claims(api):
    client, db = api
    body = client.post(URL, json={"group": CHANNELS, "deck_id": "d2"}).json()
    assert body["approved_ids"] == ["a2"] and status(db, "a1") == "pending"
    assert client.post(URL, json={"group": CHANNELS}).json()["approved_ids"] == ["a1"], "no deck: every deck"


def test_a_turnover_claim_without_a_revenue_or_volume_answer_is_skipped_until_it_is_answered(api):
    client, db = api
    db[decks.CANDIDATES_COLLECTION].docs.append(claim("g1", snippet="GMV EUR 900,000", value=900000))
    body = client.post(URL, json={"group": REVENUE}).json()
    assert (body["approved"], body["skipped"], body["skipped_ids"]) == (3, 1, ["g1"]) and status(db, "g1") == "pending"
    answered = client.put(f"/api/audits/{AUDIT}/claims/g1/turnover", json={"as": "volume", "reason": "deck_says_processed_volume"})
    assert answered.status_code == 200, answered.text
    assert client.post(URL, json={"group": REVENUE}).json()["approved_ids"] == ["g1"]


def test_a_claim_whose_type_is_still_to_be_chosen_is_skipped_as_a_single_approve_refuses_it(api):
    client, db = api
    one = client.put(f"/api/audits/{AUDIT}/decks/candidates/o1", json={"status": "approved"})
    assert one.status_code == 400
    body = client.post(URL, json={"group": OTHER}).json()
    assert (body["approved"], body["skipped_ids"]) == (0, ["o1"]) and status(db, "o1") == "pending"


def test_a_claim_whose_save_fails_stays_to_review_and_the_rest_are_approved(api, monkeypatch):
    client, db = api
    collection = db[decks.CANDIDATES_COLLECTION]
    real = collection.update_one

    async def flaky(flt, update, *a, **k):
        if flt.get("id") == "r1":
            raise RuntimeError("write failed")
        return await real(flt, update, *a, **k)

    monkeypatch.setattr(collection, "update_one", flaky)
    body = client.post(URL, json={"group": REVENUE}).json()
    assert (body["approved"], body["skipped"], body["skipped_ids"]) == (2, 1, ["r1"])
    assert (status(db, "r1"), status(db, "r2")) == ("pending", "approved")


def test_the_register_and_the_csv_hold_the_approved_claims_as_a_single_approve_leaves_them(api):
    client, db = api
    one = client.put(f"/api/audits/{AUDIT}/decks/candidates/r2", json={"status": "approved"}).json()
    client.post(URL, json={"group": REVENUE})
    first = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "r1")
    single = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "r2")
    assert first["status"] == one["status"] == "approved" and set(first) == set(single), "the same fields are written as Approve writes"
    register = client.get(f"/api/audits/{AUDIT}/claims").json()["register"]
    assert {r["claim_id"] for r in register} >= {"r1", "r2", "r4", "e1"}
    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/audits/{AUDIT}/claims.csv").text)))
    assert {"r1", "r2", "e1"} <= {r.get("claim_id") for r in rows}


def test_a_bad_request_is_refused_and_a_missing_audit_is_a_404(api):
    client, db = api
    for body in ({}, {"group": 0}, {"group": 99}, {"group": "revenue"}, {"group": REVENUE, "extra": 1}):
        assert client.post(URL, json=body).status_code == 422, body
    assert client.post("/api/audits/nope/decks/candidates/approve-all", json={"group": REVENUE}).status_code == 404
    assert all(status(db, c) == "pending" for c in ("r1", "r2"))
