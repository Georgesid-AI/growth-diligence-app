"""Amount columns named turnover, volume, GMV or TPV ask once: revenue or volume? (docs/specs/chat-upload.md section 15)"""
import pytest

import test_chat_upload as chat
from test_chat_upload import api, AUDIT  # noqa: F401  (the fixture)

from app import column_rules as cr

CSV = ("Customer ID,Invoice Date,{amount},Currency\n" + "\n".join(f"C{i},2024-01-{i + 1:02d},{100 + i},EUR" for i in range(8)) + "\n").encode()


def state(client):
    return next(c for c in chat.view(client)["columns"] if c["field"] == "amount" or c.get("money_ask"))


def money(client, kind, column):
    return client.post(f"/api/audits/{AUDIT}/datasets/revenue/decisions",
                       json=[{"column": column, "action": "confirm", "money_kind": kind}])


@pytest.mark.parametrize("header", ["Total Turnover", "Transaction Volume", "GMV", "TPV (EUR)", "Revenue Turnover"])
def test_the_header_words_ask_the_question(header):
    s = cr.new_state(header, "amount", "rules", "auto", 100)
    assert cr.asks_money(s) and cr.needs_money(s) and cr.pending_count([s]) == 1


@pytest.mark.parametrize("header", ["Amount", "Revenue", "Total", "ARR"])
def test_other_amount_headers_do_not(header):
    assert not cr.asks_money(cr.new_state(header, "amount", "rules", "auto", 100))


def test_only_a_mapped_amount_field_asks():
    assert not cr.asks_money(cr.new_state("Volume", None, None, "unused"))
    assert not cr.asks_money(cr.new_state("Volume", "currency", "rules", "auto", 100))


def test_an_amount_column_named_turnover_holds_the_mapping_until_the_analyst_answers(api):
    body = chat.upload(api, "f.csv", CSV.replace(b"{amount}", b"Total Turnover")).json()
    col = chat.by_column(body)["Total Turnover"]
    assert col["money_ask"] and col["pending"] and body["pending"] == 1 and not body["saved"]
    refused = api.post(f"/api/audits/{AUDIT}/compute")
    assert refused.status_code == 409
    done = money(api, "revenue", "Total Turnover").json()
    assert done["pending"] == 0 and done["saved"] and done["mapping"]["amount"] == "Total Turnover"
    assert done["columns"][[c["column"] for c in done["columns"]].index("Total Turnover")]["money_kind"] == "revenue"


def test_a_volume_column_never_feeds_the_engine_and_the_field_stays_open(api):
    chat.upload(api, "f.csv", CSV.replace(b"{amount}", b"Total Volume"))
    done = money(api, "volume", "Total Volume").json()
    assert done["mapping"]["amount"] is None and "amount" in done["missing_required"]


def test_the_answer_is_asked_once_and_reused_for_the_same_file(api):
    content = CSV.replace(b"{amount}", b"Total GMV")
    chat.upload(api, "f.csv", content)
    money(api, "volume", "Total GMV")
    again = chat.upload(api, "f.csv", content).json()
    assert again["pending"] == 0 and chat.by_column(again)["Total GMV"]["money_kind"] == "volume"


def test_a_bad_answer_or_a_column_that_does_not_ask_is_refused(api):
    chat.upload(api, "f.csv", CSV.replace(b"{amount}", b"Amount"))
    assert money(api, "volume", "Amount").status_code == 400
    assert api.post(f"/api/audits/{AUDIT}/datasets/revenue/decisions",
                    json=[{"column": "Amount", "action": "confirm", "money_kind": "gross"}]).status_code == 422


# The question also covers the P&L "revenue" field and the CRM "amount" field (MONEY_FIELDS), not only the revenue file's.
PNL = ("Month,Sales & Marketing,{revenue},Cost of revenue\n"
       + "\n".join(f"2024-{m:02d}-01,{1000 + m},{9000 + m},{3000 + m}" for m in range(1, 7)) + "\n").encode()
CRM = ("Deal ID,Created,Close Date,Stage,{amount}\n"
       + "\n".join(f"D{i},2024-01-{i + 1:02d},2024-02-{i + 1:02d},Won,{500 + i}" for i in range(8)) + "\n").encode()


def decide(client, dtype, kind, column):
    return client.post(f"/api/audits/{AUDIT}/datasets/{dtype}/decisions",
                       json=[{"column": column, "action": "confirm", "money_kind": kind}])


@pytest.mark.parametrize("dtype,field,header", [("pnl", "revenue", "Total Turnover"), ("crm", "amount", "Deal Volume")])
def test_the_question_covers_the_pnl_revenue_and_the_crm_amount_fields(dtype, field, header):
    assert cr.asks_money(cr.new_state(header, field, "rules", "auto", 100))
    assert not cr.asks_money(cr.new_state("Amount" if dtype == "crm" else "Revenue", field, "rules", "auto", 100))


def test_a_pnl_turnover_column_holds_the_mapping_until_answered_and_a_volume_answer_drops_it(api):
    body = chat.upload(api, "pnl.csv", PNL.replace(b"{revenue}", b"Turnover")).json()
    assert body["dtype"] == "pnl"
    col = chat.by_column(body)["Turnover"]
    assert col["field"] == "revenue" and col["money_ask"] and col["pending"] and not body["saved"]
    kept = decide(api, "pnl", "revenue", "Turnover").json()
    assert kept["pending"] == 0 and kept["mapping"]["revenue"] == "Turnover"
    chat.upload(api, "pnl.csv", PNL.replace(b"{revenue}", b"Turnover"), replace="true")
    dropped = decide(api, "pnl", "volume", "Turnover").json()
    assert dropped["pending"] == 0 and dropped["mapping"]["revenue"] is None and "revenue" in dropped["missing_required"]


def test_a_crm_deal_volume_column_asks_and_a_volume_answer_keeps_it_out_of_the_mapping(api):
    body = chat.upload(api, "crm.csv", CRM.replace(b"{amount}", b"Value (GMV)")).json()
    assert body["dtype"] == "crm"
    col = chat.by_column(body)["Value (GMV)"]
    assert col["field"] == "amount" and col["money_ask"] and col["pending"]
    dropped = decide(api, "crm", "volume", "Value (GMV)").json()
    assert dropped["mapping"]["amount"] is None and "amount" in dropped["missing_required"]
