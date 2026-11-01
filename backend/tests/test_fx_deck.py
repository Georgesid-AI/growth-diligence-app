"""FX rates apply to deck claims as well as uploaded files (task of 2026-10-09, item 6). Synthetic data only (rule 15)."""
import copy

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402

from app import decks  # noqa: E402

AUDIT = "audit-fx"
USD_CLAIM = {"audit_id": AUDIT, "id": "m1", "deck_id": "d1", "status": "pending", "claim_type": "market", "value": 5e9,
             "value_high": None, "unit": None, "currency": "USD", "target_date": None, "file": "deck.pptx", "order": 0,
             "sources": [{"file": "deck.pptx", "slide": 2, "kind": "text"}], "snippet": "Market size $5bn"}


@pytest.fixture()
def fx_api(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT, "reporting_currency": "EUR", "fiscal_year_end": 12, "as_of_month": None, "results": None})
    db[decks.CANDIDATES_COLLECTION].docs.append(copy.deepcopy(USD_CLAIM))
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


def claim(client):
    return client.get(f"/api/audits/{AUDIT}/decks").json()["candidates"][0]


def test_a_usd_claim_needs_a_rate_until_one_is_entered_and_the_rate_needs_no_revenue_file(fx_api):
    client, db = fx_api
    assert claim(client)["fx"]["rate"] is None
    done = client.put(f"/api/audits/{AUDIT}/fx", json={"fx": {"usd": 0.92}})
    assert done.status_code == 200 and done.json()["fx"] == {"USD": 0.92}
    assert db["datasets"].docs == [], "no revenue file was needed"
    assert claim(client)["fx"]["rate"] == 0.92
    assert client.get(f"/api/audits/{AUDIT}").json()["fx"] == {"USD": 0.92}




def test_a_bad_rate_or_currency_is_refused(fx_api):
    client, _ = fx_api
    for bad in ({"USD": 0}, {"USD": -1}, {"US": 1.1}, {"USD1": 1.1}, {"USD": "x"}):
        assert client.put(f"/api/audits/{AUDIT}/fx", json={"fx": bad}).status_code in (400, 422), bad






def test_the_reason_names_the_pair():
    from test_claim_matching import run_claim
    row = run_claim({"claim_type": "revenue", "snippet": "ARR £100,000", "currency": "GBP", "value": 100000, "target_date": "2024-02"})
    assert row["reason"] == "FX rate needed: GBP→EUR"


# The item 6 artefact (run 45c08448-acdc-4310-a4e6-480ae5d84bbf, mapping step; claim row from the screenshot): a USD market
# size of 52 billion for FY2028 from page 11 of a deck, a rate of 0.9 entered with the mapping, shown converted.
ITEM6_CLAIM = {**USD_CLAIM, "id": "m6", "value": 52e9, "target_date": "2028", "period_text": "FY2028", "file": "deck.pdf",
               "sources": [{"file": "deck.pdf", "page": 11, "kind": "table"}], "snippet": "Market size ($52 B)"}




