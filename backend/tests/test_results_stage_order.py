"""Results stage ordering and completeness (Architecture change, rule 32; task of 2026-11-05).

1. The results are calculated only after the deck claims are done for every deck with figures.
2. A stored result carries the time of the latest reading or claims it was built from; a later reading or claims makes it older.
3. The claims step stores, per deck, the pages read in the first and the second read and the pages missing; "done" needs full coverage.
4. The second read is stored page by page.
5. The stage timeouts scale with the work.
6. The memo rates Data reliability "not rated" and names a deck the results were built without.
7. One log line per claims run and per results run.
Synthetic data only; every provider is a script."""
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from test_page_pipeline import AUDIT as DECK_AUDIT, TITLE, _page_db, claim, deck  # noqa: E402
from test_structure_reading import AUDIT as AUDIT_S  # noqa: E402
from test_run_audit import AUDIT, add_deck, stage, upload_files  # noqa: E402

from app import decks, ic_memo, readings, run_audit, structures, verdict as vd  # noqa: E402
from app.decks import TEXT_COLLECTION  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402

LINES = [(50, 500, 12, "800 Paying Users"), (50, 480, 12, "$150,000 annual revenue FY2025"), (50, 460, 12, "97% margins")]
ONE = json.dumps({"type": "page_claims", "claims": [claim("p1r2c1", 800, metric="customers", unit="count"), claim("p1r3c1", 150000, period="2025")]})


class Cut(BaseException):
    """The run is cut: no handler of Exception catches it."""


def record(expected, first, second, second_on=True):
    return run_audit.claims_record(expected, first, second, second_on, "2026-11-05T09:00:00+00:00")


def set_deck(client, **fields):
    client.db[decks.TEXT_COLLECTION].docs[0].update(fields)


# --- 3. the record ------------------------------------------------------------------------------------------------------------

def test_a_record_is_complete_only_with_every_page_read_and_each_second_read_equal_to_the_first():
    assert run_audit.record_complete(record([1, 2, 3], [1, 2, 3], [1, 2, 3]))
    first_short = record([1, 2, 3], [1, 2], [1, 2])
    assert first_short["missing"] == [3] and not run_audit.record_complete(first_short)
    second_short = record([1, 2, 3], [1, 2, 3], [1, 2])
    assert second_short["missing"] == [3] and not run_audit.record_complete(second_short), "the second read must cover what the first covers"
    assert run_audit.record_complete(record([1, 2, 3], [1, 2, 3], [], second_on=False)), "with the second read off, the first alone is enough"
    assert not run_audit.record_complete(None)


def test_the_incomplete_message_counts_the_missing_pages_over_the_pages_with_figures():
    gate = run_audit.decks_gate([{"file": "a.pdf", "ai_status": "read", "claims_record": record(list(range(1, 45)), list(range(1, 42)), list(range(1, 42)))}])
    assert gate["state"] == "incomplete"
    assert run_audit.incomplete_message(gate) == "Deck claims incomplete: 3 of 44 pages. Retry this stage."


def test_a_deck_the_page_reader_does_not_apply_to_does_not_hold_the_results_back():
    for status in ("python_only", "blocked", "prompt_missing"):
        gate = run_audit.decks_gate([{"file": "a.pdf", "ai_status": status, "claims_record": record([1, 2], [], [])}])
        assert gate["state"] == "clear", status


# --- 4. page by page ----------------------------------------------------------------------------------------------------------

def read_one_page_deck(monkeypatch, replies, **env):
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    db = _page_db(deck([TITLE, *LINES]))
    adapter = t.FakeAdapter(replies=replies)
    asyncio.run(structures.process_deck(db, DECK_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    return db, adapter


def test_the_record_of_a_deck_read_twice_is_complete_and_counts_both_reads(monkeypatch, second_page_read):
    db, adapter = read_one_page_deck(monkeypatch, [ONE])
    doc = db[TEXT_COLLECTION].docs[0]
    assert adapter.calls == 2
    assert doc["claims_record"]["expected"] == [1] and doc["claims_record"]["first"] == [1] and doc["claims_record"]["second"] == [1]
    assert doc["claims_record"]["missing"] == [] and run_audit.record_complete(doc["claims_record"])
    assert doc["page_reads"][0]["second"] is True and doc["claims_at"]


def test_a_page_whose_second_read_fails_is_missing_and_is_read_again_by_the_retry_from_that_page_alone(monkeypatch, second_page_read):
    db, adapter = read_one_page_deck(monkeypatch, [ONE, "fail"])
    doc = db[TEXT_COLLECTION].docs[0]
    assert doc["claims_record"]["first"] == [1] and doc["claims_record"]["second"] == [] and doc["claims_record"]["missing"] == [1]
    assert doc["retry_pages"] == [1], "the retry asks for the page whose second read is missing"
    before = adapter.calls
    adapter._replies[:] = [ONE]
    asyncio.run(structures.process_deck(db, DECK_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    doc = db[TEXT_COLLECTION].docs[0]
    assert doc["claims_record"]["missing"] == [] and doc["page_reads"][0]["second"] is True
    assert adapter.calls == before + 1, "the first read comes from the cache: one call, the second read"


def test_pages_already_read_stay_stored_when_the_batch_stops(monkeypatch, second_page_read):
    """Two pages; the run is cut after page 1 has been stored (the second page's call raises past every guard): page 1 stays in the record."""
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    from test_deck_list_reread import REPLY_1, REPLY_2, open_audit, two_pages
    _, db, adapter = open_audit(monkeypatch, two_pages(), [REPLY_1, REPLY_1, REPLY_2], ai_status="reading")
    from app.llm import gateway
    real = gateway.read_structure

    async def second_page_dies(*args, **kwargs):
        if kwargs.get("pages") == [2]:
            await asyncio.sleep(0.05)          # page 1 finishes first
            raise Cut()            # not an Exception: nothing below catches it
        return await real(*args, **kwargs)
    monkeypatch.setattr(gateway, "read_structure", second_page_dies)
    with pytest.raises(Cut):
        asyncio.run(structures.pages.process_deck_pages(db, AUDIT_S, "d1", adapter=adapter, sleep=t._noop_sleep))
    doc = db[TEXT_COLLECTION].docs[0]
    assert doc["claims_record"]["first"] == [1] and doc["claims_record"]["second"] == [1], "page 1 was stored when it finished"
    assert doc["claims_record"]["missing"] == [2]
    assert [r["pages"] for r in doc["page_reads"]] == [[1]]


# --- 1. the order ------------------------------------------------------------------------------------------------------------

def test_the_stages_run_mapping_claims_engine():
    assert run_audit.STAGES == ("mapping", "claims", "engine")


def test_the_results_wait_while_a_deck_is_being_read_and_are_not_calculated(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, ai_status="reading")
    out = stage(run_api, "engine")
    assert (out["status"], out["message"]) == ("running", run_audit.DECKS_READING)
    assert not run_api.db["audits"].docs[0]["results"]


def test_the_results_are_not_calculated_on_partial_deck_figures(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=record([1, 2, 3], [1, 2], [1, 2]))
    out = stage(run_api, "engine")
    assert out["status"] == "waiting" and out["message"] == run_audit.WAIT_CLAIMS
    assert not run_api.db["audits"].docs[0]["results"]
    assert run_api.post(f"/api/audits/{AUDIT}/compute").status_code == 409, "the compute endpoint refuses too"


def test_the_claims_stage_fails_on_an_incomplete_record_and_names_the_pages(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=record([1, 2, 3, 4], [1, 2], [1, 2]))
    out = stage(run_api, "claims")        # nothing to queue: no retry pages stored
    assert (out["status"], out["message"]) == ("failed", "Deck claims incomplete: 2 of 4 pages. Retry this stage.")


def test_the_claims_stage_is_done_when_every_deck_is_complete_and_then_the_results_run(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=record([1, 2], [1, 2], [1, 2]))
    assert stage(run_api, "claims")["status"] == "done"
    out = stage(run_api, "engine")
    assert out["status"] == "done" and run_api.db["audits"].docs[0]["results"]
    assert run_api.db["audits"].docs[0]["results_basis"]["decks"] == ["testco_board.pptx"]


def test_a_retry_of_the_claims_stage_queues_the_deck_for_its_missing_pages(run_api, monkeypatch):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=record([1, 2], [1], [1]), retry_pages=[2])
    queued = []

    async def fake(db, audit_id, deck_id, **kwargs):
        queued.append(deck_id)
    monkeypatch.setattr(structures, "process_deck_safely", fake)
    out = stage(run_api, "claims")
    assert out["status"] == "running" and queued == ["d1"]
    queued.clear()
    run_api.post(f"/api/audits/{AUDIT}/run/claims?poll=true")
    assert queued == [], "asking again for a stage already started queues nothing twice"


# --- 2. the age of the results ------------------------------------------------------------------------------------------------

def test_results_carry_the_time_of_the_latest_claims_and_become_older_when_claims_are_rewritten(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=record([1], [1], [1]), claims_at="2026-11-05T09:00:00+00:00")
    stage(run_api, "engine")
    basis = run_api.db["audits"].docs[0]["results_basis"]
    assert basis["latest"] >= "2026-11-05T09:00:00+00:00"
    summary = run_api.get(f"/api/audits/{AUDIT}/review").json()
    assert summary["results_older"] is False and summary["results_older_text"] is None
    later = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    set_deck(run_api, claims_at=later)
    summary = run_api.get(f"/api/audits/{AUDIT}/review").json()
    assert summary["results_older"] is True and summary["results_older_text"] == "Results are older than the latest reading – run Calculating results again."
    assert summary["engine_stale"] is True, "Run audit offers the results step again"
    assert run_api.get(f"/api/audits/{AUDIT}/results").json()["audit"]["results_older"] is True
    stage(run_api, "engine")
    assert run_api.get(f"/api/audits/{AUDIT}/review").json()["results_older"] is False, "calculating again clears it"


def test_a_file_read_again_after_the_results_makes_them_older(run_api):
    upload_files(run_api)
    stage(run_api, "engine")
    run_api.db[readings.USES].docs.append({"audit_id": AUDIT, "key": "k1", "at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
    assert run_api.get(f"/api/audits/{AUDIT}/review").json()["results_older"] is True


def test_the_memo_says_the_results_are_older(run_api):
    upload_files(run_api)
    add_deck(run_api)
    stage(run_api, "engine")
    set_deck(run_api, claims_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
    text = run_api.get(f"/api/audits/{AUDIT}/memo.md").text
    assert run_audit.RESULTS_OLDER in text and ic_memo.RESULTS_OLDER == run_audit.RESULTS_OLDER


# --- 5. the timeouts ------------------------------------------------------------------------------------------------------------

def test_the_timeout_grows_with_the_pages_and_the_reads_per_page():
    assert run_audit.stage_timeout(0, 2) == run_audit.TIMEOUT_BASE_SECONDS
    assert run_audit.stage_timeout(44, 2) == run_audit.TIMEOUT_BASE_SECONDS + 44 * 2 * run_audit.TIMEOUT_PER_PAGE_READ_SECONDS
    assert run_audit.stage_timeout(44, 2) > 24 * 5, "longer than the fixed 24 polls of 5 s a 44-page audit used to get"
    assert run_audit.stage_timeout(44, 2) > run_audit.stage_timeout(44, 1) > run_audit.stage_timeout(10, 1)


def test_a_running_stage_tells_the_caller_how_long_it_may_take(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, ai_status="reading", claims_record=record(list(range(1, 45)), [], []))
    assert stage(run_api, "claims")["timeout_seconds"] == run_audit.stage_timeout(44, 2)
    assert stage(run_api, "engine")["timeout_seconds"] == run_audit.stage_timeout(44, 2)


# --- 6. the memo ---------------------------------------------------------------------------------------------------------------

def test_a_result_built_with_fewer_decks_than_have_figures_is_not_rated_and_names_the_missing_deck(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=record([1], [1], [1]))
    stage(run_api, "engine")
    run_api.db[decks.TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d2", "file": "second_deck.pdf", "ai_status": "read",
                                                  "claims_record": record([1, 2], [1, 2], [1, 2])})
    text = run_api.get(f"/api/audits/{AUDIT}/memo.md").text
    reliability = next(line for line in text.splitlines() if line.startswith("| Data reliability"))
    assert vd.NOT_RATED_DECKS == "not rated – deck claims incomplete" and "not rated – deck claims incomplete" in reliability
    flagged = text.split("## Worth flagging")[1].split("## ")[0]
    line, = [x for x in flagged.splitlines() if x.startswith("- Deck claims incomplete")]
    assert "second_deck.pdf" in line and "testco_board.pptx" not in line
    rated = run_api.get(f"/api/audits/{AUDIT}/verdict").json()
    assert "deck claims incomplete" in json.dumps(rated)


def test_a_result_built_with_every_deck_keeps_its_rating(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=record([1], [1], [1]))
    stage(run_api, "engine")
    text = run_api.get(f"/api/audits/{AUDIT}/memo.md").text
    assert "deck claims incomplete" not in text


# --- 7. the log ------------------------------------------------------------------------------------------------------------------

def test_one_line_per_claims_run_and_per_results_run_with_the_pages_read_missing_elapsed_and_timeout(run_api, caplog):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=record([1, 2, 3], [1, 2], [1]))
    caplog.set_level(logging.INFO)
    stage(run_api, "claims")
    line, = [r.getMessage() for r in caplog.records if r.getMessage().startswith("claims run:")]
    assert "d1:first=2/3,second=1/2" in line and "pages_missing=2" in line and "elapsed=" in line and f"timeout={run_audit.stage_timeout(3, 2)}s" in line
    assert "testco" not in line, "codes and counts only"
    set_deck(run_api, claims_record=record([1, 2, 3], [1, 2, 3], [1, 2, 3]))
    caplog.clear()
    stage(run_api, "engine")
    line, = [r.getMessage() for r in caplog.records if r.getMessage().startswith("results run:")]
    assert "d1:first=3/3,second=3/3" in line and "pages_missing=0" in line and "elapsed=" in line and "timeout=" in line


def test_the_page_reader_logs_its_own_line_per_deck(monkeypatch, second_page_read, caplog):
    caplog.set_level(logging.INFO)
    read_one_page_deck(monkeypatch, [ONE])
    line, = [r.getMessage() for r in caplog.records if r.getMessage().startswith("claims run:")]
    assert "first=1/1" in line and "second=1/1" in line and "missing=-" in line and "elapsed=" in line and "timeout=" in line


def test_the_pipeline_module_still_exposes_the_page_reader_switch():
    assert pipeline.second_read_enabled() in (True, False)
    assert server.run_audit.STAGES[1] == "claims"


def test_the_stored_page_entries_stay_in_page_order_whichever_page_answers_first(monkeypatch):
    from test_deck_list_reread import REPLY_1, REPLY_2, open_audit, two_pages
    from app.llm import gateway
    _, db, adapter = open_audit(monkeypatch, two_pages(), [REPLY_2, REPLY_1], ai_status="reading")
    real, seen = gateway.read_structure, {"two": False}

    async def page_two_first(*args, **kwargs):
        if kwargs.get("pages") == [1]:
            while not seen["two"]:
                await asyncio.sleep(0)
        result = await real(*args, **kwargs)
        if kwargs.get("pages") == [2]:
            seen["two"] = True
        return result
    monkeypatch.setattr(gateway, "read_structure", page_two_first)
    asyncio.run(structures.pages.process_deck_pages(db, AUDIT_S, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert [r["pages"] for r in db[TEXT_COLLECTION].docs[0]["page_reads"]] == [[1], [2]]
    assert db[TEXT_COLLECTION].docs[0]["claims_record"]["first"] == [1, 2]


# --- Continue without page N (George, 2026-11-05) ---------------------------------------------------------------------------------------------

def unreadable_record(expected=(1, 2, 3), first=(1, 2), second=(1, 2), unreadable=((3, "too_large"),)):
    return run_audit.claims_record(list(expected), list(first), list(second), True, "2026-11-05T09:00:00+00:00", unreadable=list(unreadable))


def continue_without(client, pages, deck_id="d1"):
    return client.post(f"/api/audits/{AUDIT}/decks/{deck_id}/continue-without", json={"pages": pages})


def test_the_claims_failure_offers_continue_without_for_a_page_that_can_never_be_read(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=unreadable_record())
    out = stage(run_api, "claims")
    assert out["status"] == "failed" and out["message"] == "Deck claims incomplete: 1 of 3 pages. Retry this stage."
    assert out["can_continue"] == [{"deck_id": "d1", "file": "testco_board.pptx", "pages": [{"page": 3, "reason": "too large for the token cap"}]}]


def test_a_page_missing_for_a_retryable_reason_is_not_offered(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=unreadable_record(first=(1,), second=(1,), unreadable=()))
    out = stage(run_api, "claims")
    assert out["status"] == "failed" and out["can_continue"] == []


def test_continuing_without_the_page_stores_an_override_and_the_deck_counts_complete_then_the_results_run(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=unreadable_record())
    assert stage(run_api, "engine")["status"] == "waiting"
    r = continue_without(run_api, [3])
    assert r.status_code == 200, r.text
    override, = run_api.db[decks.TEXT_COLLECTION].docs[0]["page_overrides"]
    assert (override["page"], override["reason"]) == (3, "too_large") and override["at"]
    assert stage(run_api, "claims")["status"] == "done"
    assert stage(run_api, "engine")["status"] == "done"


def test_continue_without_refuses_a_page_that_can_be_read_or_is_not_missing(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=unreadable_record(first=(1,), second=(1,), unreadable=((3, "too_large"),)))
    assert continue_without(run_api, [2]).status_code == 409, "page 2 is retryable"
    assert continue_without(run_api, [1]).status_code == 409, "page 1 was read"
    assert continue_without(run_api, [3], deck_id="nope").status_code == 404
    assert "page_overrides" not in run_api.db[decks.TEXT_COLLECTION].docs[0]


def test_worth_flagging_names_the_deck_page_and_reason_and_the_override_survives_a_new_read(run_api):
    upload_files(run_api)
    add_deck(run_api)
    set_deck(run_api, claims_record=unreadable_record())
    continue_without(run_api, [3])
    stage(run_api, "engine")
    text = run_api.get(f"/api/audits/{AUDIT}/memo.md").text
    flagged = text.split("## Worth flagging")[1].split("## ")[0]
    assert "- Deck testco_board.pptx: page 3 not read (too large for the token cap)" in flagged
    set_deck(run_api, claims_record=unreadable_record())      # a later read finds the page unreadable again: the override still stands
    assert stage(run_api, "claims")["status"] == "done"


def test_the_record_keeps_the_unreadable_pages_with_their_status_when_the_page_reader_stops_on_them(monkeypatch, second_page_read):
    from app.llm import gateway
    monkeypatch.setattr(gateway, "PAGE_INPUT_CAP", 50)
    from test_page_pipeline import AUDIT as A
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    db = _page_db(deck([TITLE, *LINES]))

    class Big(t.FakeAdapter):
        def count_tokens(self, **kw):
            return 1200
    asyncio.run(structures.process_deck(db, A, "d1", adapter=Big(replies=[ONE]), sleep=t._noop_sleep))
    record_ = db[TEXT_COLLECTION].docs[0]["claims_record"]
    assert record_["unreadable"] == [{"page": 1, "reason": "too_large"}] and record_["missing"] == [1]
