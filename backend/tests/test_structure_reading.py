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

from app.llm import gateway, guards, redaction  # noqa: E402
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
     "value_cell": "r2c2", "period_cells": ["r1c2"], "proposed_flags": []}]}


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


def test_a_structure_over_3000_input_tokens_is_not_sent():
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    adapter.input_tokens = 3001
    result, _ = _read(_db(), adapter=adapter)
    assert (result.status, result.reason, adapter.calls) == ("too_large", "Too large for AI reading", 0)


def test_the_200000_token_cap_counts_billed_input_and_output_and_stops_with_the_spec_message():
    db = _db()
    db["llm_calls"].docs.append({"run_id": AUDIT, "step": "structures", "cache_hit": False, "input_tokens": 190000,
                                 "output_tokens": 4000, "estimated_cost_usd": 0.0, "timestamp": "2026-10-05T00:00:00"})
    adapter = t.FakeAdapter(replies=[json.dumps(REPLY)])
    adapter.input_tokens = 2001            # 194,000 used + 2,001 input + 4,000 max_tokens > 200,000
    result, _ = _read(db, adapter=adapter)
    assert result.status == "stopped" and adapter.calls == 0
    assert result.reason == ("AI reading stopped: this audit reached its 200,000-token limit. The remaining "
                             "structures were read by Python only.")
    adapter.input_tokens = 2000            # exactly at the cap: the call goes out
    result, _ = _read(db, adapter=adapter)
    assert result.status == "read" and adapter.calls == 1


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
    assert usage.calls == 0 and usage.structure_calls == 1 and usage.structure_token_cap == 200000
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
     "period_cells": [], "proposed_flags": []}
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
