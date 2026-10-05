"""Model reading of deck structures and spreadsheet headers (docs/specs/llm-structure-reading.md).

Recorded replies (tests/fixtures/structure_replies/, public test decks only) are replayed through the
fake adapter: no test reaches a live API. They are written in the model's output format against the
structures the parser finds on the public decks; no live call was made to produce them.
"""
import asyncio
import copy
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app.llm import gateway, guards  # noqa: E402
from app.llm.schemas import StructureReply  # noqa: E402
from app.structures import redact, verify  # noqa: E402
import test_llm_gateway as t  # noqa: E402

REPLIES = BACKEND / "tests" / "fixtures" / "structure_replies"
DECKS = BACKEND.parent / "tests" / "fixtures" / "decks" / "decks"
AUDIT = "audit-s"
AUDIT_DOC = {"id": AUDIT, "company_name": "Zero2Hero", "client_name": "Northbridge Capital",
             "engagement_reference": "ENG-2026-041", "structure_reading_consent": True, "fiscal_year_end": 12,
             "results": None}
TEXT = "r1c2: FY2025\nr1c3: FY2026\nr2c1: Revenue\nr2c2: £1,200,000\nr2c3: £1,500,000"
REPLY = {"type": "table", "items": [
    {"metric": "revenue", "period": "FY2025", "value": 1200000, "unit": "GBP", "actual_or_forecast": "forecast",
     "unit_other": None, "value_cell": "r2c2", "period_cells": ["r1c2"], "proposed_flags": []}]}


def _db(**audit):
    db = t.FakeDB()
    db["audits"].docs.append({**copy.deepcopy(AUDIT_DOC), **audit})
    return db


def _read(db, text=TEXT, kind="table", replies=None, adapter=None, **kwargs):
    adapter = adapter or t.FakeAdapter(replies=[json.dumps(r) for r in (replies or [REPLY])])
    result = asyncio.run(gateway.read_structure(db, AUDIT, text, kind, adapter=adapter, sleep=t._noop_sleep, **kwargs))
    return result, adapter


def _fixtures():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(REPLIES.glob("*.json"))]


def _structure(fixture):
    from app.decks import parser
    deck = parser.parse_deck((DECKS / fixture["file"]).read_bytes(), fixture["file"])
    return next(s for s in deck["structures"]
                if (s.get("slide") or s.get("page")) == fixture["page"] and s["type"] == fixture["type"])


# ---------------------------------------------------------------------------
# Recorded replies on the public test decks, replayed and verified
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f"{f['file']}-p{f['page']}-{f['type']}")
def test_recorded_replies_replay_through_the_gateway_and_the_verifier(fixture):
    pytest.importorskip("pdfplumber")
    pytest.importorskip("pptx")
    structure = _structure(fixture)
    cells, _ = redact.redact_structure(structure["cells"], "Zero2Hero", {})
    text = redact.structure_text(cells)
    db = _db()
    result, adapter = _read(db, text, fixture["type"], [fixture["reply"]])
    assert result.status == "read" and adapter.calls == 1, result.reason
    sent = json.loads(adapter.payloads[0])
    assert sent == {"type": fixture["type"], "text": text}, "the type and the structure text, nothing else"
    checked = verify.verify(structure, result.items)
    statuses = [i["status"] for i in checked["items"]]
    assert {"verified": statuses.count("verified"), "suggestion": statuses.count("suggestion")} == fixture["expected"]


def test_the_call_is_pinned_to_one_model_with_no_temperature_no_tools_and_the_structure_schema(monkeypatch):
    monkeypatch.setenv("NARRATIVE_MODEL", "claude-opus-5-5")      # the narrative setting does not move it
    result, adapter = _read(_db())
    assert result.status == "read" and result.model == "claude-sonnet-5-5" == gateway.STRUCTURE_MODEL
    request, = adapter.requests
    assert request["model"] == "claude-sonnet-5-5" and request["temperature"] is None
    assert request["max_tokens"] == gateway.STRUCTURE_MAX_TOKENS
    assert set(request["json_schema"]["properties"]) == {"type", "items"}
    assert "claude-sonnet-5-5" in gateway.MODEL_PRICING_USD, "the pinned model has a price entry"


# ---------------------------------------------------------------------------
# Units: 20 listed currencies; any other ISO currency is "other", with its code in unit_other
# ---------------------------------------------------------------------------
LISTED_CURRENCIES = ("EUR", "USD", "GBP", "CHF", "BGN", "RON", "PLN", "CZK", "HUF", "SEK", "NOK", "DKK", "TRY", "UAH",
                     "RSD", "JPY", "CNY", "INR", "AUD", "CAD")


def test_the_output_schema_lists_20_currencies_and_other_with_the_code_in_unit_other():
    from app.llm import schemas
    schema = schemas.structure_output_schema()
    item = schema["properties"]["items"]["items"]
    assert item["properties"]["unit"] == {"anyOf": [
        {"type": "string", "enum": [*LISTED_CURRENCIES, "other", "%", "x", "count", "days", "months", "years"]},
        {"type": "null"}]}
    assert item["properties"]["unit_other"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert item["required"] == list(item["properties"]) and item["additionalProperties"] is False
    assert set(LISTED_CURRENCIES) < set(schemas.ISO_CURRENCIES), "listed codes are ISO 4217 codes"
    assert not [code for code in schemas.ISO_CURRENCIES if code not in LISTED_CURRENCIES and code in json.dumps(schema)]


ABSENT = object()


@pytest.mark.parametrize("unit, unit_other, valid", [
    ("other", "ZAR", True),
    ("GBP", None, True),
    ("%", None, True),
    (None, None, True),
    ("ZAR", None, False),                   # an unlisted code is not a unit of its own any more
    ("other", None, False),                 # "other" names its code
    ("other", "USD", False),                # a listed currency has its own value
    ("other", "XYZ", False),                # not an ISO 4217 code
    ("other", "zar", False),
    ("other", "Jane Doe (CEO)", False),     # free text never passes
    ("GBP", "GBP", False),                  # a code stands only beside "other"
    ("%", "ZAR", False),
    ("GBP", ABSENT, False),                 # exactly the schema's fields: unit_other is always written
])
def test_unit_other_holds_an_unlisted_iso_code_and_stands_only_beside_other(unit, unit_other, valid):
    item = {**REPLY["items"][0], "unit": unit, "unit_other": unit_other}
    if unit_other is ABSENT:
        del item["unit_other"]
    reply = json.dumps({"type": "table", "items": [item]})
    if valid:
        parsed = gateway.parse_structure_reply(reply, "table", TEXT)
        assert (parsed.items[0].unit, parsed.items[0].unit_other) == (unit, unit_other)
    else:
        with pytest.raises(gateway.GatewayError, match="did not match the schema"):
            gateway.parse_structure_reply(reply, "table", TEXT)


def test_a_currency_outside_the_list_is_read_as_other_and_reaches_the_approval_row_as_its_code():
    item = {**REPLY["items"][0], "unit": "other", "unit_other": "ZAR"}
    result, _ = _read(_db(), replies=[{"type": "table", "items": [item]}])
    assert result.status == "read", result.reason
    assert (result.items[0]["unit"], result.items[0]["unit_other"]) == ("other", "ZAR")
    structure = {"type": "table", "header_rows": 1, "cells": redact.parse_structure_text(TEXT)}
    checked, = verify.verify(structure, result.items)["items"]
    assert checked["status"] == verify.VERIFIED

    def row(item):
        found = structures.candidate_from_item(item, structure, {"file": "plan.pdf"}, None, 12)
        return found["currency"], found["unit"]
    assert row(checked) == ("ZAR", None)
    assert row({**checked, "unit": "GBP", "unit_other": None}) == ("GBP", None)
    assert row({**checked, "unit": "%", "unit_other": None}) == (None, "%")
    stored_before = {k: v for k, v in checked.items() if k != "unit_other"}
    assert row({**stored_before, "unit": "ZAR"}) == ("ZAR", None), "a reading stored under the old schema"


def test_the_adapter_sends_no_tools_and_no_temperature_to_the_provider(monkeypatch):
    sent = {}

    class Messages:
        def create(self, **kwargs):
            sent.update(kwargs)

            class Response:
                content, stop_reason = [type("B", (), {"type": "text", "text": json.dumps(REPLY)})()], "end_turn"
                usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()
            return Response()

    adapter = gateway.AnthropicAdapter(api_key="test")
    adapter._client = type("C", (), {"messages": Messages()})()
    adapter.complete(model=gateway.STRUCTURE_MODEL, system="s", user_payload="u", max_tokens=10, temperature=None,
                     json_schema={"type": "object"})
    assert "tools" not in sent and "temperature" not in sent and sent["output_config"]["format"]["type"] == "json_schema"


def test_the_adapter_counts_the_text_alone_with_no_system_prompt_and_no_schema():
    sent = []

    class Messages:
        def count_tokens(self, **kwargs):
            sent.append(kwargs)
            return type("R", (), {"input_tokens": 7})()

    adapter = gateway.AnthropicAdapter(api_key="test")
    adapter._client = type("C", (), {"messages": Messages()})()
    assert adapter.count_tokens(model=gateway.STRUCTURE_MODEL, system=None, user_payload="r1c1: Revenue",
                                json_schema=None) == 7
    adapter.count_tokens(model=gateway.STRUCTURE_MODEL, system="s", user_payload="u", json_schema={"type": "object"})
    assert sent[0] == {"model": gateway.STRUCTURE_MODEL, "messages": [{"role": "user", "content": "r1c1: Revenue"}]}
    assert sent[1]["system"] == "s" and sent[1]["output_config"]["format"]["schema"] == {"type": "object"}


def test_the_adapter_raises_on_a_refusal_stop_reason():
    class Messages:
        def create(self, **kwargs):
            class Response:
                content, stop_reason = [], "refusal"
                usage = type("U", (), {"input_tokens": 10, "output_tokens": 0})()
            return Response()
    adapter = gateway.AnthropicAdapter(api_key="test")
    adapter._client = type("C", (), {"messages": Messages()})()
    with pytest.raises(gateway.GatewayError) as exc:
        adapter.complete(model=gateway.STRUCTURE_MODEL, system="s", user_payload="u", max_tokens=10, temperature=None,
                         json_schema={"type": "object"})
    assert exc.value.reason == "model_refused"


def test_a_refusal_is_not_retried_and_the_structure_is_not_read():
    class Refusing(t.FakeAdapter):
        def complete(self, **kwargs):
            self.calls += 1
            raise gateway.GatewayError("model_refused", "declined")
    result, adapter = _read(_db(), adapter=Refusing())
    assert (result.status, result.reason, adapter.calls) == ("not_read", "Not read by AI", 1)


# ---------------------------------------------------------------------------
# Schema validation, cited cells, the type
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    {**REPLY, "comment": "extra field"},
    {"type": "table", "items": [{**REPLY["items"][0], "note": "Revenue grew strongly"}]},
    {"type": "table", "items": [{**REPLY["items"][0], "value_cell": "r9c9"}]},          # no such cell
    {"type": "table", "items": [{**REPLY["items"][0], "period_cells": ["r1c2", "r1c3", "r2c1"]}]},
    {"type": "table", "items": [{**REPLY["items"][0], "period": "next year"}]},
    {"type": "column_mapping", "items": []},                                             # a deck structure is never one
    "not json",
])
def test_a_reply_that_fails_validation_is_asked_again_once_then_not_read(bad):
    reply = bad if isinstance(bad, str) else json.dumps(bad)
    adapter = t.FakeAdapter(replies=[reply, reply])
    result, _ = _read(_db(), adapter=adapter)
    assert (result.status, result.reason, adapter.calls) == ("not_read", "Not read by AI", 2)
    adapter = t.FakeAdapter(replies=[reply, json.dumps(REPLY)])
    result, _ = _read(_db(), adapter=adapter)
    assert (result.status, adapter.calls) == ("read", 2), "the one reask recovers"


def test_the_type_may_be_corrected_within_the_deck_types_and_the_change_is_logged(caplog):
    import logging
    db = _db()
    with caplog.at_level(logging.INFO):
        result, _ = _read(db, replies=[{**REPLY, "type": "unit_economics"}])
    assert (result.status, result.type, result.model_type) == ("read", "table", "unit_economics")
    stored, = db[gateway.STRUCTURES_COLLECTION].docs
    assert (stored["type"], stored["model_type"]) == ("table", "unit_economics")
    assert "type_change=table->unit_economics" in caplog.text
    mapping_text = "r1c1: Customer\nr1c2: Amount\nc2 sample: 1200"
    result, adapter = _read(_db(), mapping_text, "column_mapping", replies=[REPLY, REPLY])
    assert result.status == "not_read" and adapter.calls == 2, "a column mapping stays a column mapping"


def test_the_schema_lists_match_the_claim_types_and_the_mapping_fields():
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "structure_reading_test")
    from app.decks import claims
    from app.llm import schemas
    import server
    fields = {f for d in server.FIELD_DEFS.values() for group in ("required", "optional") for f in d[group]}
    assert schemas.CLAIM_METRICS == claims.CLAIM_TYPES
    assert set(schemas.MAPPING_FIELDS) == fields
    assert set(schemas.STRUCTURE_METRICS) == set(claims.CLAIM_TYPES) | {"use_of_funds"} | fields
    assert StructureReply.model_json_schema()["additionalProperties"] is False


# ---------------------------------------------------------------------------
# Consent, cache, caps
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("consent", [False, None])
def test_without_consent_no_call_is_made(consent):
    audit = {"structure_reading_consent": consent} if consent is not None else {}
    db = t.FakeDB()
    db["audits"].docs.append({k: v for k, v in {**AUDIT_DOC, **audit}.items()
                              if consent is not None or k != "structure_reading_consent"})
    result, adapter = _read(db)
    assert result.status == "no_consent" and adapter.calls == 0 and getattr(adapter, "counted", 0) == 0


def test_a_cache_hit_makes_no_call_and_no_audit_is_served_another_audits_result():
    db = _db()
    first, adapter = _read(db)
    again, cached = _read(db)
    assert first.status == again.status == "read" and again.cache_hit and cached.calls == 0
    assert again.items == first.items and again.key == first.key
    db["audits"].docs.append({**AUDIT_DOC, "id": "audit-other"})
    other = t.FakeAdapter(replies=[json.dumps(REPLY)])
    asyncio.run(gateway.read_structure(db, "audit-other", TEXT, "table", adapter=other, sleep=t._noop_sleep))
    assert other.calls == 1, "the same text in another audit is read again, not served from this audit"
    bypass, adapter = _read(db, use_cache=False)
    assert adapter.calls == 1 and not bypass.cache_hit


def test_the_cache_key_covers_text_type_prompt_and_model():
    key = gateway.structure_key(TEXT, "table", "r4:v1", "claude-sonnet-5-5")
    assert key != gateway.structure_key(TEXT + "x", "table", "r4:v1", "claude-sonnet-5-5")
    assert key != gateway.structure_key(TEXT, "chart", "r4:v1", "claude-sonnet-5-5")
    assert key != gateway.structure_key(TEXT, "table", "r5:v1", "claude-sonnet-5-5")
    assert key != gateway.structure_key(TEXT, "table", "r4:v1", "claude-opus-5-5")


def test_a_structure_over_3000_tokens_of_text_is_not_sent():
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    adapter.text_tokens, adapter.input_tokens = 3001, 3500
    result, _ = _read(_db(), adapter=adapter)
    assert (result.status, result.reason, adapter.calls) == ("too_large", "Too large for AI reading", 0)
    assert adapter.count_requests == [{"system": None, "user_payload": TEXT, "json_schema": None}], \
        "the structure text alone is counted, and nothing more once it is over"


def test_the_3000_cap_is_on_the_structure_text_alone_not_the_prompt_and_schema():
    db = _db()
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    adapter.text_tokens, adapter.input_tokens = 2900, 4000
    result, _ = _read(db, adapter=adapter)
    assert (result.status, adapter.calls) == ("read", 1)
    whole = adapter.count_requests[1]
    assert whole["system"] and whole["json_schema"] and json.loads(whole["user_payload"])["text"] == TEXT
    # The 400,000 cap counts the whole call: 392,300 used + 4,000 input + 4,000 max_tokens is over
    # (with the text's 2,900 it would fit).
    db["llm_calls"].docs.append({"run_id": AUDIT, "step": "structures", "cache_hit": False, "input_tokens": 387000,
                                 "output_tokens": 1000, "estimated_cost_usd": 0.0, "timestamp": "2026-10-05T00:00:00"})
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    adapter.text_tokens, adapter.input_tokens = 2900, 4000
    result, _ = _read(db, adapter=adapter, use_cache=False)
    assert result.status == "stopped" and adapter.calls == 0


def test_the_400000_token_cap_counts_billed_input_and_output_and_stops_with_the_spec_message():
    db = _db()
    db["llm_calls"].docs.append({"run_id": AUDIT, "step": "structures", "cache_hit": False, "input_tokens": 390000,
                                 "output_tokens": 4000, "estimated_cost_usd": 0.0, "timestamp": "2026-10-05T00:00:00"})
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    adapter.input_tokens = 2001            # 394,000 used + 2,001 input + 4,000 max_tokens > 400,000
    result, _ = _read(db, adapter=adapter)
    assert result.status == "stopped" and adapter.calls == 0
    assert result.reason == ("AI reading stopped: this audit reached its 400,000-token limit. The remaining "
                             "structures were read by Python only.")
    adapter.input_tokens = 2000            # exactly at the cap: the call goes out
    result, _ = _read(db, adapter=adapter)
    assert result.status == "read" and adapter.calls == 1


def test_an_audit_of_8_decks_of_5_structures_fits_the_token_cap():
    """At the live run's ~9,000 billed input tokens a read and up to 900 output tokens, the 40 reads of an audit of
    8 decks of 5 structures each fit under the per-audit cap, and the 41st is refused. Under 200,000 the 20th was."""
    class Read(t.FakeAdapter):
        input_tokens, text_tokens = 9000, 100

        def complete(self, **kwargs):
            reply, tokens_in, _ = super().complete(**kwargs)
            return reply, tokens_in, 900
    db, adapter = _db(), Read(replies=[json.dumps({"type": "table", "items": []})])
    statuses = [_read(db, f"r1c1: Revenue\nr1c2: {n}", adapter=adapter)[0].status for n in range(41)]
    assert statuses == ["read"] * 40 + ["stopped"]


def test_a_cap_refusal_logs_a_not_read_line(monkeypatch, caplog):
    """A structure the daily spend cap or the 400,000-token cap refuses was not read and printed nothing, so a run
    that hit a cap showed only "0 of N structures read". It now logs reason=spend_cap or reason=token_cap."""
    import logging
    from datetime import datetime, timezone
    db = _db()
    db["llm_calls"].docs.append({"run_id": AUDIT, "step": "structures", "cache_hit": False, "input_tokens": 394000,
                                 "output_tokens": 4000, "estimated_cost_usd": 0.0, "timestamp": "2026-10-05T00:00:00"})
    with caplog.at_level(logging.INFO):
        result, adapter = _read(db)
    assert (result.status, adapter.calls) == ("stopped", 0)
    assert caplog.text.count("structure not read:") == 1
    assert "structure not read: run_id=audit-s step=structures hash=" in caplog.text
    assert "reason=token_cap status=- type=-" in caplog.text
    caplog.clear()
    monkeypatch.setenv("LLM_DAILY_SPEND_CAP_USD", "0.01")
    db = _db()
    db["llm_calls"].docs.append({"run_id": "elsewhere", "cache_hit": False, "estimated_cost_usd": 1.0,
                                 "timestamp": datetime.now(timezone.utc).isoformat()})
    with caplog.at_level(logging.INFO):
        result, adapter = _read(db)
    assert (result.status, adapter.calls) == ("not_read", 0)
    assert caplog.text.count("structure not read:") == 1 and "reason=spend_cap status=- type=-" in caplog.text
    assert db["llm_calls"].docs[-1]["status"] == "daily_spend_cap_exceeded", "llm_calls keeps the guard's code"


def test_the_15_call_cap_counts_narrative_calls_only():
    db = t.make_db()
    for _ in range(guards.MAX_CALLS_PER_RUN):
        db["llm_calls"].docs.append({"run_id": t.RUN_ID, "step": "structures", "cache_hit": False,
                                     "input_tokens": 10, "output_tokens": 10, "estimated_cost_usd": 0.0,
                                     "timestamp": "2026-10-05T00:00:00+00:00"})
    adapter = t.FakeAdapter()
    result = asyncio.run(gateway.generate_narrative(db, t.RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))
    assert adapter.calls == 1 and result.narrative_status in ("ok", "flagged"), "structure calls never use the call cap"
    assert asyncio.run(guards.calls_made(db, t.RUN_ID)) == 1


def test_the_daily_spend_cap_and_the_lock_apply_to_structure_calls(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setenv("LLM_DAILY_SPEND_CAP_USD", "0.01")
    db = _db()
    db["llm_calls"].docs.append({"run_id": "elsewhere", "cache_hit": False, "estimated_cost_usd": 1.0,
                                 "timestamp": datetime.now(timezone.utc).isoformat()})
    result, adapter = _read(db)
    assert result.status == "not_read" and adapter.calls == 0
    assert db["llm_locks"].docs and all(not lock["held"] for lock in db["llm_locks"].docs), "lock taken, then released"
    assert {lock["step"] for lock in db["llm_locks"].docs} == {"structures"}


# ---------------------------------------------------------------------------
# Logging, usage, Delete audit
# ---------------------------------------------------------------------------
def test_storage_and_logs_hold_the_model_output_and_metadata_never_the_text_sent():
    db = _db()
    result, _ = _read(db, deck_id="deck-1", page=19)
    stored, = db[gateway.STRUCTURES_COLLECTION].docs
    assert {"audit_id", "key", "content_hash", "type", "model_type", "output", "prompt_version", "model",
            "input_tokens", "output_tokens", "estimated_cost_usd", "deck_id", "page", "created_at"} <= set(stored)
    assert (stored["deck_id"], stored["page"], stored["model"]) == ("deck-1", 19, "claude-sonnet-5-5")
    call, = db["llm_calls"].docs
    assert (call["step"], call["deck_id"], call["content_hash"]) == ("structures", "deck-1", stored["content_hash"])
    blob = json.dumps([stored, call])
    for needle in ("Revenue", "£1,200,000", TEXT):
        assert needle not in blob, f"{needle!r} was stored"


def test_usage_gains_per_deck_cost_and_keeps_narrative_calls_apart():
    db = _db()
    _read(db, deck_id="deck-1")
    _read(db, deck_id="deck-1")             # a cache hit
    usage = asyncio.run(gateway.usage_for_run(db, AUDIT))
    assert usage.calls == 0 and usage.structure_calls == 1 and usage.structure_token_cap == 400000
    deck = usage.by_deck["deck-1"]
    assert (deck.calls, deck.cache_hits, deck.input_tokens, deck.output_tokens) == (1, 1, 1200, 300)
    assert deck.estimated_cost_usd == pytest.approx(gateway.estimate_cost_usd("claude-sonnet-5-5", 1200, 300))


def test_purge_run_removes_the_stored_structure_readings():
    db = _db()
    _read(db, deck_id="deck-1")
    purged = asyncio.run(gateway.purge_run(db, AUDIT))
    assert purged["llm_structures"] == 1 and db[gateway.STRUCTURES_COLLECTION].docs == []
    assert db["llm_calls"].docs == []


# ---------------------------------------------------------------------------
# Column mapping: header stack of at most 3 rows, samples for numeric and date columns, a profile
# only for text columns; one-click confirmation; confirmed mappings reused per header set
# ---------------------------------------------------------------------------
import app.structures as structures  # noqa: E402

SECRET = "Jane Doe Holdings"           # a text cell value: never on the column-mapping path


def _sheet():
    columns = ["Kunde", "Rechnungsdatum", "Betrag", "Notiz", "Kundennummer"]
    rows = [{"Kunde": f"{SECRET} {i}", "Rechnungsdatum": f"2025-0{i}-28T00:00:00", "Betrag": 100.5 * i,
             "Notiz": f"call {SECRET}", "Kundennummer": 10000 + i} for i in range(1, 6)]
    return columns, rows


def test_numeric_and_date_columns_send_up_to_3_samples_and_text_columns_a_profile_only():
    columns, rows = _sheet()
    text = structures.column_mapping_text(columns, rows, "Target", {}, ("Kundennummer",))
    parsed = redact.parse_column_text(text)
    assert parsed["samples"] == {2: ["2025-01-28", "2025-02-28", "2025-03-28"], 3: ["100.5", "201", "301.5"]}
    assert set(parsed["profiles"]) == {1, 4, 5}, "text columns and the customer column send a profile"
    assert parsed["profiles"][1] == {"distinct": 5, "length": 19, "shape": "Aa Aa Aa 0"}
    assert SECRET.lower() not in text.lower() and "10001" not in text, "no text cell value, no customer number"
    assert redact.column_text_problem(text) is None


def test_the_header_stack_is_capped_at_the_3_rows_nearest_the_data():
    columns = ["Revenue report 2025", "Unnamed: 1", "Unnamed: 2"]
    rows = [{"Revenue report 2025": "Prepared by finance", "Unnamed: 1": None, "Unnamed: 2": None},
            {"Revenue report 2025": None, "Unnamed: 1": 2025, "Unnamed: 2": None},
            {"Revenue report 2025": "Month", "Unnamed: 1": "Jan", "Unnamed: 2": "Feb"},
            {"Revenue report 2025": "Revenue", "Unnamed: 1": 100, "Unnamed: 2": 200}]
    headers, samples, _ = structures.column_mapping_input(columns, rows)
    assert [(c["row"], c["col"], c["text"]) for c in headers] == [
        (1, 1, "Prepared by finance"), (2, 2, "2025"), (3, 1, "Month"), (3, 2, "Jan"), (3, 3, "Feb")]
    assert "Revenue report 2025" not in {c["text"] for c in headers}, "the 4th row from the data is left out"
    assert samples == {2: ["100"], 3: ["200"]}


def _api(monkeypatch, replies, consent=True):
    pytest.importorskip("fastapi")
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "structure_reading_test")
    from fastapi.testclient import TestClient
    import server
    db = t.FakeDB()
    db["audits"].docs.append({**AUDIT_DOC, "structure_reading_consent": consent})
    monkeypatch.setattr(server, "db", db)
    adapter = t.FakeAdapter(replies=[json.dumps(r) for r in replies])
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: adapter)
    return TestClient(server.app, raise_server_exceptions=False), db, adapter


GERMAN = "Kunde,Rechnungsdatum,Betrag,Waehrung\nAcme GmbH,2025-01-31,100,EUR\nBeta AG,2025-02-28,200,EUR\n"
MAPPING_REPLY = {"type": "column_mapping", "items": [
    {"metric": f, "period": None, "value": None, "unit": None, "actual_or_forecast": "unknown", "value_cell": cell,
     "unit_other": None, "period_cells": [], "proposed_flags": []}
    for f, cell in (("customer_id", "r1c1"), ("invoice_date", "r1c2"), ("amount", "r1c3"), ("currency", "r1c4"),
                    ("deal_id", "r1c1"))]}


def test_the_model_proposes_what_the_aliases_miss_and_the_screen_marks_it_as_a_suggestion(monkeypatch):
    client, db, adapter = _api(monkeypatch, [MAPPING_REPLY])
    r = client.post(f"/api/audits/{AUDIT}/datasets/revenue/upload", files={"file": ("rev.csv", GERMAN)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert adapter.calls == 1 and json.loads(adapter.payloads[0])["type"] == "column_mapping"
    assert body["suggested_mapping"]["customer_id"] == "Kunde" and body["mapping_source"]["customer_id"] == "ai"
    assert body["suggested_mapping"]["invoice_date"] == "Rechnungsdatum"
    assert "deal_id" not in body["suggested_mapping"], "a field of another file type is left out"
    sent = json.loads(adapter.payloads[0])["text"]
    assert "Acme" not in sent and "Beta" not in sent, "customer cells travel as a profile"
    stored, = db[gateway.STRUCTURES_COLLECTION].docs
    assert stored["statuses"] == ["suggestion"] * 5, "a column mapping is never Verified"


def test_one_click_confirms_and_the_confirmed_mapping_is_reused_for_the_same_headers(monkeypatch):
    client, db, adapter = _api(monkeypatch, [MAPPING_REPLY])
    client.post(f"/api/audits/{AUDIT}/datasets/revenue/upload", files={"file": ("rev.csv", GERMAN)})
    mapping = {"customer_id": "Kunde", "invoice_date": "Rechnungsdatum", "amount": "Betrag", "currency": "Waehrung"}
    assert client.put(f"/api/audits/{AUDIT}/datasets/revenue/mapping", json={"mapping": mapping}).status_code == 200
    again = client.post(f"/api/audits/{AUDIT}/datasets/revenue/upload", files={"file": ("rev2.csv", GERMAN)}).json()
    assert adapter.calls == 1, "the stored correction is used: no second model call"
    assert {f: again["suggested_mapping"][f] for f in mapping} == mapping
    assert set(again["mapping_source"].values()) == {"stored"}
    client.delete(f"/api/audits/{AUDIT}")
    assert db[structures.COLUMN_MAPPINGS_COLLECTION].docs == [], "Delete audit removes the stored mapping"


def test_without_consent_the_mapping_comes_from_the_aliases_only(monkeypatch):
    client, _, adapter = _api(monkeypatch, [MAPPING_REPLY], consent=False)
    body = client.post(f"/api/audits/{AUDIT}/datasets/revenue/upload", files={"file": ("rev.csv", GERMAN)}).json()
    assert adapter.calls == 0 and body["ai_reading"]["status"] == "no_consent"
    assert "ai" not in body["mapping_source"].values()


def test_a_proposal_names_a_field_of_this_file_type_and_cites_an_existing_header():
    items = [dict(MAPPING_REPLY["items"][0]), {**MAPPING_REPLY["items"][0], "metric": "deal_id", "value_cell": "r1c3"},
             {**MAPPING_REPLY["items"][0], "metric": "amount", "value_cell": "r1c9"},
             {**MAPPING_REPLY["items"][0], "metric": "currency", "value_cell": "r1c1"}]
    fields = ["customer_id", "invoice_date", "amount", "currency"]
    assert structures.proposed_mapping(items, ["Kunde", "Datum", "Betrag"], fields) == {"customer_id": "Kunde"}, \
        "deal_id is a CRM field, r1c9 does not exist, Kunde is already proposed"


def test_the_aliases_keep_their_fields_and_the_model_fills_the_rest(monkeypatch):
    reply = {"type": "column_mapping", "items": [
        {**MAPPING_REPLY["items"][0], "metric": "amount", "value_cell": "r1c4"},
        {**MAPPING_REPLY["items"][0], "metric": "customer_id", "value_cell": "r1c1"}]}
    client, _, _ = _api(monkeypatch, [reply])
    sheet = "Kunde,Rechnungsdatum,Amount,Betrag,Waehrung\nAcme,2025-01-31,1,2,EUR\n"
    body = client.post(f"/api/audits/{AUDIT}/datasets/revenue/upload", files={"file": ("r.csv", sheet)}).json()
    assert (body["suggested_mapping"]["amount"], body["mapping_source"]["amount"]) == ("Amount", "rules")
    assert (body["suggested_mapping"]["customer_id"], body["mapping_source"]["customer_id"]) == ("Kunde", "ai")


# ---------------------------------------------------------------------------
# Consent (spec section 4)
# ---------------------------------------------------------------------------
NEW_AUDIT = {"company_name": "Zero2Hero", "client_name": "Northbridge Capital", "engagement_reference": "ENG-2026-041"}


def test_consent_is_ticked_at_creation_by_default_and_every_change_is_logged_with_its_time(monkeypatch):
    client, db, _ = _api(monkeypatch, [])
    created = client.post("/api/audits", json=NEW_AUDIT).json()
    assert created["structure_reading_consent"] is True
    assert [e["value"] for e in created["consent_log"]] == [True] and created["consent_log"][0]["at"]
    assert (created["client_name"], created["engagement_reference"]) == ("Northbridge Capital", "ENG-2026-041")
    client.put(f"/api/audits/{created['id']}", json={"structure_reading_consent": False})
    client.put(f"/api/audits/{created['id']}", json={"structure_reading_consent": False})      # no change: no entry
    stored = next(a for a in db["audits"].docs if a["id"] == created["id"])
    assert [e["value"] for e in stored["consent_log"]] == [True, False] and all(e["at"] for e in stored["consent_log"])
    unticked = client.post("/api/audits", json={**NEW_AUDIT, "structure_reading_consent": False}).json()
    assert unticked["structure_reading_consent"] is False and [e["value"] for e in unticked["consent_log"]] == [False]


@pytest.mark.parametrize("missing", ["client_name", "engagement_reference"])
def test_audit_creation_refuses_a_missing_client_name_or_engagement_reference(monkeypatch, missing):
    client, _, _ = _api(monkeypatch, [])
    assert client.post("/api/audits", json={k: v for k, v in NEW_AUDIT.items() if k != missing}).status_code == 422
    assert client.post("/api/audits", json={**NEW_AUDIT, missing: " "}).status_code == 422


def test_an_audit_created_before_consent_stays_unticked_until_it_has_an_engagement_reference(monkeypatch):
    client, db, adapter = _api(monkeypatch, [REPLY])
    db["audits"].docs.append({"id": "old", "company_name": "Old Co", "results": None})
    result = asyncio.run(gateway.read_structure(db, "old", TEXT, "table", adapter=adapter, sleep=t._noop_sleep))
    assert result.status == "no_consent" and adapter.calls == 0, "no field means unticked"
    assert client.put("/api/audits/old", json={"structure_reading_consent": True}).status_code == 400
    assert client.put("/api/audits/old", json={"structure_reading_consent": True,
                                              "engagement_reference": "ENG-9"}).status_code == 200


# ---------------------------------------------------------------------------
# Orchestration: decks wait for the mapped revenue file, then are read, verified and listed
# ---------------------------------------------------------------------------
class RecordedAdapter(t.FakeAdapter):
    """Replays the recorded reply whose structure the request carries; an empty reading otherwise."""

    def __init__(self):
        super().__init__()
        self.fixtures = _fixtures()

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema):
        sent = json.loads(user_payload)
        reply = next((f["reply"] for f in self.fixtures if f["type"] == sent["type"] and f["match"] in sent["text"]),
                     {"type": sent["type"], "items": []})
        self._replies = [json.dumps(reply)]
        self.calls_before = self.calls
        return super().complete(model=model, system=system, user_payload=user_payload, max_tokens=max_tokens,
                                temperature=temperature, json_schema=json_schema)


REVENUE = "Customer,Invoice Date,Amount,Currency\nAcme Retail,2025-01-31,100,EUR\nBeta Stores,2025-02-28,200,EUR\n"
REVENUE_MAPPING = {"customer_id": "Customer", "invoice_date": "Invoice Date", "amount": "Amount", "currency": "Currency"}


def _deck_api(monkeypatch, consent=True):
    pytest.importorskip("pdfplumber")
    client, db, _ = _api(monkeypatch, [], consent=consent)
    adapter = RecordedAdapter()
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: adapter)
    return client, db, adapter


def _upload_deck(client, name="05-zero2hero.pdf"):
    r = client.post(f"/api/audits/{AUDIT}/decks/upload", files={"file": (name, (DECKS / name).read_bytes())})
    assert r.status_code == 200, r.text
    return r.json()


def _map_revenue(client):
    client.post(f"/api/audits/{AUDIT}/datasets/revenue/upload", files={"file": ("rev.csv", REVENUE)})
    assert client.put(f"/api/audits/{AUDIT}/datasets/revenue/mapping", json={"mapping": REVENUE_MAPPING}).status_code == 200


def _deck(client):
    return client.get(f"/api/audits/{AUDIT}/decks").json()


def test_a_client_name_or_engagement_reference_in_a_deck_cell_goes_out_as_redacted_and_the_structure_is_read():
    from app import structures
    from app.decks import TEXT_COLLECTION
    db = _db()
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "mapping": REVENUE_MAPPING,
                                "mapped_at": "2026-10-05T00:00:00"})
    cells = [{"row": 1, "col": 1, "text": "Prepared for Northbridge Capital"}, {"row": 1, "col": 2, "text": "FY2025"},
             {"row": 2, "col": 1, "text": "Revenue (eng-2026-041)"}, {"row": 2, "col": 2, "text": "£1,200,000"}]
    db[TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "plan.pptx", "page_unit": "slide",
                                     "structures": [{"type": "table", "slide": 1, "header_rows": 1, "cells": cells}]})
    adapter = t.FakeAdapter(replies=[json.dumps({"type": "table", "items": []})])
    status = asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert (status, adapter.calls) == (structures.READ, 1)
    assert json.loads(adapter.payloads[0])["text"] == \
        "r1c1: Prepared for [redacted]\nr1c2: FY2025\nr2c1: Revenue ([redacted])\nr2c2: £1,200,000"


def test_a_client_name_in_a_spreadsheet_header_goes_out_as_redacted(monkeypatch):
    client, _, adapter = _api(monkeypatch, [MAPPING_REPLY])
    sheet = "Kunde,Rechnungsdatum,Betrag Northbridge Capital,Waehrung\nAcme,2025-01-31,1,EUR\n"
    client.post(f"/api/audits/{AUDIT}/datasets/revenue/upload", files={"file": ("r.csv", sheet)})
    sent = json.loads(adapter.payloads[0])["text"]
    assert "r1c3: Betrag [redacted]" in sent and "Northbridge" not in sent


def test_a_corrected_period_is_verified_counted_on_the_deck_and_the_models_period_stays_stored(monkeypatch):
    from app import structures
    from app.decks import TEXT_COLLECTION, CANDIDATES_COLLECTION
    literal = {"type": "table", "items": [
        {"metric": "revenue", "period": "2025-04", "value": 5000000, "unit": "USD", "actual_or_forecast": "forecast",
         "unit_other": None, "value_cell": "r3c2", "period_cells": ["r2c2", "r1c2"], "proposed_flags": []}]}
    client, db, adapter = _api(monkeypatch, [literal])
    db["audits"].docs[0]["fiscal_year_end"] = 3
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "mapping": REVENUE_MAPPING,
                                "mapped_at": "2026-10-05T00:00:00"})
    cells = [{"row": 1, "col": 2, "text": "FY2025"}, {"row": 2, "col": 2, "text": "Apr"},
             {"row": 3, "col": 1, "text": "Revenue"}, {"row": 3, "col": 2, "text": "$5M"}]
    db[TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "plan.pptx", "page_unit": "slide",
                                     "uploaded_at": "2026-10-05T00:00:00",
                                     "structures": [{"type": "table", "slide": 2, "header_rows": 2, "cells": cells}]})
    asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    row, = [c for c in db[CANDIDATES_COLLECTION].docs if c.get("origin") == "ai"]
    assert (row["ai_label"], row["target_date"], row["period_start"], row["period_end"]) == \
        ("Verified", "FY2025-04", "2024-04-01", "2024-04-30")
    stored, = db[gateway.STRUCTURES_COLLECTION].docs
    assert stored["output"]["items"][0]["period"] == "2025-04", "the stored reading keeps the model's period"
    assert stored["periods_corrected"] == 1
    deck, = client.get(f"/api/audits/{AUDIT}/decks").json()["decks"]
    assert deck["periods_corrected"] == 1
    # December: the model's reading holds, so nothing is corrected; the row keeps Python's label.
    client.put(f"/api/audits/{AUDIT}", json={"fiscal_year_end": 12})
    deck, = client.get(f"/api/audits/{AUDIT}/decks").json()["decks"]
    row = next(c for c in db[CANDIDATES_COLLECTION].docs if c.get("origin") == "ai")
    assert deck["periods_corrected"] == 0 and db[gateway.STRUCTURES_COLLECTION].docs[0]["periods_corrected"] == 0
    assert (row["ai_label"], row["target_date"], row["period_start"]) == ("Verified", "FY2025-04", "2025-04-01")


def test_a_deck_uploaded_while_consent_was_off_is_flagged_once_consent_is_on_and_is_not_read(monkeypatch):
    from app.decks import TEXT_COLLECTION
    client, db, adapter = _deck_api(monkeypatch, consent=False)
    _upload_deck(client)
    db[TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "old", "file": "old.pptx", "structures": [],
                                     "uploaded_at": "2020-01-01T00:00:00"})      # uploaded before AI reading existed
    assert [d["uploaded_before_consent"] for d in _deck(client)["decks"]] == [False, False], "off: nothing to say"
    client.put(f"/api/audits/{AUDIT}", json={"structure_reading_consent": True})
    _map_revenue(client)
    assert [d["uploaded_before_consent"] for d in _deck(client)["decks"]] == [True, True]
    deck_reads = lambda: [p for p in adapter.payloads if json.loads(p)["type"] != "column_mapping"]  # noqa: E731
    assert deck_reads() == [], "not read until it is uploaded again"
    _upload_deck(client)
    newest = _deck(client)["decks"][0]
    assert (newest["ai_status"], newest["uploaded_before_consent"]) == ("read", False) and deck_reads()


def test_a_deck_waits_for_the_mapped_revenue_file_and_is_read_once_it_is(monkeypatch):
    client, db, adapter = _deck_api(monkeypatch)
    upload = _upload_deck(client)
    listed = _deck(client)
    assert listed["decks"][0]["ai_status"] == "waiting" and listed["decks"][0]["ai_message"] == "waiting for revenue file"
    assert adapter.calls == 0, "nothing is sent before the customers are in the mapping"
    assert not [c for c in listed["candidates"] if c.get("origin") == "ai"]
    _map_revenue(client)
    calls_for_mapping = 1                    # the revenue upload's column-mapping call is not queued
    assert adapter.calls == calls_for_mapping + upload["structures"], "every structure read once"
    deck = _deck(client)["decks"][0]
    assert deck["ai_status"] == "read" and deck["sent_pages"] == [11, 17, 19, 22]
    assert deck["ai_cost_usd"] == pytest.approx(upload["structures"] * gateway.estimate_cost_usd("claude-sonnet-5-5", 1200, 300))
    usage = client.get(f"/api/runs/{AUDIT}/llm-usage").json()
    assert usage["by_deck"][upload["deck_id"]]["calls"] == upload["structures"] and usage["calls"] == 0
    assert usage["structure_calls"] == upload["structures"] + calls_for_mapping


def test_results_show_in_the_approval_list_labelled_and_citing_their_cell(monkeypatch):
    client, db, adapter = _deck_api(monkeypatch)
    _map_revenue(client)
    _upload_deck(client)
    ai = [c for c in _deck(client)["candidates"] if c.get("origin") == "ai"]
    panel = [c for c in ai if c["sources"][0]["structure"] == "kpi_panel" and c["sources"][0]["page"] == 19]
    assert sorted((c["claim_type"], c["value"], c["ai_label"], c["sources"][0]["cell"]) for c in panel) == [
        ("gross_profit", 150000, "Verified", "r2c1"), ("users", 5000, "Verified", "r3c1")]
    assert panel[0]["period_text"] == "23 Y/E" and panel[0]["target_date"] == "2023"
    table = [c for c in ai if c["sources"][0]["structure"] == "table"]
    assert [(c["value"], c["ai_label"], c["sources"][0]["cell"]) for c in table] == [(20000, "AI suggestion, not verified", "r4c4")], \
        "the 14 table values Python already lists in the same cells are not listed twice; the slip stays, unverified"
    assert all(c["status"] == "pending" for c in ai)


def test_unticked_consent_is_the_python_only_path(monkeypatch):
    client, db, adapter = _deck_api(monkeypatch, consent=False)
    _map_revenue(client)
    _upload_deck(client)
    listed = _deck(client)
    assert adapter.calls == 0 and listed["decks"][0]["ai_status"] == "python_only"
    assert listed["candidates"] and not [c for c in listed["candidates"] if c.get("origin") == "ai"]


def test_a_deck_already_read_is_not_sent_again_when_the_crm_file_is_mapped_later(monkeypatch):
    client, db, adapter = _deck_api(monkeypatch)
    _map_revenue(client)
    _upload_deck(client)
    before = adapter.calls
    crm = "Deal ID,Account,Created,Close Date,Stage,Amount\nD1,Zeta,2025-01-01,2025-02-01,won,10\n"
    client.post(f"/api/audits/{AUDIT}/datasets/crm/upload", files={"file": ("crm.csv", crm)})
    client.put(f"/api/audits/{AUDIT}/datasets/crm/mapping", json={"mapping": {"deal_id": "Deal ID"}})
    assert adapter.calls == before + 1, "only the CRM file's own column-mapping call"


def test_uploading_the_same_deck_again_is_served_from_the_cache_and_lists_no_row_twice(monkeypatch):
    client, db, adapter = _deck_api(monkeypatch)
    _map_revenue(client)
    _upload_deck(client)
    first = [c for c in _deck(client)["candidates"] if c.get("origin") == "ai"]
    approved = first[0]
    client.put(f"/api/audits/{AUDIT}/decks/candidates/{approved['id']}", json={"status": "approved"})
    before = adapter.calls
    _upload_deck(client)
    again = [c for c in _deck(client)["candidates"] if c.get("origin") == "ai"]
    assert adapter.calls == before, "every structure is a cache hit"
    assert len(again) == len(first), "the approved row is kept and not added again"
    assert any(c["id"] == approved["id"] and c["status"] == "approved" for c in again)


def test_the_token_cap_stops_the_remaining_structures_and_the_deck_says_so(monkeypatch):
    client, db, adapter = _deck_api(monkeypatch)
    _map_revenue(client)
    db["llm_calls"].docs.append({"run_id": AUDIT, "step": "structures", "cache_hit": False, "input_tokens": 394000,
                                 "output_tokens": 0, "estimated_cost_usd": 0.0, "timestamp": "2026-10-05T00:00:00"})
    before = adapter.calls
    _upload_deck(client)
    deck = _deck(client)["decks"][0]
    assert adapter.calls == before and deck["ai_status"] == "stopped"
    assert deck["ai_message"] == ("AI reading stopped: this audit reached its 400,000-token limit. The remaining "
                                  "structures were read by Python only.")
    stored = db["deck_text"].docs[0]["structures"]
    assert {s["ai"]["status"] for s in stored} == {"stopped"}


def test_a_new_fiscal_year_end_re_verifies_the_model_readings(monkeypatch):
    client, db, adapter = _deck_api(monkeypatch)
    _map_revenue(client)
    _upload_deck(client)
    panel = [c for c in db["deck_candidates"].docs if c.get("origin") == "ai" and c["claim_type"] == "gross_profit"
             and c["sources"][0]["structure"] == "kpi_panel"]
    assert panel[0]["ai_label"] == "Verified"
    client.put(f"/api/audits/{AUDIT}/decks/candidates/{panel[0]['id']}", json={"status": "pending"})
    # The recorded reading cites "23 Y/E" as FY2023: it stays verified under any year-end, its range moves.
    client.put(f"/api/audits/{AUDIT}", json={"fiscal_year_end": 3})
    after = next(c for c in db["deck_candidates"].docs if c["id"] == panel[0]["id"])
    assert after["ai_label"] == "Verified" and (after["period_start"], after["period_end"]) == ("2022-04-01", "2023-03-31")


def test_a_reading_whose_match_depends_on_the_year_end_is_re_verified_under_the_new_one():
    """"Year 1" counted from "Start: Jan 2025" is January to December 2025: a reading of it as the year
    2025 holds with a December year-end only."""
    from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION
    from app import structures
    structure = {"type": "table", "header_rows": 1, "ai": {"key": "k1"}, "cells": [
        {"row": 1, "col": 1, "text": "Start: Jan 2025"}, {"row": 1, "col": 2, "text": "Year 1"},
        {"row": 2, "col": 1, "text": "Revenue"}, {"row": 2, "col": 2, "text": "£2M"}]}
    item = {"metric": "revenue", "period": "2025", "value": 2000000, "unit": "GBP", "actual_or_forecast": "forecast",
            "unit_other": None, "value_cell": "r2c2", "period_cells": ["r1c2", "r1c1"], "proposed_flags": []}
    db = _db()
    db[TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "structures": [structure]})
    db[gateway.STRUCTURES_COLLECTION].docs.append({"audit_id": AUDIT, "key": "k1", "type": "table",
                                                   "output": {"type": "table", "items": [item]}})
    db[CANDIDATES_COLLECTION].docs.append({"id": "c1", "audit_id": AUDIT, "deck_id": "d1", "structure_key": "k1",
                                           "status": "pending", "cell": "r2c2", "claim_type": "revenue",
                                           "value": 2000000, "ai_status": "verified", "ai_label": "Verified"})
    labels = []
    for year_end in (3, 12):
        asyncio.run(structures.reverify_audit(db, AUDIT, year_end))
        labels.append(db[CANDIDATES_COLLECTION].docs[0]["ai_label"])
    assert labels == ["AI suggestion, not verified", "Verified"]


def test_delete_audit_removes_model_outputs_cache_and_mapping(monkeypatch):
    client, db, adapter = _deck_api(monkeypatch)
    _map_revenue(client)
    _upload_deck(client)
    assert db[gateway.STRUCTURES_COLLECTION].docs and db["pseudonym_map"].docs and db["column_mappings"].docs
    purged = client.delete(f"/api/audits/{AUDIT}").json()
    assert purged["llm_purged"]["llm_structures"] > 0
    for name in (gateway.STRUCTURES_COLLECTION, "pseudonym_map", "column_mappings", "llm_calls", "deck_candidates",
                 "deck_text"):
        assert db[name].docs == [], name


def _consistency_script():
    import importlib.util
    spec = importlib.util.spec_from_file_location("consistency_run", BACKEND.parent / "scripts" / "consistency_run.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def test_the_consistency_script_reports_agreement_match_rate_cost_and_cache_hits_without_a_live_call(
        monkeypatch, tmp_path):
    """scripts/consistency_run.py is manual (live API, costs money); --fake checks its arithmetic."""
    pytest.importorskip("pdfplumber")
    import tempfile
    script = _consistency_script()
    monkeypatch.setattr(script, "REPORTS", tmp_path / "docs" / "test-runs")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temp"))
    (tmp_path / "temp").mkdir()
    report = script.main(["--fake", "--deck", "05-zero2hero.pdf"])
    assert [p.name.split("_")[0] for p in (tmp_path / "temp").iterdir()] == ["consistency"]
    assert not script.REPORTS.exists(), "a fake run's report never lands in docs/test-runs"
    assert report["agreement_pct"]["table"] == 100.0 and report["agreement_pct"]["kpi_panel"] == 100.0
    assert report["verifier_match_rate_pct"] == pytest.approx(100.0 * 16 / 17, abs=0.1), "14 + 2 verified of 17 per pass"
    assert report["cache_hit_rate_pct"] == {"pass_2": 100.0, "pass_3": 100.0}
    assert report["per_deck"]["05-zero2hero.pdf"]["structures"] == 5
    assert report["model_reads"] == 5 * 3, "passes 2 and 3 bypass the cache after counting its hits"
    assert report["period_corrected"] == 0

    class WrongYear(script.FakeAdapter):
        """Replays the recorded replies with one revenue period a year off: its value still matches its cell."""
        def complete(self, **kwargs):
            reply, tokens_in, tokens_out = super().complete(**kwargs)
            body = json.loads(reply)
            for item in body["items"]:
                if (item["metric"], item["value"], item["period"]) == ("revenue", 150000, "FY2023"):
                    item["period"] = "FY2021"
            return json.dumps(body), tokens_in, tokens_out
    report = asyncio.run(script.run(["05-zero2hero.pdf"], 3, script.MemoryDB(), WrongYear()))
    assert report["period_corrected"] == 3, "one per pass"
    assert report["verifier_match_rate_pct"] == pytest.approx(100.0 * 16 / 17, abs=0.1), "a corrected item is verified"
    os.environ.pop("ANTHROPIC_API_KEY", None)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        script.main(["--yes", "--deck", "05-zero2hero.pdf"])


def _drifting(script):
    """The recorded replies, read a little differently from pass to pass (05-zero2hero.pdf page 19): pass 2 writes
    the FY2023 revenue's unit as USD, pass 3 writes its period as "2023" and leaves out the KPI panel's users. In
    every pass the FY2022 users cite their row label as period cell and the FY2023 gross profit proposes a total
    mismatch, so both stay unverified."""
    class Drifting(script.FakeAdapter):
        def __init__(self):
            super().__init__()
            self.calls = {}

        def complete(self, **kwargs):
            reply, tokens_in, tokens_out = super().complete(**kwargs)
            n = self.calls[kwargs["user_payload"]] = self.calls.get(kwargs["user_payload"], 0) + 1   # the pass
            body = json.loads(reply)
            items = []
            for item in body["items"]:
                key = (item["metric"], item["value_cell"])
                if key == ("revenue", "r4c3"):
                    item.update({2: {"unit": "USD"}, 3: {"period": "2023"}}.get(n, {}))
                if key == ("users", "r3c1") and n == 3:
                    continue
                if key == ("users", "r2c2"):
                    item["period_cells"] = ["r2c1"]
                if key == ("gross_profit", "r6c3"):
                    item["proposed_flags"] = ["total_mismatch"]
                items.append(item)
            return json.dumps({**body, "items": items}), tokens_in, tokens_out
    return Drifting


def test_the_consistency_report_shows_where_passes_disagree_why_items_are_unverified_and_the_fixed_prompt(
        monkeypatch, tmp_path):
    """The diagnostics of a fake run: agreement on metric, period, value and cell after the verifier's
    normalisation next to the old all-field figure; the fields that differ per disagreeing structure; a reason
    per unverified item; the fixed prompt's tokens apart from the structure text's."""
    pytest.importorskip("pdfplumber")
    from app.decks import parser
    from app.llm import cache, prompt_store, schemas
    script = _consistency_script()
    report = asyncio.run(script.run(["05-zero2hero.pdf"], 3, script.MemoryDB(), _drifting(script)()))
    # Table: 15 items, one written three ways (USD, then "2023"): 14 of 17 as written, 15 of 15 normalised.
    # KPI panel: its users missing in pass 3, so 1 of 2 either way.
    assert report["agreement_pct_old"] == {"hiring_table": None, "kpi_panel": 50.0, "table": 82.4}
    assert report["agreement_pct"] == {"hiring_table": None, "kpi_panel": 50.0, "table": 100.0}
    assert (report["agreement_pct_all_old"], report["agreement_pct_all"]) == (78.9, 94.1), "15 of 19; 16 of 17"
    assert report["disagreements"] == [
        {"deck": "05-zero2hero.pdf", "page": 19, "type": "table", "fields": ["period", "unit"],
         "same_after_normalisation": True},
        {"deck": "05-zero2hero.pdf", "page": 19, "type": "kpi_panel", "fields": ["cell", "items"],
         "same_after_normalisation": False}]
    zero = dict.fromkeys(script.FIELDS, 0)
    assert report["disagreement_fields"] == {
        "hiring_table": {"structures": 1, "disagreeing": 0, **zero},
        "kpi_panel": {"structures": 3, "disagreeing": 1, **zero, "cell": 1, "items": 1},
        "table": {"structures": 1, "disagreeing": 1, **zero, "period": 1, "unit": 1}}
    assert report["unverified_reasons"] == {"table": {**dict.fromkeys(script.REASONS, 0), "value not in cell": 3,
                                                      "period not rebuilt": 3, "other": 3}}
    where = {"deck": "05-zero2hero.pdf", "page": 19, "type": "table", "passes": 3}
    assert report["unverified_items"] == [
        {**where, "value_cell": "r6c3", "reason": "other", "detail": "flag not reproduced"},
        {**where, "value_cell": "r2c2", "reason": "period not rebuilt", "detail": None},
        {**where, "value_cell": "r4c4", "reason": "value not in cell", "detail": None}]
    assert report["verifier_match_rate_pct"] == 82.0, "41 of 50 items: 15 + 2, 15 + 2, 15 + 1"

    # Tokens: the fake counter is one token per 4 characters of what would be sent.
    def count(system=None, payload="", schema=None):
        return (len(system or "") + len(payload) + (len(json.dumps(schema)) if schema else 0)) // 4
    system, schema = prompt_store.load(gateway.STRUCTURE_PROMPT).text, schemas.structure_output_schema()
    empty = cache.canonical_json({"type": "table", "text": ""})
    texts = [redact.structure_text(redact.redact_structure(s["cells"], "05-zero2hero", {}, set())[0])
             for s in parser.parse_deck((DECKS / "05-zero2hero.pdf").read_bytes(), "05-zero2hero.pdf")["structures"]]
    assert report["tokens"] == {
        "fixed_prompt": count(system, empty, schema), "system_prompt": count(system, empty) - count(payload=empty),
        "output_schema": count(payload=empty, schema=schema) - count(payload=empty),
        "empty_message": count(payload=empty),
        "structure_text_avg": round(sum(count(payload=text) for text in texts) / 5, 1), "structures_counted": 5,
        "billed_input_per_model_read": 1000.0}

    path = script.write_report(report, tmp_path, 3, fake=True)
    text = path.read_text(encoding="utf-8")
    tokens = report["tokens"]
    for line in (
            "| table | 100.0% | 82.4% |", "| kpi_panel | 50.0% | 50.0% |", "| all | 94.1% | 78.9% |",
            "| Type | Structures | Disagreeing | metric | period | value | unit | cell | other | items |",
            "| kpi_panel | 3 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |", "| table | 1 | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 0 |",
            "| 05-zero2hero.pdf | 19 | table | period, unit | yes |",
            "| 05-zero2hero.pdf | 19 | kpi_panel | cell, items | no |",
            "| Type | value not in cell | period not rebuilt | lowest-header rule | metric invalid | other "
            "| Unverified |",
            "| table | 3 | 3 | 0 | 0 | 3 | 9 |", "| all | 3 | 3 | 0 | 0 | 3 | 9 |",
            "| 05-zero2hero.pdf | 19 | table | r6c3 | other (flag not reproduced) | 3 |",
            "| 05-zero2hero.pdf | 19 | table | r2c2 | period not rebuilt | 3 |",
            "| 05-zero2hero.pdf | 19 | table | r4c4 | value not in cell | 3 |",
            f"- Fixed prompt: {tokens['fixed_prompt']:,} (system prompt {tokens['system_prompt']:,}, output schema "
            f"{tokens['output_schema']:,}, empty message {tokens['empty_message']:,})",
            f"- Structure text, average of 5 structures: {tokens['structure_text_avg']:,} (the gateway's 3,000-token "
            "measure: the text alone)",
            "- Billed input per model read: 1,000.0"):
        assert line in text, line
    assert script.summary(report).startswith("Agreement 94.1% (target 95.0%: missed; old method 78.9%); verified 82.0%")

    class Uncountable:
        def count_tokens(self, **kwargs):
            raise RuntimeError("count_tokens unavailable")
    failed = asyncio.run(script.fixed_tokens(Uncountable()))
    assert failed == dict.fromkeys(("fixed_prompt", "system_prompt", "output_schema", "empty_message")), \
        "a failed count is n/a and never stops a paid run"
    report["tokens"].update(failed)
    assert "- Fixed prompt: n/a (system prompt n/a, output schema n/a, empty message n/a)" in \
        script.write_report(report, tmp_path, 3, fake=True).read_text(encoding="utf-8")


def test_roadmap_items_are_reported_apart_from_the_verified_rate(tmp_path):
    """A roadmap item is counted with whether Python rebuilt its date from the cited cells, and is left out of the
    match and unverified rates and their reasons: a milestone has no value, so it is never verified."""
    pytest.importorskip("pdfplumber")
    script = _consistency_script()

    def milestone(cell, period, cells):
        return {"metric": "product", "period": period, "value": None, "unit": None, "actual_or_forecast": "actual",
                "unit_other": None, "value_cell": cell, "period_cells": cells, "proposed_flags": []}

    class Tea(script.FakeAdapter):
        """The TEA roadmap (page 11), as the model might read four of its milestones."""
        def complete(self, **kwargs):
            sent = json.loads(kwargs["user_payload"])
            if sent["type"] != "roadmap" or "r8c2: Rich dApps running on network" not in sent["text"]:
                return super().complete(**kwargs)
            items = [milestone("r3c2", "2021", ["r1c2"]),             # the year at the top of its box
                     milestone("r8c2", "2021-Q4", ["r8c1", "r7c1"]),  # the quarter left of it, the year above that
                     milestone("r2c2", "2021-Q2", ["r2c1", "r1c1"]),  # period headers above and beside: no period
                     milestone("r4c3", None, [])]                      # no date: matches, but nothing is rebuilt
            return json.dumps({"type": "roadmap", "items": items}), 1000, 20
    decks = ["03-buffer.pptx", "05-zero2hero.pdf", "10-tea.pdf"]
    report = asyncio.run(script.run(decks, 3, script.MemoryDB(), Tea()))
    assert (report["roadmap_items"], report["roadmap_dates_rebuilt"]) == (24, 6), \
        "4 Buffer milestones (dates below their lines: none rebuilt) and 4 TEA ones (2 rebuilt), in each of 3 passes"
    assert report["verifier_match_rate_pct"] == 94.1 and report["unverified_rate_pct"] == 5.9, \
        "16 of 17 zero2hero items per pass; no roadmap item in the rates"
    assert list(report["unverified_reasons"]) == ["table"]
    assert [row["type"] for row in report["unverified_items"]] == ["table"]
    assert report["agreement_pct"]["roadmap"] == 100.0, "agreement still counts roadmap items"
    assert "roadmap items: 24, date rebuilt from cell: 6;" in script.summary(report)
    text = script.write_report(report, tmp_path, 3, fake=True).read_text(encoding="utf-8")
    assert "- Roadmap items: 24, date rebuilt from cell: 6" in text
    assert "| roadmap |" not in text.split("## Unverified items: reasons")[1].split("## Cache hit rate")[0]


@pytest.mark.parametrize("grid, header_rows, spans, item, reason", [
    # A quarterly value cited against its year header: the year is a period header, but not the lowest.
    ("quarters", 2, {(1, 2): 4}, dict(value=3000000, period="2025", cells=["r1c2"]), ("lowest-header rule", None)),
    # A month in its row and a year above it: the rules build no period from either.
    ([["", "2025"], ["Jan", "£1M"]], 1, None, dict(value=1000000, period="2025", cells=["r1c2"], cell="r2c2"),
     ("lowest-header rule", None)),
    ("quarters", 2, {(1, 2): 4}, dict(value=3000000, period="2025-Q3", cells=["r2c4"]), ("period not rebuilt", None)),
    ("quarters", 2, {(1, 2): 4}, dict(value=3000000, period="2025-Q3", cells=["r3c1"]), ("period not rebuilt", None)),
    ("quarters", 2, {(1, 2): 4}, dict(value=3000000, period="2025-Q3", cells=[]), ("period not rebuilt", None)),
    # The cells rebuild 2025-Q3, which replaces the model's year: a period corrected, verified.
    ("quarters", 2, {(1, 2): 4}, dict(value=3000000, period="2024-Q3", cells=["r2c4", "r1c2"]), None),
    ("quarters", 2, {(1, 2): 4}, dict(value=3100000, period="2025-Q3", cells=["r2c4", "r1c2"]),
     ("value not in cell", None)),
    ("quarters", 2, {(1, 2): 4}, dict(value=None, period="2025-Q3", cells=["r2c4", "r1c2"]), ("other", "no value")),
    ("quarters", 2, {(1, 2): 4}, dict(value=3100000, period="2025-Q3", cells=["r2c4", "r1c2"], metric="amount"),
     ("metric invalid", None)),
    ("quarters", 2, {(1, 2): 4},
     dict(value=3000000, period="2025-Q3", cells=["r2c4", "r1c2"], flags=["total_mismatch"]),
     ("other", "flag not reproduced")),
    ("quarters", 2, {(1, 2): 4}, dict(value=3000000, period="2025-Q3", cells=["r2c4", "r1c2"]), None),
])
def test_each_unverified_item_gets_the_first_reason_that_applies(grid, header_rows, spans, item, reason):
    import test_structure_verifier as v
    script = _consistency_script()
    if grid == "quarters":
        grid = [["", "2025", "", "", ""], ["", "Q1", "Q2", "Q3", "Q4"], ["Revenue", "$1M", "$2M", "$3M", "$4M"]]
    structure = v._struct(grid, header_rows=header_rows, spans=spans)
    sent = v._item(item["value"], item.get("cell", "r3c4"), item["period"], item["cells"],
                   metric=item.get("metric", "revenue"), flags=item.get("flags", ()))
    checked, = verify.verify(structure, [sent])["items"]
    assert (None if checked["status"] == verify.VERIFIED else script.unverified_reason(structure, checked)) == reason


@pytest.mark.parametrize("change, fields", [
    ({}, []),
    ({"value": 150000.0}, []),                                       # one number, written two ways
    ({"value_cell": "r4c9"}, ["cell"]),
    ({"metric": "sales"}, ["metric"]),
    ({"period": "2023"}, ["period"]),
    ({"value": 150001}, ["value"]),
    ({"unit": "USD"}, ["unit"]),
    ({"actual_or_forecast": "actual"}, ["other"]),
    ({"period_cells": []}, ["other"]),
    ({"proposed_flags": ["total_mismatch"]}, ["other"]),
    (None, ["cell", "items"]),                                       # left out in the second pass
])
def test_the_fields_that_differ_are_found_by_lining_items_up_by_value_cell(change, fields):
    script = _consistency_script()
    kept = {"metric": "revenue", "period": "FY2022", "value": 130550, "unit": "GBP", "actual_or_forecast": "forecast",
            "unit_other": None, "value_cell": "r4c2", "period_cells": ["r1c2"], "proposed_flags": []}
    item = {"metric": "revenue", "period": "FY2023", "value": 150000, "unit": "GBP", "actual_or_forecast": "forecast",
            "unit_other": None, "value_cell": "r4c3", "period_cells": ["r1c3"], "proposed_flags": []}
    second = [kept] if change is None else [kept, {**item, **change}]
    assert script.differing_fields([[kept, item], second, [kept, item]]) == fields


def test_two_passes_writing_other_with_different_codes_differ_in_unit():
    script = _consistency_script()
    zar = {"metric": "revenue", "period": "FY2023", "value": 150000, "unit": "other", "unit_other": "ZAR",
           "actual_or_forecast": "forecast", "value_cell": "r4c3", "period_cells": ["r1c3"], "proposed_flags": []}
    mxn = {**zar, "unit_other": "MXN"}
    assert script.differing_fields([[zar], [mxn], [zar]]) == ["unit"]
    assert script.differing_fields([[zar], [zar], [zar]]) == []
    assert script._item_key(zar) != script._item_key(mxn), "the old agreement key tells them apart too"


def _motor_without_a_server(monkeypatch, names, drop_fails=False):
    """Real motor: it binds a client to the event loop of the client's first call and runs every later call
    on that loop. Only the blocking pymongo call is answered here, so no MongoDB server is needed."""
    import motor.frameworks.asyncio as framework
    from pymongo.errors import AutoReconnect
    real, dropped = framework.run_on_executor, []

    def answer(sync_method, delegate, *args, **kwargs):
        if sync_method.__name__ == "list_database_names":
            return list(names)
        if sync_method.__name__ == "drop_database":
            if drop_fails:
                raise AutoReconnect("connection lost")
            dropped.append(args[0])
            return None
        raise AssertionError(f"unexpected server call {sync_method.__name__}")
    monkeypatch.setattr(framework, "run_on_executor", lambda loop, fn, *a, **k: real(loop, answer, fn, *a, **k))
    return dropped


def test_the_live_run_drops_its_scratch_database_in_the_event_loop_it_ran_in(monkeypatch, tmp_path, capsys):
    """`consistency_run.py --yes` crashed with "RuntimeError: Event loop is closed" at drop_database and wrote
    no report: motor had bound the client to the run's loop, which asyncio.run had closed."""
    pytest.importorskip("pdfplumber")
    import datetime
    script = _consistency_script()
    dropped = _motor_without_a_server(monkeypatch, ["consistency_run", "consistency_run_old", "growth_diligence"])
    run = script.run

    async def live_run(decks, passes, db, adapter=None, **kwargs):
        await db.client.list_database_names()            # a motor call binds the client to this loop, as an insert does
        return await run(decks, passes, script.MemoryDB(), script.FakeAdapter())     # no MongoDB, no live API
    monkeypatch.setattr(script, "run", live_run)
    monkeypatch.setattr(script, "REPORTS", tmp_path / "docs" / "test-runs")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    report = script.main(["--yes", "--deck", "05-zero2hero.pdf"])
    assert report["per_deck"]["05-zero2hero.pdf"]["structures"] == 5
    assert dropped == ["consistency_run", "consistency_run_old", "consistency_run"], \
        "leftovers of earlier runs at start, by name pattern; this run's own at the end; never another database"
    day = datetime.date.today().isoformat()
    path = tmp_path / "docs" / "test-runs" / f"consistency_{day}.md"
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["Dropped scratch database consistency_run left by an earlier run",
                       "Dropped scratch database consistency_run_old left by an earlier run"]
    assert [line.split(":")[0] for line in out[2:5]] == [f"[1/1] 05-zero2hero.pdf pass {n}/3" for n in (1, 2, 3)]
    assert all("5 of 5 structures read" in line for line in out[2:5]), "one progress line per deck and pass"
    assert out[5:7] == [f"Report: {path}", script.summary(report)], "the report path and a summary line"
    assert out[6].startswith("Agreement 100.0% (target 95.0%: met; old method 100.0%); verified 94.1%")
    text = path.read_text(encoding="utf-8")
    assert "\n".join(out[7:]) + "\n" == text, \
        "then the whole report: the file is untracked and lost on re-import, so it is copied from stdout"
    assert text.startswith(f"# Consistency run {day}\n\nLive API. Decks: 1. Passes: 3. Model: {gateway.STRUCTURE_MODEL}.")
    for line in ("| table | 100.0% |", "| kpi_panel | 100.0% |", "- Match rate: 94.1%", "| 2 | 100.0% |", "| 3 | 100.0% |",
                 "| 05-zero2hero.pdf | 5 | 15,000 | 300 |"):
        assert line in text, line
    script.main(["--yes", "--deck", "05-zero2hero.pdf"])
    assert path.read_text(encoding="utf-8") == text, "a later run the same day never overwrites a report"
    assert (path.parent / f"consistency_{day}-2.md").exists()
    del dropped[:]
    with pytest.raises(SystemExit, match="--db must be consistency_run"):
        script.main(["--yes", "--db", "growth_diligence"])
    assert dropped == [], "the run drops only a database it may clean up at the next start"


def test_a_failed_drop_keeps_the_paid_report(monkeypatch, tmp_path):
    """The report is written before the scratch database is dropped; the next run drops what is left."""
    pytest.importorskip("pdfplumber")
    from pymongo.errors import AutoReconnect
    script = _consistency_script()
    _motor_without_a_server(monkeypatch, [], drop_fails=True)
    run = script.run

    async def live_run(decks, passes, db, adapter=None, **kwargs):
        return await run(decks, passes, script.MemoryDB(), script.FakeAdapter())
    monkeypatch.setattr(script, "run", live_run)
    monkeypatch.setattr(script, "REPORTS", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    with pytest.raises(AutoReconnect):
        script.main(["--yes", "--deck", "05-zero2hero.pdf"])
    assert [p.name.split("_")[0] for p in tmp_path.iterdir()] == ["consistency"]


def test_a_live_run_writes_its_diagnostic_beside_the_report_before_the_drop(monkeypatch, tmp_path):
    pytest.importorskip("pdfplumber")
    import datetime
    from pymongo.errors import AutoReconnect
    script = _consistency_script()
    _motor_without_a_server(monkeypatch, [], drop_fails=True)
    run = script.run

    async def live_run(decks, passes, db, adapter=None, **kwargs):
        return await run(decks, passes, script.MemoryDB(), script.FakeAdapter(), diagnostic=kwargs["diagnostic"])
    monkeypatch.setattr(script, "run", live_run)
    monkeypatch.setattr(script, "REPORTS", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    with pytest.raises(AutoReconnect):
        script.main(["--yes", "--diagnostic", "--deck", "05-zero2hero.pdf"])
    day = datetime.date.today().isoformat()
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"consistency_{day}.md", f"consistency_{day}_diagnostic.md"]
    assert "£ 250,000" in (tmp_path / f"consistency_{day}_diagnostic.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Provider errors: the HTTP status and error type are recorded, 429 and 529 are retried
# ---------------------------------------------------------------------------
CELL_MESSAGE = "cannot read cell 'Jane Doe (CEO)'"


def _sdk_error(status, error_type, retry_after=None):
    """The error the Anthropic SDK raises for this HTTP status. Its message and body quote a cell, as a provider
    message may: neither reaches a log or llm_calls."""
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    headers = {} if retry_after is None else {"retry-after": str(retry_after)}
    response = httpx2.Response(status, headers=headers,
                               request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    body = {"type": "error", "error": {"type": error_type, "message": CELL_MESSAGE}}
    return anthropic.Anthropic(api_key="test")._make_status_error(CELL_MESSAGE, body=body, response=response)


class _Failing(t.FakeAdapter):
    """Raises `errors` from complete() and `count_errors` from count_tokens() in turn, then replays REPLY."""

    def __init__(self, errors=(), count_errors=()):
        super().__init__(replies=[json.dumps(REPLY)])
        self.errors, self.count_errors = list(errors), list(count_errors)

    def complete(self, **kwargs):
        if self.errors:
            self.calls += 1
            raise self.errors.pop(0)
        return super().complete(**kwargs)

    def count_tokens(self, **kwargs):
        if self.count_errors:
            raise self.count_errors.pop(0)
        return super().count_tokens(**kwargs)


def _read_slept(db, adapter):
    """read_structure with a sleep that records the backoff instead of waiting."""
    slept = []

    async def sleep(seconds):
        slept.append(seconds)
    return asyncio.run(gateway.read_structure(db, AUDIT, TEXT, "table", adapter=adapter, sleep=sleep)), slept


def test_a_provider_error_is_logged_and_recorded_with_its_http_status_and_type(caplog):
    """The live consistency run logged "reason=provider_error" and 0 tokens for every call after the first deck,
    and nothing said why. The not-read line and the llm_calls record carry the HTTP status and the provider's
    error type, for the call and for the token count before it; the message is never read."""
    import logging
    db = _db()
    with caplog.at_level(logging.INFO):
        result, slept = _read_slept(db, adapter := _Failing([_sdk_error(400, "invalid_request_error")]))
    assert (result.status, adapter.calls, slept) == ("not_read", 1, []), "a 400 is not retried"
    call, = db["llm_calls"].docs
    assert (call["status"], call["http_status"], call["error_type"]) == ("provider_error", 400, "invalid_request_error")
    assert "tokens=0/0 cost=0.000000 reason=provider_error status=400 type=invalid_request_error" in caplog.text

    db = _db()
    with caplog.at_level(logging.INFO):
        result, _ = _read_slept(db, adapter := _Failing(count_errors=[_sdk_error(403, "permission_error")]))
    assert (result.status, adapter.calls) == ("not_read", 0)
    call, = db["llm_calls"].docs
    assert (call["status"], call["http_status"], call["error_type"], call["input_tokens"], call["cache_hit"]) == \
        ("provider_error", 403, "permission_error", 0, False), "a failed token count is recorded too"
    assert "reason=provider_error status=403 type=permission_error" in caplog.text
    assert "Jane Doe" not in caplog.text + json.dumps(db["llm_calls"].docs)


def test_429_and_529_are_retried_three_times_honouring_retry_after(caplog):
    """A burst of rate limits or overloads does not fail the structure: 3 attempts, each wait the longer of the
    backoff (1 s, 2 s) and the provider's retry-after, at most RETRY_AFTER_MAX_SECONDS so the lock (300 s) cannot
    expire mid-call. The token count is retried the same way."""
    import logging
    burst = [_sdk_error(429, "rate_limit_error", retry_after=7), _sdk_error(529, "overloaded_error")]
    result, slept = _read_slept(_db(), adapter := _Failing(burst))
    assert (result.status, adapter.calls, slept) == ("read", 3, [7.0, 2.0]), "retry-after 7 s, then the 2 s backoff"

    db = _db()
    with caplog.at_level(logging.INFO):
        result, slept = _read_slept(db, adapter := _Failing([_sdk_error(429, "rate_limit_error", retry_after=600)] * 3))
    assert (result.status, adapter.calls) == ("not_read", 3)
    assert slept == [gateway.RETRY_AFTER_MAX_SECONDS] * 2 == [20.0, 20.0]
    assert 4 * gateway.REQUEST_TIMEOUT_SECONDS + 2 * gateway.RETRY_AFTER_MAX_SECONDS < guards.LOCK_TTL_SECONDS, \
        "the worst call under the lock (4 attempts at the timeout, 2 capped waits) fits in it"
    call, = db["llm_calls"].docs
    assert (call["status"], call["http_status"], call["error_type"]) == ("provider_unreachable", 429, "rate_limit_error")
    assert "reason=provider_unreachable status=429 type=rate_limit_error" in caplog.text

    result, slept = _read_slept(_db(), _Failing(count_errors=[_sdk_error(429, "rate_limit_error", retry_after=5)]))
    assert (result.status, slept) == ("read", [5.0])


def test_the_consistency_run_logs_one_not_read_line_per_structure_and_pass(caplog):
    """On passes 2 and 3 each "structure not read" line printed twice: the lookup that counts cache hits called
    the model when the cache missed, then the call with the cache bypassed did again. The lookup reads the cache
    only, so a failed structure is sent once per pass, and its line names the HTTP status and error type."""
    pytest.importorskip("pdfplumber")
    import logging
    script = _consistency_script()

    class Failing(script.FakeAdapter):
        calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            raise _sdk_error(400, "invalid_request_error")
    adapter = Failing()
    with caplog.at_level(logging.WARNING):
        report = asyncio.run(script.run(["05-zero2hero.pdf"], 3, script.MemoryDB(), adapter))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("structure not read:")]
    assert (adapter.calls, len(lines), report["not_read"]) == (15, 15, 15), "5 structures, 3 passes, once each"
    assert all(line.endswith("reason=provider_error status=400 type=invalid_request_error") for line in lines)
    assert report["cache_hit_rate_pct"] == {"pass_2": 0.0, "pass_3": 0.0}


def test_one_provider_error_does_not_stop_the_calls_after_it_in_the_deck_or_the_next():
    """The circuit breaker (spec section 7: the per-audit lock, the daily spend cap, the retry policy) does not open
    on an error: after a failed call the next structure and the next deck are still sent. Each deck is read in its
    own audit, so it has its own lock, and the lock is released after every call."""
    pytest.importorskip("pdfplumber")
    script = _consistency_script()

    class OnceFailing(script.FakeAdapter):
        failed = False

        def complete(self, **kwargs):
            if not self.failed:
                self.failed = True
                raise _sdk_error(400, "invalid_request_error")
            return super().complete(**kwargs)
    db = script.MemoryDB()
    report = asyncio.run(script.run(["05-zero2hero.pdf", "10-tea.pdf"], 1, db, OnceFailing()))
    assert (report["not_read"], report["model_reads"]) == (1, 8), "the first of 5 + 3 structures only"
    locks = db[guards.LOCKS_COLLECTION].docs
    assert len(locks) == 2 and not any(lock["held"] for lock in locks), "one lock per deck, none left held"


def test_the_consistency_run_pauses_between_structure_calls(monkeypatch, tmp_path):
    """--pause (default 2 s) waits between structure calls, not after the last; --fake does not wait."""
    pytest.importorskip("pdfplumber")
    script = _consistency_script()
    slept = []

    async def sleep(seconds):
        slept.append(seconds)
    asyncio.run(script.run(["05-zero2hero.pdf"], 3, script.MemoryDB(), script.FakeAdapter(), pause=2.0, sleep=sleep))
    assert slept == [2.0] * 14, "between the 15 structure calls"

    _motor_without_a_server(monkeypatch, [])
    run, pauses = script.run, []

    async def live_run(decks, passes, db, adapter=None, **kwargs):
        pauses.append(kwargs["pause"])
        return await run(decks, passes, script.MemoryDB(), script.FakeAdapter())
    monkeypatch.setattr(script, "run", live_run)
    monkeypatch.setattr(script, "REPORTS", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    script.main(["--yes", "--deck", "05-zero2hero.pdf"])
    script.main(["--yes", "--deck", "05-zero2hero.pdf", "--pause", "0.5"])
    assert pauses == [2.0, 0.5]


# ---------------------------------------------------------------------------
# --diagnostic: the cell text behind each unverified item and disagreeing structure, public test decks only
# ---------------------------------------------------------------------------
def _seen(metric, value, unit, period, verifier):
    return {"metric": metric, "value": value, "unit": unit, "period": period, "verifier": verifier}


def test_the_diagnostic_gives_the_cell_text_and_every_pass_of_each_unverified_item_and_disagreeing_structure(
        tmp_path):
    """The report names a cell, not what it says. --diagnostic adds, for every unverified item and every
    disagreeing structure: deck, page, cell id, the cell's text as sent to the model, the model's metric, value,
    unit and period in each pass, and the verifier's result for each (verified or the reason), in a file of its own
    beside the report. The report and its JSON keys are unchanged."""
    pytest.importorskip("pdfplumber")
    script = _consistency_script()
    rows = []
    report = asyncio.run(script.run(["05-zero2hero.pdf"], 3, script.MemoryDB(), _drifting(script)(), diagnostic=rows))
    assert report == asyncio.run(script.run(["05-zero2hero.pdf"], 3, script.MemoryDB(), _drifting(script)())), \
        "the report is the same with or without the diagnostic"
    where = {"deck": "05-zero2hero.pdf", "page": 19, "type": "table"}
    flagged = _seen("gross_profit", 50000, "GBP", "FY2023", "other (flag not reproduced)")
    users = _seen("users", 200, "count", "FY2022", "period not rebuilt")
    shared = [_seen("revenue", 250000, "GBP", "FY2024", "verified"),
              _seen("users", 20000, "count", "FY2024", "value not in cell")]
    assert [r for r in rows if r["section"] == "unverified"] == [
        {**where, "section": "unverified", "cell": "r6c3", "cell_text": "£ 50,000",
         "reason": "other (flag not reproduced)", "passes": [[flagged]] * 3},
        {**where, "section": "unverified", "cell": "r2c2", "cell_text": "200", "reason": "period not rebuilt",
         "passes": [[users]] * 3},
        {**where, "section": "unverified", "cell": "r4c4", "cell_text": "£ 250,000", "reason": "value not in cell",
         "passes": [shared] * 3}], "every item citing the cell, in each pass, with the verifier's result"
    assert [r for r in rows if r["section"] == "disagreeing"] == [
        {**where, "section": "disagreeing", "cell": "r4c3", "cell_text": "£ 150,000", "reason": None,
         "passes": [[_seen("revenue", 150000, "GBP", "FY2023", "verified")],
                    [_seen("revenue", 150000, "USD", "FY2023", "verified")],
                    [_seen("revenue", 150000, "GBP", "2023", "verified")]]},
        {**where, "type": "kpi_panel", "section": "disagreeing", "cell": "r3c1", "cell_text": "5K Users",
         "reason": None, "passes": [[_seen("users", 5000, "count", "FY2023", "verified")]] * 2 + [[]]}], \
        "the cells whose readings differ between passes, as the model wrote them"

    path = script.write_report(report, tmp_path, 3, fake=True)
    rows.append({**where, "section": "unverified", "cell": "r9c9", "cell_text": "Plan | B\nnext", "reason": "other",
                 "passes": [None, [], [_seen("product", None, None, None, "other (no value)")]]})
    diagnostic = script.write_diagnostic(rows, path, 3)
    assert diagnostic == tmp_path / f"{path.stem}_diagnostic.md", "beside its report, named after it"
    text = diagnostic.read_text(encoding="utf-8")
    for line in (
            f"# Consistency run {path.stem.split('_', 1)[1]}: diagnostic",
            "| Deck | Page | Type | Cell | Cell text | Reason | Pass 1 | Pass 2 | Pass 3 |",
            "| 05-zero2hero.pdf | 19 | table | r4c4 | £ 250,000 | value not in cell | "
            + " | ".join(["revenue 250000 GBP FY2024: verified; users 20000 count FY2024: value not in cell"] * 3)
            + " |",
            "| 05-zero2hero.pdf | 19 | table | r9c9 | Plan \\| B next | other | not read | no item | product null null "
            "null: other (no value) |",
            "| Deck | Page | Type | Cell | Cell text | Pass 1 | Pass 2 | Pass 3 |",
            "| 05-zero2hero.pdf | 19 | table | r4c3 | £ 150,000 | revenue 150000 GBP FY2023: verified | "
            "revenue 150000 USD FY2023: verified | revenue 150000 GBP 2023: verified |",
            "| 05-zero2hero.pdf | 19 | kpi_panel | r3c1 | 5K Users | users 5000 count FY2023: verified | users 5000 "
            "count FY2023: verified | no item |"):
        assert line in text.splitlines(), line
    report_text = path.read_text(encoding="utf-8")
    assert "5K Users" not in report_text and "£ 250,000" not in report_text, "the report itself holds no cell text"


def test_the_diagnostic_runs_only_on_the_10_public_test_decks(monkeypatch, tmp_path, capsys):
    """--diagnostic writes cell text, so it refuses any deck that is not one of the 10 public test decks, by file
    name and SHA-256: another file in the folder, a public name holding other bytes, a path to a public deck. It
    refuses before anything is read, sent or written; without --diagnostic every deck runs as before."""
    pytest.importorskip("pdfplumber")
    import hashlib
    import shutil
    import tempfile
    script = _consistency_script()
    on_disk = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in DECKS.iterdir() if not p.name.startswith(".")}
    assert script.PUBLIC_DECKS == on_disk and len(on_disk) == 10, "the 10 decks of the folder, byte for byte"
    folder, temp = tmp_path / "decks", tmp_path / "temp"
    folder.mkdir()
    temp.mkdir()
    shutil.copy(DECKS / "05-zero2hero.pdf", folder / "05-zero2hero.pdf")
    shutil.copy(DECKS / "05-zero2hero.pdf", folder / "client-deck.pdf")
    (folder / "10-tea.pdf").write_bytes((DECKS / "10-tea.pdf").read_bytes() + b"\n")
    monkeypatch.setattr(script, "DECKS", folder)
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    for deck in ("client-deck.pdf", "10-tea.pdf", "../decks/05-zero2hero.pdf", str(folder / "05-zero2hero.pdf")):
        with pytest.raises(SystemExit, match=f"--diagnostic runs on the 10 public test decks only: {deck} is not one"):
            script.main(["--fake", "--diagnostic", "--deck", "05-zero2hero.pdf", "--deck", deck])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="public test decks only: client-deck.pdf"):
        script.main(["--yes", "--diagnostic", "--deck", "client-deck.pdf"])
    assert not any(temp.iterdir()), "refused before anything is written"
    script.main(["--fake", "--deck", "client-deck.pdf"])
    assert [p.name.endswith("_diagnostic.md") for p in temp.iterdir()] == [False], "without --diagnostic, as before"
    capsys.readouterr()

    script.main(["--fake", "--diagnostic", "--deck", "05-zero2hero.pdf"])
    out = capsys.readouterr().out
    diagnostic, = temp.glob("consistency_*_diagnostic.md")
    assert diagnostic.with_name(diagnostic.name.replace("_diagnostic", "")).exists()
    assert f"Diagnostic: {diagnostic}" in out.splitlines(), "its path is printed"
    assert "£ 250,000" in diagnostic.read_text(encoding="utf-8") and "£ 250,000" not in out, \
        "its cell text is not: stdout carries the report only"


# ---------------------------------------------------------------------------
# Leftover risks closed in this change
# ---------------------------------------------------------------------------
def test_a_background_failure_marks_the_deck_not_read_and_logs_the_error_type_only(monkeypatch, caplog):
    import logging
    client, db, adapter = _deck_api(monkeypatch)

    async def boom(*args, **kwargs):
        raise RuntimeError("cannot read cell 'Jane Doe (CEO)'")
    monkeypatch.setattr(structures, "process_deck", boom)
    with caplog.at_level(logging.INFO):
        _upload_deck(client)
    assert _deck(client)["decks"][0]["ai_status"] == "not_read", "never left 'reading'"
    assert "structure reading failed: run_id=audit-s" in caplog.text and "error=RuntimeError" in caplog.text
    assert "Jane Doe" not in caplog.text


def test_a_short_engagement_reference_is_withheld_as_a_word_and_never_inside_one():
    db = _db(engagement_reference="E7")
    result, adapter = _read(db, "r1c1: Plan E7\nr1c2: £1M")
    assert (result.reason, adapter.calls) == ("refused: engagement_reference", 0), "sent as written, it is refused"
    cells, _ = redact.redact_structure([{"row": 1, "col": 1, "text": "Plan E7"}, {"row": 1, "col": 2, "text": "£1M"}],
                                       "Zero2Hero", {}, redact.withheld_values(db["audits"].docs[0]))
    result, adapter = _read(db, redact.structure_text(cells), replies=[{"type": "table", "items": []}])
    assert result.status == "read" and json.loads(adapter.payloads[0])["text"] == "r1c1: Plan [redacted]\nr1c2: £1M"
    result, adapter = _read(db, "r1c1: Plan E70\nr1c2: £1M", replies=[{"type": "table", "items": []}])
    assert result.status == "read", "E70 is not the reference"


def test_ordinary_text_with_a_dot_is_not_taken_for_a_file_name():
    result, _ = _read(_db(), "r1c1: 2.key metrics\nr1c2: £1M", replies=[{"type": "table", "items": []}])
    assert result.status == "read"
    result, adapter = _read(_db(), "r1c1: See plan_v2.xlsx\nr1c2: £1M")
    assert result.status == "refused" and adapter.calls == 0


def test_a_metric_must_belong_to_the_kind_of_structure_read():
    deck_reply = {"type": "table", "items": [{**REPLY["items"][0], "metric": "invoice_date"}]}
    result, adapter = _read(_db(), replies=[deck_reply, deck_reply])
    assert result.status == "not_read" and adapter.calls == 2, "a spreadsheet field is not a deck claim"
    mapping_reply = {"type": "column_mapping", "items": [{**MAPPING_REPLY["items"][0], "metric": "revenue_growth"}]}
    result, adapter = _read(_db(), "r1c1: Customer\nr1c2: Amount\nc2 sample: 1200", "column_mapping",
                            replies=[mapping_reply, mapping_reply])
    assert result.status == "not_read" and adapter.calls == 2, "a claim type is not a spreadsheet field"
    both = {"type": "column_mapping", "items": [{**MAPPING_REPLY["items"][0], "metric": "revenue", "value_cell": "r1c2"}]}
    result, _ = _read(_db(), "r1c1: Customer\nr1c2: Revenue\nc2 sample: 1200", "column_mapping", replies=[both])
    assert result.status == "read", "revenue is a P&L field and a claim type"


def test_an_edited_ai_row_keeps_the_label_under_parsed_never_next_to_the_analysts_value(monkeypatch):
    client, db, adapter = _deck_api(monkeypatch)
    _map_revenue(client)
    _upload_deck(client)
    row = next(c for c in _deck(client)["candidates"] if c.get("ai_label") == "Verified")
    edited = client.put(f"/api/audits/{AUDIT}/decks/candidates/{row['id']}", json={"value": 1}).json()
    assert edited["status"] == "edited" and edited["ai_label"] is None
    assert edited["parsed"]["ai_label"] == "Verified" and edited["parsed"]["value"] == row["value"]


def test_every_structure_refusal_reason_in_the_code_is_declared_in_the_boundary_test():
    import ast as _ast
    import test_gateway_data_boundary as boundary
    found = set()
    for path, function in ((BACKEND / "app" / "llm" / "gateway.py", "structure_text_problem"),
                           (BACKEND / "app" / "structures" / "redact.py", "column_text_problem")):
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        body = next(n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef) and n.name == function)
        found |= {n.value.value for n in _ast.walk(body) if isinstance(n, _ast.Return)
                  and isinstance(n.value, _ast.Constant) and isinstance(n.value.value, str)}
        found |= {"client_name", "engagement_reference"} if function == "structure_text_problem" else set()
    assert found == boundary.STRUCTURE_REFUSALS, "a new refusal reason is declared in test_gateway_data_boundary.py"
