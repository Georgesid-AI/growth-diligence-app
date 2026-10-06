"""Tests for the LLM gateway.

These run without MongoDB and without an ANTHROPIC_API_KEY: Mongo is replaced by
a small in-memory stub and the provider by a fake adapter that counts calls. No
test in this file can reach a real model provider.
"""
import asyncio
import copy
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
                if op == "$ne" and value == operand:
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
    def __init__(self, modified_count=0, deleted_count=0, upserted_id=None):
        self.modified_count = modified_count
        self.deleted_count = deleted_count
        self.upserted_id = upserted_id


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return self._docs[:n]


class FakeCollection:
    def __init__(self):
        self.docs = []
        self.indexes = []

    async def create_index(self, keys, unique=False):
        keys = list(keys)
        if unique:
            seen = [tuple(d.get(k) for k, _ in keys) for d in self.docs]
            if len(seen) != len(set(seen)):
                from pymongo.errors import DuplicateKeyError
                raise DuplicateKeyError("E11000 duplicate key error")
        self.indexes.append({"keys": keys, "unique": unique})

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
            # Like Mongo: an upsert seeds the new document from the filter's
            # equality fields, then applies $setOnInsert and $set.
            new = {k: v for k, v in flt.items() if not k.startswith("$") and not isinstance(v, dict)}
            new.update(update.get("$setOnInsert", {}))
            new.update(update.get("$set", {}))
            self.docs.append(new)
            return FakeResult(modified_count=0, upserted_id=len(self.docs))
        return FakeResult(modified_count=0)

    async def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, flt)]
        return FakeResult(deleted_count=before - len(self.docs))

    async def replace_one(self, flt, doc, upsert=False):
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                self.docs[i] = dict(doc)
                return FakeResult(modified_count=1)
        if upsert:
            self.docs.append(dict(doc))
        return FakeResult(modified_count=0)

    async def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                del self.docs[i]
                return FakeResult(deleted_count=1)
        return FakeResult(deleted_count=0)

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
    "headline": "Ending ARR is 3,129,600 EUR with NRR at 104%.",
    "what_this_means": "Net revenue retention of 104% indicates the existing base expands.",
    "table_rows": [
        {"label": "Ending ARR", "value": "3,129,600 EUR", "source_key": "arr"},
        {"label": "NRR", "value": "104%", "source_key": "nrr"},
    ],
    "worth_flagging": ["Gross revenue churn stands at 6%."],
    "next_actions": ["Request the contract list behind the Enterprise segment."],
    "source_keys": ["arr", "nrr", "gross_churn"],
}


class FakeAdapter:
    """Stands in for AnthropicAdapter. Counts calls; never touches a network."""

    def __init__(self, replies=None, raise_with=None):
        self.calls = 0
        self.payloads = []
        self._replies = list(replies or [json.dumps(GOOD_NARRATIVE)])
        self._raise_with = raise_with

    input_tokens = 1200           # what count_tokens reports for a whole call and complete bills
    text_tokens = None            # what count_tokens reports for the structure text alone (None: input_tokens)

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema):
        self.calls += 1
        self.payloads.append(user_payload)
        self.requests = getattr(self, "requests", []) + [
            {"model": model, "max_tokens": max_tokens, "temperature": temperature, "json_schema": json_schema}]
        if self._raise_with is not None:
            raise self._raise_with
        reply = self._replies[min(self.calls - 1, len(self._replies) - 1)]
        return reply, self.input_tokens, 300

    def count_tokens(self, *, model, system, user_payload, json_schema):
        self.counted = getattr(self, "counted", 0) + 1
        self.count_requests = getattr(self, "count_requests", []) + [
            {"system": system, "user_payload": user_payload, "json_schema": json_schema}]
        if system is None and self.text_tokens is not None:
            return self.text_tokens
        return self.input_tokens


async def _noop_sleep(_seconds):
    return None


def make_db():
    """Fresh DB per test.

    Deep-copied: `dict(RESULTS_DOC)` would share the nested `results` dict, so a
    test that changes a figure to simulate a recompute would silently rewrite
    the fixture for every test that ran after it.
    """
    db = FakeDB()
    db["audits"].docs.append(copy.deepcopy(RESULTS_DOC))
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
def test_hard_tier_fabricated_figure_in_headline_sinks_the_narrative():
    """A number the engine never produced, in the headline, is read as fact."""
    fabricated = dict(GOOD_NARRATIVE)
    fabricated["headline"] = "ARR grew 42.7 percent year on year."

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
    assert "42.7" in result.unmatched_numbers
    assert result.metrics, "metrics survive a rejected narrative"
    assert logged[0]["status"] == "numeric_guard_rejected"
    assert "42.7" in logged[0]["unmatched_numbers"]
    assert logged[0]["estimated_cost_usd"] > 0, "a rejected call still cost money"


def test_hard_tier_fabricated_figure_in_a_table_row_sinks_the_narrative():
    fabricated = json.loads(json.dumps(GOOD_NARRATIVE))
    fabricated["table_rows"][0]["value"] = "8675309"

    async def run():
        db = make_db()
        return await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=FakeAdapter(replies=[json.dumps(fabricated)]), sleep=_noop_sleep
        )

    result = asyncio.run(run())
    assert result.narrative_status == "unavailable"
    assert result.narrative is None
    assert "8675309" in result.unmatched_numbers


def test_soft_tier_fabricated_figure_in_prose_is_flagged_not_dropped():
    """Prose numbers are usually rhetorical, so the narrative still ships."""
    fabricated = dict(GOOD_NARRATIVE)
    fabricated["what_this_means"] = "This implies 42.7 percent growth next year."

    async def run():
        db = make_db()
        result = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=FakeAdapter(replies=[json.dumps(fabricated)]), sleep=_noop_sleep
        )
        logged = await db["llm_calls"].find({"run_id": RUN_ID}).to_list(10)
        return result, logged

    result, logged = asyncio.run(run())
    assert result.narrative_status == "flagged"
    assert result.narrative is not None, "a flagged narrative is still returned"
    assert result.unmatched_numbers == ["42.7"]
    assert logged[0]["status"] == "flagged"
    assert logged[0]["unmatched_numbers"] == ["42.7"]


def test_soft_tier_unmatched_numbers_in_lists_are_flagged():
    fabricated = dict(GOOD_NARRATIVE)
    fabricated["worth_flagging"] = ["Only 3 of the quarters are computable."]
    fabricated["next_actions"] = ["Ask for the 7 missing invoices."]

    async def run():
        db = make_db()
        return await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=FakeAdapter(replies=[json.dumps(fabricated)]), sleep=_noop_sleep
        )

    result = asyncio.run(run())
    assert result.narrative_status == "flagged"
    assert result.unmatched_numbers == ["3", "7"]


def test_flagged_status_survives_a_cache_hit():
    """The second viewer must see the same warning as the first."""
    fabricated = dict(GOOD_NARRATIVE)
    fabricated["what_this_means"] = "This implies 42.7 percent growth next year."

    async def run():
        db = make_db()
        first = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=FakeAdapter(replies=[json.dumps(fabricated)]), sleep=_noop_sleep
        )
        second_adapter = FakeAdapter()
        second = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=second_adapter, sleep=_noop_sleep
        )
        return first, second, second_adapter

    first, second, second_adapter = asyncio.run(run())
    assert first.narrative_status == "flagged"
    assert second.narrative_status == "flagged", "cache hit must not upgrade to ok"
    assert second.cache_hit is True
    assert second.unmatched_numbers == ["42.7"]
    assert second_adapter.calls == 0


def test_allowlist_permits_100_and_configured_window_lengths():
    """"Above 100" and "12-month" are structural, not fabricated figures."""
    phrased = dict(GOOD_NARRATIVE)
    phrased["what_this_means"] = (
        "Retention above 100 means the base expands on a 12 month view."
    )
    phrased["worth_flagging"] = ["The 24 month comparison is also available."]

    async def run():
        db = make_db()
        return await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=FakeAdapter(replies=[json.dumps(phrased)]), sleep=_noop_sleep
        )

    result = asyncio.run(run())
    assert result.narrative_status == "ok", result.unmatched_numbers
    assert result.unmatched_numbers == []


def test_allowlist_is_per_step():
    """cac_efficiency allows 4 quarters; growth_engine does not."""
    assert 4 in gateway.STEP_CONFIG["cac_efficiency"]["windows"]
    assert 4 not in gateway.STEP_CONFIG["growth_engine"]["windows"]
    payload = {"x": 1}
    assert "4" in gateway.allowed_numerals(payload, gateway.STEP_CONFIG["cac_efficiency"]["windows"])
    assert "4" not in gateway.allowed_numerals(payload, gateway.STEP_CONFIG["growth_engine"]["windows"])
    # 100 is allowed everywhere.
    assert "100" in gateway.allowed_numerals(payload, ())


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


def test_numeric_guard_unit_splits_hard_from_soft():
    payload = {"arr": {"value": 3129600}, "nrr": {"overall_pct": 104.2}}

    clean = Narrative(headline="ARR is 3129600", what_this_means="NRR 104.2")
    result = gateway.numeric_guard(clean, payload)
    assert result.hard == [] and result.soft == []

    hard = Narrative(headline="ARR grew 17.5 percent", what_this_means="")
    assert gateway.numeric_guard(hard, payload).hard == ["17.5"]

    soft = Narrative(headline="ARR is 3129600", what_this_means="Up 17.5 percent.")
    result = gateway.numeric_guard(soft, payload)
    assert result.hard == [] and result.soft == ["17.5"]

    # A number unmatched in both tiers is reported once, as hard.
    both = Narrative(headline="Grew 17.5 percent", what_this_means="Again, 17.5.")
    result = gateway.numeric_guard(both, payload)
    assert result.hard == ["17.5"] and result.soft == []
    assert result.all == ["17.5"]

    # Windows are allowlisted per step.
    windowed = Narrative(headline="ARR is 3129600", what_this_means="On a 12 month view.")
    assert gateway.numeric_guard(windowed, payload, windows=[12]).soft == []
    assert gateway.numeric_guard(windowed, payload, windows=[]).soft == ["12"]


def test_source_key_guard_rejects_unknown_key():
    payload = {"arr": {"value": 1}}
    bad = Narrative(
        headline="x", what_this_means="y",
        table_rows=[{"label": "Made up", "value": "1", "source_key": "not_a_key"}],
    )
    assert "not_a_key" in gateway.source_key_guard(bad, payload)


# ---------------------------------------------------------------------------
# source_key form: the live 400 was dotted paths rejected against bare names
# ---------------------------------------------------------------------------
NESTED_PAYLOAD = {
    "metrics": {
        "acv_path": {
            "acv": 28451,
            "customers_needed": 211,
            "required_vs_observed_24m": 15.67,
            "overall_band": {"label": "Consultative sales"},
            "bands": [{"label": "Mid", "count": 40}],
        },
        "arr": {"value": 3129600},
    },
}


def _row(source_key):
    return {"label": "x", "value": "1", "source_key": source_key}


def test_guard_accepts_the_dotted_paths_the_model_actually_produces():
    """Regression for the live failure: every key below is real and was rejected."""
    rejected_live = [
        "metrics.acv_path.acv",
        "metrics.acv_path.customers_needed",
        "metrics.acv_path.required_vs_observed_24m",
        "metrics.acv_path.overall_band",
    ]
    n = Narrative(headline="h", what_this_means="w",
                  table_rows=[_row(k) for k in rejected_live])
    assert gateway.source_key_guard(n, NESTED_PAYLOAD) is None


def test_guard_still_accepts_bare_leaf_names():
    """Formatting must not cost a narrative when the figure is traceable."""
    n = Narrative(headline="h", what_this_means="w", table_rows=[_row("acv")])
    assert gateway.source_key_guard(n, NESTED_PAYLOAD) is None


def test_guard_still_rejects_a_path_that_does_not_exist():
    n = Narrative(headline="h", what_this_means="w",
                  table_rows=[_row("metrics.acv_path.made_up")])
    assert "metrics.acv_path.made_up" in gateway.source_key_guard(n, NESTED_PAYLOAD)


def test_guard_rejects_a_real_leaf_under_the_wrong_parent():
    """`acv` exists, but not at metrics.arr.acv - a wrong path is still wrong."""
    n = Narrative(headline="h", what_this_means="w", table_rows=[_row("metrics.arr.acv")])
    assert "metrics.arr.acv" in gateway.source_key_guard(n, NESTED_PAYLOAD)


def test_source_key_paths_are_dotted_and_list_transparent():
    paths = gateway.source_key_paths(NESTED_PAYLOAD)
    assert "metrics.acv_path.acv" in paths
    assert "metrics.acv_path.overall_band.label" in paths
    # An array contributes its fields under the array's own path, not an index.
    assert "metrics.acv_path.bands.label" in paths
    assert not any("[" in p for p in paths)
    assert paths == sorted(paths)


def test_model_is_given_the_valid_key_list_in_the_exact_accepted_form():
    """Whatever the model is told is citable must in fact be citable."""
    captured = {}

    class PayloadCapturingAdapter(FakeAdapter):
        def complete(self, *, user_payload, **kwargs):
            captured["payload"] = json.loads(user_payload)
            return super().complete(user_payload=user_payload, **kwargs)

    async def run():
        db = make_db()
        db["audits"].docs[0]["results"]["acv_path"] = {"acv": 28451, "customers_needed": 211}
        return await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=PayloadCapturingAdapter(), sleep=_noop_sleep
        )

    asyncio.run(run())
    listed = captured["payload"]["valid_source_keys"]
    assert "metrics.acv_path.acv" in listed, listed
    outbound = {k: v for k, v in captured["payload"].items() if k != "valid_source_keys"}
    accepted = gateway.accepted_source_keys(outbound)
    missing = [k for k in listed if k not in accepted]
    assert missing == [], f"the model is offered keys the guard would reject: {missing}"


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


def test_a_narrative_provider_error_records_its_http_status_and_type_and_honours_retry_after():
    """Shaped like the SDK's APIStatusError: status_code, type (the body's error type), response headers. The
    message is never read."""
    from types import SimpleNamespace

    class ProviderError(Exception):
        def __init__(self, status, error_type, retry_after=None):
            super().__init__("cannot read cell 'Jane Doe (CEO)'")
            self.status_code, self.type = status, error_type
            self.response = SimpleNamespace(headers={} if retry_after is None else {"retry-after": str(retry_after)})

    async def run(error):
        db, slept = make_db(), []

        async def sleep(seconds):
            slept.append(seconds)
        adapter = FakeAdapter(raise_with=error)
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=adapter, sleep=sleep)
        call, = db["llm_calls"].docs
        return (call["status"], call["http_status"], call["error_type"]), adapter.calls, slept, json.dumps(call)

    record, calls, slept, stored = asyncio.run(run(ProviderError(400, "invalid_request_error")))
    assert (record, calls, slept) == (("provider_error", 400, "invalid_request_error"), 1, [])
    record, calls, slept, stored = asyncio.run(run(ProviderError(429, "rate_limit_error", retry_after=3)))
    assert (record, calls, slept) == (("provider_unreachable", 429, "rate_limit_error"), 3, [3.0, 3.0])
    assert "Jane Doe" not in stored


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
        "output_tokens", "estimated_cost_usd", "cache_hit", "status",
        "unmatched_numbers", "timestamp",
    }
    blob = json.dumps(row)
    assert "You are writing" not in blob, "prompt text leaked into the call log"
    assert "3129600" not in blob, "payload contents leaked into the call log"
    assert "3,129,600" not in blob, "formatted payload contents leaked into the call log"


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
    assert result.prompt_version == "v7", "the version is returned, the text is not"


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


# ---------------------------------------------------------------------------
# Read-only path: opening an audit must never spend
# ---------------------------------------------------------------------------
def test_read_only_returns_not_generated_when_nothing_cached():
    async def run():
        db = make_db()
        result = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        logged = await db["llm_calls"].find({"run_id": RUN_ID}).to_list(10)
        return result, logged

    result, logged = asyncio.run(run())
    assert result.narrative_status == "not_generated"
    assert result.narrative is None
    assert result.metrics, "metrics come back even with no narrative"
    assert logged == [], "a read is not a call and must not be logged"


def test_read_only_returns_the_cached_narrative_with_its_date():
    async def run():
        db = make_db()
        generated = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        read = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        return generated, read

    generated, read = asyncio.run(run())
    assert generated.narrative_status == "ok"
    assert read.narrative_status == "ok"
    assert read.cache_hit is True
    assert read.narrative.headline == generated.narrative.headline
    assert read.generated_at, "the UI needs the date the narrative was written"


def test_read_only_preserves_flagged_status():
    fabricated = dict(GOOD_NARRATIVE)
    fabricated["what_this_means"] = "This implies 42.7 percent growth next year."

    async def run():
        db = make_db()
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=FakeAdapter(replies=[json.dumps(fabricated)]), sleep=_noop_sleep
        )
        return await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")

    read = asyncio.run(run())
    assert read.narrative_status == "flagged"
    assert read.unmatched_numbers == ["42.7"]


def test_read_only_cannot_reach_a_provider():
    """Structural: nothing on the read path can construct or call an adapter.

    Checks the parsed code, not the text, so prose in the docstring explaining
    that it must not reach the adapter does not trip the assertion.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(gateway.read_cached_narrative))
    fn = tree.body[0]
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body

    names = set()
    calls = set()
    for node in body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                names.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                names.add(sub.attr)
                calls.add(sub.attr)

    offenders = {n for n in names if "adapter" in n.lower()}
    assert offenders == set(), f"read path references an adapter: {offenders}"
    assert "complete" not in calls, "read path invokes a provider completion"


def test_read_only_misses_when_the_numbers_changed():
    """Stale narratives must not resurface against recomputed results."""
    async def run():
        db = make_db()
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        # Recompute changes a figure, so the cache key changes too.
        db["audits"].docs[0]["results"]["arr"]["value"] = 4000000
        return await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")

    read = asyncio.run(run())
    assert read.narrative_status == "not_generated", (
        "a narrative written about superseded numbers must not be served"
    )


def test_superseded_is_false_when_nothing_was_ever_written():
    async def run():
        db = make_db()
        return await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")

    result = asyncio.run(run())
    assert result.narrative_status == "not_generated"
    assert result.superseded is False


def test_superseded_is_true_when_the_numbers_moved_on():
    """A narrative exists for this run+step, but not for the current figures."""
    async def run():
        db = make_db()
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        db["audits"].docs[0]["results"]["arr"]["value"] = 4000000
        return await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")

    result = asyncio.run(run())
    assert result.narrative_status == "not_generated"
    assert result.superseded is True
    assert result.narrative is None, "the stale narrative must not be served"


def test_superseded_is_scoped_to_the_step():
    """A narrative for one step must not mark another step superseded."""
    async def run():
        db = make_db()
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        return await gateway.read_cached_narrative(db, RUN_ID, "path_to_plan")

    result = asyncio.run(run())
    assert result.superseded is False


def test_superseded_clears_after_regenerating():
    async def run():
        db = make_db()
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        db["audits"].docs[0]["results"]["arr"]["value"] = 4000000
        stale = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        # The regenerated narrative must cite the NEW figure - one citing the
        # old 3,129,600 EUR would (correctly) be rejected by the hard numeric guard.
        updated = json.loads(json.dumps(GOOD_NARRATIVE))
        updated["headline"] = "Ending ARR is 4,000,000 EUR with NRR at 104%."
        updated["table_rows"][0]["value"] = "4,000,000 EUR"
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=FakeAdapter(replies=[json.dumps(updated)]), sleep=_noop_sleep
        )
        fresh = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        return stale, fresh

    stale, fresh = asyncio.run(run())
    assert stale.superseded is True
    assert fresh.narrative_status == "ok"
    assert fresh.superseded is False
    assert fresh.narrative is not None


# ---------------------------------------------------------------------------
# Structured-output schema
# ---------------------------------------------------------------------------
def _object_nodes(node, path="$"):
    """Yield (path, node) for every object node in a JSON schema."""
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            yield path, node
        for key, value in node.items():
            yield from _object_nodes(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _object_nodes(value, f"{path}[{i}]")


def test_output_schema_seals_every_object_node():
    """Structured outputs 400 unless EVERY object sets additionalProperties:false.

    Pydantic emits it for the root only, so $defs.TableRow (the nested model
    behind table_rows) arrives without it and the whole request is rejected.
    """
    from app.llm.schemas import narrative_output_schema

    schema = narrative_output_schema()
    nodes = dict(_object_nodes(schema))
    assert nodes, "schema has no object nodes - the walker is looking at the wrong shape"

    unsealed = [p for p, n in nodes.items() if n.get("additionalProperties") is not False]
    assert unsealed == [], f"object node(s) missing additionalProperties:false: {unsealed}"

    # The nested model is the one Pydantic misses, so assert it by name.
    assert "$.$defs.TableRow" in nodes
    assert schema["$defs"]["TableRow"]["additionalProperties"] is False


def test_output_schema_does_not_mutate_the_pydantic_schema():
    """Sealing is a transport concern; the model's own schema stays as Pydantic
    generated it, so other callers are unaffected."""
    from app.llm.schemas import narrative_output_schema

    narrative_output_schema()
    raw = Narrative.model_json_schema()
    assert raw["$defs"]["TableRow"].get("additionalProperties") is None


def test_output_schema_preserves_the_narrative_contract():
    """Sealing must not change what the model is asked for."""
    from app.llm.schemas import narrative_output_schema

    sealed = narrative_output_schema()
    raw = Narrative.model_json_schema()
    assert set(sealed["properties"]) == set(raw["properties"])
    assert sealed["properties"].keys() >= {
        "headline", "what_this_means", "table_rows",
        "worth_flagging", "next_actions", "source_keys",
    }
    assert set(sealed["$defs"]["TableRow"]["required"]) == {"label", "value", "source_key"}


def test_seal_objects_handles_nesting_pydantic_does_not_produce():
    """Arrays of objects, anyOf branches and deep $defs are all covered."""
    from app.llm.schemas import _seal_objects

    schema = {
        "type": "object",
        "properties": {
            "rows": {"type": "array", "items": {"type": "object", "properties": {"a": {"type": "string"}}}},
            "choice": {"anyOf": [{"type": "object", "properties": {"b": {"type": "string"}}},
                                 {"type": "string"}]},
        },
        "$defs": {"Deep": {"type": "object", "properties": {
            "inner": {"type": "object", "properties": {"c": {"type": "string"}}}}}},
    }
    sealed = _seal_objects(schema)
    unsealed = [p for p, n in _object_nodes(sealed) if n.get("additionalProperties") is not False]
    assert unsealed == []
    # A non-object branch is left alone.
    assert sealed["properties"]["choice"]["anyOf"][1] == {"type": "string"}


def test_gateway_sends_the_sealed_schema_to_the_provider():
    """End to end: what the adapter receives is what the API will accept."""
    captured = {}

    class SchemaCapturingAdapter(FakeAdapter):
        def complete(self, *, json_schema, **kwargs):
            captured["schema"] = json_schema
            return super().complete(json_schema=json_schema, **kwargs)

    async def run():
        db = make_db()
        return await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=SchemaCapturingAdapter(), sleep=_noop_sleep
        )

    result = asyncio.run(run())
    assert result.narrative_status == "ok", result.reason
    unsealed = [p for p, n in _object_nodes(captured["schema"])
                if n.get("additionalProperties") is not False]
    assert unsealed == [], f"gateway sent an unsealed schema: {unsealed}"


# ---------------------------------------------------------------------------
# Number extraction: a hyphen is only a minus sign outside a word
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    # The live false positive: "sub-1%" was read as -1, so a narrative that
    # said churn was under one percent got flagged for a number nobody wrote.
    ("sub-1%", {"1"}),
    ("non-12-month", {"12"}),
    # A genuine negative must still read as negative.
    ("-5", {"-5"}),
    ("a drop of -5", {"-5"}),
    # Dates are separators, not subtraction.
    ("2027-12-31", {"2027", "12", "31"}),
    # Digits after an underscore still count - this is how key names contribute.
    ("observed_net_new_per_year_12m", {"12"}),
    # Mixed prose.
    ("churn was sub-1% against NRR of 104.2", {"1", "104.2"}),
    # A range is two numbers, not one negative.
    ("3.5-4.5", {"3.5", "4.5"}),
    # Punctuation is not word-like, so the sign survives.
    ("(-5)", {"-5"}),
    ("margin -12.5 percent", {"-12.5"}),
    # A hyphen straight after a letter is part of the word.
    ("temperature-0.2", {"0.2"}),
    ("year-3 cohort", {"3"}),
])
def test_number_extraction_hyphen_handling(text, expected):
    assert redaction.numbers_in(text) == expected


def test_sub_one_percent_no_longer_flags_a_narrative():
    """End to end: the prose that caused the live false positive now passes.

    "sub-1%" yields 1, and 1 is not in the payload - but it is not -1 either,
    which is the invented figure the guard was reporting.
    """
    prose = dict(GOOD_NARRATIVE)
    prose["what_this_means"] = "Gross churn is sub-1% on a 12 month view."
    # The default fixture cites 6% here; the payload below sets churn to 1, so
    # this line has to move with it or it becomes a genuine unmatched number.
    prose["worth_flagging"] = ["Gross revenue churn stands at 1 percent."]

    async def run():
        db = make_db()
        # 1 appears in the computed results, so the sentence is fully supported.
        db["audits"].docs[0]["results"]["gross_churn"]["overall_pct"] = 1
        return await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=FakeAdapter(replies=[json.dumps(prose)]), sleep=_noop_sleep
        )

    result = asyncio.run(run())
    assert result.narrative_status == "ok", result.unmatched_numbers
    assert "-1" not in result.unmatched_numbers


def test_a_real_negative_is_still_caught_when_unsupported():
    """The fix must not blind the guard to genuine negative fabrications."""
    prose = dict(GOOD_NARRATIVE)
    prose["what_this_means"] = "Net new customers fell by -37 last quarter."

    async def run():
        db = make_db()
        return await gateway.generate_narrative(
            db, RUN_ID, "growth_engine",
            adapter=FakeAdapter(replies=[json.dumps(prose)]), sleep=_noop_sleep
        )

    result = asyncio.run(run())
    assert result.narrative_status == "flagged"
    assert result.unmatched_numbers == ["-37"]


def test_negative_values_in_the_payload_are_still_matchable():
    """A negative the engine really produced must satisfy the guard."""
    payload = {"metrics": {"net_new": -37}}
    n = Narrative(headline="Net new was -37", what_this_means="")
    assert gateway.numeric_guard(n, payload).hard == []


# ---------------------------------------------------------------------------
# Row references stay out of the model payload but not out of the data
# ---------------------------------------------------------------------------
SOURCE_BLOCK = {
    "file": "revenue.csv", "sheet": "Sheet1", "rows": "rows 2–500 (499 rows)",
    "row_numbers": [2, 3, 4], "rule": "ARR = current-month recurring MRR × 12",
}


def test_outbound_payload_drops_row_references_and_file_names_but_keeps_the_rule():
    computed = {
        "reporting_currency": "EUR",
        "metrics": {
            "arr": {"value": 3129600, "source": dict(SOURCE_BLOCK)},
            "win_rate": {"won": 3, "founder_involved_excluded": {"count": 1, "rows": [7]}},
        },
    }
    out = gateway.build_outbound(computed, {})
    src = out["metrics"]["arr"]["source"]
    assert src == {"rule": "ARR = current-month recurring MRR × 12"}
    assert "rows" not in out["metrics"]["win_rate"]["founder_involved_excluded"]
    assert out["metrics"]["win_rate"]["founder_involved_excluded"]["count"] == "1"
    assert "row_numbers" not in cache.canonical_json(out)
    assert not any(p.endswith(".row_numbers") for p in gateway.source_key_paths(out))


def test_stripping_row_references_does_not_modify_the_stored_results():
    computed = {"metrics": {"arr": {"value": 1, "source": dict(SOURCE_BLOCK)}}}
    gateway.build_outbound(computed, {})
    assert computed["metrics"]["arr"]["source"]["row_numbers"] == [2, 3, 4]
    assert computed["metrics"]["arr"]["source"]["rows"] == "rows 2–500 (499 rows)"


# ---------------------------------------------------------------------------
# Provenance disclosure (model + time; prompt version stays in the audit trail)
# ---------------------------------------------------------------------------
def test_disclosure_for_run_reports_the_model_that_wrote_the_stored_narrative():
    async def run():
        db = make_db()
        before = await gateway.disclosure_for_run(db, RUN_ID)
        await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep
        )
        return before, await gateway.disclosure_for_run(db, RUN_ID), db

    before, block, db = asyncio.run(run())
    assert before is None, "nothing to disclose before any narrative exists"
    assert block["models"] == [gateway.DEFAULT_MODEL] and block["mixed_models"] is False
    assert re.fullmatch(
        rf"Narrative generated by {re.escape(gateway.DEFAULT_MODEL)} on \d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}} UTC\.",
        block["text"],
    ), block["text"]
    assert "v7" not in block["text"]
    # the prompt version is still recorded in the audit trail
    assert db["llm_narratives"].docs[0]["prompt_version"] == "v7"
    assert db["llm_calls"].docs[0]["prompt_version"] == "v7"


def test_disclosure_never_calls_a_provider():
    class Boom:
        def complete(self, **kw):  # pragma: no cover - must not be reached
            raise AssertionError("disclosure must be read-only")

    async def run():
        db = make_db()
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        return await gateway.disclosure_for_run(db, RUN_ID)

    assert asyncio.run(run()) is not None


# ---------------------------------------------------------------------------
# One model and one prompt release per run
# ---------------------------------------------------------------------------
def test_steps_have_no_model_of_their_own():
    """The model is a run-level setting; a step cannot override it."""
    assert all("model" not in c for c in gateway.STEP_CONFIG.values())


def test_run_model_defaults_and_is_overridable(monkeypatch):
    monkeypatch.delenv("NARRATIVE_MODEL", raising=False)
    assert gateway.run_model() == gateway.DEFAULT_MODEL
    monkeypatch.setenv("NARRATIVE_MODEL", "claude-sonnet-5")
    assert gateway.run_model() == "claude-sonnet-5"


def test_unpriced_model_is_refused_so_the_spend_cap_cannot_be_bypassed(monkeypatch):
    monkeypatch.setenv("NARRATIVE_MODEL", "claude-typo-9")
    with pytest.raises(gateway.GatewayError) as exc:
        gateway.run_model()
    assert exc.value.reason == "model_not_configured"

    async def run():
        db = make_db()
        gen = await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        return gen, await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")

    gen, read = asyncio.run(run())
    assert gen.narrative_status == "unavailable" and "model_not_configured" in gen.reason
    assert read.narrative_status == "not_generated"


def test_every_step_in_a_run_is_generated_by_the_same_model(monkeypatch):
    monkeypatch.setenv("NARRATIVE_MODEL", "claude-sonnet-5")

    async def run():
        db = make_db()
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        return db

    db = asyncio.run(run())
    assert {d["model"] for d in db["llm_narratives"].docs} == {"claude-sonnet-5"}
    assert {d["model"] for d in db["llm_calls"].docs} == {"claude-sonnet-5"}


def test_release_manifest_matches_the_prompt_files():
    """Editing a prompt without bumping the release (and re-recording its hash) fails here."""
    manifest = prompt_store.release_manifest()
    on_disk = sorted(p.stem for p in prompt_store.PROMPTS_DIR.glob("*.md") if p.stem != prompt_store.RELEASE_FILE)
    assert sorted(manifest) == on_disk, "every prompt file must be listed in RELEASE.md"
    stale = [n for n in on_disk if manifest[n] != prompt_store.file_hash(n)]
    assert stale == [], (
        f"prompt(s) {stale} changed since release {prompt_store.release()!r} was recorded: bump the "
        "release in prompts/RELEASE.md, then run `python -m app.llm.prompt_store --record`"
    )
    assert re.fullmatch(r"r\d+", prompt_store.release())


def test_release_stamp_is_part_of_the_cache_key():
    prompt = prompt_store.load("growth_engine")
    assert prompt_store.tag_for("r2", prompt.version) == f"r2:{prompt.version}"
    assert prompt_store.tag_for("r3", prompt.version) != prompt_store.tag_for("r2", prompt.version)
    key = lambda tag: cache.cache_key(RUN_ID, "growth_engine", tag, "claude-opus-5", {"a": 1})
    assert key(prompt_store.tag_for("r2", prompt.version)) != key(prompt_store.tag_for("r3", prompt.version))


def test_baseline_release_keeps_the_cache_keys_that_existed_before_releases():
    prompt = prompt_store.load("growth_engine")
    assert prompt_store.tag_for(prompt_store.BASELINE_RELEASE, prompt.version) == prompt.version


def test_the_shipped_release_is_r7_and_its_cache_tag_carries_it():
    prompt = prompt_store.load("growth_engine")
    assert prompt_store.release() == "r7" and prompt.version == "v7"
    assert prompt_store.cache_tag(prompt) == "r7:v7", "narratives written under r6/v7 are not served under r7/v7"
    structure = prompt_store.load("structure_reading")
    assert structure.version == "v4" and prompt_store.cache_tag(structure) == "r7:v4", \
        "the title cell of a KPI panel (deck-parser.md section 7, issue #48) is v4 of release r7"


def test_a_release_bump_makes_every_cached_narrative_unreachable_until_regenerated(monkeypatch):
    """What a release bump does: old narratives stay stored but are not
    served, the read path says a narrative existed, and nothing is regenerated by reading."""

    async def run():
        db = make_db()
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        served = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        monkeypatch.setattr(prompt_store, "release", lambda: "r8")
        after_bump = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        disclosure_after = await gateway.disclosure_for_run(db, RUN_ID)
        calls_after_read = len(db["llm_calls"].docs)
        regenerated = await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        return db, served, after_bump, disclosure_after, calls_after_read, regenerated

    db, served, after_bump, disclosure_after, calls_after_read, regenerated = asyncio.run(run())
    assert served.narrative_status == "ok"
    assert after_bump.narrative_status == "not_generated" and after_bump.superseded is True
    assert after_bump.superseded_reason == "prompt_release_changed"
    assert disclosure_after is None, "no served narrative, so nothing to disclose"
    assert calls_after_read == 1, "reading never spends"
    assert regenerated.narrative_status == "ok" and regenerated.cache_hit is False
    stored = db["llm_narratives"].docs
    assert len(stored) == 2, "the old narrative is kept, not deleted"
    assert {d["prompt_release"] for d in stored} == {"r7", "r8"}


# ---------------------------------------------------------------------------
# Why an earlier narrative is not shown: the reader is told the true reason
# ---------------------------------------------------------------------------
def test_data_change_is_reported_as_data_changed():
    async def run():
        db = make_db()
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        db["audits"].docs[0]["results"]["arr"]["value"] = 4000000
        return await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")

    r = asyncio.run(run())
    assert r.superseded is True and r.superseded_reason == "data_changed"


def test_model_change_is_reported_as_model_changed_not_data_changed(monkeypatch):
    async def run():
        db = make_db()
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        monkeypatch.setenv("NARRATIVE_MODEL", "claude-sonnet-5")
        return await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")

    r = asyncio.run(run())
    assert r.narrative_status == "not_generated"
    assert r.superseded is True and r.superseded_reason == "model_changed"


def test_narrative_written_before_releases_were_stamped_is_still_served_then_explained_after_a_bump(monkeypatch):
    """A record with no prompt_release counts as the baseline release r1: served while r1 is
    current, reported as a release change once a later release ships."""
    async def run():
        db = make_db()
        monkeypatch.setattr(prompt_store, "release", lambda: prompt_store.BASELINE_RELEASE)   # as it was written
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        for doc in db["llm_narratives"].docs:
            doc.pop("prompt_release", None)
        before = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        monkeypatch.setattr(prompt_store, "release", lambda: "r2")
        after = await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")
        return before, after

    before, after = asyncio.run(run())
    assert before.narrative_status == "ok" and before.cache_hit is True
    assert after.narrative_status == "not_generated" and after.superseded_reason == "prompt_release_changed"


def test_release_bump_together_with_a_data_change_is_reported_as_data_changed(monkeypatch):
    async def run():
        db = make_db()
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        monkeypatch.setattr(prompt_store, "release", lambda: "r3")
        db["audits"].docs[0]["results"]["arr"]["value"] = 4000000
        return await gateway.read_cached_narrative(db, RUN_ID, "growth_engine")

    assert asyncio.run(run()).superseded_reason == "data_changed"


def test_nothing_stored_means_no_superseded_reason():
    async def run():
        return await gateway.read_cached_narrative(make_db(), RUN_ID, "growth_engine")

    r = asyncio.run(run())
    assert r.superseded is False and r.superseded_reason is None


# ---------------------------------------------------------------------------
# Partial CAC quarters are shown on the dashboard but not given to the model
# ---------------------------------------------------------------------------
def _cac_computed():
    L = lambda m: {"months": m, "sm_expense": 9000.0, "reason": None}
    return {"reporting_currency": "EUR", "metrics": {"cac_payback": {
        "default_l": 1, "headline_quarter": "2024-Q3", "partial_quarter_excluded": "2025-Q1",
        "quarters": {
            "2024-Q3": {"new_mrr": 1000.0, "gross_margin_pct": 75.0, "months_in_quarter": 3,
                        "partial": False, "L0": L(9.0), "L1": L(18.8), "L2": L(9.7)},
            "2025-Q1": {"new_mrr": 400.0, "gross_margin_pct": 77.0, "months_in_quarter": 2,
                        "partial": True, "L0": L(20.0), "L1": L(29.0), "L2": L(11.0)},
        }}}}


def test_partial_quarter_figures_are_withheld_from_the_model_payload():
    computed = _cac_computed()
    out = gateway.build_outbound(computed, {})
    q = out["metrics"]["cac_payback"]["quarters"]
    assert q["2024-Q3"]["L1"]["months"] == "18.8 months", "complete quarters are sent as before"
    assert q["2025-Q1"]["L1"] == {
        "months": None, "reason": "partial quarter (2 of 3 months); not comparable"}
    assert "29" not in json.dumps(q["2025-Q1"]) and "20.0" not in json.dumps(q["2025-Q1"])
    assert out["metrics"]["cac_payback"]["headline_quarter"] == "2024-Q3"
    assert q["2025-Q1"]["months_in_quarter"] == "2"


def test_withholding_partial_quarters_does_not_touch_the_stored_results():
    computed = _cac_computed()
    gateway.build_outbound(computed, {})
    assert computed["metrics"]["cac_payback"]["quarters"]["2025-Q1"]["L1"]["months"] == 29.0


def test_the_narrative_sees_the_segment_view_as_well_as_the_simple_view():
    """The prose must not be able to state one view's conclusion while the panel shows the other:
    both views are in the payload."""
    results = {"arr": {"value": 1.0}, "acv_path": {"acv": 2.0}, "segment_paths": {"available": True, "gap_arr": 5.0}}
    sliced = gateway._slice_for_step(results, "growth_engine")
    assert "segment_paths" in sliced and "acv_path" in sliced


def test_narratives_for_run_returns_the_served_narratives_and_never_calls_a_provider():
    async def run():
        db = make_db()
        before = await gateway.narratives_for_run(db, RUN_ID)
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        calls = len(db["llm_calls"].docs)
        after = await gateway.narratives_for_run(db, RUN_ID)
        return before, after, calls, len(db["llm_calls"].docs), gateway.disclosure_from(after)

    before, after, calls_before, calls_after, block = asyncio.run(run())
    assert before == []
    assert [n.step for n in after] == ["growth_engine"] and after[0].narrative is not None
    assert after[0].row_labels, "the readable names travel with the narrative into the export"
    assert calls_before == calls_after, "reading for the export never spends"
    assert block["models"] == [gateway.DEFAULT_MODEL]


def test_a_narrative_that_no_longer_matches_the_numbers_is_not_exported():
    async def run():
        db = make_db()
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        db["audits"].docs[0]["results"]["arr"]["value"] = 4000000
        return await gateway.narratives_for_run(db, RUN_ID)

    assert asyncio.run(run()) == []


# ---------------------------------------------------------------------------
# NRR fields say what they count; windows are stated; the two views are shown together
# ---------------------------------------------------------------------------
def _walk(node, path=""):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i in node:
            yield from _walk(i, path)


def _results_with_nrr_detail():
    return {
        "nrr": {"month": "2025-02", "trailing_window_months": 12, "overall_pct": 116.69, "nrr_base_customers": 39,
                "by_segment": {"SMB": {"nrr_pct": 95.08, "nrr_base_customers": 10}},
                "by_cohort": {
                    "2024-Q1": {"nrr_pct": 127.42, "nrr_base_customers": 5},
                    "2024-Q3": {"nrr_pct": None, "nrr_base_customers": 0,
                                "reason": "cohort younger than 12 months: none of its customers had revenue 12 months before the as-of month"}}},
        "gross_churn": {"month": "2025-02", "trailing_window_months": 12, "overall_pct": 7.0},
    }


def test_the_model_never_sees_an_unexplained_zero_or_an_ambiguous_n():
    computed = {"reporting_currency": "EUR", "metrics": _results_with_nrr_detail()}
    out = gateway.build_outbound(computed, {})["metrics"]
    cohort = out["nrr"]["by_cohort"]["2024-Q3"]
    assert cohort["nrr_base_customers"] == "0" and cohort["nrr_pct"] is None
    assert cohort["reason"].startswith("cohort younger than 12 months")
    for path, node in _walk(out):
        if "nrr_pct" in node and node["nrr_pct"] is None:
            assert node.get("reason"), f"null NRR at {path} has no reason"
        if path.split(".")[0] == "nrr":
            assert "n" not in node, f"ambiguous n at {path}: NRR counts are named nrr_base_customers"


def test_nrr_and_gross_churn_state_their_twelve_month_window_in_the_payload():
    out = gateway.build_outbound({"reporting_currency": "EUR", "metrics": _results_with_nrr_detail()}, {})["metrics"]
    assert out["nrr"]["trailing_window_months"] == "12" and out["gross_churn"]["trailing_window_months"] == "12"


def _both_views_results():
    return {
        "acv_path": {"required_vs_observed_12m": 1.28},
        "segment_paths": {"available": True, "reconciliation": {"12": {
            "window_months": 12, "available": True, "path_to_plan_ratio": 1.28, "factor_compounded_base": 0.8,
            "factor_landed_acv": 1.25, "factor_gross_rate": 0.8, "segment_ratio": 1.024}}},
    }


def _generate_with(rows, results=None, headline="The simple view needs 1.28x the observed rate and the segment view 1.02x."):
    narrative = {
        "headline": headline,
        "what_this_means": "Both are shown.", "table_rows": rows, "worth_flagging": [], "next_actions": [], "source_keys": [],
    }

    async def run():
        db = make_db()
        db["audits"].docs[0]["results"].update(results or _both_views_results())
        return await gateway.generate_narrative(
            db, RUN_ID, "growth_engine", adapter=FakeAdapter(replies=[json.dumps(narrative)]), sleep=_noop_sleep)

    return asyncio.run(run())


SIMPLE_ROW = {"label": "Simple", "value": "1.28x", "source_key": "metrics.acv_path.required_vs_observed_12m"}
SEGMENT_ROW = {"label": "Segment", "value": "1.02x", "source_key": "metrics.segment_paths.reconciliation.12.segment_ratio"}


def test_a_table_citing_both_views_is_accepted():
    assert _generate_with([SIMPLE_ROW, SEGMENT_ROW]).narrative_status == "ok"


def test_a_table_citing_only_the_simple_view_is_rejected():
    r = _generate_with([SIMPLE_ROW])
    assert r.narrative_status == "unavailable" and "segment view" in r.reason and "without" in r.reason


def test_a_table_citing_only_the_segment_view_is_rejected():
    r = _generate_with([SEGMENT_ROW])
    assert r.narrative_status == "unavailable" and "simple view" in r.reason


def test_the_views_guard_applies_only_when_the_views_have_been_reconciled():
    results = _both_views_results()
    results["segment_paths"]["reconciliation"]["12"] = {"window_months": 12, "available": False,
                                                          "reason": "some active customers have no segment"}
    assert _generate_with([SIMPLE_ROW], results, headline="The simple view needs 1.28x the observed rate.").narrative_status == "ok"


def test_a_rejected_one_sided_narrative_is_logged_as_such_and_counted():
    async def run():
        db = make_db()
        db["audits"].docs[0]["results"].update(_both_views_results())
        narrative = {"headline": "x 1.28x", "what_this_means": "", "table_rows": [SIMPLE_ROW],
                     "worth_flagging": [], "next_actions": [], "source_keys": []}
        await gateway.generate_narrative(db, RUN_ID, "growth_engine",
                                         adapter=FakeAdapter(replies=[json.dumps(narrative)]), sleep=_noop_sleep)
        return db["llm_calls"].docs

    logged = asyncio.run(run())
    assert [c["status"] for c in logged] == ["views_guard_rejected"]


# ---------------------------------------------------------------------------
# What the r2 prompt tells the model (the rules behind the payload changes)
# ---------------------------------------------------------------------------
def _prompt_text():
    return prompt_store.load("growth_engine").text


def test_prompt_says_nrr_and_gross_churn_are_trailing_twelve_month_figures():
    text = _prompt_text()
    assert "trailing-twelve-month" in text and "trailing_window_months" in text
    assert "Never present either as the figure for the as-of" in text


def test_prompt_says_a_null_nrr_is_reported_with_its_reason_not_as_a_zero():
    text = _prompt_text()
    assert "nrr_base_customers" in text and "reason" in text
    assert "younger than twelve months" in text and "is expected, not a data problem" in text


def test_prompt_requires_both_views_and_names_the_reconciliation_fields():
    text = _prompt_text()
    for needle in ("simple view", "segment view", "segment_paths.reconciliation", "path_to_plan_ratio",
                   "factor_compounded_base", "factor_landed_acv", "factor_gross_rate", "segment_ratio",
                   "Never present one view as the finding", "arithmetic, not forecasts"):
        assert needle in text, needle


def test_every_field_the_prompt_names_exists_in_a_real_payload():
    """The prompt can only refer to keys the engine really sends."""
    pytest.importorskip("pandas")
    pytest.importorskip("fastapi")
    pytest.importorskip("motor")
    import os
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "prompt_keys_test")
    import demo_data
    import growth_engine as ge
    import server
    spec = demo_data.DEMO_AUDITS[0]
    datasets, meta = demo_data.build(spec)
    norm = {t: server.normalize(server.df_to_records(df), t, m) for t, (df, m) in datasets.items()}
    fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
    fx[spec["reporting_currency"].upper()] = 1.0
    cfg = {"reporting_currency": spec["reporting_currency"], "target_arr": spec["target_arr"],
           "target_date": spec["target_date"], "fx": fx, "billing_terms": {}, "default_l": 1, "as_of_month": None}
    src = {t: {"file": meta[t]["file"], "sheet": meta[t]["sheet"]} for t in datasets}
    res = server.sanitize(ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], cfg, src))
    out = gateway.build_outbound({"reporting_currency": "EUR", "metrics": gateway._slice_for_step(res, "growth_engine")}, {})
    keys = {k for _, node in _walk(out) for k in node}
    for needle in ("trailing_window_months", "nrr_base_customers", "reason", "required_vs_observed_12m",
                   "reconciliation", "path_to_plan_ratio", "factor_compounded_base", "factor_landed_acv",
                   "factor_gross_rate", "segment_ratio"):
        assert needle in keys, needle


# ---------------------------------------------------------------------------
# The price table: verified entries, and no fallback
# ---------------------------------------------------------------------------
def test_price_table_has_exactly_the_verified_entries():
    assert gateway.MODEL_PRICING_USD == {
        "claude-opus-5-5": {"input": 4.00, "output": 20.00},
        "claude-opus-5": {"input": 5.00, "output": 25.00},
        "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
        "claude-sonnet-5": {"input": 2.00, "output": 10.00},
        "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    }


def test_the_pre_existing_entries_are_unchanged():
    p = gateway.MODEL_PRICING_USD
    assert p["claude-opus-5"] == {"input": 5.00, "output": 25.00}
    assert p["claude-sonnet-5"] == {"input": 2.00, "output": 10.00}
    assert p["claude-haiku-4-5"] == {"input": 1.00, "output": 5.00}


def test_the_new_models_can_be_selected_and_are_costed_at_their_own_price(monkeypatch):
    for model, expected in (("claude-sonnet-5-5", 2.00 + 10.00), ("claude-opus-5-5", 4.00 + 20.00)):
        monkeypatch.setenv("NARRATIVE_MODEL", model)
        assert gateway.run_model() == model
        # one million tokens in and one million out
        assert gateway.estimate_cost_usd(model, 1_000_000, 1_000_000) == pytest.approx(expected)


def test_a_narrative_generated_on_a_newly_priced_model_is_logged_with_its_cost(monkeypatch):
    monkeypatch.setenv("NARRATIVE_MODEL", "claude-sonnet-5-5")

    async def run():
        db = make_db()
        await gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=FakeAdapter(), sleep=_noop_sleep)
        return db["llm_calls"].docs, db["llm_narratives"].docs

    calls, stored = asyncio.run(run())
    assert calls[0]["model"] == "claude-sonnet-5-5" and stored[0]["model"] == "claude-sonnet-5-5"
    assert calls[0]["status"] in ("ok", "flagged")


def test_an_unpriced_model_is_still_refused_even_if_it_looks_like_a_priced_one(monkeypatch):
    for bad in ("claude-sonnet-5-6", "claude-opus-5-5-20260401", "Claude-Sonnet-5-5", "claude-sonnet-5-5 ", "sonnet"):
        monkeypatch.setenv("NARRATIVE_MODEL", bad)
        if bad.strip() == "claude-sonnet-5-5":       # surrounding whitespace is trimmed, the string is the same
            assert gateway.run_model() == "claude-sonnet-5-5"
            continue
        with pytest.raises(gateway.GatewayError) as exc:
            gateway.run_model()
        assert exc.value.reason == "model_not_configured", bad


def test_there_is_no_default_price_in_the_code():
    """A .get(model, <default>) or a price-table fallback would let an unpriced model through."""
    source = (BACKEND / "app" / "llm" / "gateway.py").read_text()
    assert "MODEL_PRICING_USD.get(model, " not in source
    assert "DEFAULT_PRICE" not in source and "FALLBACK_PRICE" not in source
