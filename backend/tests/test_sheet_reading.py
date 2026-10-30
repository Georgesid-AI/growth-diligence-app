"""The sheet reader through the gateway (docs/design/read-check-review.md sections 3, 8, 9; CLAUDE.md rule 16 as amended for PR 2).

One model call per spreadsheet; every non-empty cell of every recognised sheet, masked by the one module (name learning included); the
prompt `sheet_reading` from the store (a test stub here); an allow-listed model id only; the reading stored once and served to the same file in any
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
from app.llm import gateway, redaction, schemas  # noqa: E402
from app.structures import redact  # noqa: E402

MODEL = "claude-sonnet-5-5"
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


def test_one_call_per_spreadsheet_with_the_store_prompt_and_the_allow_listed_model():
    db = audit_db()
    result, adapter = read(db)
    assert result.status == "read" and adapter.calls == 1
    request = adapter.requests[0]
    assert request["model"] == MODEL
    assert request["system"] == next(d["text"] for d in db["prompts"].docs if d["name"] == "sheet_reading"), "the prompt comes from the store"
    assert request["json_schema"] is None, "no strict output schema: the provider refused the file map's grammar (George, 2026-10-30)"
    sent = json.loads(adapter.payloads[0])
    assert set(sent["schema"]["properties"]) == {"map_version", "kind", "sheets", "figures"} and sent["answer"] == schemas.FILE_MAP_ANSWER
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
    assert sent["type"] == "sheet_reading" and set(sent) == {"type", "text", "answer", "schema"}
    assert sent["schema"] == schemas.file_map_schema(), "the file map's schema as text, the same for every file"
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


def test_the_sheet_reading_and_its_retry_go_out_with_temperature_zero():
    """The gateway hands the adapter temperature 0 on the call and on the fix retry (the adapter withholds it from models that reject it)."""
    bad = file_map()
    bad["sheets"][0]["sheet"] = "Another sheet"
    result, adapter = read(audit_db(), adapter=t.FakeAdapter(replies=[json.dumps(bad), json.dumps(file_map())]))
    assert result.status == "read" and adapter.calls == 2, "the first reply fails validation, the retry is read"
    assert [r["temperature"] for r in adapter.requests] == [0, 0]


def test_changed_prompt_text_is_a_new_reading_even_under_the_same_version_label():
    """The stored-reading key holds a hash of the prompt text sent, not its version label; the label stays on the record for display."""
    db = audit_db()
    first, adapter = read(db)
    stub = next(d for d in db["prompts"].docs if d["name"] == "sheet_reading")
    stub["text"] += " (edited)"                                 # same version label, different text
    second, adapter = read(db, adapter=adapter)
    assert first.status == second.status == "read" and adapter.calls == 2, "the edited prompt is read again"
    assert first.reading_key != second.reading_key and not second.cache_hit
    assert len(db[readings.READINGS].docs) == 2 and {d["prompt_version"] for d in db[readings.READINGS].docs} == {stub["version"]}
    third, adapter = read(db, adapter=adapter)
    assert third.cache_hit and adapter.calls == 2, "the same text is still served from storage"


def test_the_same_file_in_another_audit_of_the_same_account_gets_the_stored_reading_with_no_second_call():
    db = audit_db()
    db["audits"].docs[0]["owner"] = "tester-1"
    db["audits"].docs.append({"id": "a2", "company_name": COMPANY, "structure_reading_consent": True, "owner": "tester-1"})
    first, adapter = read(db, "a1")
    again, second = read(db, "a2", adapter=adapter)
    assert adapter.calls == 1, "the second upload made no provider call"
    assert again.status == "read" and again.cache_hit is True
    assert again.file_map == first.file_map, "the stored reading, in this audit's masked space"
    assert len(db[readings.READINGS].docs) == 1 and len(db[readings.USES].docs) == 2
    assert [c["cache_hit"] for c in db["llm_calls"].docs] == [False, True]
    assert db["llm_calls"].docs[1]["input_tokens"] == 0


def test_two_accounts_uploading_the_same_file_make_two_model_calls_and_never_see_each_others_reading():
    """F6 of the review of PR 205: a stored reading belongs to one account. The second account's upload is read again, its llm_calls row
    is no cache hit, and the first account's restored names never reach it."""
    db = audit_db()
    db["audits"].docs[0]["owner"] = "tester-1"
    db["audits"].docs.append({"id": "a2", "company_name": COMPANY, "structure_reading_consent": True, "owner": "tester-2"})
    _, adapter = read(db, "a1")
    other, adapter = read(db, "a2", adapter=adapter)
    assert adapter.calls == 2 and other.cache_hit is False
    assert [c["cache_hit"] for c in db["llm_calls"].docs] == [False, False]
    docs = db[readings.READINGS].docs
    assert len(docs) == 2 and {d["account"] for d in docs} == {"tester-1", "tester-2"} and len({d["key"] for d in docs}) == 2
    again, adapter = read(db, "a2", adapter=adapter)
    assert adapter.calls == 2 and again.cache_hit is True, "the same account twice: one call"


def test_a_reading_goes_with_the_last_audit_of_its_account_and_stays_for_the_other_account():
    db = audit_db()
    db["audits"].docs[0]["owner"] = "tester-1"
    db["audits"].docs.append({"id": "a2", "company_name": COMPANY, "structure_reading_consent": True, "owner": "tester-1"})
    db["audits"].docs.append({"id": "a3", "company_name": COMPANY, "structure_reading_consent": True, "owner": "tester-2"})
    _, adapter = read(db, "a1")
    for audit in ("a2", "a3"):
        _, adapter = read(db, audit, adapter=adapter)
    assert len(db[readings.READINGS].docs) == 2 and len(db[readings.USES].docs) == 3
    asyncio.run(gateway.purge_run(db, "a1"))
    assert {d["account"] for d in db[readings.READINGS].docs} == {"tester-1", "tester-2"}, "a2 still uses the first account's reading"
    asyncio.run(gateway.purge_run(db, "a2"))
    assert {d["account"] for d in db[readings.READINGS].docs} == {"tester-2"}, "the last audit of the account took its reading with it"


def test_a_new_prompt_version_or_model_is_a_new_reading_beside_the_old_one(monkeypatch):
    from app.llm import prompt_store
    db = audit_db()
    _, adapter = read(db)
    asyncio.run(prompt_store.upload(db, "sheet_reading", "TEST ONLY second version"))
    read(db, adapter=adapter)
    assert adapter.calls == 2 and {d["prompt_version"] for d in db[readings.READINGS].docs} == {"v1", "v2"}
    monkeypatch.setenv("SHEET_READER_MODEL", "claude-opus-5-5")
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


@pytest.mark.parametrize("model", ["latest", "claude-sonnet-latest", "sonnet", "claude-haiku-4-5", "claude-sonnet-5-5-20260101", "claude-sonnet-5-5-latest",
                                   "claude-opus-4-5", "Claude-Sonnet-5-5"])
def test_a_model_off_the_allow_list_is_refused_before_anything_is_sent(monkeypatch, model):
    monkeypatch.setenv("SHEET_READER_MODEL", model)
    db = audit_db()
    result, adapter = read(db)
    assert result.status == "blocked" and result.reason == gateway.SHEET_READER_BLOCKED
    assert adapter.calls == 0 and not getattr(adapter, "counted", 0), "no token count either: nothing left the server"
    assert not db[readings.READINGS].docs and not db["llm_calls"].docs
    assert "token_map" not in db["audits"].docs[0], "not even the masking ran"


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-5", "claude-opus-5"])
def test_an_allow_listed_id_is_accepted_and_priced(monkeypatch, model):
    monkeypatch.setenv("SHEET_READER_MODEL", model)
    assert gateway.sheet_reader_problem() is None
    assert gateway.estimate_cost_usd(model, 1_000_000, 0) == gateway.estimate_cost_usd(gateway.price_model(model), 1_000_000, 0) > 0


def test_the_gateway_names_no_latest_alias_and_the_default_is_the_structure_model():
    source = (BACKEND / "app" / "llm" / "gateway.py").read_text(encoding="utf-8")
    assert not re.search(r"claude-(?:sonnet|opus)[\w-]*latest", source) and '"latest"' not in source
    assert gateway.SHEET_READER_MODELS == {"claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-5", "claude-opus-5"}
    assert all(m in gateway.MODEL_PRICING_USD for m in gateway.SHEET_READER_MODELS)
    import os
    os.environ.pop("SHEET_READER_MODEL", None)
    assert gateway.sheet_reader_model() == gateway.STRUCTURE_MODEL and gateway.sheet_reader_problem() is None


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
    assert result.status == "not_read" and adapter.calls == 2, "one retry, then not read"
    assert result.reason == gateway.SHEET_READING_NOT_MATCHED
    assert json.loads(adapter.payloads[1])["errors"] == [{"loc": "sheets", "type": "unknown_sheet",
                                                          "msg": "a sheet named in the reply was not in the request, or kind is not sheet"}]
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


def test_two_audits_re_reading_different_items_of_one_reading_do_not_share_a_second_reading():
    db = audit_db()
    db["audits"].docs.append({"id": "a2", "company_name": COMPANY, "structure_reading_consent": True, "fiscal_year_end": 12})
    read(db)
    read(db, audit="a2")
    one = [{"item": "figure:Client-01 report:B3:revenue", "reason": "Reading says 5; cell B3 holds 447223.43."}]
    two = [{"item": "figure:Client-01 report:C3:revenue", "reason": "Reading says 6; cell C3 holds 451000."}]
    again = {"map_version": 1, "kind": "sheet", "sheets": [], "figures": []}
    adapter = t.FakeAdapter(replies=[json.dumps(again), json.dumps({**again, "map_version": 1, "figures": []})])
    a, adapter = read(db, audit="a1", adapter=adapter, recheck=one)
    b, adapter = read(db, audit="a2", adapter=adapter, recheck=two)
    assert adapter.calls == 2 and a.cache_hit is False and b.cache_hit is False, "different items are different second readings"
    c, adapter = read(db, audit="a2", adapter=adapter, recheck=one)
    assert adapter.calls == 2 and c.cache_hit is True, "the same item, asked by another audit, is served"
    assert len(db[readings.REREADS].docs) == 2


def test_no_rule_decides_that_a_sheet_is_a_ledger_and_every_sheet_with_cells_is_sent():
    """Item 7 of the review of PR 205: the rules' record-layout test is gone; a long invoice list is sent whole like any sheet (the token
    cap refuses a file that is too large, with its message)."""
    from app.structures import reading_input
    from app import column_rules as cr
    rows = ["Customer,Invoice Date,Amount"] + [f"C-{i:03d},2024-01-{1 + i % 28:02d},{100 + i}" for i in range(120)]
    sheets = cr.read_workbook("\n".join(rows).encode(), "invoices.csv")
    sent = redact.parse_reading_text(reading_input.reading_text(sheets))
    assert len(sent) == 1 and len(sent[0]["cells"]) == 121 * 3
    assert not hasattr(reading_input, "RECORD_ROWS") and not hasattr(reading_input, "RECORD_LAYOUT")
    assert "import recognition" not in open(reading_input.__file__, encoding="utf-8").read(), "the rules' reading of a sheet decides nothing here"


def test_startup_logs_one_line_naming_what_is_missing_and_the_app_still_starts(monkeypatch, caplog):
    import server
    assert server.check_sheet_reader in server.app.router.on_startup, "the check is registered to run when the app starts"
    db = t.FakeDB()
    db["prompts"].docs[:] = [d for d in db["prompts"].docs if d["name"] != "sheet_reading"]     # no sheet_reading prompt in the store
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setenv("SHEET_READER_MODEL", "claude-haiku-4-5")
    with caplog.at_level(logging.ERROR):
        asyncio.run(server.check_sheet_reader())
    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(lines) == 1 and "sheet_reading" in lines[0] and "claude-haiku-4-5" in lines[0]
    # prompt present and model allowed: quiet
    caplog.clear()
    monkeypatch.setenv("SHEET_READER_MODEL", MODEL)
    asyncio.run(__import__("app.llm.prompt_store", fromlist=["upload"]).upload(db, "sheet_reading", "TEST ONLY prompt"))
    with caplog.at_level(logging.ERROR):
        asyncio.run(server.check_sheet_reader())
    assert not caplog.records


def test_startup_check_stays_up_when_the_store_cannot_be_read(monkeypatch, caplog):
    import server

    class Broken:
        def __getitem__(self, name):
            raise RuntimeError("store down")
    monkeypatch.setattr(server, "db", Broken())
    with caplog.at_level(logging.ERROR):
        asyncio.run(server.check_sheet_reader())               # does not raise
    assert [r.getMessage() for r in caplog.records] == ["sheet reader check failed at startup: error=RuntimeError"]


def test_the_schema_goes_as_compact_text_in_the_request_and_no_strict_output_schema_is_sent():
    """George, 2026-10-30: the provider refused the file map as a strict output schema ("The compiled grammar is too large"), so the schema
    is text inside the request and the code validates. What still applies of the former construct test: the text is FileMap's own schema
    with every field, its closed words and cell patterns (the model is told them), compact (no pydantic titles), the same on every call."""
    from app.llm import schemas
    from schemas.metrics import FileMap
    schema = schemas.file_map_schema()
    assert schemas.output_schema("sheet_reading") is None
    assert set(schema["properties"]) == set(FileMap.model_fields) and set(schema["$defs"]) == {
        "MapEvidence", "MapFigure", "MapLastActual", "MapRow", "MapSheet", "MapSource", "MapVariance", "MapVarianceColumns"}
    assert "title" not in json.dumps(schema) and "pattern" in json.dumps(schema["$defs"]["MapRow"]["properties"]["cells"])
    assert len(json.dumps(schema, separators=(",", ":"))) < 12_000, "compact: a few thousand tokens beside the cells"
    db = audit_db()
    result, adapter = read(db)
    request, sent = adapter.requests[0], json.loads(adapter.payloads[0])
    assert request["json_schema"] is None and request["prior"] is None and sent["schema"] == schema
    assert adapter.count_requests[-1]["json_schema"] is None and json.loads(adapter.count_requests[-1]["user_payload"])["schema"] == schema, \
        "the token count is of the request as sent, schema text included"
    assert result.status == "read"


def test_a_reply_with_a_wrong_field_type_gets_one_retry_carrying_the_errors_then_not_read():
    """The retry is one conversation: the request, the reply that failed and a fix request with the first ten validation errors (location,
    type, message; never the reply's values). A second failure is "not read" with the strip's reason, and both raw replies are kept on the
    reading record, as received, for diagnosis; the record is never served as a reading."""
    bad = file_map()
    bad["sheets"][0]["header_row"] = "two"                       # an int field as a word
    bad["sheets"][0]["rows"][0]["row"] = "three"
    for i in range(12):
        bad["figures"].append({"metric": "revenue", "value": "n/a", "evidence": f"f{i}"})        # 12 more: the errors are capped at ten
    adapter = t.FakeAdapter(replies=[json.dumps(bad), "Sorry, here it is:\n" + json.dumps(bad)])
    db = audit_db()
    result, adapter = read(db, adapter=adapter)
    assert adapter.calls == 2, "exactly one retry"
    assert result.status == "not_read" and result.reason == gateway.SHEET_READING_NOT_MATCHED == "reading did not match the map schema"
    assert result.rejected.startswith("schema: ") and "header_row" in result.rejected and "value" in result.rejected
    first, retry = adapter.requests
    assert first["prior"] is None and retry["prior"] == [{"role": "user", "content": adapter.payloads[0]},
                                                           {"role": "assistant", "content": json.dumps(bad)}]
    fix = json.loads(adapter.payloads[1])
    assert set(fix) == {"type", "fix", "errors"} and fix["type"] == "sheet_reading" and fix["fix"] == schemas.FILE_MAP_FIX
    assert len(fix["errors"]) == 10 == schemas.FILE_MAP_ERRORS_SENT and all(set(e) == {"loc", "type", "msg"} for e in fix["errors"])
    assert fix["errors"][0] == {"loc": "sheets.0.header_row", "type": "int_parsing",
                                "msg": "Input should be a valid integer, unable to parse string as an integer"}
    assert "two" not in json.dumps(fix["errors"]) and "n/a" not in json.dumps(fix["errors"]), "the input is never echoed"
    assert retry["system"] == first["system"] and retry["json_schema"] is None
    record = db[readings.READINGS].docs
    assert len(record) == 1 and record[0]["status"] == "not_read" and record[0]["reason"] == gateway.SHEET_READING_NOT_MATCHED
    assert record[0]["raw_responses"] == [json.dumps(bad), "Sorry, here it is:\n" + json.dumps(bad)], "both replies, as received"
    assert "file_map" not in record[0] and record[0]["file_hash"] == HASH and record[0]["model"] == MODEL
    assert db[readings.USES].docs and db[readings.USES].docs[0]["key"] == record[0]["key"], "goes with the audit (purge)"
    # Not a reading: the file is read again, and the reading then replaces the record.
    again, adapter2 = read(db)
    assert again.status == "read" and adapter2.calls == 1 and not again.cache_hit
    assert [d.get("status") for d in db[readings.READINGS].docs] == [None] and db[readings.READINGS].docs[0]["file_map"]["kind"] == "sheet"
    # The retry that succeeds is a reading.
    fixed = t.FakeAdapter(replies=[json.dumps(bad), json.dumps(file_map())])
    ok, fixed = read(audit_db(), file_hash="b" * 64, adapter=fixed)
    assert ok.status == "read" and fixed.calls == 2 and ok.file_map["sheets"][0]["header_row"] == 2


def test_fences_and_prose_around_the_json_are_stripped_before_parsing():
    wrapped = "Here is the file map:\n```json\n" + json.dumps(file_map(), indent=1) + "\n```\nLet me know if you need more."
    result, adapter = read(audit_db(), adapter=t.FakeAdapter(replies=[wrapped]))
    assert result.status == "read" and adapter.calls == 1 and result.file_map["sheets"][0]["header_row"] == 2
    assert gateway._json_object("no object here") == "no object here" and gateway._json_object("") == ""
    result, adapter = read(audit_db(), file_hash="c" * 64, adapter=t.FakeAdapter(replies=["I cannot read this sheet."]))
    assert result.status == "not_read" and adapter.calls == 2 and result.reason == gateway.SHEET_READING_NOT_MATCHED
    assert json.loads(adapter.payloads[1])["errors"][0]["type"] == "json_invalid"


def test_a_reading_that_leaves_out_the_optional_fields_still_validates():
    from schemas.metrics import FileMap
    assert FileMap.model_validate({"map_version": 1, "kind": "deck", "sheets": [], "figures": [{"evidence": "p1"}]}).figures[0].value is None
