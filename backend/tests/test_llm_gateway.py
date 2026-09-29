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
    "headline": "Ending ARR is 3,129,600 EUR with NRR at 104%.",
    "what_this_means": "Net revenue retention of 104% indicates the existing base expands.",
    "table_rows": [
        {"label": "Ending ARR", "value": "3,129,600 EUR", "source_key": "arr"},
        {"label": "NRR", "value": "104%", "source_key": "nrr"},
    ],
    "worth_flagging": ["Gross revenue churn stands at 6%."],
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
    assert result.prompt_version == "v4", "the version is returned, the text is not"


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
