"""The mapping miss on three uploaded workbooks (2026-10-16, docs/specs/chat-upload.md sections 3, 4.1 and 19): the type
rules, the model asked once for a file's type, every sheet read, leading empty columns dropped, period headers melted, the
units of the title rows, the miss message, and one test per export layout in tests/fixtures/mapping/. Every test runs on
the in-memory Mongo stub and the fake adapter: nothing reaches a provider."""
import json
import logging

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from mapping_shapes import FIXTURES, crm_anonymous_to_2028, pnl_to_2028, revenue_to_2028  # noqa: E402
from test_chat_upload import AUDIT, adapter_of, mapping_reply, upload  # noqa: E402

from app import column_rules as cr  # noqa: E402
from app.structures import redact  # noqa: E402

TITLE = "Revenue through 31 December 2028"


def type_reply(word):
    return json.dumps({"type": "file_type", "file_type": word})


def sheets_of(content, name):
    return cr.read_workbook(content, name)


# ---------------------------------------------------------------------------
# Finding 1: why the CRM workbook was asked for revenue fields
# ---------------------------------------------------------------------------
def test_an_mrr_header_and_an_account_id_do_not_make_a_crm_workbook_the_revenue_file():
    found, _, shares = cr.detect_workbook(sheets_of(crm_anonymous_to_2028(), "CRM.xlsx"))
    assert found != "revenue", shares
    assert shares["revenue"] < cr.DETECTION_MIN_SHARE, "customer, date and amount must all be present for revenue"


def test_revenue_needs_customer_date_and_amount_each_at_80_or_more():
    for header, expected in ((["Customer", "Invoice Date", "Amount"], "revenue"), (["Account ID", "Existing MRR EUR", "Segment"], None),
                             (["MRR", "Date", "Notes"], None)):
        sheet = cr.read_sheet((",".join(header) + "\nA,2024-01-01,5\nB,2024-02-01,6\n").encode(), "x.csv")
        assert cr.detect_type(sheet)[0] == expected, header


def test_stage_owner_created_and_won_columns_make_a_crm_file_and_cost_lines_a_pnl():
    crm = cr.read_sheet(b"Deal,Created,Closed,Stage,Owner\nD1,2024-01-01,2024-02-01,won,Ann\nD2,2024-01-02,2024-03-01,lost,Bo\n", "x.csv")
    pnl = cr.read_sheet(b"Cost of sales,Payroll,EBITDA\n10,20,30\n11,21,31\n", "x.csv")
    assert cr.detect_type(crm)[0] == "crm" and cr.detect_type(pnl)[0] == "pnl"


def test_snake_case_headers_and_line_labels_are_read_with_underscores_as_spaces():
    """The type rules read a header or a line label as the mapping does (2026-10-17, chat-upload.md sections 3 and 19): an
    underscore is punctuation, so it no longer hides a word from the signature and cost-line rules."""
    crm = cr.read_sheet(b"deal_id,created_date,close_date,stage,owner\nD1,2024-01-01,2024-02-01,won,Ann\n"
                        b"D2,2024-01-02,2024-03-01,lost,Bo\n", "x.csv")
    assert (cr.detect_type(crm)[0], cr.type_shares(crm)["crm"]) == ("crm", 1.0)
    pnl = cr.read_sheet(b"line_item,Jan-24,Feb-24,Mar-24\ncost_of_sales,10,11,12\nstaff_costs,20,21,22\n"
                        b"gross_profit,30,31,32\nnet_income,5,6,7\n", "x.csv")
    assert pnl.wide and cr.detect_type(pnl)[0] == "pnl" and cr.type_shares(pnl)["pnl"] == 1.0, "four cost lines in the labels"


# ---------------------------------------------------------------------------
# Finding 2: the model did not run while columns showed "Rules", confidence 0 (state "unused")
# ---------------------------------------------------------------------------
def test_a_saved_mapping_that_maps_nothing_is_not_reused_so_the_model_runs_again(api):
    api.state["adapter"] = t.FakeAdapter(replies=[mapping_reply()])        # the model leaves every sent column out
    first = upload(api, "CRM.xlsx", crm_anonymous_to_2028(), dtype="crm").json()
    states = {c["column"]: c["state"] for c in first["columns"]}
    assert states.pop("Account ID") == "unsure", "the rules' deal id at 80, which the reply leaves out, waits (section 4.2)"
    assert set(states.values()) <= {"unused", "auto"}, "columns both sides leave out are Not used (section 4.2)"
    first = api.post(f"/api/audits/{AUDIT}/datasets/crm/decisions", json=[
        {"column": "Account ID", "action": "correct", "field": None, "reason": "not_needed"}]).json()
    assert first["pending"] == 0, "nothing waits, so the mapping saved"
    calls = adapter_of(api).calls
    assert len(api.db["column_mappings"].docs) == 1, "a version with no mapped column was written"
    other = crm_anonymous_to_2028()
    from openpyxl import load_workbook
    import io
    wb = load_workbook(io.BytesIO(other))
    wb["Accounts"]["C20"] = "an extra line"
    buf = io.BytesIO()
    wb.save(buf)
    upload(api, "CRM_b.xlsx", buf.getvalue(), dtype="crm", replace="true")
    assert adapter_of(api).calls > calls, "the same headers on other bytes must not reuse a mapping that mapped nothing"


# ---------------------------------------------------------------------------
# Fix 3: leading empty columns; fix 4: every sheet; fix 5: wide to long; fix 6: units
# ---------------------------------------------------------------------------
def test_leading_empty_columns_are_dropped_and_no_unnamed_column_is_left():
    for content, name in ((crm_anonymous_to_2028(), "CRM.xlsx"), (revenue_to_2028(), "Revenue.xlsx"), (pnl_to_2028(), "PnL.xlsx")):
        for sheet in sheets_of(content, name):
            assert not any(c.startswith("Unnamed") for c in sheet.columns), (sheet.sheet, sheet.columns)
    accounts = sheets_of(crm_anonymous_to_2028(), "CRM.xlsx")[0]
    assert accounts.header_row == 6 and accounts.columns[0] == "Account ID" and len(accounts.columns) == 17


def test_every_sheet_is_read_and_the_best_one_is_chosen_for_the_role():
    sheets = sheets_of(crm_anonymous_to_2028(), "CRM.xlsx")
    assert [s.sheet for s in sheets] == ["Accounts", "Annual tracker", "Funnel and evidence"]
    from openpyxl import Workbook
    import io
    wb = Workbook()
    wb.active.title = "Cover"
    wb.active.append(["Notes only"])
    ws = wb.create_sheet("Deals")
    ws.append(["Deal ID", "Created", "Close Date", "Stage", "Amount"])
    ws.append(["D1", "2024-01-01", "2024-02-01", "won", 100])
    ws.append(["D2", "2024-01-05", "2024-03-01", "lost", 200])
    buf = io.BytesIO()
    wb.save(buf)
    found, sheet, _ = cr.detect_workbook(cr.read_workbook(buf.getvalue(), "x.xlsx"))
    assert (found, sheet.sheet) == ("crm", "Deals")


def test_period_headers_are_melted_into_a_period_and_a_value_and_only_the_first_table_is_read():
    revenue = sheets_of(revenue_to_2028(), "Revenue.xlsx")[0]
    assert revenue.wide == {"periods": 10, "monthly": False}
    assert revenue.columns == ["Line", "Period", "Value"] and revenue.header_row == 5
    assert set(revenue.frame["Line"]) == {"Revenue", "Gross profit", "New customers", "Customers at year-end", "ARR"}, \
        "the forecast, the budget comparison and the notes below the first table are not read"
    assert len(revenue.frame) == 50 and set(revenue.frame["Period"]) == set(["2023", "Q1:24", "Q2:24", "Q3:24", "2024 YTD", "2024",
                                                                          "2025", "2026", "2027", "2028"])
    assert revenue.row_numbers[0] == 6 and revenue.row_numbers[-1] == 10, "each value keeps the sheet row of its line"


def test_months_across_the_columns_become_dates():
    sheet = cr.read_sheet((FIXTURES / "wide_monthly_revenue.csv").read_bytes(), "wide.csv")
    assert sheet.wide == {"periods": 12, "monthly": True} and sheet.columns == ["Customer", "Currency", "Date", "Value"]
    assert len(sheet.frame) == 72 and str(sheet.frame["Date"].iloc[0])[:10] == "2024-01-01"


@pytest.mark.parametrize("title", ["EUR thousands", "EUR 000", "k EUR", "Revenue (€k)", "in thousands", "EUR '000"])
def test_units_are_read_from_the_title_rows(title):
    sheet = cr.read_sheet(f"Management accounts\n{title}\n\nMonth,Revenue,Cost of sales,Payroll\n2024-01-01,5,1,2\n2024-02-01,6,1,2\n".encode(), "x.csv")
    assert sheet.unit_scale == 1000 and sheet.unit_note and "multiplied by 1,000" in sheet.unit_note


def test_a_title_without_thousands_leaves_the_figures_alone():
    sheet = cr.read_sheet(b"Management accounts\nRevenue through 31 December 2028\n\nMonth,Revenue,Cost of sales,Payroll\n2024-01-01,5,1,2\n2024-02-01,6,1,2\n", "x.csv")
    assert sheet.unit_scale == 1 and sheet.unit_note is None


def test_thousands_scale_the_money_fields_in_the_engine_input_and_leave_the_stored_rows_alone(api):
    body = upload(api, "accountant_pnl.csv", (FIXTURES / "accountant_pnl.csv").read_bytes()).json()
    assert body["dtype"] == "pnl" and body["unit_note"] and "EUR thousands" in body["unit_note"]
    doc = api.db["datasets"].docs[0]
    assert doc["unit_scale"] == 1000 and doc["rows"][0]["Revenue"] == 120, "the file's own figures are stored as written"
    frame = server.normalize(doc["rows"], "pnl", doc["mapping"], doc["row_numbers"], doc["unit_scale"])
    assert frame["revenue"].iloc[0] == 120_000 and frame["_row"].iloc[0] == 6


# ---------------------------------------------------------------------------
# Fix 7: the miss message in place of the empty mapping rows
# ---------------------------------------------------------------------------
MISSED = [
    (revenue_to_2028(), "Revenue_to_2028.xlsx", "revenue", {"customer_id", "invoice_date", "currency"}),
    (pnl_to_2028(), "PnL_to_2028.xlsx", "pnl", {"sm_expense", "revenue", "cost_of_revenue"}),
    (crm_anonymous_to_2028(), "CRM_Anonymous_to_2028.xlsx", "crm", {"created_date", "close_date", "stage"}),
]


# The ids are the file names: the workbook bytes carry the time they were built, so two xdist workers would collect
# different ids and the run would stop before any test.
@pytest.mark.parametrize("content,name,word,missing", MISSED, ids=[name for _, name, _, _ in MISSED])
def test_the_three_files_that_missed_end_in_one_miss_message_that_names_what_is_missing(api, content, name, word, missing):
    api.state["adapter"] = t.FakeAdapter(replies=[type_reply(word), mapping_reply()])
    body = upload(api, name, content).json()
    assert body["dtype"] == word and body["sheet"] in ("Revenue", "P&L", "Accounts", "Annual tracker")
    if word == "pnl":       # a P&L statement is no longer a miss: its line table replaces the message (chat-upload.md section 26)
        assert body["miss"] is None and body["sheet_map"]["lines"] and body["pnl_grain"] == "yearly"
        return
    miss = body["miss"]
    assert miss and missing <= set(miss["missing"]), miss
    assert miss["looks"]["shape"] == ("summary" if word != "crm" else "table")
    assert not any(c["column"].startswith("Unnamed") for c in body["columns"])


def test_a_file_that_maps_cleanly_has_no_miss(api):
    body = upload(api, "stripe_invoices.csv", (FIXTURES / "stripe_invoices.csv").read_bytes()).json()
    assert body["miss"] is None and body["pending"] == 0


# ---------------------------------------------------------------------------
# Fix 9: the model is asked once per file, for its type, with the sheet names, title rows, headers and the masked sample
# ---------------------------------------------------------------------------
def test_rules_decide_the_type_and_the_model_is_not_asked_when_they_reach_80(api):
    upload(api, "accountant_pnl.csv", (FIXTURES / "accountant_pnl.csv").read_bytes())
    assert [json.loads(p)["type"] for p in adapter_of(api).payloads] == ["column_mapping"], "no file-type call"


def test_a_file_the_rules_cannot_place_is_sent_once_and_the_answer_is_kept_by_the_file_hash(api):
    api.state["adapter"] = t.FakeAdapter(replies=[type_reply("crm"), mapping_reply()])
    body = upload(api, "CRM_Anonymous_to_2028.xlsx", crm_anonymous_to_2028()).json()
    assert body["dtype"] == "crm" and body["type_source"] == "ai"
    type_calls = [p for p in adapter_of(api).payloads if json.loads(p)["type"] == "file_type"]
    assert len(type_calls) == 1, "one model call for the file's type"
    kept = [d for d in api.db["column_mappings"].docs if d.get("kind") == "file_type"]
    assert len(kept) == 1 and kept[0]["file_type"] == "crm" and len(kept[0]["file_hash"]) == 64
    calls = adapter_of(api).calls
    again = upload(api, "CRM_Anonymous_to_2028.xlsx", crm_anonymous_to_2028())
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "same_file" and adapter_of(api).calls == calls


def test_the_cached_type_is_used_for_the_same_bytes_without_a_model_call(api):
    api.state["adapter"] = t.FakeAdapter(replies=[type_reply("crm"), mapping_reply()])
    upload(api, "CRM.xlsx", crm_anonymous_to_2028())
    api.db["datasets"].docs.clear()
    calls = adapter_of(api).calls
    upload(api, "CRM.xlsx", crm_anonymous_to_2028())
    assert [p for p in adapter_of(api).payloads[calls:] if json.loads(p)["type"] == "file_type"] == []


def test_what_the_model_reads_for_a_file_type_is_sheet_names_title_rows_headers_and_the_masked_sample(api):
    api.state["adapter"] = t.FakeAdapter(replies=[type_reply("crm"), mapping_reply()])
    upload(api, "CRM.xlsx", crm_anonymous_to_2028())
    text = json.loads(adapter_of(api).payloads[0])["text"]
    parsed = redact.parse_file_type_text(text)
    assert [s["name"] for s in parsed] == ["Accounts", "Annual tracker", "Funnel and evidence"]
    assert [c["text"] for c in parsed[0]["titles"]] == ["Accounts through 31 December 2028", "EUR; accounts anonymised"]
    assert parsed[0]["headers"][0]["text"] == "Account ID" and len({c["row"] for c in parsed[0]["headers"]}) == 1
    assert all(len(v) <= 3 for s in parsed for v in s["samples"].values())
    for value in ("ACC-0001", "Mid-market", "no contradiction found", "Owner A", "email 2024-01-02", "Claimed"):
        assert value not in text, "no text cell value of a data row is sent"
    assert redact.file_type_text_problem(text) is None


def test_the_file_type_text_is_never_stored_and_its_title_is_never_logged(api, caplog):
    caplog.set_level(logging.DEBUG)
    api.state["adapter"] = t.FakeAdapter(replies=[type_reply("revenue"), mapping_reply()])
    upload(api, "Revenue_to_2028.xlsx", revenue_to_2028())
    stored = json.dumps([api.db[n].docs for n in ("llm_structures", "llm_calls", "column_mappings")], default=str)
    assert TITLE not in stored and "Source inputs" not in stored and "Revenue through" not in stored
    assert "Revenue through" not in caplog.text and "Source inputs" not in caplog.text
    assert any(r.get("structure_type") == "file_type" for r in api.db["llm_calls"].docs)


def test_no_consent_no_model_and_the_analyst_is_asked_for_the_type(api):
    api.db["audits"].docs[0]["structure_reading_consent"] = False
    body = upload(api, "CRM.xlsx", crm_anonymous_to_2028()).json()
    assert body["status"] == "unknown_type" and adapter_of(api).calls == 0


def test_a_failed_type_call_leaves_the_type_to_the_analyst(api):
    api.state["adapter"] = t.FakeAdapter(replies=["not json"])
    body = upload(api, "CRM.xlsx", crm_anonymous_to_2028()).json()
    assert body["status"] == "unknown_type" and api.db["datasets"].docs == []
    again = upload(api, "CRM.xlsx", crm_anonymous_to_2028(), dtype="crm").json()
    assert again["dtype"] == "crm" and again["type_source"] == "you"


def test_the_model_saying_unknown_leaves_the_type_to_the_analyst(api):
    api.state["adapter"] = t.FakeAdapter(replies=[type_reply("unknown")])
    assert upload(api, "CRM.xlsx", crm_anonymous_to_2028()).json()["status"] == "unknown_type"


def test_the_company_name_in_a_title_row_is_masked_before_the_model_reads_them(api):
    from openpyxl import Workbook
    import io
    wb = Workbook()
    ws = wb.active
    ws["C2"] = "Fixture Target Ltd monthly report"
    ws.append([])
    for j, h in enumerate(["Line", "2023", "2024", "2025"]):
        ws.cell(5, 3 + j, h)
    ws.cell(6, 3, "Metric")
    for j in range(3):
        ws.cell(6, 4 + j, 10 + j)
    buf = io.BytesIO()
    wb.save(buf)
    api.state["adapter"] = t.FakeAdapter(replies=[type_reply("unknown")])
    upload(api, "x.xlsx", buf.getvalue())
    text = json.loads(adapter_of(api).payloads[0])["text"]
    assert "Fixture Target Ltd" not in text and "[redacted]" in text


# ---------------------------------------------------------------------------
# Change the type
# ---------------------------------------------------------------------------
def test_the_analyst_changes_the_type_and_the_stored_sheet_is_read_as_the_new_type(api):
    api.state["adapter"] = t.FakeAdapter(replies=[type_reply("revenue"), mapping_reply()])
    first = upload(api, "CRM.xlsx", crm_anonymous_to_2028()).json()
    assert first["dtype"] == "revenue"
    resp = api.post(f"/api/audits/{AUDIT}/datasets/revenue/type", json={"to": "crm"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dtype"] == "crm" and body["type_source"] == "you"
    assert [d["dtype"] for d in api.db["datasets"].docs] == ["crm"], "the file is stored once, under the new type"
    assert {"stage", "close_date"} <= set(body["miss"]["missing"])


def test_a_type_that_is_already_loaded_needs_the_replace_answer(api):
    upload(api, "stripe_invoices.csv", (FIXTURES / "stripe_invoices.csv").read_bytes())
    upload(api, "hubspot_deals.csv", (FIXTURES / "hubspot_deals.csv").read_bytes())
    refused = api.post(f"/api/audits/{AUDIT}/datasets/crm/type", json={"to": "revenue"})
    assert refused.status_code == 409 and len(api.db["datasets"].docs) == 2
    assert api.post(f"/api/audits/{AUDIT}/datasets/crm/type", json={"to": "revenue", "replace": True}).status_code == 200


# ---------------------------------------------------------------------------
# Fix 8: one test per export layout: the required fields are mapped at 80 or more, or the miss message is shown
# ---------------------------------------------------------------------------
LAYOUTS = {"stripe_invoices.csv": "revenue", "xero_invoices.csv": "revenue", "hubspot_deals.csv": "crm", "pipedrive_deals.csv": "crm",
           "accountant_pnl.csv": "pnl", "wide_monthly_revenue.csv": "revenue"}


@pytest.mark.parametrize("name", sorted(LAYOUTS))
def test_each_export_layout_maps_its_required_fields_at_80_or_shows_the_miss_message(api, name):
    body = upload(api, name, (FIXTURES / name).read_bytes()).json()
    assert body["dtype"] == LAYOUTS[name], "the type is detected by the rules"
    required = body["fields"]["required"]
    rows = {c["field"]: c for c in body["columns"] if c["field"]}
    if body["miss"]:
        assert body["miss"]["missing"], "a miss names the missing fields"
        return
    for field in required:
        assert field in rows and rows[field]["confidence"] >= 80 and rows[field]["state"] == "auto", (field, rows.get(field))
    assert body["pending"] == 0
