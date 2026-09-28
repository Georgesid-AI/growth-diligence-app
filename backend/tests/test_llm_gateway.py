"""Tests for the LLM gateway.

These run without MongoDB and without an ANTHROPIC_API_KEY: Mongo is replaced by
a small in-memory stub and the provider by a fake adapter that counts calls. No
test in this file can reach a real model provider.
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.llm import cache, gateway, guards, prompt_store, redaction  # noqa: E402
from app.llm.schemas import Narrative  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal async Mongo stub
# ---------------------------------------------------------------------------
def _matches(doc, flt):
    for key, cond in flt.items():
        if key == "$and":
            if not all(_matches(doc, c) for c in cond):
                return False
        elif key == "$or":
            if not any(_matches(doc, c) for c in cond):
                return False
        elif isinstance(cond, dict):
            value = doc.get(key)
            for op, operand in cond.items():
                if op == "$gte" and not (value is not None and value >= operand):
                    return False
                if op == "$lt" and not (value is not None and value < operand):
                    return False
                if op == "$in" and value not in operand:
                    return False
        else:
            if doc.get(key) != cond:
                return False
    return True


def _project(doc, projection):
    if not projection:
        return dict(doc)
    include = {k: v for k, v in projection.items() if k != "_id" and v}
    if not include:
        return {k: v for k, v in doc.items() if k != "_id"}
    return {k: doc[k] for k in include if k in doc}


class FakeResult:
    def __init__(self, modified_count=0, deleted_count=0):
        self.modified_count = modified_count
        self.deleted_count = deleted_count


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return self._docs[:n]


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def find_one(self, flt, projection=None):
        for d in self.docs:
            if _matches(d, flt):
                return _project(d, projection)
        return None

    def find(self, flt, projection=None):
        return FakeCursor([_project(d, projection) for d in self.docs if _matches(d, flt)])

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return FakeResult()

    async def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                d.update(update.get("$set", {}))
                return FakeResult(modified_count=1)
        if upsert:
            new = dict(update.get("$set", {}))
            self.docs.append(new)
        return FakeResult(modified_count=0)

    async def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, flt)]
        return FakeResult(deleted_count=before - len(self.docs))

    async def count_documents(self, flt):
        return sum(1 for d in self.docs if _matches(d, flt))

    def aggregate(self, pipeline):
        docs = self.docs
        total = 0.0
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if _matches(d, stage["$match"])]
            if "$group" in stage:
                field = stage["$group"]["total"]["$sum"].lstrip("$")
                total = sum(float(d.get(field, 0.0)) for d in docs)
                return FakeCursor([{"_id": None, "total": total}])
        return FakeCursor([])


class FakeDB:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, FakeCollection())

    def __getattr__(self, name):
        return self[name]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
RUN_ID = "run-abc"
REAL_NAMES = ["Northwind Trading Ltd", "Acme Corporation", "Contoso GmbH"]

RESULTS_DOC = {
    "id": RUN_ID,
    "reporting_currency": "EUR",
    "target_arr": 6000000,
    "target_date": "2027-12-31",
    "as_of_month": "2026-06",
    "computed_at": "2026-09-26T10:00:00Z",
    "results": {
        "as_of_month": "2026-06",
        "reporting_currency": "EUR",
        "arr": {"value": 3129600, "mrr": 260800, "month": "2026-06",
                "customer": REAL_NAMES[0]},
        "nrr": {"overall_pct": 104.2, "n": 110, "month": "2026-06",
                "by_segment": {"Enterprise": {"customer": REAL_NAMES[1]}}},
        "gross_churn": {"overall_pct": 6.1, "month": "2026-06"},
        "win_rate": {"win_rate_pct": 28.7, "won": 269, "lost": 667},
        # Must never be sent: lives outside the projection, included here to
        # prove load_computed_results does not pick it up.
    },
    "datasets": {"revenue": {"rows": [{"customer": REAL_NAMES[2], "amount": 999999}]}},
}

GOOD_NARRATIVE = {
    "headline": "Ending ARR is 3129600 EUR with NRR at 104.2 percent.",
    "what_this_means": "Net revenue retention of 104.2 indicates the existing base expands.",
    "table_rows": [
        {"label": "Ending ARR", "value": "3129600", "source_key": "arr"},
        {"label": "NRR", "value": "104.2", "source_key": "nrr"},
    ],
    "worth_flagging": ["Gross revenue churn stands at 6.1 percent."],
    "next_actions": ["Request the contract list behind Customer_01."],
    "source_keys": ["arr", "nrr", "gross_churn"],
}


class FakeAdapter:
    """Stands in for AnthropicAdapter. Counts calls; never touches a network."""

    def __init__(self, replies=None, raise_with=None):
        self.calls = 0
        self.payloads = []
        self._replies = list(replies or [json.dumps(GOOD_NARRATIVE)])
        self._raise_with = raise_with

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema):
        self.calls += 1
        self.payloads.append(user_payload)
        if self._raise_with is not None:
            raise self._raise_with
        reply = self._replies[min(self.calls - 1, len(self._replies) - 1)]
        return reply, 1200, 300


async def _noop_sleep(_seconds):
    return None


def make_db():
    db = FakeDB()
    db["audits"].docs.append(dict(RESULTS_DOC))
    return db


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
def test_redaction_no_real_identifier_in_outbound_payload():
    """No value held in pseudonym_map may appear in what leaves the server."""
    async def run():
        db = make_db()
        computed = await gateway.load_computed_results(db, RUN_ID, "growth_engine")
        mapping = await redaction.get_or_create_map(db, RUN_ID, computed)
        outbound = redaction.redact(computed, mapping)

        blob = cache.canonical_json(outbound)
        stored = await db["pseudonym_map"].find_one({"run_id": RUN_ID})

        # Every real identifier the map knows about is gone from the payload.
        for real in stored["mapping"]:
            assert real not in blob, f"real identifier leaked: {real!r}"
        assert redaction.find_leaks(outbound, mapping) == []
        # And the pseudonyms did land, so redaction actually ran.
        assert any(p in blob for p in mapping.values())
        return mapping

    mapping = asyncio.run(run())
    assert mapping[REAL_NAMES[0]].startswith("Customer_")


def test_redaction_is_stable_across_calls():
    """The same run must map an identifier to the same pseudonym every time."""
    async def run():
        db = make_db()
        computed = await gateway.load_computed_results(db, RUN_ID, "growth_engine")
        first = await redaction.get_or_create_map(db, RUN_ID, computed)
        second = await redaction.get_or_create_map(db, RUN_ID, computed)
        return first, second

    first, second = asyncio.run(run())
    assert first == second


def test_restore_puts_real_names_back():
    mapping = {"Acme Corporation": "Customer_01"}
    assert redaction.restore("Customer_01 churned", mapping) == "Acme Corporation churned"


def test_gateway_never_loads_uploaded_rows():
    """The projection must exclude datasets - raw uploaded values are off-limits."""
    async def run():
        db = make_db()
        computed = await gateway.load_computed_results(db, RUN_ID, "growth_engine")
        return cache.canonical_json(computed)

    blob = asyncio.run(run())
    assert "datasets" not in blob
    assert "999999" not in blob, "an uploaded row value reached the gateway payload"


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def test_call_cap_refuses_the_sixteenth_call():
    async def run():
        db = make_db()
        for _ in range(guards.MAX_CALLS_PER_RUN):
            await db["llm_calls"].insert_one({
                "run_id": RUN_ID, "cache_hit": False, "estimated_cost_usd": 0.0,
                "timestamp": "2026-09-28T00:00:00+00:00",
            })
        adapter = FakeAdapter()
        result = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=adapter, sleep=_noop_sleep
        )
        return result, adapter

    result, adapter = asyncio.run(run())
    assert result.narrative_status == "unavailable"
    assert "call_cap_exceeded" in result.reason
    assert adapter.calls == 0, "refusal must not call the provider"
    assert result.metrics, "metrics must still be returned"


def test_spend_cap_refuses_when_exceeded(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_SPEND_CAP_USD", "0.01")

    async def run():
        db = make_db()
        from datetime import datetime, timezone
        await db["llm_calls"].insert_one({
            "run_id": "some-other-run", "cache_hit": False,
            "estimated_cost_usd": 0.50,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        adapter = FakeAdapter()
        result = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=adapter, sleep=_noop_sleep
        )
        return result, adapter

    result, adapter = asyncio.run(run())
    assert result.narrative_status == "unavailable"
    assert "daily_spend_cap_exceeded" in result.reason
    assert adapter.calls == 0
    assert result.metrics


def test_malformed_spend_cap_falls_back_to_default(monkeypatch):
    """A typo must not read as 'unlimited'."""
    monkeypatch.setenv("LLM_DAILY_SPEND_CAP_USD", "five dollars")
    assert guards.daily_spend_cap_usd() == guards.DEFAULT_DAILY_SPEND_CAP_USD


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def test_cache_hit_makes_zero_provider_calls():
    async def run():
        db = make_db()
        first_adapter = FakeAdapter()
        first = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=first_adapter, sleep=_noop_sleep
        )
        second_adapter = FakeAdapter()
        second = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=second_adapter, sleep=_noop_sleep
        )
        return first, first_adapter, second, second_adapter

    first, first_adapter, second, second_adapter = asyncio.run(run())
    assert first.narrative_status == "ok", first.reason
    assert first_adapter.calls == 1
    assert second.narrative_status == "ok", second.reason
    assert second.cache_hit is True
    assert second_adapter.calls == 0, "cache hit must not call the provider"
    assert second.narrative.headline == first.narrative.headline


def test_cache_key_changes_with_prompt_version_and_model():
    payload = {"a": 1}
    base = cache.cache_key(RUN_ID, "growth_engine", "v1", "claude-opus-5", payload)
    assert base != cache.cache_key(RUN_ID, "growth_engine", "v2", "claude-opus-5", payload)
    assert base != cache.cache_key(RUN_ID, "growth_engine", "v1", "claude-sonnet-5", payload)
    assert base != cache.cache_key(RUN_ID, "growth_engine", "v1", "claude-opus-5", {"a": 2})


def test_canonical_json_is_key_order_independent():
    assert cache.canonical_json({"b": 1, "a": 2}) == cache.canonical_json({"a": 2, "b": 1})


# ---------------------------------------------------------------------------
# Numeric guard
# ---------------------------------------------------------------------------
def test_numeric_guard_rejects_a_fabricated_figure():
    """A number the engine never produced must sink the whole narrative."""
    fabricated = dict(GOOD_NARRATIVE)
    fabricated["what_this_means"] = (
        "Retention above 100 means the base expands, implying 42.7 percent growth."
    )

    async def run():
        db = make_db()
        adapter = FakeAdapter(replies=[json.dumps(fabricated)])
        result = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=adapter, sleep=_noop_sleep
        )
        logged = await db["llm_calls"].find({"run_id": RUN_ID}).to_list(10)
        return result, logged

    result, logged = asyncio.run(run())
    assert result.narrative_status == "unavailable"
    assert "42.7" in result.reason
    assert result.narrative is None
    assert result.metrics, "metrics survive a rejected narrative"
    assert logged[0]["status"] == "numeric_guard_rejected"
    assert logged[0]["estimated_cost_usd"] > 0, "a rejected call still cost money"


def test_numeric_guard_accepts_numbers_present_in_payload():
    async def run():
        db = make_db()
        adapter = FakeAdapter()
        return await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=adapter, sleep=_noop_sleep
        )

    result = asyncio.run(run())
    assert result.narrative_status == "ok", result.reason
    assert result.narrative.headline


def test_numeric_guard_unit():
    payload = {"arr": {"value": 3129600}, "nrr": {"overall_pct": 104.2}}
    clean = Narrative(headline="ARR is 3129600", what_this_means="NRR 104.2")
    assert gateway.numeric_guard(clean, payload) is None
    dirty = Narrative(headline="ARR grew 17.5 percent", what_this_means="")
    assert "17.5" in gateway.numeric_guard(dirty, payload)


def test_source_key_guard_rejects_unknown_key():
    payload = {"arr": {"value": 1}}
    bad = Narrative(
        headline="x", what_this_means="y",
        table_rows=[{"label": "Made up", "value": "1", "source_key": "not_a_key"}],
    )
    assert "not_a_key" in gateway.source_key_guard(bad, payload)


# ---------------------------------------------------------------------------
# Failure behaviour
# ---------------------------------------------------------------------------
def test_provider_failure_returns_metrics_with_status_unavailable():
    class Boom(Exception):
        status_code = 503

    async def run():
        db = make_db()
        adapter = FakeAdapter(raise_with=Boom("upstream on fire"))
        result = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=adapter, sleep=_noop_sleep
        )
        return result, adapter

    result, adapter = asyncio.run(run())
    assert result.narrative_status == "unavailable"
    assert result.narrative is None
    assert result.metrics["arr"]["value"] == 3129600, "computed metrics still returned"
    # Two retries on a 5xx, so three attempts in total, then give up.
    assert adapter.calls == gateway.MAX_PROVIDER_RETRIES + 1


def test_bad_request_is_not_retried():
    """A 400 is a bug, not a blip - retrying just spends money twice."""
    class BadRequest(Exception):
        status_code = 400

    async def run():
        db = make_db()
        adapter = FakeAdapter(raise_with=BadRequest("invalid"))
        result = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=adapter, sleep=_noop_sleep
        )
        return result, adapter

    result, adapter = asyncio.run(run())
    assert result.narrative_status == "unavailable"
    assert adapter.calls == 1


def test_parse_failure_retries_once_then_fails():
    async def run():
        db = make_db()
        adapter = FakeAdapter(replies=["not json at all", "still not json"])
        result = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=adapter, sleep=_noop_sleep
        )
        return result, adapter

    result, adapter = asyncio.run(run())
    assert result.narrative_status == "unavailable"
    assert adapter.calls == gateway.MAX_PARSE_RETRIES + 1
    assert result.metrics


def test_parse_failure_recovers_on_the_retry():
    async def run():
        db = make_db()
        adapter = FakeAdapter(replies=["garbage", json.dumps(GOOD_NARRATIVE)])
        result = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=adapter, sleep=_noop_sleep
        )
        return result, adapter

    result, adapter = asyncio.run(run())
    assert result.narrative_status == "ok", result.reason
    assert adapter.calls == 2


def test_scaffolded_step_returns_metrics_without_calling_provider():
    async def run():
        db = make_db()
        adapter = FakeAdapter()
        result = await gateway.generate_narrative(
            db, RUN_ID, "path_to_plan", adapter=adapter, sleep=_noop_sleep
        )
        return result, adapter

    result, adapter = asyncio.run(run())
    assert result.narrative_status == "unavailable"
    assert "scaffolded" in result.reason
    assert adapter.calls == 0


# ---------------------------------------------------------------------------
# Logging, usage, cleanup
# ---------------------------------------------------------------------------
def test_llm_calls_log_holds_no_prompt_or_payload_text():
    async def run():
        db = make_db()
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        return await db["llm_calls"].find({"run_id": RUN_ID}).to_list(10)

    rows = asyncio.run(run())
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {
        "run_id", "step", "prompt_version", "model", "input_tokens",
        "output_tokens", "estimated_cost_usd", "cache_hit", "status", "timestamp",
    }
    blob = json.dumps(row)
    assert "You are writing" not in blob, "prompt text leaked into the call log"
    assert "3129600" not in blob, "payload contents leaked into the call log"


def test_usage_endpoint_totals():
    async def run():
        db = make_db()
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        return await gateway.usage_for_run(db, RUN_ID)

    usage = asyncio.run(run())
    assert usage.calls == 1, "cache hits are not billed calls"
    assert usage.cache_hits == 1
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 300
    assert usage.estimated_cost_usd > 0
    assert usage.call_cap == guards.MAX_CALLS_PER_RUN


def test_purge_run_removes_every_artefact():
    async def run():
        db = make_db()
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        purged = await gateway.purge_run(db, RUN_ID)
        remaining = {
            "llm_calls": len(db["llm_calls"].docs),
            "llm_narratives": len(db["llm_narratives"].docs),
            "pseudonym_map": len(db["pseudonym_map"].docs),
            "llm_locks": len(db["llm_locks"].docs),
        }
        return purged, remaining

    purged, remaining = asyncio.run(run())
    assert purged["llm_narratives"] >= 1
    assert purged["llm_calls"] >= 1
    assert purged["pseudonym_map"] == 1
    assert all(count == 0 for count in remaining.values()), remaining


# ---------------------------------------------------------------------------
# Architectural invariants
# ---------------------------------------------------------------------------
def test_prompt_text_never_returned_in_a_response():
    async def run():
        db = make_db()
        result = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        return result

    result = asyncio.run(run())
    blob = json.dumps(result.model_dump())
    prompt_body = prompt_store.load("growth_engine").text
    assert prompt_body[:60] not in blob
    assert "Absolute rules" not in blob
    assert result.prompt_version == "v1", "the version is returned, the text is not"


def test_no_file_io_outside_prompt_store():
    """The gateway's only data accessor is Mongo. prompt_store is the sole
    module allowed to touch disk, and only for its own prompts directory."""
    package = BACKEND / "app" / "llm"
    offenders = []
    io_pattern = re.compile(r"\bopen\(|Path\([^)]*\)\.(read|write)_|os\.(open|listdir|walk)\b")
    for path in package.glob("*.py"):
        if path.name == "prompt_store.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if io_pattern.search(line) and not line.strip().startswith("#"):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], "file I/O found outside prompt_store:\n" + "\n".join(offenders)


def test_api_key_has_no_default_in_code():
    """The key comes from ANTHROPIC_API_KEY only - never a literal, never a
    REACT_APP_* variable the frontend could see."""
    source = (BACKEND / "app" / "llm" / "gateway.py").read_text()
    assert "REACT_APP" not in source
    assert re.search(r'api_key\s*=\s*["\']sk-', source) is None
    assert 'os.environ.get("ANTHROPIC_API_KEY", "")' in source


def test_adapter_refuses_to_run_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    adapter = gateway.AnthropicAdapter(api_key="")
    with pytest.raises(gateway.GatewayError) as exc:
        adapter._ensure_client()
    assert exc.value.reason == "provider_not_configured"


def test_temperature_is_withheld_from_models_that_reject_it():
    """Sampling params were removed on current Opus/Sonnet: sending temperature
    to claude-opus-5 is a 400, so the adapter must omit it."""
    assert gateway.DEFAULT_MODEL not in gateway.MODELS_ACCEPTING_TEMPERATURE
    assert gateway.STEP_CONFIG["growth_engine"]["temperature"] == 0.2


def test_only_growth_engine_has_a_prompt():
    assert gateway.STEP_CONFIG["growth_engine"]["enabled"] is True
    scaffolded = [s for s, c in gateway.STEP_CONFIG.items() if not c["enabled"]]
    assert scaffolded, "other steps should be scaffolded as config entries"
    for step in scaffolded:
        with pytest.raises(FileNotFoundError):
            prompt_store.load(gateway.STEP_CONFIG[step]["prompt"])
