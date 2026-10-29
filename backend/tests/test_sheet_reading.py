"""The sheet reader through the gateway (docs/design/read-check-review.md sections 3, 8, 9; CLAUDE.md rule 16 as amended for PR 2).

One model call per spreadsheet; every non-empty cell of every recognised sheet, masked by the one module (name learning included); the
prompt `sheet_reading` from the store (a test stub here); a dated model only; the reading stored once and served to the same file in any
audit with no second call. Synthetic data only; the fake adapter counts calls and no test can reach a provider."""
import asyncio
import copy
import json
import logging
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import test_llm_gateway as t  # noqa: E402
from app import readings  # noqa: E402
from app.llm import gateway, redaction  # noqa: E402
from app.structures import redact  # noqa: E402

MODEL = "claude-sonnet-5-5-20260101"
COMPANY = "Orchid Test Co"
EMAIL = "pat.sample@orchid-example.test"
HASH = "a" * 64
CELLS = [
    {"row": 1, "col": 1, "text": f"{COMPANY} monthly report, EUR"},
    {"row": 2, "col": 1, "text": "Metric"}, {"row": 2, "col": 2, "text": "Jan-24"}, {"row": 2, "col": 3, "text": "Feb-24"},
    {"row": 2, "col": 5, "text": "Owner"},
    {"row": 3, "col": 1, "text": "Revenue"}, {"row": 3, "col": 2, "text": "447223.43"}, {"row": 3, "col": 3, "text": "451000"},
    {"row": 3, "col": 5, "text": "Pat Sample"},
    {"row": 4, "col": 1, "text": f"Contact: {EMAIL}"},
    {"row": 5, "col": 1, "text": "Customers"}, {"row": 6, "col": 1, "text": "Zenith Retail Ltd"}, {"row": 6, "col": 2, "text": "12"},
    {"row": 7, "col": 1, "text": "Revenue"}, {"row": 7, "col": 2, "text": "0.0123456789"},
]
TEXT = redact.reading_text([{"name": f"{COMPANY} report", "cells": CELLS}])


def file_map(**over):
    row = {"row": 3, "label_cell": "A3", "role": "revenue", "metric": "revenue", "basis": "monthly", "actual_plan": "mixed",
           "boundary_col": "B", "segment": None, "parent_row": None, "unit": "money", "currency": "EUR", "cells": "B3:C3",
           "variance_of": None, "by_column": False, "evidence": "Revenue row"}
    sheet = {"sheet": "Client-01 report", "header_row": 2, "label_col": "A", "first_period_col": "B", "last_period_col": "C",
             "granularity": "monthly", "currency": "EUR", "currency_cell": "A1",
             "last_actual": {"column": "B", "period": "2024-01", "evidence": []}, "rows": [row]}
    return {"map_version": 1, "kind": "sheet", "sheets": [sheet], "figures": [], **over}


def audit_db(audit="a1", consent=True, company=COMPANY):
    db = t.FakeDB()
    db["audits"].docs.append({"id": audit, "company_name": company, "structure_reading_consent": consent, "fiscal_year_end": 12})
    return db


@pytest.fixture(autouse=True)
def reader_env(monkeypatch):
    monkeypatch.setenv("SHEET_READER_MODEL", MODEL)
    monkeypatch.delenv("READER_V1", raising=False)


def read(db, audit="a1", adapter=None, text=TEXT, file_hash=HASH, **kwargs):
    adapter = adapter or t.FakeAdapter(replies=[json.dumps(file_map())])
    result = asyncio.run(gateway.read_structure(db, audit, text, "sheet_reading", adapter=adapter, sleep=t._noop_sleep, file_hash=file_hash,
                                                **kwargs))
    return result, adapter


def test_one_call_per_spreadsheet_with_the_store_prompt_and_the_dated_model():
    db = audit_db()
    result, adapter = read(db)
    assert result.status == "read" and adapter.calls == 1
    request = adapter.requests[0]
    assert request["model"] == MODEL
    assert request["system"] == next(d["text"] for d in db["prompts"].docs if d["name"] == "sheet_reading"), "the prompt comes from the store"
    assert request["json_schema"]["required"] == ["map_version", "kind", "sheets", "figures"]
    assert result.file_map["sheets"][0]["rows"][0]["role"] == "revenue" and result.model == MODEL and result.prompt_version == "v1"


def test_no_prompt_text_in_the_repository_for_the_sheet_reader():
    source = (BACKEND / "app" / "llm" / "gateway.py").read_text(encoding="utf-8")
    assert "sheet_reading" in source and "You are" not in source.split("SHEET_READING_PROMPT")[1][:400]
    stub = (BACKEND / "tests" / "fixtures" / "prompts" / "sheet_reading.md").read_text(encoding="utf-8")
    assert "TEST ONLY" in stub and len(stub) < 300


def test_the_payload_is_every_cell_masked_and_nothing_else():
    db = audit_db()
    result, adapter = read(db)
    sent = json.loads(adapter.payloads[0])
    assert sent["type"] == "sheet_reading" and set(sent) == {"type", "text"}
    lines = sent["text"].split("\n")
    assert lines[0] == "sheet 1: Client-01 report"
    assert len(lines) == 1 + len(CELLS), "every non-empty cell, none sampled, none cut"
    for secret in (COMPANY, "Orchid", EMAIL, "Pat Sample", "Zenith"):
        assert secret not in sent["text"], f"{secret!r} reached the provider"
    assert "A1: Client-01 monthly report, EUR" in lines and "E3: [person]" in lines and "A6: Client-02" in lines
    assert "A4: Contact: [email]" in lines and "A3: Revenue" in lines, "a metric label is not a person, whatever column it stands in"
    assert "B3: 447223.43" in lines and "B7: 0.0123456789" in lines, "a figure goes as it stands"
    assert result.masked["lines"] == len(CELLS) and result.masked["people_columns"] == 1 and result.masked["company"] >= 2


def test_a_revenue_label_under_a_customers_title_goes_out_unchanged_and_a_company_name_is_learned():
    db = audit_db()
    read(db)
    tokens = redaction_map(db)
    assert tokens.get("Zenith Retail Ltd") == "Client-02" and "Revenue" not in tokens and "Customers" not in tokens
    sent = json.loads(read(db, "a1", file_hash="b" * 64)[1].payloads[0])["text"]
    assert "A3: Revenue" in sent and "A7: Revenue" in sent and "A5: Customers" in sent


def redaction_map(db):
    return asyncio.run(redaction.get_map(db, "a1"))


def test_the_same_file_in_any_audit_gets_the_stored_reading_with_no_second_call():
    db = audit_db()
    db["audits"].docs.append({"id": "a2", "company_name": COMPANY, "structure_reading_consent": True})
    first, adapter = read(db, "a1")
    again, second = read(db, "a2", adapter=adapter)
    assert adapter.calls == 1, "the second upload made no provider call"
    assert again.status == "read" and again.cache_hit is True
    assert again.file_map == first.file_map, "the stored reading, in this audit's masked space"
    assert len(db[readings.READINGS].docs) == 1 and len(db[readings.USES].docs) == 2
    assert [c["cache_hit"] for c in db["llm_calls"].docs] == [False, True]
    assert db["llm_calls"].docs[1]["input_tokens"] == 0


def test_a_new_prompt_version_or_model_is_a_new_reading_beside_the_old_one(monkeypatch):
    from app.llm import prompt_store
    db = audit_db()
    _, adapter = read(db)
    asyncio.run(prompt_store.upload(db, "sheet_reading", "TEST ONLY second version"))
    read(db, adapter=adapter)
    assert adapter.calls == 2 and {d["prompt_version"] for d in db[readings.READINGS].docs} == {"v1", "v2"}
    monkeypatch.setenv("SHEET_READER_MODEL", "claude-opus-5-5-20260401")
    read(db, adapter=adapter)
    assert adapter.calls == 3 and len(db[readings.READINGS].docs) == 3


def test_the_stored_reading_has_the_names_restored_and_the_checks_get_it_masked_for_the_audit():
    db = audit_db()
    read(db)
    stored = db[readings.READINGS].docs[0]["file_map"]
    assert stored["sheets"][0]["sheet"] == f"{COMPANY} report", "display un-masks on the server"
    assert "Client-01" not in json.dumps(stored)
    other = audit_db("a9")
    result, _ = read(other, "a9")
    assert result.status == "read" and result.cache_hit is False


@pytest.mark.parametrize("model", ["", "latest", "claude-sonnet-latest", "claude-sonnet-5-5", "claude-opus-5-5", "sonnet",
                                   "claude-haiku-4-5-20251001", "claude-sonnet-5-5-2026", "claude-sonnet-5-5-20260101-latest"])
def test_a_model_that_is_not_a_dated_sonnet_or_opus_version_is_refused_before_anything_is_sent(monkeypatch, model):
    monkeypatch.setenv("SHEET_READER_MODEL", model)
    db = audit_db()
    result, adapter = read(db)
    assert result.status == "blocked" and result.reason == gateway.SHEET_READER_BLOCKED
    assert adapter.calls == 0 and not getattr(adapter, "counted", 0), "no token count either: nothing left the server"
    assert not db[readings.READINGS].docs and not db["llm_calls"].docs
    assert "token_map" not in db["audits"].docs[0], "not even the masking ran"


@pytest.mark.parametrize("model", ["claude-sonnet-5-5-20260101", "claude-opus-5-5-20260401", "claude-sonnet-5-20260101"])
def test_a_dated_sonnet_or_opus_version_is_accepted_and_priced_as_its_family(monkeypatch, model):
    monkeypatch.setenv("SHEET_READER_MODEL", model)
    assert gateway.sheet_reader_problem() is None
    assert gateway.estimate_cost_usd(model, 1_000_000, 0) == gateway.estimate_cost_usd(gateway.price_model(model), 1_000_000, 0) > 0


def test_the_gateway_names_no_latest_alias_and_no_default_reader_model():
    source = (BACKEND / "app" / "llm" / "gateway.py").read_text(encoding="utf-8")
    assert not re.search(r"claude-(?:sonnet|opus)[\w-]*latest", source) and '"latest"' not in source
    assert gateway.DATED_READER_MODEL.fullmatch("claude-sonnet-5-5-20260101") and not gateway.DATED_READER_MODEL.fullmatch("claude-sonnet-5-5")


def test_a_file_over_the_limit_is_refused_with_a_message_and_nothing_is_cut_or_sent():
    db = audit_db()
    adapter = t.FakeAdapter()
    adapter.text_tokens = gateway.SHEET_READING_INPUT_CAP + 1
    result, adapter = read(db, adapter=adapter)
    assert result.status == "too_large" and "too large to read in full" in result.reason and f"{gateway.SHEET_READING_INPUT_CAP:,}" in result.reason
    assert adapter.calls == 0 and not db[readings.READINGS].docs
    ok = t.FakeAdapter(replies=[json.dumps(file_map())])
    ok.text_tokens = gateway.SHEET_READING_INPUT_CAP
    assert read(audit_db(), adapter=ok)[0].status == "read", "exactly at the limit is read in full"


def test_a_reply_cut_at_max_tokens_says_the_file_has_too_many_rows_and_stores_nothing():
    class Cut(t.FakeAdapter):
        def complete(self, **kw):
            self.calls += 1
            error = gateway.GatewayError("truncated", "cut")
            error.tokens = (100, 16000)
            raise error
    db = audit_db()
    result, _ = read(db, adapter=Cut())
    assert result.status == "truncated" and result.reason == gateway.SHEET_READING_CUT and not db[readings.READINGS].docs


def test_no_consent_no_hash_and_no_prompt_send_nothing():
    for kwargs, db_, status in ((dict(), audit_db(consent=False), "no_consent"), (dict(file_hash=None), audit_db(), "not_read")):
        result, adapter = read(db_, **kwargs)
        assert result.status == status and adapter.calls == 0
    db = audit_db()
    db["prompts"].docs[:] = [d for d in db["prompts"].docs if d["name"] != "sheet_reading"]
    result, adapter = read(db)
    assert result.status == "not_read" and adapter.calls == 0


def test_a_reply_naming_a_sheet_that_was_not_sent_is_a_parse_failure_and_the_cell_checks_are_not_the_gateways():
    bad = file_map()
    bad["sheets"][0]["sheet"] = "Another sheet"
    result, adapter = read(audit_db(), adapter=t.FakeAdapter(replies=[json.dumps(bad)]))
    assert result.status == "not_read" and adapter.calls == 2, "one reask, then not read"
    far = file_map()
    far["sheets"][0]["rows"][0]["cells"] = "B3:ZZ99"
    assert read(audit_db(), adapter=t.FakeAdapter(replies=[json.dumps(far)]))[0].status == "read", "a citation outside the sheet is a check's rejection"


def test_nothing_sent_reaches_the_call_log_or_the_log_lines(caplog):
    caplog.set_level(logging.DEBUG)
    db = audit_db()
    db["audits"].docs.append({"id": "a2", "company_name": COMPANY, "structure_reading_consent": True})
    _, adapter = read(db)
    read(db, "a2", adapter=adapter)                          # the stored reading, served to another audit: its call record is logged too
    assert [c["cache_hit"] for c in db["llm_calls"].docs] == [False, True]
    blob = json.dumps(db["llm_calls"].docs, default=str) + "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("Zenith", "Pat Sample", EMAIL, "447223", "Orchid", "Revenue"):
        assert secret not in blob
    sent = json.loads(adapter.payloads[0])["text"].split("\n")
    assert not [line for line in sent if line in blob] and "sheet 1:" not in blob, "not even the masked text of the cells is logged"
    assert db["llm_calls"].docs[0]["structure_type"] == "sheet_reading" and db["llm_calls"].docs[0]["status"] == "ok"
    assert "llm_structures" not in {n for n, c in db._cols.items() if c.docs}, "the reading lives in `readings`, not beside the structure cache"


def test_the_old_mapping_calls_stay_on_by_default_and_go_off_with_reader_v1_off(monkeypatch):
    refused = ("file_type", "file_recognition", "sheet_structure", "column_mapping")
    assert gateway.reader_v1_enabled() is True
    for value in ("", "on", "ON", "anything"):
        monkeypatch.setenv("READER_V1", value)
        assert gateway.reader_v1_enabled() is True
    monkeypatch.setenv("READER_V1", "off")
    assert gateway.reader_v1_enabled() is False
    for kind in refused:
        adapter = t.FakeAdapter()
        result = asyncio.run(gateway.read_structure(audit_db(), "a1", "r1c1: Revenue", kind, adapter=adapter, sleep=t._noop_sleep))
        assert result.status == "not_read" and adapter.calls == 0, kind
    assert read(audit_db())[0].status == "read", "the new reader is not behind the flag"


def test_a_second_reading_of_rejected_items_is_stored_beside_the_first_and_made_once():
    db = audit_db()
    first, adapter = read(db)
    items = [{"item": "figures:Client-01 report:B3:revenue", "reason": "Reading says 5; cell B3 holds 447223.43."}]
    again = {"map_version": 1, "kind": "sheet", "sheets": [], "figures": []}
    adapter = t.FakeAdapter(replies=[json.dumps(again)])
    a, adapter = read(db, adapter=adapter, recheck=items)
    assert a.status == "read" and adapter.calls == 1
    assert json.loads(adapter.payloads[0])["recheck"] == items
    b, adapter = read(db, adapter=adapter, recheck=items)
    assert adapter.calls == 1 and b.cache_hit is True, "the same item with the same reason is never read again"
    assert len(db[readings.READINGS].docs) == 1 and len(db[readings.REREADS].docs) == 1
    assert db[readings.READINGS].docs[0]["file_map"] == copy.deepcopy(db[readings.READINGS].docs[0]["file_map"])
