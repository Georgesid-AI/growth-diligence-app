"""Deck page reads, speed and panel (George, 2026-10-23): up to 8 pages are read at a time, 4 for the rest of the deck after a 429; a page
with no figure is named in the panel before any call; the fixed prompt is a cached prefix on every page call; a page is given 60 seconds,
then "page n not read" and the deck keeps going; the next Run audit asks only for the pages not read; the panel reads "page n of N"
while reading and the totals when done. What the model sees, the caps and the costs are those of the one-by-one read."""
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")

from test_page_pipeline import LINES, TITLE, _page_db, deck, grid_of  # noqa: E402
from test_structure_reading import AUDIT, t  # noqa: E402

from app import structures  # noqa: E402
from app.decks import TEXT_COLLECTION, pages  # noqa: E402
from app.llm import gateway, guards  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402

EMPTY = json.dumps({"type": "page_claims", "claims": []})
PROSE_ONLY = [(50, 560, 20, "Our mission"), (50, 500, 12, "We help teams ship faster")]


def many_pages(count, plain=()):
    """A deck of `count` pages, each the same figure page, except the numbers in `plain` (prose, no digits)."""
    figure, prose = deck([TITLE, *LINES]), deck(PROSE_ONLY)
    blocks = [dict(b, page=n) for n in range(1, count + 1) for b in (prose if n in plain else figure)["blocks"]]
    return {"blocks": blocks, "structures": []}


def page_of(user_payload):
    """The number of the page a call carries (the page text opens with its page marker)."""
    return int(json.loads(user_payload)["text"].split("p")[1].split("r")[0])


class Gauge(t.FakeAdapter):
    """Counts the calls in flight at once; every call holds for `hold` seconds. `limit_at` calls answer 429 once (the rate limit)."""

    def __init__(self, hold=0.05, rate_limit_on=(), slow=(), failing=()):
        super().__init__(replies=[EMPTY])
        self.hold, self.rate_limit_on, self.slow, self.failing = hold, set(rate_limit_on), set(slow), set(failing)
        self.running = self.peak = 0
        self.seen = []
        self.after_limit = []
        self.limited = False
        self.lock = threading.Lock()

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema, cache_system=False):
        page = page_of(user_payload)
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
            self.seen.append(page)
            if self.limited:
                self.after_limit.append(self.running)
        try:
            if page in self.slow:
                time.sleep(self.slow_for)
            time.sleep(self.hold)
            if page in self.rate_limit_on and not self.limited:
                self.limited = True
                raise gateway.RetryableProviderError("429", 429, "rate_limit_error")
            if page in self.failing:
                raise gateway.GatewayError("provider_error", "no", 500, "api_error")
            return super().complete(model=model, system=system, user_payload=user_payload, max_tokens=max_tokens,
                                    temperature=temperature, json_schema=json_schema, cache_system=cache_system)
        finally:
            with self.lock:
                self.running -= 1

    slow_for = 0.6


def read(db, parsed, adapter, **kwargs):
    grids = pages.page_grids(parsed["blocks"])
    return asyncio.run(pipeline.read_pages(db, AUDIT, "d1", grids, "Zero2Hero", {}, adapter=adapter, sleep=t._noop_sleep,
                                           per_call=1, **kwargs))


# ---------------------------------------------------------------------------
# (1) eight at a time; (rate limit) four for the rest of the deck
# ---------------------------------------------------------------------------
def test_up_to_eight_pages_are_read_at_a_time_in_page_order():
    parsed = many_pages(20)
    adapter = Gauge()
    reads = read(_page_db(parsed), parsed, adapter, parallel=pipeline.PARALLEL_PAGES)
    assert pipeline.PARALLEL_PAGES == 8 and adapter.peak == 8
    assert [[pages.page_number(g) for g in grids] for grids, _ in reads] == [[n] for n in range(1, 21)], "results come back in page order"
    assert all(r.status == "read" for _, r in reads)


def test_one_by_one_is_still_what_the_scripts_get_by_default():
    parsed = many_pages(4)
    adapter = Gauge(hold=0.01)
    grids = pages.page_grids(parsed["blocks"])
    asyncio.run(pipeline.read_pages(_page_db(parsed), AUDIT, "d1", grids, "Zero2Hero", {}, adapter=adapter, sleep=t._noop_sleep))
    assert adapter.peak == 1 and len(adapter.seen) == 1, "five pages to a call, one call after another"


def test_after_a_rate_limit_error_four_pages_at_a_time_for_the_rest_of_the_deck():
    parsed = many_pages(24)
    adapter = Gauge(rate_limit_on={3})
    reads = read(_page_db(parsed), parsed, adapter, parallel=pipeline.PARALLEL_PAGES)
    assert pipeline.PARALLEL_AFTER_RATE_LIMIT == 4 and adapter.limited and adapter.peak == 8, "eight at first"
    # The calls already running when the 429 was seen finish (up to eight beside the first ones after it); the last eight calls of the deck
    # start long after, and run beside at most 3 others.
    assert max(adapter.after_limit[-8:]) <= 4, "for the rest of the deck, never more than four at once"
    assert all(r.status == "read" for _, r in reads), "the 429 is retried by the gateway; every page is read"


def test_a_rate_limit_error_the_gateway_gives_up_on_also_lowers_the_limit_and_the_page_is_not_read():
    parsed = many_pages(16)

    class Limited(Gauge):
        def complete(self, **kw):
            if page_of(kw["user_payload"]) == 2:
                time.sleep(self.hold)
                raise gateway.RetryableProviderError("429", 429, "rate_limit_error")
            return super().complete(**kw)

    adapter = Limited()
    reads = read(_page_db(parsed), parsed, adapter, parallel=8)
    by_page = {pages.page_number(g[0]): r for g, r in reads}
    assert by_page[2].status == "not_read" and all(r.status == "read" for n, r in by_page.items() if n != 2)
    assert adapter.limited is False, "(the page-2 error is the Limited class's own, not the gauge's)"


# ---------------------------------------------------------------------------
# (2) the skip rule: no digits, no call; the panel names the pages
# ---------------------------------------------------------------------------
def test_a_page_with_no_digit_is_skipped_before_any_call_and_named():
    parsed = many_pages(8, plain={3, 7})
    db = _page_db(parsed)
    grids = pages.page_grids(parsed["blocks"])
    assert pipeline.skipped_pages(grids, "Zero2Hero", {}, 8) == [3, 7]
    adapter = Gauge(hold=0.01)
    reads = read(db, parsed, adapter, parallel=8)
    assert sorted(adapter.seen) == [1, 2, 4, 5, 6, 8] and len(reads) == 6, "pages 3 and 7 never reach the gateway"
    assert 3 not in {pages.page_number(g) for grids_of, _ in reads for g in grids_of}


def test_pages_the_document_has_but_the_parser_found_no_text_on_are_skipped_too():
    parsed = many_pages(4)
    grids = pages.page_grids(parsed["blocks"])
    assert pipeline.skipped_pages(grids, "Zero2Hero", {}, 6) == [5, 6]
    assert pipeline.skipped_pages(grids, "Zero2Hero", {}) == []


# ---------------------------------------------------------------------------
# (3) the fixed prompt is a cached prefix on every page call
# ---------------------------------------------------------------------------
def test_every_page_call_marks_the_deck_reading_prompt_as_a_cached_prefix():
    parsed = many_pages(6)
    adapter = Gauge(hold=0.01)
    read(_page_db(parsed), parsed, adapter, parallel=8)
    assert len(adapter.requests) == 6 and all(r["cache_system"] is True for r in adapter.requests)


def test_the_adapter_sends_the_system_prompt_with_a_cache_control_block_for_a_page_call():
    from types import SimpleNamespace
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="{}")],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=2, cache_creation_input_tokens=0, cache_read_input_tokens=0))

    adapter = gateway.AnthropicAdapter(api_key="not-a-key")
    adapter._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    adapter.complete(model=gateway.STRUCTURE_MODEL, system="S", user_payload="{}", max_tokens=10, temperature=None, json_schema={}, cache_system=True)
    assert sent["system"] == [{"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}]


# ---------------------------------------------------------------------------
# (4) the timeout, the error, the retry
# ---------------------------------------------------------------------------
def test_a_page_that_times_out_is_not_read_and_the_deck_keeps_going():
    parsed = many_pages(6)
    adapter = Gauge(hold=0.01, slow={2})
    reads = read(_page_db(parsed), parsed, adapter, parallel=8, page_timeout=0.2)
    by_page = {pages.page_number(g[0]): r for g, r in reads}
    assert (by_page[2].status, by_page[2].reason) == ("not_read", "timeout")
    assert all(by_page[n].status == "read" for n in (1, 3, 4, 5, 6))


def test_the_page_timeout_is_sixty_seconds():
    assert pipeline.PAGE_TIMEOUT_SECONDS == 60.0


def _run_deck(db, adapter):
    return asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))


def test_a_page_that_errors_or_times_out_is_logged_and_listed_and_only_it_is_asked_again(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    monkeypatch.setattr(pipeline, "PAGE_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(pipeline, "read_pages", _with_timeout(pipeline.read_pages, 0.2))
    caplog.set_level(logging.WARNING)
    parsed = many_pages(6, plain={4})
    db = _page_db(parsed)
    first = Gauge(hold=0.01, slow={2}, failing={5})
    assert _run_deck(db, first) == "read"
    doc, = db[TEXT_COLLECTION].docs
    assert doc["unread_pages"] == [2, 5] and doc["retry_pages"] == [2, 5] and doc["skipped_pages"] == [4]
    lines = [r.getMessage() for r in caplog.records if "not read: run_id" in r.getMessage() and "page " in r.getMessage()]
    assert any(m.startswith("page 2 not read") and "reason=timeout" in m for m in lines) and any(m.startswith("page 5 not read") for m in lines)
    assert not any(deck_text in " ".join(lines) for deck_text in ("Traction", "Paying Users")), "codes only, never a line of the deck"

    # The next Run audit: the deck is queued again, and only pages 2 and 5 are asked for.
    assert asyncio.run(structures.queue_unread_pages(db, AUDIT)) == ["d1"] and doc["ai_status"] == "reading"
    second = Gauge(hold=0.01)
    assert _run_deck(db, second) == "read"
    assert sorted(second.seen) == [2, 5]
    assert not [c for c in db["llm_calls"].docs if c["status"] == "cache_hit"], "pages already read are not even asked of the gateway's cache"
    assert doc["unread_pages"] == [] and doc["retry_pages"] == []
    assert asyncio.run(structures.queue_unread_pages(db, AUDIT)) == [], "nothing left to retry: nothing queued"


def _with_timeout(real, seconds):
    async def run(*args, **kwargs):
        return await real(*args, **{**kwargs, "page_timeout": seconds})
    return run


def test_a_deck_with_no_page_left_to_retry_is_not_queued_and_one_being_read_is_not_queued_twice():
    parsed = many_pages(2)
    db = _page_db(parsed)
    doc, = db[TEXT_COLLECTION].docs
    doc.update(ai_status="read", retry_pages=[])
    assert asyncio.run(structures.queue_unread_pages(db, AUDIT)) == []
    doc.update(ai_status="reading", retry_pages=[2])
    assert asyncio.run(structures.queue_unread_pages(db, AUDIT)) == []


# ---------------------------------------------------------------------------
# (5) the status text
# ---------------------------------------------------------------------------
def test_the_deck_carries_the_progress_while_reading_and_the_totals_when_done(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    parsed = many_pages(5, plain={3})
    db = _page_db(parsed)
    seen = []

    class Watching(Gauge):
        def complete(self, **kw):
            seen.append(dict(db[TEXT_COLLECTION].docs[0].get("read_progress") or {}))
            return super().complete(**kw)

    assert _run_deck(db, Watching(hold=0.01)) == "read"
    assert seen and all(s["total"] == 4 for s in seen), "four pages go to the model, one is skipped"
    doc, = db[TEXT_COLLECTION].docs
    assert doc["skipped_pages"] == [3]


def test_the_deck_list_sends_the_panel_its_status_fields():
    assert {"read_progress", "skipped_pages", "unread_pages"} <= set(_deck_fields())


def _deck_fields():
    import importlib
    import inspect
    import re
    source = inspect.getsource(importlib.import_module("server").list_deck_candidates)
    return re.findall(r'"(\w+)": 1', source)


# ---------------------------------------------------------------------------
# the caps are those of the one-by-one read
# ---------------------------------------------------------------------------
def test_the_token_cap_stops_the_same_call_as_a_one_by_one_read_and_the_rest_are_not_called(monkeypatch):
    """Page reads in flight count at their worst case, but a read the cap refuses only because of them waits for them: the read
    that finds the cap reached with nothing beside it stops, and no later page makes a call."""
    parsed = many_pages(14)
    db = _page_db(parsed)
    monkeypatch.setattr(guards, "STRUCTURE_TOKEN_CAP", 3 * (gateway.PAGE_MAX_TOKENS + 1500))
    adapter = Gauge(hold=0.02)
    reads = read(db, parsed, adapter, parallel=8)
    statuses = [r.status for _, r in reads]
    served = statuses.count("read")
    assert 1 <= served < 14 and "stopped" in statuses
    assert len(adapter.seen) == served, "a stopped page makes no provider call"
    used = sum(c["input_tokens"] + c["output_tokens"] for c in db["llm_calls"].docs if c["status"] == "ok")
    assert used <= guards.STRUCTURE_TOKEN_CAP, "the logged tokens of the served pages stay under the cap"
    assert gateway._inflight_tokens.get(AUDIT, 0) == 0, "nothing stays reserved"


def test_a_failed_or_cancelled_read_releases_its_reserved_tokens_and_the_lock():
    parsed = many_pages(3)
    db = _page_db(parsed)
    adapter = Gauge(hold=0.01, slow={1})
    read(db, parsed, adapter, parallel=8, page_timeout=0.1)
    assert gateway._inflight_tokens.get(AUDIT, 0) == 0
    assert not [doc for doc in db[guards.LOCKS_COLLECTION].docs if doc.get("held")]


def test_grids_and_text_sent_are_those_of_the_one_by_one_read():
    """The text a one-page call carries is the page's own redacted text from the one builder; the call carries no other page."""
    parsed = many_pages(3)
    adapter = Gauge(hold=0.01)
    grids = pages.page_grids(parsed["blocks"])
    read(_page_db(parsed), parsed, adapter, parallel=8)
    sent = sorted(json.loads(p)["text"] for p in adapter.payloads)
    want = sorted(pipeline.batch_text(b) for b in pipeline.batches(grids, "Zero2Hero", {}, 1))
    assert sent == want and all(len(redact_pages(text)) == 1 for text in sent)


def redact_pages(text):
    return [line for line in text.splitlines() if line.startswith("p") and "r1c1" in line]


def test_grid_helper_is_importable():
    assert grid_of([TITLE, *LINES])["page"] == 1


# ---------------------------------------------------------------------------
# a deck "reading" for more than 10 minutes is taken as not read; Run audit restarts it (George, 2026-10-23, comment on PR 166)
# ---------------------------------------------------------------------------
def test_a_deck_reading_for_over_ten_minutes_is_restarted_with_the_message_restarted_and_a_younger_one_is_left_alone():
    from datetime import datetime, timedelta, timezone
    db = _page_db(many_pages(2))
    doc, = db[TEXT_COLLECTION].docs
    now = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
    doc.update(ai_status="reading", reading_since=(now - timedelta(minutes=9, seconds=59)).isoformat(), read_progress={"done": 1, "total": 2})
    assert asyncio.run(structures.queue_stale_reading(db, AUDIT, now)) == [], "9 minutes 59 seconds: still reading"
    assert doc["ai_status"] == "reading" and doc["read_progress"] == {"done": 1, "total": 2} and not doc.get("ai_message")
    doc["reading_since"] = (now - timedelta(minutes=10, seconds=1)).isoformat()
    assert asyncio.run(structures.queue_stale_reading(db, AUDIT, now)) == ["d1"]
    assert doc["ai_status"] == "reading" and doc["ai_message"] == structures.RESTARTED == "restarted"
    assert "read_progress" not in doc, "a restarted read starts again at the first page"
    assert asyncio.run(structures.queue_stale_reading(db, AUDIT)) == [], "the clock starts again, so the deck is not restarted twice"
    # a deck read before this change has no start time: its upload time stands; one with neither is left alone
    del doc["reading_since"]
    doc["uploaded_at"] = (now - timedelta(hours=1)).isoformat()
    assert asyncio.run(structures.queue_stale_reading(db, AUDIT, now)) == ["d1"]
    del doc["reading_since"]
    del doc["uploaded_at"]
    assert asyncio.run(structures.queue_stale_reading(db, AUDIT, now)) == []
    doc.update(ai_status="read", reading_since=(now - timedelta(hours=2)).isoformat())
    assert asyncio.run(structures.queue_stale_reading(db, AUDIT, now)) == [], "only a deck still reading is restarted"


def test_the_restarted_deck_keeps_the_pages_it_read_and_asks_only_for_the_rest(monkeypatch):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    db = _page_db(many_pages(4))
    doc, = db[TEXT_COLLECTION].docs
    assert _run_deck(db, Gauge(hold=0.01, failing={3})) == "read" and doc["unread_pages"] == [3]
    doc.update(ai_status="reading", reading_since="2026-10-23T00:00:00+00:00")
    assert asyncio.run(structures.queue_stale_reading(db, AUDIT)) == ["d1"]
    second = Gauge(hold=0.01)
    assert _run_deck(db, second) == "read" and sorted(second.seen) == [3]
    assert doc["ai_message"] is None, "the message is cleared when the read ends"
