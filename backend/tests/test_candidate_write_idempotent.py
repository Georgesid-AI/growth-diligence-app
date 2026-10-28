"""Reading the same deck twice leaves one candidate per (deck_id, structure_key, order, cell) (live bug, 2026-10-28: every figure of an
audit listed twice, two stored candidates identical but for their id). Synthetic pages only."""
import asyncio
import json

import pytest

from app import structures
from app.decks import CANDIDATES_COLLECTION
from test_page_pipeline import LINES, REPLY, TITLE, _page_db, deck
from test_structure_reading import AUDIT, t


@pytest.fixture(autouse=True)
def ai_pipeline(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")


def _read(db, times, together):
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])

    async def go():
        runs = [structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep) for _ in range(times)]
        if together:
            await asyncio.gather(*runs)
        else:
            for run in runs:
                await run

    asyncio.run(go())
    return db[CANDIDATES_COLLECTION].docs


def _keys(docs):
    return [(d["deck_id"], d["structure_key"], d["order"], (d["sources"][0].get("cell"))) for d in docs]


@pytest.mark.parametrize("together", [False, True], ids=["one after the other", "two reads at once"])
def test_reading_the_same_deck_twice_leaves_one_candidate_per_key(together):
    docs = _read(_page_db(deck([TITLE, *LINES])), 2, together)
    assert docs and len(_keys(docs)) == len(set(_keys(docs))), "a figure is listed once"


def test_two_stored_copies_of_one_candidate_are_listed_once_with_both_page_references():
    from app.decks import claims
    cell = {"page": 3, "cell": "r9c8", "kind": "page"}
    other = {"page": 12, "cell": "r9c8", "kind": "page"}
    a = {"id": "a", "deck_id": "d", "structure_key": "k", "order": 3, "cell": "r9c8", "status": "pending", "sources": [cell]}
    b = {**a, "id": "b", "sources": [cell, other]}
    lone = {"id": "c", "deck_id": "d", "structure_key": "k", "order": 4, "cell": "r9c8", "status": "pending", "sources": [cell]}
    by_hand = {"id": "e", "deck_id": "d", "order": 3, "cell": "r9c8", "status": "pending", "sources": [cell]}      # no structure key: never folded
    folded = claims.fold_twins([a, b, lone, by_hand])
    assert [c["id"] for c in folded] == ["a", "c", "e"] and folded[0]["sources"] == [cell, other]
    answered = claims.fold_twins([a, {**b, "status": "approved"}])
    assert len(answered) == 1 and answered[0]["status"] == "approved", "the copy the analyst answered stands"
