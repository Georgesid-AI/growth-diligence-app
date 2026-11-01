"""Read, check, re-read once, set the as-of month (docs/design/read-check-review.md sections 3, 5, 6, 9; PR 2), end to end on the in-memory
Mongo stub: the upload route, the gateway, the stored reading, the checks and the audit's as-of fields. The provider is a router that
answers a sheet reading from a script and refuses everything else, so no test can reach a model."""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from app import readings, usage as usage_mod  # noqa: E402
from app.llm import gateway  # noqa: E402
from upload_support import AUDIT, AUDIT_DOC, upload  # noqa: E402
from upload_support import FIXTURES, MONTHLY  # noqa: E402

MODEL = "claude-sonnet-5-5"
COMPANY = "Northwind Test Co"
SHEET = "CSV"


class Router(t.FakeAdapter):
    """Answers `sheet_reading` calls from a script (a first reading, then a second for a re-read) and refuses every other call."""

    def __init__(self, first, again=None):
        super().__init__()
        self.first, self.again, self.sheet_calls, self.sheet_payloads = first, again, 0, []

    def complete(self, **kw):
        sent = json.loads(kw["user_payload"])
        if sent["type"] != "sheet_reading":
            raise gateway.GatewayError("model_refused", "not scripted")
        self.sheet_calls += 1
        self.sheet_payloads.append(sent)
        reply = self.again if "recheck" in sent else self.first
        if reply is None:
            raise gateway.GatewayError("model_refused", "nothing scripted")
        return json.dumps(reply), 3000, 400


def evidence(kind, text, **over):
    return {"kind": kind, "text": text, "row": None, "column": None, "cell": None, "cells": None, "other_cells": None, "word": None,
            "multiple": None, **over}


def good_map(revenue=10625, evidence_list=None):
    """The fixture MONTHLY as a reader maps it: months B..M, actuals to June (column G), the plan words over H (title) and row 9."""
    return {"map_version": 1, "kind": "sheet", "figures": [
        {"metric": "revenue", "value": float(revenue), "unit": "money", "currency": "EUR", "period": "2025-06", "basis": "monthly",
         "actual_plan": "actual", "segment": None, "source": {"sheet": SHEET, "cell": "G4", "page": None, "text_layer": None},
         "evidence": "Recognised revenue row, June column"}],
        "sheets": [{"sheet": SHEET, "header_row": 3, "label_col": "A", "first_period_col": "B", "last_period_col": "M", "granularity": "monthly",
                    "currency": "EUR", "currency_cell": "A4",
                    "last_actual": {"column": "G", "period": "2025-06", "evidence": evidence_list or [
                        evidence("label_contains", "Forecast title over July", cell="H2", word="Forecast")]},
                    "rows": [{"row": 4, "label_cell": "A4", "role": "revenue", "metric": "revenue", "basis": "monthly", "actual_plan": "mixed",
                              "boundary_col": "G", "segment": None, "parent_row": None, "unit": "money", "currency": "EUR", "cells": "B4:M4",
                              "variance_of": None, "by_column": False, "evidence": "Recognised revenue"}]}]}


@pytest.fixture()
def flow(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({**AUDIT_DOC, "company_name": COMPANY, "usage": usage_mod.empty()})
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setenv("SHEET_READER_MODEL", MODEL)
    monkeypatch.delenv("READER_V1", raising=False)
    state = {"adapter": Router(good_map())}
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: state["adapter"])
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.state = db, state
    return client


def audit_of(client, audit=AUDIT):
    return client.get(f"/api/audits/{audit}").json()


def monthly():
    return (FIXTURES / MONTHLY).read_bytes()


def test_an_uploaded_report_is_read_checked_and_sets_the_as_of_month_with_its_evidence(flow):
    assert upload(flow, MONTHLY, monthly()).status_code == 200
    router = flow.state["adapter"]
    assert router.sheet_calls == 1
    got = audit_of(flow)
    assert (got["as_of_month"], got["as_of_by"], got["as_of_file"]) == ("2025-06-30", "detected", MONTHLY)
    assert got["as_of_evidence"] == "Forecast title over July (confirmed on sheet CSV, column G)"
    assert got["as_of_proposal"] == {"month": "2025-06-30", "file": MONTHLY, "evidence": got["as_of_evidence"]}
    assert "as_of_cue" not in got and got["sheet_reads_pending"] == 0
    checks = flow.db[readings.CHECKS].docs[0]
    assert checks["status"] == "read" and checks["month"] == "2025-06" and checks["counts"]["rejected"] == 0
    assert checks["counts"]["confirmed"] >= 3 and checks["rereads"] == [] and checks["model"] == MODEL
    assert flow.db["audits"].docs[0]["usage"]["steps"]["sheet_reading"] == {"read": 1}


def test_the_payload_of_the_upload_is_the_masked_file_in_full(flow):
    upload(flow, MONTHLY, monthly())
    text = flow.state["adapter"].sheet_payloads[0]["text"]
    lines = text.split("\n")
    assert lines[0] == "sheet 1: CSV" and len(lines) == 1 + sum(1 for ln in monthly().decode().split("\n")[:12] for cell in ln.split(",") if cell)
    assert "Northwind" not in text and "A1: Client-01 - monthly management report" in lines
    assert "A8: Logo churn %" in lines and "A11: Pipeline" in lines and "A7: Customers" in lines, "metric labels are not company names"
    assert "G4: 10625" in lines and "M12: 0.1787" in lines, "every row to the last, every column to the last, no sampling"


def test_a_rejected_item_is_read_once_more_with_its_reason_and_the_second_reading_is_checked_like_the_first(flow):
    flow.state["adapter"] = Router(good_map(revenue=11000), good_map(revenue=10625))
    upload(flow, MONTHLY, monthly())
    router = flow.state["adapter"]
    assert router.sheet_calls == 2
    assert router.sheet_payloads[1]["recheck"] == [{"item": "figure:CSV:G4:revenue", "reason": "Reading says 11000; cell G4 holds 10625."}]
    checks = flow.db[readings.CHECKS].docs[0]
    assert checks["counts"]["rejected"] == 0 and checks["rereads"] == [
        {"item": "figure:CSV:G4:revenue", "first_reason": "Reading says 11000; cell G4 holds 10625.", "reread": "agrees with the cell",
         "outcome": "confirmed", "reason": None, "action": "corrected automatically"}]
    assert len(flow.db[readings.READINGS].docs) == 1 and len(flow.db[readings.REREADS].docs) == 1, "both readings are kept"
    first = flow.db[readings.READINGS].docs[0]["file_map"]
    assert first["figures"][0]["value"] == 11000.0, "the stored first reading is never edited"


def test_a_second_reading_that_repeats_the_first_stays_rejected_and_waits_for_a_card(flow):
    flow.state["adapter"] = Router(good_map(revenue=11000), good_map(revenue=11000))
    upload(flow, MONTHLY, monthly())
    checks = flow.db[readings.CHECKS].docs[0]
    assert checks["counts"]["rejected"] == 1 and checks["rereads"][0]["reread"] == "repeats the first reading"
    assert checks["rereads"][0]["action"] == "card"
    assert flow.state["adapter"].sheet_calls == 2, "one re-read, never a third call"
    assert audit_of(flow)["as_of_month"] == "2025-06-30", "a rejected figure does not take the confirmed boundary away"


def test_a_re_read_that_is_also_rejected_keeps_the_first_reading_beside_the_second_for_the_card(flow):
    flow.state["adapter"] = Router(good_map(revenue=11000), good_map(revenue=12000))
    upload(flow, MONTHLY, monthly())
    entry = flow.db[readings.CHECKS].docs[0]["rereads"][0]
    assert entry["reread"] == "gives a third value" and entry["action"] == "card"
    assert entry["first"]["value"] == 11000.0 and entry["second"]["value"] == 12000.0
    assert entry["first"]["source"]["cell"] == entry["second"]["source"]["cell"] == "G4"
    assert flow.db[readings.READINGS].docs[0]["file_map"]["figures"][0]["value"] == 11000.0, "the stored first reading is not edited"
    assert flow.db[readings.REREADS].docs[0]["output"]["figures"][0]["value"] == 12000.0


def test_a_re_read_that_is_confirmed_carries_no_pair(flow):
    flow.state["adapter"] = Router(good_map(revenue=11000), good_map(revenue=10625))
    upload(flow, MONTHLY, monthly())
    assert "first" not in flow.db[readings.CHECKS].docs[0]["rereads"][0]


def test_the_same_file_in_another_audit_gets_the_stored_reading_and_makes_no_call(flow):
    upload(flow, MONTHLY, monthly())
    flow.db["audits"].docs.append({**AUDIT_DOC, "id": "audit-two", "company_name": COMPANY, "usage": usage_mod.empty()})
    router = flow.state["adapter"]
    again = flow.post("/api/audits/audit-two/datasets/upload", files={"file": (MONTHLY, monthly())})
    assert again.status_code == 200 and router.sheet_calls == 1, "no second call"
    two = audit_of(flow, "audit-two")
    assert (two["as_of_month"], two["as_of_by"]) == ("2025-06-30", "detected")
    assert len(flow.db[readings.READINGS].docs) == 1 and len(flow.db[readings.USES].docs) == 2
    assert [c["cache_hit"] for c in flow.db["llm_calls"].docs if c["structure_type"] == "sheet_reading"] == [False, True]


def test_a_typed_month_wins_and_the_readers_proposal_stays_beside_it(flow):
    upload(flow, MONTHLY, monthly())
    typed = flow.put(f"/api/audits/{AUDIT}", json={"as_of_month": "2025-03-31"}).json()
    assert (typed["as_of_month"], typed["as_of_by"]) == ("2025-03-31", "analyst")
    assert typed["as_of_proposal"]["month"] == "2025-06-30", "the proposal is kept beside the typed month"
    override = flow.db[readings.OVERRIDES].docs[0]
    assert (override["item"], override["old"], override["new"], override["who"]) == ("as_of_month", "2025-06-30", "2025-03-31", "analyst")
    assert override["at"] and override["why"]
    asyncio_run(server._refresh_as_of(AUDIT))
    kept = audit_of(flow)
    assert (kept["as_of_month"], kept["as_of_proposal"]["month"]) == ("2025-03-31", "2025-06-30"), "a refresh never overwrites a typed month"
    cleared = flow.put(f"/api/audits/{AUDIT}", json={"as_of_month": None}).json()
    assert (cleared["as_of_month"], cleared["as_of_by"]) == ("2025-06-30", "detected")


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def test_with_no_confirmed_month_there_is_none_and_the_upload_goes_on(flow):
    flow.state["adapter"] = Router(good_map(evidence_list=[evidence("layout", "the plan columns look different")]))
    assert upload(flow, MONTHLY, monthly()).status_code == 200
    got = audit_of(flow)
    assert got["as_of_month"] is None and got["as_of_evidence"] is None and got["as_of_proposal"] is None
    checks = flow.db[readings.CHECKS].docs[0]
    assert checks["month"] is None and checks["counts"]["cannot_check"] >= 1


@pytest.mark.parametrize("setup", ["no_model", "no_consent", "model_fails", "prompt_missing"])
def test_the_upload_goes_on_whatever_the_reader_cannot_do(flow, monkeypatch, setup):
    if setup == "no_model":
        monkeypatch.setenv("SHEET_READER_MODEL", "latest")
    elif setup == "no_consent":
        flow.db["audits"].docs[0]["structure_reading_consent"] = False
    elif setup == "model_fails":
        flow.state["adapter"] = Router(None)
    else:
        flow.db["prompts"].docs[:] = [d for d in flow.db["prompts"].docs if d["name"] != "sheet_reading"]
    assert upload(flow, MONTHLY, monthly()).status_code == 200
    got = audit_of(flow)
    assert got["as_of_month"] is None and not got.get("sheet_reads_pending")
    assert not flow.db[readings.READINGS].docs
    assert flow.db["datasets"].docs, "the file is stored as before"




def test_delete_audit_removes_the_reading_the_checks_and_the_overrides_with_the_last_audit(flow):
    upload(flow, MONTHLY, monthly())
    flow.put(f"/api/audits/{AUDIT}", json={"as_of_month": "2025-03-31"})
    assert all(flow.db[c].docs for c in (readings.READINGS, readings.USES, readings.CHECKS, readings.OVERRIDES))
    gone = flow.request("DELETE", f"/api/audits/{AUDIT}", json={"confirm": COMPANY})
    assert gone.status_code == 200 and gone.json()["llm_purged"]["readings"] == 1
    assert all(not flow.db[c].docs for c in readings.COLLECTIONS), "no document of the audit survives in any collection"


def test_compute_reads_the_stored_map_and_series_by_role_and_needs_no_confirmation(flow):
    """PR 4 step a: Calculate takes its inputs from the stored reading; the revenue row is the only row mapped, so the other roles say so."""
    upload(flow, MONTHLY, monthly())
    got = flow.post(f"/api/audits/{AUDIT}/compute")
    assert got.status_code == 200, got.text
    results = got.json()
    series = results["revenue_series"]
    assert series["months"][0] == "2025-01" and series["months"][-1] == "2025-06", "to the confirmed as-of month, the plan months are left out"
    assert series["data"][-1]["total"] == 10625.0 and series["source"]["rule"].startswith("Revenue = the revenue row")
    by_name = {m["metric"]: m for m in results["role_metrics"]["metrics"]}
    assert by_name["customers"]["reason"] == "needs a customers row" and by_name["monthly_churn"]["reason"] == "needs a churn_rate row"
    assert by_name["ending_arr"]["reason"] == "needs an arr row or an mrr row"
    assert results["contract_version"] == 16
    assert flow.get(f"/api/audits/{AUDIT}/results").status_code == 200


# --- rules 14 and 17 on the upload (tests/test_gateway_data_boundary.py names the rule): what the reader's upload stores and logs ---------------

def _all_documents(db):
    return {name: json.dumps(col.docs, default=str) for name, col in db._cols.items()}


def test_no_collection_holds_the_text_the_sheet_reader_was_sent_and_the_calls_hold_counts_only(flow):
    upload(flow, MONTHLY, monthly())
    texts = [p["text"] for p in flow.state["adapter"].sheet_payloads]
    assert texts, "the model was asked"
    stored = _all_documents(flow.db)
    for text in texts:
        for line in text.split("\n")[1:]:
            assert line not in stored.get("llm_calls", ""), line
    assert all(set(c) <= {"run_id", "step", "prompt_version", "model", "input_tokens", "output_tokens", "estimated_cost_usd", "image_tokens",
                          "image_cost_usd", "cache_hit", "status", "unmatched_numbers", "timestamp", "content_hash", "deck_id", "http_status",
                          "error_type", "structure_type", "file_hash", "refused_input_tokens"} for c in flow.db["llm_calls"].docs)


def test_the_log_lines_of_an_upload_a_compute_and_a_delete_hold_no_file_name_cell_value_or_company_name(flow, caplog):
    import logging
    caplog.set_level(logging.INFO)
    upload(flow, MONTHLY, monthly())
    flow.post(f"/api/audits/{AUDIT}/compute")
    flow.get(f"/api/audits/{AUDIT}/blockers")
    flow.request("DELETE", f"/api/audits/{AUDIT}", json={"confirm": COMPANY})
    log = "\n".join(r.getMessage() for r in caplog.records)
    assert "upload: run_id=" in log and "sheet reading: run_id=" in log, "the lines were written"
    for secret in (MONTHLY, COMPANY, "10625", "Recognised revenue"):
        assert secret not in log, f"{secret!r} reached a log line"


def test_an_old_xls_workbook_and_a_file_that_is_not_a_sheet_are_refused_with_their_messages_and_nothing_is_stored(flow):
    """The upload keeps the two refusals of the former chat upload (their tests went with the old path in PR 4): an .xls is refused with the
    save-as message, any other extension with the one-line reason; neither is stored, read or counted as an upload."""
    r = upload(flow, "old.xls", b"\xd0\xcf\x11\xe0 not a modern workbook")
    assert r.status_code == 400 and r.json()["detail"] == server.XLS_REFUSED == "Save as .xlsx or .csv and upload again."
    r = upload(flow, "notes.txt", b"revenue 100")
    assert r.status_code == 400 and r.json()["detail"] == "Only .xlsx and .csv files are supported"
    assert flow.db["datasets"].docs == [] and flow.state["adapter"].sheet_calls == 0
    assert flow.db["audits"].docs[0]["usage"]["files"] == {"uploaded": {}, "rejected": {"xls": 1, "txt": 1}}
