"""Chat-style upload and column mapping (docs/specs/chat-upload.md): type detection, the rule-then-model-then-analyst
mapping, saved mappings, degrade-on-failure, the delete confirmation, the blocker banner, the revenue reconciliation
and the "Other" note. Every test runs on the in-memory Mongo stub and the fake adapter: nothing reaches a provider."""
import asyncio
import io
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
import growth_engine as ge  # noqa: E402
import pandas as pd  # noqa: E402

from app import column_rules as cr  # noqa: E402
from app import decks, structures, usage as usage_mod  # noqa: E402
from app.llm import gateway, guards  # noqa: E402
from app.structures import redact  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
MESSY = BACKEND / "tests" / "fixtures" / "messy"
SAMPLE = BACKEND.parent / "sample_data"
AUDIT = "audit-chat"
COMPANY = "Fixture Target Ltd"
CUSTOMERS = ["Alder Works", "Birch Labs", "Cedar Foods", "Dune Print", "Elm Studio", "Fern Tools", "Birch Labs Ltd"]

AUDIT_DOC = {"id": AUDIT, "company_name": COMPANY, "client_name": "Northbridge Capital",
             "engagement_reference": "ENG-2026-041", "structure_reading_consent": True, "fiscal_year_end": 12,
             "reporting_currency": "EUR", "target_arr": 1000000, "target_date": "2027-12-31", "as_of_month": None,
             "results": None, "status": "draft", "usage": usage_mod.empty()}


def mapping_reply(*pairs):
    """A column-mapping reply: (field, header position) pairs, each citing the header cell r1c<position>."""
    return json.dumps({"type": "column_mapping", "items": [
        {"metric": f, "period": None, "value": None, "unit": None, "actual_or_forecast": "unknown",
         "value_cell": f"r1c{pos}", "unit_other": None, "period_cells": [], "proposed_flags": []} for f, pos in pairs]})


class SlowAdapter(t.FakeAdapter):
    """A provider that takes longer than the budget."""

    def complete(self, **kwargs):
        time.sleep(0.4)
        return super().complete(**kwargs)


@pytest.fixture()
def api(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({**AUDIT_DOC, "usage": usage_mod.empty()})
    monkeypatch.setattr(server, "db", db)
    state = {"adapter": t.FakeAdapter(replies=[mapping_reply()])}
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: state["adapter"])
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.state = db, state
    return client


def adapter_of(client):
    return client.state["adapter"]


def upload(client, name, content=None, **params):
    content = content if content is not None else (MESSY / name).read_bytes()
    return client.post(f"/api/audits/{AUDIT}/datasets/upload", params=params, files={"file": (name, content)})


def view(client, dtype="revenue"):
    return next(d for d in client.get(f"/api/audits/{AUDIT}/datasets").json()["datasets"] if d["dtype"] == dtype)


def by_column(body):
    return {c["column"]: c for c in body["columns"]}


def model_text(client, n=0):
    return json.loads(adapter_of(client).payloads[n])["text"]


def sent_positions(text):
    parsed = redact.parse_column_text(text)
    return sorted({c["col"] for c in parsed["headers"]} | set(parsed["samples"]) | set(parsed["profiles"]))


def decide_all(client, body, dtype="revenue"):
    """Confirm every pending row; a row that needs a decision takes the field it proposed, else Not used."""
    decisions = [{"column": c["column"], "action": "confirm", "field": c["field"]} for c in body["columns"] if c["pending"]]
    return client.post(f"/api/audits/{AUDIT}/datasets/{dtype}/decisions", json=decisions)


# ---------------------------------------------------------------------------
# Reading a sheet: the header row, blank lines, the sheet row numbers (section 3)
# ---------------------------------------------------------------------------
def test_the_header_is_found_below_a_title_and_a_blank_row_and_rows_keep_their_sheet_numbers():
    sheet = cr.read_sheet((MESSY / "duplicate_ids_header_row3.csv").read_bytes(), "x.csv")
    assert sheet.header_row == 3 and sheet.row_numbers[:3] == [4, 5, 6] and len(sheet.frame) == 30
    assert sheet.columns == ["Date", "Amount", "Currency", "Customer ID", "Customer ID.1"]
    assert sheet.headers[3] == sheet.headers[4] == "Customer ID", "the repeat is scored on its cell text"


def test_the_same_file_as_xlsx_reads_the_same_header_and_rows():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for line in (MESSY / "duplicate_ids_header_row3.csv").read_text().splitlines():
        ws.append(line.split(",") if line else [])
    ws["B3"].value = "Amount"
    buf = io.BytesIO()
    wb.save(buf)
    sheet = cr.read_sheet(buf.getvalue(), "x.xlsx")
    assert sheet.header_row == 3 and sheet.row_numbers[0] == 4 and sheet.columns[-1] == "Customer ID.1"


def test_a_blank_cell_stays_blank_and_a_zero_stays_zero():
    sheet = cr.read_sheet((MESSY / "blank_vs_zero.csv").read_bytes(), "x.csv")
    amounts = sheet.frame["Amount"].tolist()
    assert sum(1 for v in amounts if pd.isna(v)) == 4 and sum(1 for v in amounts if v == 0) == 3
    assert cr.value_fit("numeric", amounts) == (1.0, 20, 20), "blank cells are not values; zeros are"


def test_a_one_cell_title_row_and_a_short_row_cannot_break_a_csv():
    sheet = cr.read_sheet(b"Report\n\nCustomer,Date,Amount\nA,2024-01-01,5\nB,2024-02-01\n", "x.csv")
    assert sheet.columns == ["Customer", "Date", "Amount"] and sheet.row_numbers == [4, 5]
    assert pd.isna(sheet.frame["Amount"].iloc[1])


def test_the_type_is_detected_on_the_sample_files_and_on_the_three_fixtures():
    for name, expected in (("revenue", "revenue"), ("crm", "crm"), ("pnl", "pnl")):
        sheet = cr.read_sheet((SAMPLE / f"{name}.csv").read_bytes(), f"{name}.csv")
        found, shares = cr.detect_type(sheet)
        assert found == expected and shares[expected] == 1.0
    for name in ("blank_vs_zero", "mixed_currency", "duplicate_ids_header_row3"):
        assert cr.detect_type(cr.read_sheet((MESSY / f"{name}.csv").read_bytes(), name + ".csv"))[0] == "revenue"
    assert cr.detect_type(cr.read_sheet(b"Alpha,Beta,Gamma\n1,2,3\n", "x.csv"))[0] is None


# ---------------------------------------------------------------------------
# The rules, then the model: which columns are decided and which are sent (sections 4.1, 4.2, test 1 and 2)
# ---------------------------------------------------------------------------
EXPECTED = {
    "blank_vs_zero.csv": ({"Customer ID", "Invoice Date", "Amount", "Currency", "Segment"}, ["Adj"]),
    "mixed_currency.csv": ({"Customer", "Invoice Date", "Tier"}, ["Amount"]),
    "duplicate_ids_header_row3.csv": ({"Date", "Amount", "Currency"}, ["Customer ID", "Customer ID.1"]),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_the_rules_map_exactly_the_clean_columns_and_only_the_ambiguous_ones_are_sent(api, name):
    clean, sent = EXPECTED[name]
    body = upload(api, name).json()
    states = by_column(body)
    assert {c for c, s in states.items() if s["state"] == "auto"} == clean
    columns = list(states)
    assert sent_positions(model_text(api)) == [columns.index(c) + 1 for c in sent]
    assert adapter_of(api).calls == 1


def test_a_confidence_of_zero_says_why_and_a_low_alias_asks_for_one_confirm(api):
    api.db["audits"].docs[0]["structure_reading_consent"] = False      # the rules' proposal stays on screen
    mixed = by_column(upload(api, "mixed_currency.csv").json())["Amount"]
    assert (mixed["confidence"], mixed["fit_note"]) == (0, "0 of 20 values are numbers")
    pnl = by_column(upload(api, "pnl.csv", (SAMPLE / "pnl.csv").read_bytes()).json())
    assert [c for c, s in pnl.items() if s["pending"]] == ["S&M Expense"] and pnl["S&M Expense"]["confidence"] == 30
    assert sum(1 for s in pnl.values() if s["confidence"] == 100) == 3


def test_no_customer_name_and_no_text_cell_reaches_the_model_and_a_numeric_id_sends_a_profile_only(api):
    upload(api, "duplicate_ids_header_row3.csv")
    text = model_text(api)
    parsed = redact.parse_column_text(text)
    assert set(parsed["profiles"]) == {4, 5} and not parsed["samples"], "a customer column never sends samples"
    for secret in CUSTOMERS + ["C-100", "C-101", "Quarterly revenue export", "EUR"]:
        assert secret.lower() not in text.lower(), secret
    assert redact.column_text_problem(text) is None


def test_decided_columns_and_their_headers_are_not_sent_and_at_most_20_rows_are_read(api):
    upload(api, "blank_vs_zero.csv")
    text = model_text(api)
    assert [c["text"] for c in redact.parse_column_text(text)["headers"]] == ["Adj"]
    for decided in ("Invoice Date", "Amount", "Segment", "Currency", "Customer ID"):
        assert decided not in text
    rows = [{"A": f"x{i}", "B": i} for i in range(100)]
    _, samples, profiles = structures.column_mapping_input(["A", "B"], rows, max_rows=20)
    assert samples == {2: ["0", "1", "2"]} and profiles[1]["distinct"] == 20, "the profile is built from 20 rows, not 100"


def test_the_model_proposes_an_ai_suggestion_which_waits_for_a_click_and_the_text_is_stored_nowhere(api):
    api.state["adapter"] = t.FakeAdapter(replies=[mapping_reply(("revenue_type", 6))])
    body = upload(api, "blank_vs_zero.csv").json()
    adj = by_column(body)["Adj"]
    assert (adj["state"], adj["source"], adj["field"], adj["confidence"]) == ("ai", "ai", "revenue_type", None)
    assert body["pending"] == 1 and body["saved"] is False and body["mapping"]["revenue_type"] == "Adj"
    assert api.db["llm_structures"].docs and api.db["column_mappings"].docs == [], "nothing is saved while a row waits"
    text = model_text(api)
    for name in api.db._cols:
        assert text not in json.dumps(api.db[name].docs, default=str), f"the sent text is stored in {name}"


def test_a_column_the_reply_leaves_out_is_not_used_and_with_no_consent_nothing_is_sent(api):
    body = upload(api, "blank_vs_zero.csv").json()
    assert by_column(body)["Adj"]["state"] == "unused" and body["pending"] == 0 and body["saved"] is True
    api.db["audits"].docs[0]["structure_reading_consent"] = False
    api.db["datasets"].docs.clear()
    api.db["column_mappings"].docs.clear()
    calls = adapter_of(api).calls
    body = upload(api, "blank_vs_zero.csv").json()
    assert adapter_of(api).calls == calls and by_column(body)["Adj"]["state"] == "needs"
    assert body["ai_reading"]["status"] == "no_consent"


# ---------------------------------------------------------------------------
# Decisions, compute and saved mappings (sections 4.3 and 5; tests 3 and 6)
# ---------------------------------------------------------------------------
def test_compute_is_refused_while_a_row_waits_and_runs_once_it_is_decided(api):
    api.state["adapter"] = t.FakeAdapter(replies=[mapping_reply(("revenue_type", 6))])
    body = upload(api, "blank_vs_zero.csv").json()
    refused = api.post(f"/api/audits/{AUDIT}/compute")
    assert refused.status_code == 409 and "wait for your decision" in refused.json()["detail"]
    assert api.db["audits"].docs[0]["results"] is None
    done = decide_all(api, body).json()
    assert done["pending"] == 0 and done["saved"] and done["version"] == 1
    assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 200


def test_a_required_field_that_is_not_mapped_stops_compute_and_the_status_names_it(api):
    body = upload(api, "mixed_currency.csv").json()
    assert body["missing_required"] == ["currency"] or "currency" in body["missing_required"]
    decide_all(api, body)
    assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 409


def test_saving_fx_rates_without_a_mapping_confirms_nothing(api):
    api.state["adapter"] = t.FakeAdapter(replies=[mapping_reply(("revenue_type", 6))])
    body = upload(api, "blank_vs_zero.csv").json()
    assert body["pending"] == 1
    r = api.put(f"/api/audits/{AUDIT}/datasets/revenue/mapping", json={"fx": {"USD": 0.9}, "billing_terms": {}})
    assert r.status_code == 200
    stored = api.db["datasets"].docs[0]
    assert stored["fx"] == {"USD": 0.9} and stored["mapped_at"] is None
    assert by_column(view(api))["Adj"]["state"] == "ai", "an AI suggestion is confirmed by a click only"
    assert api.db["column_mappings"].docs == []


def test_correct_takes_a_field_and_a_listed_reason_and_a_held_field_is_refused(api):
    body = upload(api, "blank_vs_zero.csv").json()
    url = f"/api/audits/{AUDIT}/datasets/revenue/decisions"
    bad = api.post(url, json=[{"column": "Adj", "action": "correct", "field": "revenue_type", "reason": "because"}])
    assert bad.status_code == 400
    held = api.post(url, json=[{"column": "Adj", "action": "correct", "field": "amount", "reason": "other_column_right"}])
    assert held.status_code == 409 and held.json()["detail"] == {"code": "field_held", "column": "Amount"}
    ok = api.post(url, json=[{"column": "Adj", "action": "correct", "field": "revenue_type", "reason": "header_misleading"}])
    row = by_column(ok.json())["Adj"]
    assert (row["state"], row["decision"], row["reason"], row["field"]) == ("corrected", "correct", "header_misleading", "revenue_type")
    counters = usage_mod.get(api.db["audits"].docs[0])["columns"]
    assert counters["corrected"] == 1 and counters["reasons"] == {"header_misleading": 1}


def test_the_same_bytes_again_apply_the_saved_mapping_with_no_call_and_no_click(api):
    api.state["adapter"] = t.FakeAdapter(replies=[mapping_reply(("revenue_type", 6))])
    body = upload(api, "blank_vs_zero.csv").json()
    decide_all(api, body)
    calls = adapter_of(api).calls
    again = upload(api, "blank_vs_zero.csv").json()
    assert adapter_of(api).calls == calls, "no model call"
    assert again["status"] == "same_file" and again["version"] == 1 and again["pending"] == 0
    assert {c["state"] for c in again["columns"]} <= {"auto", "unused"} and {c["source"] for c in again["columns"] if c["field"]} == {"saved"}
    assert len(api.db["datasets"].docs) == 1


def test_a_file_with_other_bytes_for_a_loaded_type_stores_nothing_until_replace_is_sent(api):
    upload(api, "blank_vs_zero.csv")
    other = (MESSY / "blank_vs_zero.csv").read_bytes() + b"Zed Co,2024-12-01,50,EUR,Small,\n"
    kept = api.db["datasets"].docs[0]["file_hash"]
    refused = upload(api, "again.csv", other)
    assert refused.status_code == 409 and refused.json()["detail"]["dtype"] == "revenue"
    assert api.db["datasets"].docs[0]["file_hash"] == kept
    replaced = upload(api, "again.csv", other, replace="true")
    assert replaced.status_code == 200 and replaced.json()["row_count"] == 25
    assert api.db["datasets"].docs[0]["file_hash"] != kept


def test_the_same_headers_on_other_data_use_the_saved_mapping_scaled_by_the_new_fit(api):
    api.db["audits"].docs[0]["structure_reading_consent"] = False
    upload(api, "mixed_currency.csv")
    first = by_column(view(api))
    decide_all(api, view(api))                   # Amount is mapped by the analyst although no value reads
    other = (MESSY / "mixed_currency.csv").read_text().replace("€1,200", "1200").replace('"$950"', "950") \
        .replace('"1.200,00 EUR"', "1200").replace('"1200"', "1200")
    calls = adapter_of(api).calls
    body = upload(api, "mixed_currency_b.csv", other.encode(), replace="true").json()
    amount = by_column(body)["Amount"]
    assert adapter_of(api).calls == calls, "no model call for a saved mapping"
    assert (amount["source"], amount["confidence"], amount["state"]) == ("saved", 100, "auto")
    assert first["Amount"]["confidence"] == 0


def test_a_mapping_saved_before_versions_existed_is_still_applied_to_the_same_headers(api):
    sheet = cr.read_sheet((MESSY / "blank_vs_zero.csv").read_bytes(), "x.csv")
    api.db["column_mappings"].docs.append({
        "audit_id": AUDIT, "dtype": "revenue", "header_key": structures.header_key("revenue", sheet.columns),
        "mapping": {"customer_id": "Customer ID", "invoice_date": "Invoice Date", "amount": "Amount", "currency": "Currency",
                    "revenue_type": "Adj"}, "saved_at": "2026-10-01T00:00:00"})
    calls = adapter_of(api).calls
    body = upload(api, "blank_vs_zero.csv")
    assert body.status_code == 200, body.text
    rows = by_column(body.json())
    assert adapter_of(api).calls == calls and rows["Adj"]["field"] == "revenue_type" and rows["Adj"]["source"] == "saved"
    assert rows["Segment"]["state"] == "unused", "a column the old mapping left out stays unused"


def test_a_file_stored_before_the_chat_upload_takes_decisions_like_any_other(api):
    api.db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "file": "old.csv", "sheet": "CSV",
                                    "columns": ["Customer", "Amount"], "rows": [{"Customer": "A", "Amount": 1}],
                                    "mapping": {"customer_id": "Customer", "amount": "Amount"}, "mapped_at": "2026-09-01"})
    body = api.get(f"/api/audits/{AUDIT}/datasets").json()["datasets"][0]
    assert {c["state"] for c in body["columns"]} == {"confirmed"} and body["pending"] == 0
    r = api.post(f"/api/audits/{AUDIT}/datasets/revenue/decisions", json=[
        {"column": "Amount", "action": "correct", "field": None, "reason": "not_needed"}])
    assert r.status_code == 200 and by_column(r.json())["Amount"]["state"] == "unused"


def test_an_unknown_file_stores_nothing_and_the_typed_upload_names_its_type(api):
    body = upload(api, "mystery.csv", b"Alpha,Beta\n1,2\n").json()
    assert body["status"] == "unknown_type" and api.db["datasets"].docs == []
    stored = upload(api, "mystery.csv", b"Alpha,Beta\n1,2\n", dtype="crm")
    assert stored.status_code == 200 and stored.json()["dtype"] == "crm"


def test_a_file_that_is_not_xlsx_or_csv_is_refused_and_counted_by_extension(api):
    r = upload(api, "deck.pptx", b"PK")
    assert r.status_code == 400
    api.post(f"/api/audits/{AUDIT}/usage", json={"rejected_extension": "docx"})
    rejected = usage_mod.get(api.db["audits"].docs[0])["files"]["rejected"]
    assert rejected == {"pptx": 1, "docx": 1}


def test_sheet_row_numbers_name_the_real_rows_in_the_citations(api):
    api.state["adapter"] = t.FakeAdapter(replies=[mapping_reply(("customer_id", 4))])
    body = upload(api, "duplicate_ids_header_row3.csv").json()
    assert decide_all(api, body).json()["pending"] == 0
    assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 200
    source = api.db["audits"].docs[0]["results"]["arr"]["source"]
    assert source["row_numbers"][0] == 4 and min(source["row_numbers"]) == 4, "the first data row is sheet row 4"
    assert source["file"] == "duplicate_ids_header_row3.csv"


# ---------------------------------------------------------------------------
# Degrade, don't die (section 6.1; test 4)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("failure", ["error", "timeout"])
def test_when_the_model_fails_the_sent_columns_need_a_decision_and_every_metric_still_computes(api, monkeypatch, failure):
    if failure == "timeout":
        api.state["adapter"] = SlowAdapter(replies=[mapping_reply()])
        monkeypatch.setattr(server, "MAPPING_AI_SECONDS", 0.05)
    else:
        api.state["adapter"] = t.FakeAdapter(raise_with=RuntimeError("provider down"))
    body = upload(api, "blank_vs_zero.csv").json()
    adj = by_column(body)["Adj"]
    assert (adj["state"], adj["source"], adj["field"]) == ("needs", "needs", None), "the columns that were sent need a decision"
    assert body["ai_reading"]["status"] in ("timeout", "not_read") and body["pending"] == 1
    assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 409, "nothing computes on a guess"
    done = decide_all(api, body).json()                       # the analyst decides: Adj is not used
    assert done["pending"] == 0 and by_column(done)["Adj"]["state"] == "unused"
    assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 200
    results = api.get(f"/api/audits/{AUDIT}/results").json()["results"]
    assert results["arr"]["value"] and results["arr"]["source"]["row_numbers"], "every metric carries its source"
    assert api.post(f"/api/runs/{AUDIT}/narrative/growth_engine").json()["narrative_status"] == "unavailable"


def test_a_deck_read_that_fails_leaves_pythons_candidates_in_place():
    import test_structure_reading as sr
    pytest.importorskip("pptx")
    mp = pytest.MonkeyPatch()
    try:
        client, db, adapter = sr._deck_api(mp)
        sr._map_revenue(client)
        adapter._raise_with = RuntimeError("provider down")
        sr._upload_deck(client)
        listed = sr._deck(client)
        assert listed["decks"][0]["ai_status"] == "not_read"
        assert listed["candidates"] and not [c for c in listed["candidates"] if c.get("origin") == "ai"], \
            "Python's candidates stand alone"
    finally:
        mp.undo()


def test_the_lock_is_released_when_the_call_is_cancelled_at_the_budget(api, monkeypatch):
    api.state["adapter"] = SlowAdapter(replies=[mapping_reply()])
    monkeypatch.setattr(server, "MAPPING_AI_SECONDS", 0.05)
    upload(api, "mixed_currency.csv")
    locks = api.db[guards.LOCKS_COLLECTION].docs
    assert locks and all(doc["held"] is False for doc in locks), "a cancelled call leaves the audit unlocked"
    adapter_of(api).__class__ = t.FakeAdapter            # the next call is served at once
    api.db["datasets"].docs.clear()
    body = upload(api, "mixed_currency.csv").json()
    assert body["ai_reading"]["status"] == "read", "the next structure call is not blocked by the cancelled one"


def test_a_narrative_that_cannot_be_generated_leaves_the_metrics_with_their_sources(api, monkeypatch):
    body = upload(api, "blank_vs_zero.csv").json()
    assert body["pending"] == 0
    api.state["adapter"] = t.FakeAdapter(raise_with=RuntimeError("provider down"))
    assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 200
    narrative = api.post(f"/api/runs/{AUDIT}/narrative/growth_engine")
    assert narrative.status_code == 200 and narrative.json()["narrative_status"] == "unavailable"
    results = api.get(f"/api/audits/{AUDIT}/results").json()["results"]
    assert results["arr"]["source"]["file"] == "blank_vs_zero.csv" and results["arr"]["source"]["row_numbers"]


# ---------------------------------------------------------------------------
# Typed text and the screen's own reply never reach the server (section 2): see MappingWizard.test.jsx
# Delete audit (section 6.3; test 7)
# ---------------------------------------------------------------------------
def _remaining(db, audit_id):
    left = {}
    for name, col in db._cols.items():
        n = sum(1 for d in col.docs if audit_id in (d.get("id"), d.get("audit_id"), d.get("run_id")))
        if n:
            left[name] = n
    return left


def _full_audit(api):
    upload(api, "blank_vs_zero.csv")
    api.db[decks.TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "deck.pptx", "structures": []})
    api.db[decks.CANDIDATES_COLLECTION].docs.append({"audit_id": AUDIT, "id": "c1", "status": "approved", "file": "deck.pptx"})
    api.db["llm_calls"].docs.append({"run_id": AUDIT, "step": "structures"})


def test_delete_needs_the_company_name_in_the_body_and_a_wrong_name_deletes_nothing(api):
    _full_audit(api)
    before = _remaining(api.db, AUDIT)
    # Exact and case-sensitive after trimming, as the dialog is: another case and a partial name delete nothing.
    for body in (None, {"confirm": ""}, {"confirm": "Other Company"}, {"confirm": COMPANY + "x"}, {"confirm": COMPANY.upper()},
                 {"confirm": COMPANY.lower()}, {"confirm": COMPANY[:-1]}):
        r = api.request("DELETE", f"/api/audits/{AUDIT}", json=body) if body is not None else api.delete(f"/api/audits/{AUDIT}")
        assert r.status_code == 400
    assert _remaining(api.db, AUDIT) == before


def test_the_right_name_leaves_no_document_with_the_audit_id_in_any_collection(api):
    _full_audit(api)
    other = {**AUDIT_DOC, "id": "other", "company_name": "Other"}
    api.db["audits"].docs.append(other)
    assert "column_mappings" in _remaining(api.db, AUDIT) and "datasets" in _remaining(api.db, AUDIT)
    r = api.request("DELETE", f"/api/audits/{AUDIT}", json={"confirm": f"  {COMPANY}  "})
    assert r.status_code == 200, r.text
    assert _remaining(api.db, AUDIT) == {}
    assert [a["id"] for a in api.db["audits"].docs] == ["other"]


# ---------------------------------------------------------------------------
# Revenue reconciliation and the blocker banner (section 6.2; tests 8 and 9)
# ---------------------------------------------------------------------------
def _frames(file_months, pnl_months, extra_pnl_rows=()):
    """(revenue frame, pnl frame) through normalize, so rows keep sheet numbers: one customer, one line a month."""
    rev_rows = [{"Customer": "A", "Date": f"{m}-01", "Amount": v, "Currency": "EUR"} for m, v in file_months]
    pnl_rows = [{"Month": f"{m}-01", "Revenue": v, "S&M": 1.0, "Cost": 1.0} for m, v in pnl_months]
    rev = server.normalize(rev_rows, "revenue", {"customer_id": "Customer", "invoice_date": "Date", "amount": "Amount",
                                                 "currency": "Currency"}, [10 + i for i in range(len(rev_rows))])
    pnl = server.normalize(pnl_rows, "pnl", {"month": "Month", "revenue": "Revenue", "sm_expense": "S&M",
                                             "cost_of_revenue": "Cost"}, [5 + i for i in range(len(pnl_rows))])
    return rev, pnl


def _reconcile(file_months, pnl_months):
    rev, pnl = _frames(file_months, pnl_months)
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None, "fx": {"EUR": 1.0}, "billing_terms": {},
              "default_l": 1, "as_of_month": None}
    sources = {"revenue": {"file": "rev.csv", "sheet": "CSV"}, "pnl": {"file": "pnl.csv", "sheet": "CSV"}}
    return ge.compute_all(rev, pd.DataFrame(), pnl, config, sources)["revenue_reconciliation"]


MONTHS = [f"2024-{m:02d}" for m in range(1, 13)]


def test_the_window_total_decides_and_a_single_month_above_2_percent_is_only_in_the_table():
    file = [(m, 1000.0) for m in MONTHS]
    pnl = [(m, 1000.0) for m in MONTHS]
    pnl[3] = (MONTHS[3], 900.0)         # April: the file is 11% above the P&L
    pnl[4] = (MONTHS[4], 1100.0)        # May: the file is 9% below; the total gap is 0
    rec = _reconcile(file, pnl)
    assert rec["available"] and rec["gap"] == 0 and rec["blocker"] is False
    april = next(r for r in rec["by_month"] if r["month"] == "2024-04")
    assert (april["gap"], april["gap_pct"]) == (100.0, 11.11), "the month shows in the evidence table"
    assert len(rec["by_month"]) == 12 and all(r["source"]["revenue_file"]["row_numbers"] and r["source"]["pnl"]["row_numbers"]
                                              for r in rec["by_month"]), "every row cites its rows"
    assert rec["by_month"][0]["source"]["revenue_file"]["row_numbers"] == [10]
    assert rec["by_month"][0]["source"]["pnl"]["row_numbers"] == [5]


def test_a_total_gap_above_2_percent_is_a_blocker_and_exactly_2_is_not():
    pnl = [(m, 1000.0) for m in MONTHS]
    over = _reconcile([(m, 1030.0) for m in MONTHS], pnl)
    assert over["blocker"] is True and over["gap_pct"] == 3.0
    edge = _reconcile([(m, 1020.0) for m in MONTHS], pnl)
    assert edge["blocker"] is False and edge["gap_pct"] == 2.0
    beat = _reconcile([(m, 970.0) for m in MONTHS], pnl)
    assert beat["blocker"] is True, "a gap in either direction counts"


def test_the_window_is_the_months_both_files_cover_and_at_most_the_last_12():
    long = [f"{y}-{m:02d}" for y in (2023, 2024) for m in range(1, 13)]
    rec = _reconcile([(m, 100.0) for m in long], [(m, 100.0) for m in long[6:]])
    assert (rec["first"], rec["last"], len(rec["by_month"])) == ("2024-01", "2024-12", 12)
    short = _reconcile([(m, 100.0) for m in MONTHS[:6]], [(m, 100.0) for m in MONTHS[3:]])
    assert (short["first"], short["last"]) == ("2024-04", "2024-06")


def test_without_a_pnl_there_is_no_check_no_section_and_no_blocker():
    rev, _ = _frames([(m, 1000.0) for m in MONTHS], [])
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None, "fx": {"EUR": 1.0}, "billing_terms": {},
              "default_l": 1}
    results = ge.compute_all(rev, pd.DataFrame(), pd.DataFrame(), config, {"revenue": {"file": "r.csv", "sheet": "CSV"}})
    assert results["revenue_reconciliation"] is None


def _banner_audit(api, results, mapped=True):
    api.db["audits"].docs[0]["results"] = results
    api.db["audits"].docs[0]["status"] = "computed"
    if mapped:
        api.db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "mapped_at": "2026-10-08T00:00:00"})


def _kinds(api):
    r = api.get(f"/api/audits/{AUDIT}/blockers")
    assert r.status_code == 200
    return [b["kind"] for b in r.json()["blockers"]]


def _texts(api):
    return [b["text"] for b in api.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"]]


def test_the_banner_shows_the_revenue_file_missing_until_it_is_mapped_and_clears(api):
    assert _kinds(api) == ["revenue_file_missing"]
    assert _texts(api) == ["Revenue file missing: upload and map it to compute metrics."], "no revenue file at all"
    api.db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "mapped_at": None})
    assert _kinds(api) == ["revenue_file_missing"], "uploaded but its mapping is not saved"
    assert _texts(api) == ["Revenue file uploaded – confirm the mapping to compute metrics."], \
        "the file exists: the banner says what is left to do, not that the file is missing"
    api.db["datasets"].docs[0]["mapped_at"] = "2026-10-08T00:00:00"
    assert _kinds(api) == []


def test_the_banner_shows_a_reconciliation_gap_above_2_percent_with_its_citation_and_clears(api):
    big = _reconcile([(m, 1100.0) for m in MONTHS], [(m, 1000.0) for m in MONTHS])
    _banner_audit(api, {"revenue_reconciliation": big})
    body = api.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"]
    assert [b["kind"] for b in body] == ["revenue_reconciliation"]
    assert body[0]["text"] == ("Revenue file and P&L differ by 10% over 2024-01–2024-12 (13,200 EUR vs 12,000 EUR).")
    assert body[0]["citation"]["revenue_file"]["row_numbers"] and body[0]["link"] == f"/audit/{AUDIT}/diagnostics"
    small = _reconcile([(m, 1010.0) for m in MONTHS], [(m, 1000.0) for m in MONTHS])
    api.db["audits"].docs[0]["results"] = {"revenue_reconciliation": small}
    assert _kinds(api) == []


def test_only_a_top_5_contradicted_claim_reaches_the_banner_and_a_beat_counts(api, monkeypatch):
    rows = [{"claim_id": f"c{i}", "rank": i, "evidence_label": label, "claim_type": "revenue", "claimed_value": 100.0,
             "claimed_high": None, "unit": None, "currency": "EUR", "observed_value": obs, "observed_source": {"file": "r.csv"},
             "deck_file": "board.pptx", "page_ref": "slide 4"}
            for i, (label, obs) in enumerate([("Verified", 100.0), ("Contradicted", 80.0), ("Contradicted", 140.0),
                                              ("Unverified", None), ("Contradicted", 10.0), ("Contradicted", 5.0)], 1)]

    async def fake_rows(audit_id, audit):
        return [], rows
    monkeypatch.setattr(server, "_claim_rows", fake_rows)
    _banner_audit(api, {"arr": None})
    blockers = api.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"]
    assert [b["claim_id"] for b in blockers] == ["c2", "c3", "c5"], "rank 6 is not top-5; a beat (c3) is Contradicted"
    assert blockers[0]["text"] == "Top-5 claim contradicted: revenue 100 EUR vs 80 EUR observed (board.pptx, slide 4)."
    rows[1]["evidence_label"] = rows[2]["evidence_label"] = rows[4]["evidence_label"] = "Verified"
    assert _kinds(api) == []


def test_the_banner_has_three_kinds_and_no_others():
    assert server.BLOCKER_KINDS == ("revenue_file_missing", "claim_contradicted", "revenue_reconciliation")


# ---------------------------------------------------------------------------
# The "Other" note (section 4.3; test 10)
# ---------------------------------------------------------------------------
def _correct(api, note, reason="other", column="Adj"):
    return api.post(f"/api/audits/{AUDIT}/datasets/revenue/decisions", json=[
        {"column": column, "action": "correct", "field": "revenue_type", "reason": reason, "note": note}])


def _notes(api):
    return [n["note"] for n in usage_mod.get(api.db["audits"].docs[0])["other_notes"]]


@pytest.mark.parametrize("note", [
    "the 2024 column", "see blank_vs_zero.csv", "same as blank_vs_zero", "Alder Works is wrong", "birch", "x" * 61,
    "belongs to Fixture Target Ltd", "ask Northbridge Capital", "per ENG-2026-041",
])
def test_a_note_with_a_digit_a_file_name_a_cell_text_a_name_or_over_60_characters_is_refused_and_saves_nothing(api, note):
    upload(api, "blank_vs_zero.csv")
    before = json.dumps(api.db["audits"].docs[0]["usage"]), json.dumps(api.db["datasets"].docs[0]["columns_state"])
    r = _correct(api, note)
    assert r.status_code == 400 and r.json()["detail"] == server.NOTE_REFUSED
    assert (json.dumps(api.db["audits"].docs[0]["usage"]), json.dumps(api.db["datasets"].docs[0]["columns_state"])) == before


def test_a_note_that_quotes_a_header_is_kept_with_its_code_and_nothing_else_beside_it(api):
    upload(api, "blank_vs_zero.csv")
    r = _correct(api, "  Adj is not the revenue type \x07")
    assert r.status_code == 200, r.text
    assert _notes(api) == ["Adj is not the revenue type"]
    assert usage_mod.get(api.db["audits"].docs[0])["other_notes"][0].keys() == {"note", "at"}
    mapping = api.db["column_mappings"].docs[-1]
    assert "Adj is not" not in json.dumps(mapping) and {c["reason"] for c in mapping["columns"]} == {None, "other"}


def test_a_header_that_contains_a_cell_word_still_passes_and_a_header_with_a_digit_does_not(api):
    csv = "Customer ID,Invoice Date,Amount,Currency,Segment,Large Account Flag,Plan 2024\nAlder Works,2024-01-01,5,EUR,Large,x,y\n"
    upload(api, "h.csv", csv.encode())
    api.db["datasets"].docs[0]["columns_state"] = [
        {**s, "state": "unsure" if s["column"] == "Large Account Flag" else s["state"]} for s in api.db["datasets"].docs[0]["columns_state"]]
    for column in ("Large Account Flag", "Plan 2024"):
        api.db["datasets"].docs[0]["columns_state"] = [
            {**s, "state": "unused", "field": None} if s["column"] == column else s for s in api.db["datasets"].docs[0]["columns_state"]]
    ok = _correct(api, "Large Account Flag is wrong", column="Large Account Flag")
    assert ok.status_code == 200, ok.text
    assert _notes(api) == ["Large Account Flag is wrong"], "'Large' is a cell word inside a header"
    assert _correct(api, "Plan 2024 is wrong", column="Plan 2024").status_code == 400, "a digit inside a header is refused"


def test_a_reason_outside_the_list_is_refused_and_a_note_rides_only_with_other(api):
    upload(api, "blank_vs_zero.csv")
    assert _correct(api, None, reason="free text").status_code == 400
    assert _correct(api, "Adj is not it", reason="not_needed").status_code == 200
    assert _notes(api) == [], "a note with another reason is not kept"


def test_at_most_50_notes_are_kept_the_oldest_dropped_first():
    u = usage_mod.empty()
    for i in range(55):
        usage_mod.keep_note(u, f"note {chr(97 + i % 26)}")
    assert len(u["other_notes"]) == 50


# ---------------------------------------------------------------------------
# Usage counters and totals (section 7)
# ---------------------------------------------------------------------------
def test_the_counters_hold_counts_and_codes_and_the_totals_hold_no_name_and_no_per_audit_row(api):
    upload(api, "blank_vs_zero.csv")
    api.post(f"/api/audits/{AUDIT}/usage", json={"screen": "mapping"})
    assert api.post(f"/api/audits/{AUDIT}/usage", json={"screen": "settings"}).status_code == 422, "any other screen is refused"
    assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 200
    api.get(f"/api/audits/{AUDIT}/export")
    counters = usage_mod.get(api.db["audits"].docs[0])
    assert counters["files"]["uploaded"] == {"revenue": 1} and counters["last_screen"] == "mapping"
    assert counters["first_upload_at"] and counters["first_export_at"] and counters["steps"]["compute"]["runs"] == 1
    assert counters["columns"]["rules"] == 5
    totals = api.get("/api/usage/totals")
    assert totals.status_code == 200
    blob = json.dumps(totals.json())
    for secret in (COMPANY, "blank_vs_zero", "Alder", AUDIT, "Northbridge"):
        assert secret not in blob
    assert totals.json()["audits"] == 1 and totals.json()["files"]["uploaded"] == {"revenue": 1}
    assert "audit_rows" not in totals.json() and totals.json()["median_days_to_export"] is not None


def test_an_audit_listing_and_an_audit_read_do_not_carry_the_counters(api):
    assert all("usage" not in a for a in api.get("/api/audits").json())
    assert "usage" not in api.get(f"/api/audits/{AUDIT}").json()


# ---------------------------------------------------------------------------
# The demo audits: one reconciles, one keeps a deliberate 5% gap so the banner shows
# ---------------------------------------------------------------------------
def test_the_demo_audits_reconcile_within_2_percent_except_the_one_with_a_deliberate_5_percent_gap(monkeypatch):
    db = t.FakeDB()
    monkeypatch.setattr(server, "db", db)
    asyncio.run(server.seed_demo())
    client = TestClient(server.app, raise_server_exceptions=False)
    found = {}
    for audit in db["audits"].docs:
        rec = audit["results"]["revenue_reconciliation"]
        kinds = [b["kind"] for b in client.get(f"/api/audits/{audit['id']}/blockers").json()["blockers"]]
        found[audit["company_name"].split()[0]] = (rec["gap_pct"], rec["blocker"], kinds)
    assert found["Apex"] == (0.0, False, [])
    assert found["OmniData"] == (5.0, True, ["revenue_reconciliation"])
