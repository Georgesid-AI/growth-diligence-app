"""The server-side prompt store (docs/specs/prompt-store.md; CLAUDE.md rule 26).

The gateway reads the latest version of each named prompt from the `prompts` collection and from nowhere else. A prompt that
is not loaded means the error "No prompt loaded — upload prompts on the owner page" and no model call. The real prompts are
not in the repository; these tests load the test-only stubs of tests/fixtures/prompts/ into the fake store (FakeDB). No network.
"""
import asyncio
import json
from pathlib import Path

import pytest

from app.llm import cache, gateway, prompt_store
import test_llm_gateway as t
from prompt_fixtures import stub_documents

BACKEND = Path(__file__).resolve().parent.parent
RUN_ID = t.RUN_ID
MESSAGE = "No prompt loaded — upload prompts on the owner page"


class RecordingAdapter(t.FakeAdapter):
    """FakeAdapter that keeps the system prompt each call was sent."""

    def complete(self, *, system, **kwargs):
        self.systems = getattr(self, "systems", []) + [system]
        return super().complete(system=system, **kwargs)


def run(coro):
    return asyncio.run(coro)


# --- the store: versions, hash, nothing deleted ---------------------------------------------------------------------------

def test_every_upload_is_the_next_version_with_its_hash_and_nothing_is_ever_changed_or_deleted():
    db = t.FakeDB()
    db["prompts"].docs.clear()
    first = run(prompt_store.upload(db, "growth_engine", "first text"))
    second = run(prompt_store.upload(db, "growth_engine", "first text"))        # the same text is still a new version
    other = run(prompt_store.upload(db, "data_integrity", "another prompt"))
    assert (first["version"], second["version"], other["version"]) == ("v1", "v2", "v1")
    import hashlib
    assert first["sha256"] == hashlib.sha256(b"first text").hexdigest() == second["sha256"]
    assert set(first) == {"name", "version", "uploaded_at", "sha256"}, "the returned row holds no text"
    before = [dict(d) for d in db["prompts"].docs]
    run(prompt_store.upload(db, "growth_engine", "third text"))
    assert db["prompts"].docs[:3] == before, "an upload adds a document; it never edits or removes one"
    assert {tuple(sorted(d)) for d in db["prompts"].docs} == {("name", "sha256", "text", "uploaded_at", "version")}
    assert [(d["name"], d["version"]) for d in db["prompts"].docs] == [
        ("growth_engine", "v1"), ("growth_engine", "v2"), ("data_integrity", "v1"), ("growth_engine", "v3")]
    assert any(i["unique"] and i["keys"] == [("name", 1), ("version", 1)] for i in db["prompts"].indexes), \
        "a name and version are unique, so two uploads at once cannot share a version"


def test_the_latest_version_is_numeric_so_v10_follows_v9():
    db = t.FakeDB()
    db["prompts"].docs.clear()
    for n in range(1, 11):
        run(prompt_store.upload(db, "growth_engine", f"text {n}"))
    loaded = run(prompt_store.load(db, "growth_engine"))
    assert (loaded.version, loaded.text) == ("v10", "text 10")


def test_the_list_holds_name_version_date_and_hash_never_the_text():
    db = t.FakeDB()
    db["prompts"].docs.clear()
    run(prompt_store.upload(db, "growth_engine", "SECRET METHOD ONE"))
    run(prompt_store.upload(db, "growth_engine", "SECRET METHOD TWO"))
    rows = run(prompt_store.list_versions(db))
    assert [(r["name"], r["version"]) for r in rows] == [("growth_engine", "v2"), ("growth_engine", "v1")]
    assert all(set(r) == {"name", "version", "uploaded_at", "sha256"} for r in rows)
    assert "SECRET" not in json.dumps(rows)


@pytest.mark.parametrize("name, text, why", [
    ("not_a_prompt", "text", "unknown prompt name"),
    ("../growth_engine", "text", "unknown prompt name"),
    ("growth_engine", "   \n", "empty"),
    ("growth_engine", "x" * (prompt_store.MAX_TEXT_CHARS + 1), "over"),
])
def test_an_upload_the_store_refuses_adds_nothing(name, text, why):
    db = t.FakeDB()
    db["prompts"].docs.clear()
    with pytest.raises(prompt_store.PromptRefused, match=why):
        run(prompt_store.upload(db, name, text))
    assert db["prompts"].docs == []


def test_the_names_are_the_prompts_the_gateway_reads():
    enabled = {c["prompt"] for c in gateway.STEP_CONFIG.values() if c.get("enabled")}
    assert set(prompt_store.NAMES) == enabled | {gateway.STRUCTURE_PROMPT}


def test_no_prompt_text_is_in_the_repository_only_marked_stubs():
    assert not (BACKEND / "app" / "llm" / "prompts").exists()
    assert list((BACKEND / "app" / "llm").rglob("*.md")) == []
    stubs = sorted((BACKEND / "tests" / "fixtures" / "prompts").glob("*.md"))
    assert {p.stem for p in stubs} == set(prompt_store.NAMES)
    for path in stubs:
        text = path.read_text(encoding="utf-8")
        assert "TEST ONLY" in text and len(text) < 300, f"{path.name} is a short stub marked test only"
    assert "Prompt text is never committed to the repository" in (BACKEND.parent / "CLAUDE.md").read_text(encoding="utf-8")


# --- the gateway: latest version only, missing prompt means no call ---------------------------------------------------------

def test_the_gateway_sends_the_latest_version_and_records_its_number():
    async def go():
        db = t.make_db()
        await prompt_store.upload(db, "growth_engine", "Stub two. Test only.")
        adapter = RecordingAdapter()
        result = await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep)
        return db, adapter, result

    db, adapter, result = run(go())
    assert adapter.systems == ["Stub two. Test only."] and result.prompt_version == "v2"
    assert db["llm_narratives"].docs[0]["prompt_version"] == "v2" and db["llm_calls"].docs[0]["prompt_version"] == "v2"


@pytest.mark.parametrize("step", ["growth_engine", "data_inventory", "data_integrity"])
def test_a_missing_prompt_is_the_error_message_with_the_metrics_and_no_model_call(step):
    async def go():
        db = t.make_db()
        db["prompts"].docs.clear()
        adapter = RecordingAdapter()
        result = await gateway.generate_narrative(db, RUN_ID, step, adapter=adapter, sleep=t._noop_sleep)
        return db, adapter, result

    db, adapter, result = run(go())
    assert prompt_store.NO_PROMPT == MESSAGE
    assert (result.narrative_status, result.reason) == ("unavailable", MESSAGE)
    assert result.narrative is None and result.metrics, "the computed metrics still render (CLAUDE.md rule 20)"
    assert adapter.calls == 0 and db["llm_calls"].docs == [] and db["llm_narratives"].docs == []


def test_one_missing_prompt_stops_only_its_own_step():
    async def go():
        db = t.make_db()
        db["prompts"].docs[:] = [d for d in db["prompts"].docs if d["name"] != "growth_engine"]
        adapter = RecordingAdapter()
        missing = await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep)
        return missing, adapter, await prompt_store.missing(db)

    missing, adapter, names = run(go())
    assert missing.reason == MESSAGE and adapter.calls == 0 and names == ["growth_engine"]


def test_a_prompt_with_only_blank_text_counts_as_missing():
    async def go():
        db = t.make_db()
        db["prompts"].docs[0]["text"] = " \n"
        return await gateway.generate_narrative(db, RUN_ID, db["prompts"].docs[0]["name"], adapter=RecordingAdapter(),
                                                sleep=t._noop_sleep)

    assert run(go()).reason == MESSAGE


def test_reading_and_estimating_without_a_prompt_spend_nothing_and_say_not_generated():
    async def go():
        db = t.make_db()
        db["prompts"].docs.clear()
        read = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        estimate = await gateway.estimate_narratives(db, RUN_ID)
        return read, estimate

    read, estimate = run(go())
    assert read.narrative_status == "not_generated" and read.narrative is None
    assert all(s["available"] is False and s["estimate_usd"] == 0 for s in estimate["steps"])


def test_the_structure_path_reads_nothing_without_its_prompt():
    import test_structure_reading as sr
    db = sr._db()
    db["prompts"].docs.clear()
    result, adapter = sr._read(db)
    assert result.status == "not_read" and adapter.calls == 0


# --- a new version makes the earlier narrative not shown, as a prompt change always did ---------------------------------------

def test_a_new_prompt_version_changes_the_cache_key_and_hides_the_earlier_narrative_without_deleting_it():
    async def go():
        db = t.make_db()
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=t.FakeAdapter(), sleep=t._noop_sleep)
        served = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        await prompt_store.upload(db, "growth_engine", "Stub two. Test only.")
        after = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        calls = len(db["llm_calls"].docs)
        again = await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=t.FakeAdapter(), sleep=t._noop_sleep)
        return db, served, after, calls, again

    db, served, after, calls, again = run(go())
    assert served.narrative_status == "ok" and served.prompt_version == "v1"
    assert after.narrative_status == "not_generated" and after.superseded is True
    assert after.superseded_reason == "prompt_release_changed", "the reason code the screen already words"
    assert calls == 1, "reading never spends"
    assert again.narrative_status == "ok" and again.cache_hit is False and again.prompt_version == "v2"
    assert [d["prompt_version"] for d in db["llm_narratives"].docs] == ["v1", "v2"], "the old narrative is kept"


def test_the_cache_key_carries_the_prompt_version():
    one, two = (prompt_store.Prompt("growth_engine", v, "t", "h") for v in ("v1", "v2"))
    def key(prompt):
        return cache.cache_key(RUN_ID, "growth_engine", prompt_store.cache_tag(prompt), "claude-opus-5", {"a": 1})
    assert key(one) != key(two)


def test_the_stub_documents_are_what_an_upload_writes():
    db = t.FakeDB()
    db["prompts"].docs.clear()
    for doc in stub_documents():
        row = run(prompt_store.upload(db, doc["name"], doc["text"]))
        stored = next(d for d in db["prompts"].docs if d["name"] == doc["name"])
        assert (row["version"], row["sha256"]) == (doc["version"], doc["sha256"]) == (stored["version"], stored["sha256"])
