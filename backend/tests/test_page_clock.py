"""The page clock (George, 2026-11-05, a real board pack): the 60-second page clock starts when the model call is sent, not when the page is queued.

Finding on whether page reads wait behind a running sheet read: they did. A sheet read held the audit's one structure lock (run id + step
`structures`) for its whole provider call, up to five minutes, and a page read takes that lock before it sends, inside its own 60 seconds. A
sheet read now holds a lock of its own (gateway.SHEET_LOCK_STEP), so the two run at once, and the page's clock starts when its call is sent.
A page that never got a call is recorded "not_sent" with the seconds it waited, never "timeout" and never counted as rejected."""
import asyncio
import sys
import time
from pathlib import Path

import page_images
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

import test_llm_gateway as t  # noqa: E402
from test_deck_list_reread import decks, one_page, open_audit  # noqa: E402
from test_page_pipeline import _page_db  # noqa: E402
from test_page_reads_speed import EMPTY, Gauge, many_pages  # noqa: E402
from test_sheet_by_sheet import BySheet, book  # noqa: E402
from test_structure_reading import AUDIT  # noqa: E402

from app import read_reasons, structures  # noqa: E402
from app.decks import TEXT_COLLECTION, pages  # noqa: E402
from app.llm import gateway, guards  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402


@pytest.fixture(autouse=True)
def reader_env(monkeypatch):
    monkeypatch.setenv("SHEET_READER_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("DECK_PIPELINE", "ai")


def run_pages(db, parsed, adapter, **kwargs):
    grids = pages.page_grids(parsed["blocks"])
    return pipeline.read_pages(db, AUDIT, "d1", grids, page_images.image_for, adapter=adapter, sleep=t._noop_sleep, per_call=1, **kwargs)


def test_a_page_queued_behind_a_long_call_is_not_timed_out_by_the_wait():
    parsed = many_pages(1)
    db = _page_db(parsed)

    async def scenario():
        token = await guards.acquire(db, AUDIT, guards.STRUCTURE_STEP)         # a long call holds the audit's structure lock

        async def free():
            await asyncio.sleep(0.8)                                             # four times the page timeout below
            await guards.release(db, AUDIT, guards.STRUCTURE_STEP, token)
        freeing = asyncio.ensure_future(free())
        reads = await run_pages(db, parsed, Gauge(hold=0.05), page_timeout=0.2)
        await freeing
        return reads
    (grids, result), = asyncio.run(scenario())
    assert result.status == "read", f"the page was queued, not sent, for longer than its clock: {result.status} {result.reason}"


def test_the_clock_still_runs_from_the_send_and_a_timeout_says_how_long():
    parsed = many_pages(2)
    adapter = Gauge(hold=0.01, slow={2})
    adapter.slow_for = 1.0
    reads = asyncio.run(run_pages(_page_db(parsed), parsed, adapter, parallel=2, page_timeout=0.2))
    by_page = {pages.page_number(g[0]): r for g, r in reads}
    assert (by_page[2].status, by_page[2].reason) == ("not_read", "timeout") and by_page[2].seconds == 0.2
    assert by_page[1].status == "read"


def test_a_page_that_never_got_a_call_is_not_sent_with_the_time_it_waited(monkeypatch):
    parsed = many_pages(1)
    db = _page_db(parsed)
    monkeypatch.setattr(gateway, "PAGE_LOCK_ROUNDS", 2)

    async def short_wait(db_, run_id, step, timeout=0):
        await asyncio.sleep(0.1)
        return False
    monkeypatch.setattr(guards, "wait_for_inflight", short_wait)

    adapter = Gauge(hold=0.01)

    async def scenario():
        await guards.acquire(db, AUDIT, guards.STRUCTURE_STEP)               # never released
        return await run_pages(db, parsed, adapter, page_timeout=0.05)
    (grids, result), = asyncio.run(scenario())
    assert (result.status, result.reason) == ("not_read", "not_sent") and result.seconds >= 0.2, "the wait is kept, in seconds"
    assert adapter.calls == 0


def test_a_sheet_read_in_flight_does_not_hold_up_a_page_read():
    """The sheet read holds its lock for the whole of its (here 0.8 s) call; the page read runs beside it and ends first."""
    parsed = many_pages(1)
    db = _page_db(parsed)

    class SlowSheet(BySheet):
        def complete(self, **kw):
            time.sleep(0.8)
            return super().complete(**kw)
    done = {}

    async def scenario():
        async def sheet():
            result = await gateway.read_structure(db, AUDIT, book(["Plan"]), "sheet_reading", adapter=SlowSheet(), sleep=t._noop_sleep, file_hash="c" * 64)
            done["sheet"] = (time.monotonic(), result.status)

        async def deck():
            await asyncio.sleep(0.2)                                             # the sheet call is under way
            reads = await run_pages(db, parsed, Gauge(hold=0.05), page_timeout=0.5)
            done["page"] = (time.monotonic(), reads[0][1].status)
        await asyncio.gather(sheet(), deck())
    asyncio.run(scenario())
    assert done["page"][1] == "read" and done["sheet"][1] == "read"
    assert done["page"][0] < done["sheet"][0], "the page did not wait for the sheet read"


def test_the_stored_page_entry_carries_the_reason_and_seconds_and_the_deck_line_says_it_in_plain_words(monkeypatch):
    client, db, adapter = open_audit(monkeypatch, one_page(), replies=[])
    monkeypatch.setattr(gateway, "PAGE_LOCK_ROUNDS", 1)

    async def short_wait(*a, **k):
        await asyncio.sleep(0.05)
        return False
    monkeypatch.setattr(guards, "wait_for_inflight", short_wait)

    async def scenario():
        await guards.acquire(db, AUDIT, guards.STRUCTURE_STEP)
        return await structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep)
    assert asyncio.run(scenario()) == "not_read"
    doc, = db[TEXT_COLLECTION].docs
    entry, = doc["page_reads"]
    assert entry["status"] == "not_read" and entry["reason"] == "not_sent" and isinstance(entry["seconds"], int)
    deck, = decks(client)
    assert deck["read_reason"] == read_reasons.not_sent_line(entry["seconds"]) and deck["read_reason"].startswith("Page reads were not sent (waited ")
    assert "rejected" not in deck["read_reason"] and "timeout" not in deck["read_reason"].lower()


def test_a_timed_out_deck_says_so_with_the_seconds(monkeypatch):
    client, db, adapter = open_audit(monkeypatch, one_page(), replies=[])

    class Slow(t.FakeAdapter):
        def complete(self, **kw):
            time.sleep(2.0)
            return super().complete(**kw)

    async def scenario():
        real = pipeline.read_pages

        async def quick(*a, **k):
            return await real(*a, **{**k, "page_timeout": 1.0})
        monkeypatch.setattr(pipeline, "read_pages", quick)
        return await structures.process_deck(db, AUDIT, "d1", adapter=Slow(replies=[EMPTY]), sleep=t._noop_sleep)
    assert asyncio.run(scenario()) == "not_read"
    deck, = decks(client)
    assert deck["read_reason"] == "Timed out after 1 s"
