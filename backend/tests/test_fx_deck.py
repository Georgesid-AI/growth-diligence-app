"""FX rates apply to deck claims as well as uploaded files (task of 2026-10-09, item 6). Synthetic data only (rule 15)."""
import copy

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_chat_upload as chat  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from test_chat_upload import api as chat_api, AUDIT as CHAT_AUDIT  # noqa: E402,F401

from app import claim_matching as cm  # noqa: E402
from app import decks  # noqa: E402

AUDIT = "audit-fx"
USD_CLAIM = {"audit_id": AUDIT, "id": "m1", "deck_id": "d1", "status": "pending", "claim_type": "market", "value": 5e9,
             "value_high": None, "unit": None, "currency": "USD", "target_date": None, "file": "deck.pptx", "order": 0,
             "sources": [{"file": "deck.pptx", "slide": 2, "kind": "text"}], "snippet": "Market size $5bn"}


@pytest.fixture()
def api(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT, "reporting_currency": "EUR", "fiscal_year_end": 12, "as_of_month": None, "results": None})
    db[decks.CANDIDATES_COLLECTION].docs.append(copy.deepcopy(USD_CLAIM))
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


def claim(client):
    return client.get(f"/api/audits/{AUDIT}/decks").json()["candidates"][0]


def test_a_usd_claim_needs_a_rate_until_one_is_entered_and_the_rate_needs_no_revenue_file(api):
    client, db = api
    assert claim(client)["fx"]["rate"] is None
    done = client.put(f"/api/audits/{AUDIT}/fx", json={"fx": {"usd": 0.92}})
    assert done.status_code == 200 and done.json()["fx"] == {"USD": 0.92}
    assert db["datasets"].docs == [], "no revenue file was needed"
    assert claim(client)["fx"]["rate"] == 0.92
    assert client.get(f"/api/audits/{AUDIT}").json()["fx"] == {"USD": 0.92}


def test_a_bad_rate_or_currency_is_refused(api):
    client, _ = api
    for bad in ({"USD": 0}, {"USD": -1}, {"US": 1.1}, {"USD1": 1.1}, {"USD": "x"}):
        assert client.put(f"/api/audits/{AUDIT}/fx", json={"fx": bad}).status_code in (400, 422), bad


def test_a_rate_saved_with_the_revenue_file_still_applies_and_the_audit_rate_wins(api):
    client, db = api
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "fx": {"USD": 0.5}})
    assert claim(client)["fx"]["rate"] == 0.5
    client.put(f"/api/audits/{AUDIT}/fx", json={"fx": {"USD": 0.9}})
    assert claim(client)["fx"]["rate"] == 0.9


def test_replacing_the_revenue_file_does_not_wipe_the_rates(chat_api):
    """The cause found: a re-upload wrote fx: {} over the saved rates, so a deck claim in USD read 'FX rate needed' again."""
    chat.upload(chat_api, "blank_vs_zero.csv")
    chat_api.put(f"/api/audits/{CHAT_AUDIT}/datasets/revenue/mapping", json={"fx": {"USD": 0.9}, "billing_terms": {}})
    other = (chat.MESSY / "blank_vs_zero.csv").read_bytes() + b"\n"
    chat.upload(chat_api, "blank_vs_zero.csv", other, replace="true")
    kept = next(d for d in chat_api.db["datasets"].docs if d["dtype"] == "revenue")
    assert kept["fx"] == {"USD": 0.9}


def test_the_reason_names_the_pair():
    from test_claim_matching import run_claim
    row = run_claim({"claim_type": "revenue", "snippet": "ARR £100,000", "currency": "GBP", "value": 100000, "target_date": "2024-02"})
    assert row["reason"] == "FX rate needed: GBP→EUR"
