"""Stored readings are written once and never edited (docs/design/read-check-review.md section 9, PR 2)."""
import asyncio
import copy
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import test_llm_gateway as t  # noqa: E402
from app import readings  # noqa: E402
from app.llm import gateway  # noqa: E402

READING = {"map_version": 1, "kind": "sheet", "sheets": [{"sheet": "Report", "rows": [{"row": 5, "role": "bookings"}]}], "figures": []}
HASH, PROMPT, MODEL = "f" * 64, "store:v1", "claude-sonnet-5-5-20260101"


def run(coro):
    return asyncio.run(coro)


def test_a_reading_is_written_once_and_a_second_write_returns_the_first_unchanged():
    db = t.FakeDB()
    first = run(readings.put(db, file_hash=HASH, prompt_version=PROMPT, model=MODEL, reading=READING, input_tokens=10, output_tokens=5))
    other = copy.deepcopy(READING)
    other["sheets"][0]["rows"][0]["role"] = "revenue"
    second = run(readings.put(db, file_hash=HASH, prompt_version=PROMPT, model=MODEL, reading=other))
    assert len(db[readings.READINGS].docs) == 1
    assert second["file_map"]["sheets"][0]["rows"][0]["role"] == "bookings" == first["file_map"]["sheets"][0]["rows"][0]["role"]


def test_a_new_prompt_or_model_version_is_stored_beside_the_old_reading_and_the_old_one_stays():
    db = t.FakeDB()
    run(readings.put(db, file_hash=HASH, prompt_version="store:v1", model=MODEL, reading=READING))
    run(readings.put(db, file_hash=HASH, prompt_version="store:v2", model=MODEL, reading=READING))
    run(readings.put(db, file_hash=HASH, prompt_version="store:v1", model="claude-sonnet-5-5-20260301", reading=READING))
    assert len({d["key"] for d in db[readings.READINGS].docs}) == 3
    assert run(readings.get(db, HASH, "store:v1", MODEL)) is not None
    assert run(readings.get(db, "0" * 64, "store:v1", MODEL)) is None


def test_an_override_is_a_dated_record_of_its_own_and_the_stored_reading_is_not_touched():
    db = t.FakeDB()
    stored = run(readings.put(db, file_hash=HASH, prompt_version=PROMPT, model=MODEL, reading=READING))
    before = copy.deepcopy(db[readings.READINGS].docs[0])
    o = run(readings.add_override(db, reading=stored["key"], audit_id="a1", item="sheets.0.rows.0", path="sheets.0.rows.0.role",
                                  old="bookings", new="revenue", who="analyst", why="bookings row is recognised revenue"))
    assert db[readings.READINGS].docs[0] == before
    assert {"reading", "item", "old", "new", "who", "at", "why"} <= set(o)
    register = readings.effective(stored["file_map"], run(readings.overrides_for(db, "a1")))
    assert register["sheets"][0]["rows"][0]["role"] == "revenue" and stored["file_map"]["sheets"][0]["rows"][0]["role"] == "bookings"


def test_overrides_apply_in_the_order_they_were_made_and_a_dead_path_is_skipped():
    reading = {"sheets": [{"rows": [{"role": "a"}]}]}
    rows = [{"path": "sheets.0.rows.0.role", "new": "second", "at": "2026-10-29T10:00:00"},
            {"path": "sheets.0.rows.0.role", "new": "first", "at": "2026-10-29T09:00:00"},
            {"path": "sheets.4.rows.0.role", "new": "lost", "at": "2026-10-29T11:00:00"}]
    assert readings.effective(reading, rows)["sheets"][0]["rows"][0]["role"] == "second"


def test_the_same_item_with_the_same_reason_is_read_again_never_twice():
    db = t.FakeDB()
    run(readings.put_reread(db, reading="k", item="figures.0", reason="Reading says 5; cell C5 holds 6.", prompt_version=PROMPT, model=MODEL,
                            output={"figures": []}))
    run(readings.put_reread(db, reading="k", item="figures.0", reason="Reading says 5; cell C5 holds 6.", prompt_version=PROMPT, model=MODEL,
                            output={"figures": [{"changed": True}]}))
    assert len(db[readings.REREADS].docs) == 1 and db[readings.REREADS].docs[0]["output"] == {"figures": []}
    assert run(readings.get_reread(db, "k", "figures.0", "another reason")) is None


def test_delete_audit_removes_a_reading_when_no_audit_uses_it_and_keeps_it_while_another_does():
    db = t.FakeDB()
    stored = run(readings.put(db, file_hash=HASH, prompt_version=PROMPT, model=MODEL, reading=READING))
    run(readings.put_reread(db, reading=stored["key"], item="i", reason="r", prompt_version=PROMPT, model=MODEL, output={}))
    for audit in ("a1", "a2"):
        run(readings.use(db, audit, stored["key"]))
        run(readings.use(db, audit, stored["key"]))                                   # once per audit
        run(readings.save_checks(db, audit, HASH, {"file": "x"}))
        run(readings.add_override(db, reading=stored["key"], audit_id=audit, item="i", path="p", old=1, new=2, who="analyst", why="w"))
    assert len(db[readings.USES].docs) == 2
    first = run(readings.purge_audit(db, "a1"))
    assert first["readings"] == 0 and len(db[readings.READINGS].docs) == 1
    assert not [d for d in db[readings.CHECKS].docs + db[readings.OVERRIDES].docs if d["audit_id"] == "a1"]
    second = run(gateway.purge_run(db, "a2"))
    assert second["readings"] == 1 and second["reading_rereads"] == 1
    assert all(not db[c].docs for c in readings.COLLECTIONS)
