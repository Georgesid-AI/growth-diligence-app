"""Combined fixes, part A and B (task of 2026-11-05).

A1. The structure token cap scales with the work: 200,000 + pages with figures x reads per page x 12,000, floor 600,000; every claims run logs it.
A2. A refusal for the token cap is not retryable: the claims stage fails with its own message, the record marks the pages "cap", nothing queues them again.
A3. A page whose first read came from the cache adds no tokens to the cap.
B4/B5. The claims-stage failure names the deck, the count, the reason and the action (the panel's side is in the frontend tests).
Synthetic data only; every provider is a script."""
import asyncio
import logging
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import test_llm_gateway as t  # noqa: E402
from test_page_pipeline import AUDIT as DECK_AUDIT, TITLE, _page_db, deck  # noqa: E402
from test_results_stage_order import LINES, ONE, no_read, set_deck  # noqa: E402
from test_run_audit import add_deck, stage, upload_files  # noqa: E402
from test_structure_reading import AUDIT, _db, _read  # noqa: E402

from app import run_audit, structures  # noqa: E402
from app.decks import TEXT_COLLECTION  # noqa: E402
from app.llm import gateway, guards  # noqa: E402


def with_decks(db, *page_counts, audit=AUDIT):
    for n, pages in enumerate(page_counts):
        db[TEXT_COLLECTION].docs.append({"audit_id": audit, "deck_id": f"d{n}", "claims_record": {"expected": list(range(1, pages + 1))}})
    return db


def used(db, tokens, audit=AUDIT, cache_hit=False):
    db["llm_calls"].docs.append({"run_id": audit, "step": "structures", "cache_hit": cache_hit, "input_tokens": tokens, "output_tokens": 0,
                                 "estimated_cost_usd": 0.0, "timestamp": "2026-10-05T00:00:00"})


def cap_of(db, audit=AUDIT):
    return asyncio.run(structures.audit_token_cap(db, audit))


# --- A1 -----------------------------------------------------------------------------------------------------------------------

def test_the_cap_is_200000_plus_12000_per_page_read_with_a_floor_of_600000(second_page_read):
    assert cap_of(_db()) == 600_000, "no deck: the floor"
    assert cap_of(with_decks(_db(), 10)) == 600_000, "200,000 + 10 x 2 x 12,000 = 440,000 is under the floor"
    assert cap_of(with_decks(_db(), 60, 40)) == 200_000 + 100 * 2 * 12_000, "the pages of every deck of the audit"
    other = with_decks(_db(), 100, audit="elsewhere")
    assert cap_of(other) == 600_000, "another audit's decks do not count"


def test_the_cap_counts_one_read_per_page_when_the_second_read_is_off(monkeypatch):
    monkeypatch.setenv("PAGE_SECOND_READ", "0")
    assert cap_of(with_decks(_db(), 100)) == 200_000 + 100 * 12_000


def test_the_gateway_stops_at_the_computed_cap_not_at_600000(second_page_read):
    big = with_decks(_db(), 100)                  # cap 2,600,000
    used(big, 1_000_000)
    result, adapter = _read(big, token_cap=cap_of(big))
    assert (result.status, adapter.calls) == ("read", 1), "1,000,000 used is far under the cap of this audit"
    small = _db()
    used(small, 1_000_000)
    result, adapter = _read(small)
    assert (result.status, adapter.calls) == ("stopped", 0)
    scaled = with_decks(_db(), 100)
    used(scaled, 2_599_000)
    result, adapter = _read(scaled, token_cap=cap_of(scaled))
    assert result.status == "stopped" and "2,600,000-token limit" in result.reason, result.reason


def test_the_floor_wording_is_unchanged():
    db = _db()
    used(db, 599_000)
    result, _ = _read(db)
    assert result.reason == ("AI reading stopped: this audit reached its 600,000-token limit. The remaining structures were read by Python only.")


def test_a_cap_refusal_logs_the_computed_cap(caplog, second_page_read):
    db = with_decks(_db(), 100)
    used(db, 2_599_000)
    with caplog.at_level(logging.INFO):
        _read(db, token_cap=cap_of(db))
    assert "reason=token_cap used=2599000 cap=2600000" in caplog.text


def test_the_usage_view_reports_the_computed_cap(second_page_read):
    db = with_decks(_db(), 100)
    usage = asyncio.run(gateway.usage_for_run(db, AUDIT, cap_of(db)))
    assert usage.structure_token_cap == 2_600_000


def read_deck(monkeypatch, replies, db=None, **env):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    db = db or _page_db(deck([TITLE, *LINES]))
    adapter = t.FakeAdapter(replies=replies)
    asyncio.run(structures.process_deck(db, DECK_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    return db, adapter


def test_every_claims_run_logs_the_computed_cap(monkeypatch, second_page_read, caplog):
    caplog.set_level(logging.INFO)
    read_deck(monkeypatch, [ONE])
    line, = [r.getMessage() for r in caplog.records if r.getMessage().startswith("claims run:")]
    assert "cap=600000" in line, line


def test_a_deck_read_runs_under_the_cap_its_audit_earns(monkeypatch, second_page_read):
    db = _page_db(deck([TITLE, *LINES]))
    used(db, 1_000_000, audit=DECK_AUDIT)
    db, adapter = read_deck(monkeypatch, [ONE], db=db)
    assert adapter.calls == 0, "one page of figures: the floor of 600,000 applies and 1,000,000 is over it"
    db = _page_db(deck([TITLE, *LINES]))
    used(db, 1_000_000, audit=DECK_AUDIT)
    with_decks(db, 100, audit=DECK_AUDIT)          # another deck of the audit with 100 pages with figures: the cap is 2,600,000
    db, adapter = read_deck(monkeypatch, [ONE], db=db)
    assert adapter.calls == 2


# --- A2 -----------------------------------------------------------------------------------------------------------------------

def capped_deck(monkeypatch, second_page_read_on=True):
    db = _page_db(deck([TITLE, *LINES]))
    used(db, 599_000, audit=DECK_AUDIT)
    db, adapter = read_deck(monkeypatch, [ONE], db=db)
    return db, adapter


def test_pages_the_cap_refused_are_marked_cap_in_the_record_with_the_tokens_and_the_cap(monkeypatch, second_page_read):
    db, adapter = capped_deck(monkeypatch)
    assert adapter.calls == 0
    record = db[TEXT_COLLECTION].docs[0]["claims_record"]
    assert record["unreadable"] == [{"page": 1, "reason": "cap"}] and record["missing"] == [1]
    assert record["cap"] == {"used": 599_000, "cap": 600_000}


def test_a_second_read_the_cap_refused_marks_its_page_cap_too(monkeypatch, second_page_read):
    db = _page_db(deck([TITLE, *LINES]))
    used(db, 590_000, audit=DECK_AUDIT)           # room for the first read (1,500 + max tokens), not for the second

    class Fills(t.FakeAdapter):
        def complete(self, **kw):
            reply, tokens_in, _ = super().complete(**kw)
            return reply, tokens_in, 5_000
    monkeypatch.setattr(gateway, "PAGE_MAX_TOKENS", 4_000)
    adapter = Fills(replies=[ONE])
    adapter.input_tokens = 2_000
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    asyncio.run(structures.process_deck(db, DECK_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    record = db[TEXT_COLLECTION].docs[0]["claims_record"]
    assert record["first"] == [1] and record["second"] == [] and record["unreadable"] == [{"page": 1, "reason": "cap"}], record


CAP_TEXT = ("Audit token cap reached: 599,000 of 600,000 tokens used. Retrying will not help. "
            "Options: turn off the second deck read (PAGE_SECOND_READ=0) or raise the cap.")


def cap_record():
    return run_audit.claims_record([1, 2, 3], [1], [1], True, "2026-11-05T09:00:00+00:00", capped=[2, 3], cap={"used": 599_000, "cap": 600_000})


def test_the_claims_stage_fails_on_the_cap_with_its_own_message_and_is_not_retryable(run_api, monkeypatch):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=cap_record())
    queued = []

    async def fake(db, audit_id, deck_id, **kwargs):
        queued.append(deck_id)
    monkeypatch.setattr(structures, "process_deck_safely", fake)
    out = stage(run_api, "claims")
    assert (out["status"], out["message"], out["retryable"]) == ("failed", CAP_TEXT, False)
    assert "can_continue" not in out or not out["can_continue"], "no page is offered to continue without"
    assert queued == [], "the retry does not read a page the cap refused again"


def test_a_cap_stop_leaves_no_retry_list(monkeypatch, second_page_read):
    db, _ = capped_deck(monkeypatch)
    doc = db[TEXT_COLLECTION].docs[0]
    assert doc["retry_pages"] == [] and doc["claims_record"]["missing"] == [1]


def test_continue_without_is_refused_for_a_page_the_cap_refused(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=cap_record())
    r = run_api.post(f"/api/audits/{run_audit_audit()}/decks/d1/continue-without", json={"pages": [2]})
    assert r.status_code == 409


def run_audit_audit():
    from test_run_audit import AUDIT as A
    return A


# --- A3 -----------------------------------------------------------------------------------------------------------------------

def test_a_first_read_served_from_the_cache_adds_no_tokens_to_the_cap(monkeypatch, second_page_read):
    db, adapter = read_deck(monkeypatch, [ONE])
    assert adapter.calls == 2
    before = asyncio.run(guards.structure_tokens_used(db, DECK_AUDIT))
    assert before > 0
    # The deck is read again from the start (the cache serves both reads): nothing is added.
    asyncio.run(structures.process_deck(db, DECK_AUDIT, "d1", adapter=t.FakeAdapter(replies=[ONE]), sleep=t._noop_sleep))
    assert asyncio.run(guards.structure_tokens_used(db, DECK_AUDIT)) == before
    hits = [c for c in db["llm_calls"].docs if c.get("cache_hit")]
    assert hits and all(c["input_tokens"] == 0 and c["output_tokens"] == 0 for c in hits)
    assert asyncio.run(gateway.usage_for_run(db, DECK_AUDIT)).structure_tokens == before


# --- B4 / B5 ------------------------------------------------------------------------------------------------------------------

def page_reads(*entries):
    return [{"pages": [p], "status": s, "reason": r, "second": sec} for p, s, r, sec in entries]


def test_missing_pages_are_named_with_the_deck_the_count_the_reason_and_the_action(run_api, monkeypatch, second_page_read):
    upload_files(run_api)
    add_deck(run_api)
    expected = list(range(1, 20))
    first = [p for p in expected if p not in (4, 9)]
    second = [p for p in first if p not in (5, 6, 7)]
    set_deck(run_api, claims_record=run_audit.claims_record(expected, first, second, True, "2026-11-05T09:00:00+00:00"),
             page_reads=page_reads(*[(p, "read", "", False) for p in (5, 6, 7)], (4, "not_read", "timeout", False), (9, "not_read", "timeout", False)))
    monkeypatch.setattr(structures, "process_deck_safely", no_read)
    out = run_api.post(f"/api/audits/{run_audit_audit()}/run/claims?poll=true").json()       # asking again for a stage it started: nothing is queued
    assert out["status"] == "failed" and out["retryable"] is True
    assert out["message"] == ("testco_board.pptx: 5 of 19 pages are missing: page read timed out on pages 4, 9; second read timed out on pages 5, 6, 7. "
                              "Press Retry stage — it reads only the missing pages, then calculates the results. Nothing already read is lost.")


def test_an_unreadable_page_is_named_with_its_reason_and_the_two_ways_on(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=run_audit.claims_record([1, 2, 3], [1, 2], [1, 2], True, "2026-11-05T09:00:00+00:00", unreadable=[(3, "refused")]))
    out = stage(run_api, "claims")
    assert out["status"] == "failed"
    assert out["message"] == ("testco_board.pptx: 1 of 3 pages is missing: page 3 refused by the model. "
                              "Press Continue without page 3 to go on; the memo will say the page was skipped. "
                              "Or remove the deck and upload a version without that page.")
    assert out["can_continue"][0]["pages"] == [{"page": 3, "reason": "refused by the model"}]
