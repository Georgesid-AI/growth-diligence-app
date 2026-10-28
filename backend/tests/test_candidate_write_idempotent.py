"""Reading the same deck twice leaves one candidate per (deck_id, structure_key, order, cell) (live bug, 2026-10-28: every figure of an
audit listed twice, two stored candidates identical but for their id). Synthetic pages only."""
import asyncio
import json

import pytest

from app import structures
from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION
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


def test_two_readings_of_one_figure_that_fold_keep_the_metric_name_over_the_page_heading_and_all_page_references():
    from app.decks import claims
    cell = {"page": 3, "cell": "r9c8", "kind": "page"}
    other = {"page": 12, "cell": "r9c8", "kind": "page"}
    heading = {"id": "a", "deck_id": "d", "structure_key": "k", "order": 3, "cell": "r9c8", "status": "pending", "sources": [cell],
               "label_from": "2021 REVENUE"}
    metric = {**heading, "id": "b", "sources": [cell, other], "label_from": "Recognised Revenue"}
    for pair in ([heading, metric], [metric, heading]):
        folded = claims.fold_twins(pair)
        assert len(folded) == 1 and folded[0]["label_from"] == "Recognised Revenue", "a metric name beats a heading with the year"
        assert {s["page"] for s in folded[0]["sources"]} == {3, 12}, "both page references stay"
    longer = claims.fold_twins([{**heading, "label_from": "Revenue"}, {**heading, "id": "b", "label_from": "Net recognised revenue"}])
    assert longer[0]["label_from"] == "Net recognised revenue", "of two alike, the longer"
    assert claims.fold_twins([{**heading, "label_from": None}, {**heading, "id": "b", "label_from": "MRR"}])[0]["label_from"] == "MRR"
    assert claims.fold_twins([{**heading, "label_from": "MRR"}, {**heading, "id": "b", "label_from": None}])[0]["label_from"] == "MRR"


def _waiting(db):
    db["datasets"].docs[0]["mapped_at"] = "2026-10-05T00:00:00"
    db["audits"].docs[0]["structure_reading_consent"] = True
    db[TEXT_COLLECTION].docs[0]["ai_status"] = "waiting"
    return db


def test_two_triggers_on_one_waiting_deck_make_one_model_read():
    """The upload's settle step and a Map save both call process_waiting_decks_safely: the second finds the deck taken."""
    db = _waiting(_page_db(deck([TITLE, *LINES])))
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])

    async def go():
        return await asyncio.gather(*[structures.process_waiting_decks(db, AUDIT, adapter=adapter, sleep=t._noop_sleep) for _ in range(2)])

    ran = asyncio.run(go())
    assert sorted(len(r) for r in ran) == [0, 1] and adapter.calls == 1, "one trigger read the deck, the other left it alone"
    assert len(db[CANDIDATES_COLLECTION].docs) == 3


def test_a_waiting_deck_whose_read_fails_returns_to_waiting():
    db = _waiting(_page_db(deck([TITLE, *LINES])))

    async def boom(*a, **k):
        raise RuntimeError("x")

    import pytest as _p
    with _p.MonkeyPatch.context() as m:
        m.setattr(structures, "process_deck", boom)
        asyncio.run(structures.process_waiting_decks_safely(db, AUDIT))
    assert db[TEXT_COLLECTION].docs[0]["ai_status"] == "waiting"
    assert asyncio.run(structures.process_waiting_decks(db, AUDIT, adapter=t.FakeAdapter(replies=[json.dumps(REPLY)]), sleep=t._noop_sleep)) == ["d1"]
