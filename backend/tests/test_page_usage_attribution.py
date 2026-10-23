"""Page-read calls in usage and cost (George, 2026-10-23): a page read is billed to the audit that triggered it and shows in the owner's
cost per audit and in that audit's usage; the page cache is per audit, never shared; a reply served from the cache is logged as a
cache hit, in the call log and in the server log (counts and a hash only)."""
import asyncio
import copy
import json
import logging
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")

import test_llm_gateway as t  # noqa: E402
from test_page_pipeline import LINES, PROSE, REPLY, TITLE, _page_db, deck  # noqa: E402
from test_structure_reading import AUDIT, AUDIT_DOC, REVENUE_MAPPING  # noqa: E402

from app import allowance, structures  # noqa: E402
from app.decks import TEXT_COLLECTION  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.llm.schemas import PAGE_CLAIMS  # noqa: E402

OTHER = "audit-other"


def two_audits(monkeypatch):
    """The same deck uploaded to two audits of one database."""
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = deck([TITLE, *LINES, PROSE])
    db = _page_db(parsed)
    db["audits"].docs.append({**copy.deepcopy(AUDIT_DOC), "id": OTHER})
    db["datasets"].docs.append({"audit_id": OTHER, "dtype": "revenue", "mapping": REVENUE_MAPPING, "mapped_at": "2026-10-05T00:00:00"})
    db[TEXT_COLLECTION].docs.append({"audit_id": OTHER, "deck_id": "d2", "file": "deck.pdf", "page_unit": "page",
                                     "blocks": parsed["blocks"], "structures": parsed["structures"]})
    return db


def read(db, audit, deck_id, adapter):
    return asyncio.run(structures.process_deck(db, audit, deck_id, adapter=adapter, sleep=t._noop_sleep))


def test_a_page_read_is_in_the_cost_of_the_audit_that_triggered_it_and_in_no_other(monkeypatch):
    db = two_audits(monkeypatch)
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    assert read(db, AUDIT, "d1", adapter) == "read"
    costs = {c["run_id"]: c for c in db["llm_calls"].docs}
    assert set(costs) == {AUDIT} and costs[AUDIT]["structure_type"] == PAGE_CLAIMS and costs[AUDIT]["estimated_cost_usd"] > 0
    usage = asyncio.run(gateway.usage_for_run(db, AUDIT))
    assert usage.structure_calls == 1 and usage.by_deck["d1"].calls == 1 and usage.estimated_cost_usd > 0
    assert asyncio.run(gateway.usage_for_run(db, OTHER)).estimated_cost_usd == 0
    for doc, created in zip(db["audits"].docs, ("2026-10-23T02:00:00+00:00", "2026-10-23T01:00:00+00:00")):
        doc.update(owner=None, created_at=created)               # the owner's list is newest first: AUDIT, then OTHER
    first, second = asyncio.run(allowance.audit_costs(db))["audits"]
    assert (first["calls"], first["cost_usd"] > 0) == (1, True) and (second["calls"], second["cost_usd"]) == (0, 0)


def test_the_page_cache_is_per_audit_the_same_deck_in_another_audit_is_read_and_billed_there(monkeypatch, caplog):
    db = two_audits(monkeypatch)
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    read(db, AUDIT, "d1", adapter)
    assert adapter.calls == 1
    with caplog.at_level(logging.INFO, logger="growth"):
        assert read(db, OTHER, "d2", adapter) == "read"
    assert adapter.calls == 2, "another audit never reads the first audit's cached reply"
    assert {r["audit_id"] for r in db[gateway.STRUCTURES_COLLECTION].docs} == {AUDIT, OTHER}
    billed = [c for c in db["llm_calls"].docs if not c["cache_hit"]]
    assert sorted(c["run_id"] for c in billed) == sorted([AUDIT, OTHER])
    assert not any("cache hit" in r.getMessage() for r in caplog.records)


def test_a_page_reply_served_from_the_cache_is_logged_as_a_cache_hit(monkeypatch, caplog):
    db = two_audits(monkeypatch)
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    read(db, AUDIT, "d1", adapter)
    with caplog.at_level(logging.INFO, logger="growth"):
        read(db, AUDIT, "d1", adapter)
    assert adapter.calls == 1
    hits = [c for c in db["llm_calls"].docs if c["cache_hit"]]
    assert len(hits) == 1 and (hits[0]["status"], hits[0]["run_id"], hits[0]["structure_type"], hits[0]["deck_id"]) == \
        ("cache_hit", AUDIT, PAGE_CLAIMS, "d1") and hits[0]["estimated_cost_usd"] == 0
    lines = [r.getMessage() for r in caplog.records if "structure cache hit" in r.getMessage()]
    assert len(lines) == 1 and f"run_id={AUDIT}" in lines[0] and "type=page_claims" in lines[0] and "hash=" in lines[0]
    usage = asyncio.run(gateway.usage_for_run(db, AUDIT))
    assert usage.by_deck["d1"].cache_hits == 1 and usage.by_deck["d1"].calls == 1
