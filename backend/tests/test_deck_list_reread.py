"""Opening the audit never writes (review of PR 225, George, 2026-11-03). The deck list computes which stored page replies an older normaliser
checked and says "Re-read needed" for their deck; it adds, changes and deletes no row. The stored replies are checked again on Run audit, from
the stored reply, with no model call. A version check that fails never fails the list: the deck says "check failed". A row of the structure
read, the rules read or Add from deck is no page reply's: it never makes a deck "Re-read needed"."""
import asyncio
import copy
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

import test_llm_gateway as t  # noqa: E402
from deck_actuals_support import reading  # noqa: E402
from pdf_support import pdf_page  # noqa: E402
from test_page_pipeline import LINES, PROSE, REPLY, TITLE, claim  # noqa: E402
from test_structure_reading import AUDIT, _api  # noqa: E402

import server  # noqa: E402
from app import structures  # noqa: E402
from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION  # noqa: E402
from app.decks.parser import parse_deck  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.structures import checker  # noqa: E402

PAGE_2 = [(50, 560, 20, "Pipeline"), (50, 500, 12, "120 Enterprise Customers"), (50, 480, 12, "$2,000,000 contracted revenue")]
REPLY_1 = {"type": "page_claims", "claims": REPLY["claims"][:2]}        # two claims that stand on their lines of page 1
REPLY_2 = {"type": "page_claims", "claims": [claim("p2r2c1", 120, metric="customers", unit="count", label_cell="p2r1c1"),
                                             claim("p2r3c1", 2000000, unit="USD")]}


def one_page():
    return parse_deck(pdf_page([TITLE, *LINES, PROSE]), "deck.pdf")


def two_pages():
    one, two = one_page(), parse_deck(pdf_page(PAGE_2), "deck.pdf")
    second = lambda items: [{**i, "page": 2} for i in items]  # noqa: E731
    return {**one, "pages": 2, "blocks": one["blocks"] + second(two["blocks"]), "layout": one["layout"] + second(two["layout"]),
            "structures": one["structures"] + second(two["structures"])}


def open_audit(monkeypatch, parsed, replies=(), **deck):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    client, db, adapter = _api(monkeypatch, list(replies))
    db[TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "deck.pdf", "format": "pdf", "page_unit": "page", "pages": parsed["pages"],
                                     "blocks": parsed["blocks"], "layout": parsed["layout"], "structures": parsed["structures"],
                                     "uploaded_at": datetime.now(timezone.utc).isoformat(), **deck})
    return client, db, adapter


def read(db, adapter):
    asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))


def decks(client):
    r = client.get(f"/api/audits/{AUDIT}/decks")
    assert r.status_code == 200, r.text
    return r.json()["decks"]


def snapshot(db):
    return {name: copy.deepcopy(db[name].docs) for name in (CANDIDATES_COLLECTION, TEXT_COLLECTION, gateway.STRUCTURES_COLLECTION)}


def stale(db):
    """An older normaliser checked the stored reply, and left a figure a million times too large."""
    for reply in db[gateway.STRUCTURES_COLLECTION].docs:
        reply["normaliser_version"] = 0
    next(r for r in db[CANDIDATES_COLLECTION].docs if r["claim_type"] == "revenue")["value"] = 150000 * 10 ** 6


# ---------------------------------------------------------------------------
# A poll of the deck list during a read
# ---------------------------------------------------------------------------
def test_a_deck_list_poll_during_a_two_page_read_adds_no_rows(monkeypatch):
    """The deck panel polls the list every 5 s while a deck reads. A reply the gateway has stored and the run has not yet checked is no stale
    reply: the poll writes nothing, and the run's own check then writes each row once, whatever order the pages answered in (the live case:
    page 2 answered before page 1, and the poll's rows doubled the deck's claims)."""
    client, db, adapter = open_audit(monkeypatch, two_pages(), [REPLY_2, REPLY_1], ai_status="reading")     # the first call is page 2's
    real, seen = gateway.read_structure, {}

    async def page_two_answers_first(*args, **kwargs):
        if kwargs.get("pages") == [1]:
            while "poll" not in seen:
                await asyncio.sleep(0)
        result = await real(*args, **kwargs)
        if kwargs.get("pages") == [2]:
            seen["before"] = snapshot(db)
            seen["poll"] = client.get(f"/api/audits/{AUDIT}/decks")
            seen["after"] = snapshot(db)
        return result
    monkeypatch.setattr(gateway, "read_structure", page_two_answers_first)
    read(db, adapter)
    assert seen["poll"].status_code == 200 and adapter.calls == 2
    assert seen["after"] == seen["before"], "a poll during the read adds, changes and deletes nothing"
    assert seen["after"][CANDIDATES_COLLECTION] == [], "no row exists before the run has checked a reply"
    assert not seen["poll"].json()["decks"][0]["reread_needed"], "a deck being read checks its replies itself: no 'Re-read needed' on the way"
    rows = db[CANDIDATES_COLLECTION].docs
    assert len({(r["structure_key"], r["order"], r.get("cell")) for r in rows}) == len(rows) == 4, "each figure of the two pages is one row"


# ---------------------------------------------------------------------------
# The version check on opening: read only, never fatal
# ---------------------------------------------------------------------------
def test_opening_says_re_read_needed_for_a_reply_of_an_older_normaliser_and_writes_nothing(monkeypatch):
    client, db, adapter = open_audit(monkeypatch, one_page(), [REPLY_1], ai_status="reading")
    read(db, adapter)
    db[TEXT_COLLECTION].docs[0]["ai_status"] = "read"
    assert not decks(client)[0]["reread_needed"], "a reply of the current normaliser needs nothing"
    stale(db)
    before = snapshot(db)
    for _ in range(2):
        assert decks(client)[0]["reread_needed"] is True
    assert snapshot(db) == before, "opening the audit writes and deletes nothing"
    assert adapter.calls == 1


def test_an_error_in_the_version_check_never_fails_the_deck_list_the_deck_says_check_failed(monkeypatch, caplog):
    client, db, adapter = open_audit(monkeypatch, one_page(), [REPLY_1], ai_status="reading")
    read(db, adapter)
    db[TEXT_COLLECTION].docs[0]["ai_status"] = "read"
    assert decks(client)[0].get("check_failed") in (None, False)

    def broken(*args, **kwargs):
        raise RuntimeError("the secret page text 800 Paying Users")
    monkeypatch.setattr(db[gateway.STRUCTURES_COLLECTION], "find", broken)
    caplog.set_level(logging.DEBUG)
    listed = client.get(f"/api/audits/{AUDIT}/decks")
    assert listed.status_code == 200, "the list never fails for the version check"
    body = listed.json()
    assert body["decks"][0]["check_failed"] is True and not body["decks"][0]["reread_needed"]
    assert len(body["candidates"]) == 2, "the claims are listed as before"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in logged and "secret page text" not in logged, "the log names the error type, never its message"


# ---------------------------------------------------------------------------
# Only the rows of a page reply count as lost
# ---------------------------------------------------------------------------
def test_a_deck_read_by_the_structure_read_opens_twice_with_no_re_read_needed(monkeypatch):
    """The structure read (DECK_PIPELINE=rules, audits read before 2026-10-22) stores rows with a structure key and no page reply."""
    sources = [{"file": "deck.pdf", "page": 1, "kind": "structure", "structure": "table", "cell": "r1c1"}]
    client, db, _ = open_audit(monkeypatch, one_page(), ai_status="read")
    db[CANDIDATES_COLLECTION].docs.append({**reading("c1", 150000.0, "Revenue", "FY2025", page=1, structure_key="a-structure-key", status="pending",
                                                     file="deck.pdf", sources=sources), "audit_id": AUDIT})
    for _ in range(2):
        assert not decks(client)[0].get("reread_needed"), "a structure-read row has no page reply to lose"
    assert "reread_needed" not in db[TEXT_COLLECTION].docs[0], "and nothing was written to the deck"


@pytest.mark.parametrize("origin", [None, "deck_analyst", "analyst"])
def test_rows_of_the_rules_read_and_of_add_from_deck_never_make_a_deck_re_read_needed(monkeypatch, origin):
    client, db, _ = open_audit(monkeypatch, one_page(), ai_status="read")
    db[CANDIDATES_COLLECTION].docs.append({**reading("c1", 150000.0, "Revenue", "FY2025", page=1, structure_key="rules-key", status="pending",
                                                     file="deck.pdf", origin=origin), "audit_id": AUDIT})
    assert not decks(client)[0].get("reread_needed")


def test_a_page_reply_row_whose_reply_is_gone_still_makes_its_deck_re_read_needed(monkeypatch):
    client, db, adapter = open_audit(monkeypatch, one_page(), [REPLY_1], ai_status="reading")
    read(db, adapter)
    db[TEXT_COLLECTION].docs[0]["ai_status"] = "read"
    db[gateway.STRUCTURES_COLLECTION].docs.clear()
    for row in db[CANDIDATES_COLLECTION].docs:
        row.pop("normaliser_version", None)
    assert decks(client)[0]["reread_needed"] is True


# ---------------------------------------------------------------------------
# Run audit rewrites the rows from the stored replies
# ---------------------------------------------------------------------------
@pytest.fixture()
def run_claims(monkeypatch):
    async def entered(*args, **kwargs):
        return {"entered": 0, "open": 0, "turnover_open": 0}
    monkeypatch.setattr(server, "_enter_matched_claims", entered)


def test_run_audit_checks_a_reply_of_an_older_normaliser_again_from_the_stored_reply_with_no_model_call(monkeypatch, run_claims):
    client, db, adapter = open_audit(monkeypatch, one_page(), [REPLY_1], ai_status="reading")
    read(db, adapter)
    db[TEXT_COLLECTION].docs[0]["ai_status"] = "read"
    db["audits"].docs[0]["results"] = {"as_of_month": "2025-06"}
    stale(db)
    assert decks(client)[0]["reread_needed"] is True
    r = client.post(f"/api/audits/{AUDIT}/run/claims")
    assert r.status_code == 200 and r.json()["status"] == "done", r.text
    revenue = [row["value"] for row in db[CANDIDATES_COLLECTION].docs if row["claim_type"] == "revenue"]
    assert revenue == [150000] and len(db[CANDIDATES_COLLECTION].docs) == 2, "the figure is checked again and each row is written once"
    assert adapter.calls == 1, "no model call"
    assert db[gateway.STRUCTURES_COLLECTION].docs[0]["normaliser_version"] == checker.NORMALISER_VERSION
    assert not decks(client)[0]["reread_needed"], "the flag goes when the reply has been checked again"


def test_an_error_in_the_check_again_never_fails_run_audit(monkeypatch, run_claims):
    client, db, adapter = open_audit(monkeypatch, one_page(), [REPLY_1], ai_status="reading")
    read(db, adapter)
    db[TEXT_COLLECTION].docs[0]["ai_status"] = "read"
    db["audits"].docs[0]["results"] = {"as_of_month": "2025-06"}

    async def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(structures, "renormalise_audit", broken)
    r = client.post(f"/api/audits/{AUDIT}/run/claims")
    assert r.status_code == 200 and r.json()["status"] == "done", r.text


def test_a_deck_whose_check_again_fails_is_left_flagged_and_the_other_decks_are_still_checked(monkeypatch, caplog):
    """The review's repro: a stored reply that names a page the deck does not have (a KeyError in the check). It costs that deck its check, never the others'."""
    client, db, adapter = open_audit(monkeypatch, one_page(), [REPLY_1], ai_status="reading")
    read(db, adapter)
    deck, reply = db[TEXT_COLLECTION].docs[0], db[gateway.STRUCTURES_COLLECTION].docs[0]
    deck["ai_status"] = "read"
    db[TEXT_COLLECTION].docs.append({**copy.deepcopy(deck), "deck_id": "d2", "file": "deck2.pdf"})
    db[gateway.STRUCTURES_COLLECTION].docs.append({**copy.deepcopy(reply), "key": "second-deck-key", "deck_id": "d2"})
    db[CANDIDATES_COLLECTION].docs.extend({**copy.deepcopy(r), "id": r["id"] + "-d2", "deck_id": "d2", "file": "deck2.pdf", "structure_key": "second-deck-key"}
                                          for r in list(db[CANDIDATES_COLLECTION].docs))
    for doc in db[gateway.STRUCTURES_COLLECTION].docs:
        doc["normaliser_version"] = 0
    reply["pages"] = [9]                                                 # d1's reply names a page the deck has not: d1 sorts first and fails
    caplog.set_level(logging.DEBUG)
    done = asyncio.run(structures.renormalise_audit(db, AUDIT))
    assert done == {"renormalised": 1, "re_read_needed": 0}
    by_key = {r["key"]: r for r in db[gateway.STRUCTURES_COLLECTION].docs}
    assert by_key["second-deck-key"]["normaliser_version"] == checker.NORMALISER_VERSION, "the other deck was checked again"
    assert not by_key[reply["key"]]["normaliser_version"], "the failed deck's reply is left as it was"
    assert asyncio.run(structures.decks_to_reread(db, AUDIT)) == {"d1"}, "and its deck stays flagged"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "check again failed" in logged and "error=KeyError" in logged and "deck_id=d1" in logged


def test_run_audit_leaves_a_deck_being_read_to_its_own_run(monkeypatch, run_claims):
    """A reply stored and not yet checked by the run that is reading it is no stale reply: Run audit does not check it a second time."""
    client, db, adapter = open_audit(monkeypatch, one_page(), [REPLY_1], ai_status="reading")
    read(db, adapter)
    db[TEXT_COLLECTION].docs[0]["ai_status"] = "reading"
    db["audits"].docs[0]["results"] = {"as_of_month": "2025-06"}
    stale(db)
    before = snapshot(db)
    client.post(f"/api/audits/{AUDIT}/run/claims")
    assert snapshot(db)[CANDIDATES_COLLECTION] == before[CANDIDATES_COLLECTION]
