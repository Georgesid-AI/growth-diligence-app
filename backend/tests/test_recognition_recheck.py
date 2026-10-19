"""The re-check of PR 135 (owner decisions of 19 Oct 2026, comment on the re-check): one test per item, each built from a synthetic
sheet and each shown failing with its fix switched off (CLAUDE.md rule 11).

1 metrics sheet as a revenue summary reads the confirmed revenue row only · 2 deferred, unbilled and accrued revenue are never added ·
3 several currencies · 4 the size message · 5 the currency rule for every file type · 6 N1, an invoice list the rules cannot type."""
import importlib
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import test_llm_gateway as t  # noqa: E402
from test_chat_upload import AUDIT, mapping_reply, upload  # noqa: E402
from test_revenue_recognition import FIXTURES, csv_sheets, decide, recognition_reply, rules_only  # noqa: E402

YEAR = "2025-12-31"


@pytest.fixture()
def rec():
    return importlib.import_module("app.recognition")


# ---------------------------------------------------------------------------
# 1. A revenue summary built from a metrics sheet never sums rows
# ---------------------------------------------------------------------------
KPI_SHEET = """KPI pack (EUR),,,
Metric,Jan-25,Feb-25,Mar-25
Revenue,10000,11000,12000
Net revenue retention,1.1,1.05,1.02
Gross revenue retention,0.95,0.94,0.96
Revenue YTD,10000,21000,33000
Revenue LTM,120000,121000,122000
Deferred revenue,25000,26000,27000
Customers,40,41,42
"""


def test_1_a_revenue_summary_from_a_metrics_sheet_reads_the_confirmed_revenue_row_and_adds_nothing(rec):
    got = rec.recognise(csv_sheets(KPI_SHEET), as_of_month="2025-03-31", decisions={"file_type": "revenue_summary"})
    assert got["label_mode"] == "metric" and got["file_type"] == "revenue_summary"
    assert (got["revenue_row"]["row"], got["revenue_row"]["label"]) == (3, "Revenue")
    assert [s["value"] for s in got["series"]] == [10000, 11000, 12000], "net revenue retention, YTD, LTM and deferred revenue are not added"
    assert got["series_rows"] == [3] and got["series_basis"] == "row" and got["total_rows"] == []


def test_1_the_row_the_analyst_chose_is_the_row_that_is_read(rec):
    text = "Pack (EUR),,,\nMetric,Jan-25,Feb-25,Mar-25\nProduct A revenue,100,110,120\nProduct B revenue,50,60,70\nCustomers,4,5,6\nChurn,1,1,1\n"
    got = rec.recognise(csv_sheets(text), as_of_month="2025-03-31", decisions={"file_type": "revenue_summary", "revenue_row": 4})
    assert [s["value"] for s in got["series"]] == [50, 60, 70] and got["series_rows"] == [4]


def test_1_a_sheet_of_products_or_regions_is_still_summed(rec):
    text = "Revenue by product (EUR),,,\nProduct line,Jan-25,Feb-25,Mar-25\nPlatform,10,11,12\nSupport,20,21,22\nTraining,30,31,32\n"
    got = rec.recognise(csv_sheets(text), as_of_month="2025-03-31")
    assert got["label_mode"] == "entity" and got["series_basis"] == "sum_of_rows" and [s["value"] for s in got["series"]] == [60, 63, 66]


# ---------------------------------------------------------------------------
# 2. Q1: deferred, unbilled and accrued revenue are never added to a summed series
# ---------------------------------------------------------------------------
PRODUCTS = """Revenue by product (EUR),,,
Product line,Jan-25,Feb-25,Mar-25
Platform,10,11,12
Support,20,21,22
Training,30,31,32
Consulting,5,5,5
Licences,7,7,7
Hosting,3,3,3
"""
BALANCES = PRODUCTS + "Deferred revenue,1000,1000,1000\nUnbilled revenue,200,200,200\nAccrued revenue,300,300,300\n"


@pytest.mark.parametrize("label", ["Deferred revenue", "Unbilled revenue", "Accrued revenue", "Deferred revenue (balance)", "Accrued sales"])
def test_2_a_balance_row_is_never_added_to_a_summed_series(rec, label):
    got = rec.recognise(csv_sheets(PRODUCTS + f"{label},1000,1000,1000\n"), as_of_month="2025-03-31")
    assert got["series_basis"] == "sum_of_rows" and [s["value"] for s in got["series"]] == [75, 78, 81], label


def test_2_the_three_balance_rows_together_leave_the_products_alone(rec):
    got = rec.recognise(csv_sheets(BALANCES), as_of_month="2025-03-31")
    assert [s["value"] for s in got["series"]] == [75, 78, 81]
    assert got["series_rows"] == [3, 4, 5, 6, 7, 8]


def test_2_a_balance_row_is_no_candidate_for_the_revenue_row(rec):
    for label in ("Deferred revenue", "Unbilled revenue", "Accrued revenue"):
        assert rec.is_candidate_label(label) is False, label
    assert rec.is_candidate_label("Revenue") and rec.is_candidate_label("Net revenue")


# ---------------------------------------------------------------------------
# 4. Q3: the size message
# ---------------------------------------------------------------------------
def test_4_the_size_message_does_not_mention_the_recognition():
    import server
    assert server.DATASET_TOO_LARGE == "This file is too large to store. Split it or remove empty rows and upload again."


# ---------------------------------------------------------------------------
# 5. The currency rule, for every file type and for a file nothing types
# ---------------------------------------------------------------------------
MONTHS = ["Jan-25", "Feb-25", "Mar-25", "Apr-25", "May-25", "Jun-25"]


def invoices(title=None, head="Amount", fmt=lambda n, c: str(n), customer=True, extra=None):
    cols = (["Customer"] if customer else []) + ["Invoice Date", head]
    lines = ([f"{title},,"] if title else []) + [",".join(cols)]
    for m in range(1, 7):
        for c in range(1, 5):
            amount = fmt(1000 + 10 * c + m, c)
            cells = ([f"Customer {c}"] if customer else []) + [f"2025-{m:02d}-05", f'"{amount}"']
            lines.append(",".join(cells))
    return ("\n".join(lines) + "\n").encode()


def by_month(title=None, fmt=lambda n, c: str(n), head="Customer"):
    lines = ([f"{title},,,,,,"] if title else []) + [head + "," + ",".join(MONTHS)]
    lines += [f"Customer {c}," + ",".join(f'"{fmt(100 * c + 10 * m, c)}"' for m in range(6)) for c in range(1, 5)]
    return ("\n".join(lines) + "\n").encode()


sign = lambda s: (lambda n, c: f"{s}{n:,}")                                     # noqa: E731  "€1,200"
code_before = lambda k: (lambda n, c: f"{k} {n}")                               # noqa: E731  "EUR 1200"
code_after = lambda k: (lambda n, c: f"{n:,}.00 {k}")                           # noqa: E731  "1,200.00 EUR"
two = lambda a, b: (lambda n, c: a(n, c) if c % 2 else b(n, c))                 # noqa: E731
eur, usd = sign("€"), sign("$")
EUR_CODE, USD_CODE = code_before("EUR"), code_before("USD")

COLUMN_MAPPED = {                       # name: (file, dtype param, "found" | "none" | "mixed", codes)
    "invoice title": (invoices(title="Invoices (EUR)"), None, "found", ["EUR"]),
    "invoice header": (invoices(head="Amount (EUR)"), None, "found", ["EUR"]),
    "invoice sign": (invoices(fmt=eur), None, "found", ["EUR"]),
    "invoice code before": (invoices(fmt=EUR_CODE), None, "found", ["EUR"]),
    "invoice code after": (invoices(fmt=code_after("EUR")), None, "found", ["EUR"]),
    "invoice none": (invoices(), None, "none", []),
    "invoice mixed signs": (invoices(fmt=two(eur, usd)), None, "mixed", ["EUR", "USD"]),
    "invoice mixed codes": (invoices(fmt=two(EUR_CODE, USD_CODE)), None, "mixed", ["EUR", "USD"]),
    "invoice mixed codes after": (invoices(fmt=two(code_after("EUR"), code_after("USD"))), None, "mixed", ["EUR", "USD"]),
    "invoice without customer, none": (invoices(customer=False), "revenue", "none", []),
    "invoice without customer, found": (invoices(customer=False, head="Amount (EUR)"), "revenue", "found", ["EUR"]),
    "customers by month none": (by_month(), None, "none", []),
    "customers by month title": (by_month(title="Revenue by customer (EUR)"), None, "found", ["EUR"]),
    "customers by month sign": (by_month(fmt=eur), "revenue", "found", ["EUR"]),
    "customers by month code": (by_month(fmt=EUR_CODE), "revenue", "found", ["EUR"]),
    "customers by month mixed signs": (by_month(fmt=two(eur, usd)), "revenue", "mixed", ["EUR", "USD"]),
    "customers by month mixed codes": (by_month(fmt=two(EUR_CODE, USD_CODE)), "revenue", "mixed", ["EUR", "USD"]),
    "snapshot typed as revenue, none": ((FIXTURES / "arr_snapshot.csv").read_bytes().replace(b"EUR", b"").replace(b"(", b"").replace(b")", b""),
                                        "revenue", "none", []),
}


def missing_text(body):
    """What the screen shows as missing: the required fields and the miss message's list, both."""
    return sorted(set(body.get("missing_required") or []) | set((body.get("miss") or {}).get("missing") or []))


@pytest.mark.parametrize("name", list(COLUMN_MAPPED))
def test_5_a_file_with_a_column_mapping_never_says_currency_is_not_mapped_without_a_way_to_answer(api, name):
    content, dtype, kind, codes = COLUMN_MAPPED[name]
    rules_only(api, "2025-06-30")
    resp = upload(api, "file.csv", content, **({"dtype": dtype} if dtype else {}))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("dtype") == "revenue", f"{name}: {body}"
    if kind == "found":
        assert "currency" not in missing_text(body), name
        assert not body.get("currency_pending") and body["mapping"].get("currency"), f"{name}: the currency the file shows is applied"
    elif kind == "none":
        assert "currency" not in missing_text(body), name
        assert body.get("currency_pending") is True, f"{name}: the analyst is asked, with a picker"
        done = decide(api, action="change", part="currency", currency="EUR")
        assert done.status_code == 200, f"{name}: {done.text}"
        assert not done.json().get("currency_pending") and done.json()["mapping"]["currency"], name
    else:
        assert "currency" in missing_text(body) and not body.get("currency_pending"), f"{name}: mixed currencies still block"
        assert body.get("currency_mixed") == codes, name
        assert decide(api, action="change", part="currency", currency="EUR").status_code == 400, name
        assert api.post(f"/api/audits/{AUDIT}/compute").status_code == 409


def test_5_an_invoice_list_missing_both_customer_id_and_currency_names_only_the_customer(api):
    rules_only(api, "2025-06-30")
    body = upload(api, "inv.csv", invoices(customer=False), dtype="revenue").json()
    assert missing_text(body) == ["customer_id"] and body["currency_pending"] is True


def test_5_a_file_with_one_currency_in_a_column_and_nothing_else_is_unchanged(api):
    rules_only(api, "2025-06-30")
    text = invoices().decode().replace("Amount", "Amount,Currency").replace("\n2025", "\n2025")
    lines = text.splitlines()
    out = [lines[0]] + [ln + ",EUR" for ln in lines[1:]]
    body = upload(api, "inv.csv", ("\n".join(out) + "\n").encode()).json()
    assert missing_text(body) == [] and not body.get("currency_pending")


RECOGNITION_ONLY = {                    # a file read by recognition only: its recognition line carries the question
    "monthly report found": ("Pack (EUR),,,,,,\nMetric," + ",".join(MONTHS) + "\nRevenue,10,11,12,13,14,15\nCustomers,4,5,6,7,8,9\nChurn,1,1,1,1,1,1\nMRR,1,2,3,4,5,6\n",
                             "found", ["EUR"]),
    "monthly report none": ("Pack,,,,,,\nMetric," + ",".join(MONTHS) + "\nRevenue,10,11,12,13,14,15\nCustomers,4,5,6,7,8,9\nChurn,1,1,1,1,1,1\nMRR,1,2,3,4,5,6\n",
                            "none", []),
    "monthly report mixed": ("Pack,,,,,,\nMetric," + ",".join(MONTHS) + "\nRevenue (EUR),10,11,12,13,14,15\nOther revenue (USD),1,2,3,4,5,6\nCustomers,4,5,6,7,8,9\nChurn,1,1,1,1,1,1\n",
                             "mixed", ["EUR", "USD"]),
    "summary found": ("Revenue by product line (EUR),,,\nProduct line,Jan-25,Feb-25,Mar-25\nPlatform,10,11,12\nSupport,20,21,22\nTraining,30,31,32\n",
                      "found", ["EUR"]),
    "summary none": ("Revenue by product line,,,\nProduct line,Jan-25,Feb-25,Mar-25\nPlatform,10,11,12\nSupport,20,21,22\nTraining,30,31,32\n", "none", []),
    "summary mixed": ("Revenue by product line,,,\nProduct line,Jan-25,Feb-25,Mar-25\nPlatform,\"€10\",\"€11\",\"€12\"\nSupport,\"$20\",\"$21\",\"$22\"\nTraining,30,31,32\n",
                      "mixed", ["EUR", "USD"]),
    "statement found": ((FIXTURES / "pnl_monthly.csv").read_text(), None, None),
}


@pytest.mark.parametrize("name", [n for n, v in RECOGNITION_ONLY.items() if v[1] is not None])
def test_5_a_file_read_by_recognition_only_asks_the_currency_with_a_picker_or_reads_it_or_names_the_mix(api, name):
    text, kind, codes = RECOGNITION_ONLY[name]
    rules_only(api, "2025-03-31" if name.startswith("summary") else "2025-06-30")
    body = upload(api, "file.csv", text.encode()).json()
    assert body["dtype"] == "revenue" and body["recognition_only"] is True, f"{name}: {body.get('status')}"
    cur = body["recognition"]["currency"]
    if kind == "found":
        assert cur["state"] == "seen" and cur["code"] == codes[0], name
    elif kind == "none":
        assert cur == {"code": None, "state": "confirm"}, name
        done = decide(api, action="change", part="currency", currency="EUR")
        assert done.status_code == 200 and done.json()["recognition"]["currency"] == {"code": "EUR", "state": "you"}, name
    else:
        assert cur["mixed"] is True and cur["codes"] == codes, name
        assert decide(api, action="change", part="currency", currency="EUR").status_code == 400, name


def test_5_mixed_currencies_in_a_file_read_by_recognition_only_block_with_the_mixed_message_and_not_a_choice(api):
    rules_only(api, "2025-06-30")
    text = RECOGNITION_ONLY["monthly report mixed"][0]
    body = upload(api, "file.csv", text.encode()).json()
    assert body["recognition"]["currency"]["mixed"] is True and body["saved"] is False
    assert body["currency_mixed"] == ["EUR", "USD"], "the status line names the currencies found; no choice can clear it"


def test_5_an_untyped_file_has_no_currency_message_until_the_analyst_types_it(api):
    rules_only(api, "2025-06-30")
    body = upload(api, "x.csv", b"Alpha,Beta,Gamma\nx,y,z\nx,y,z\n").json()
    assert body["status"] == "unknown_type" and "currency" not in json.dumps(body["recognition"])
    typed = upload(api, "x.csv", invoices(), dtype="revenue").json()
    assert typed["dtype"] == "revenue" and "currency" not in missing_text(typed)


# ---------------------------------------------------------------------------
# 6. N1: an invoice list the rules cannot type
# ---------------------------------------------------------------------------
INVOICE_FIXTURE = (FIXTURES / "invoice_transactions.csv").read_bytes()


def invoice_reply():
    return recognition_reply(file_type="invoice_transactions", revenue_row=None, last_actual_column=None, currency="EUR", non_revenue_rows=[])


def test_n1_the_invoice_fixture_with_consent_is_stored_as_the_revenue_file_with_the_models_type(api):
    api.db["audits"].docs[0]["as_of_month"] = "2025-06-30"
    api.state["adapter"] = t.FakeAdapter(replies=[invoice_reply(), mapping_reply()])
    body = upload(api, "invoice_transactions.csv", INVOICE_FIXTURE).json()
    assert body.get("status") != "unknown_type", body
    assert body["dtype"] == "revenue" and body["type_source"] == "ai"
    assert body["recognition"]["file_type"] == "invoice_transactions"


def test_n1_the_invoice_fixture_without_consent_goes_to_the_type_picker(api):
    rules_only(api, "2025-06-30")
    body = upload(api, "invoice_transactions.csv", INVOICE_FIXTURE).json()
    assert body["status"] == "unknown_type" and api.db["datasets"].docs == []
    assert api.state["adapter"].calls == 0


def test_n1_the_invoice_fixture_after_a_failed_call_goes_to_the_type_picker(api):
    api.db["audits"].docs[0]["as_of_month"] = "2025-06-30"
    api.state["adapter"] = t.FakeAdapter(replies=["not json"])
    body = upload(api, "invoice_transactions.csv", INVOICE_FIXTURE).json()
    assert body["status"] == "unknown_type" and api.db["datasets"].docs == []


def test_n1_a_snapshot_the_model_names_still_goes_to_the_type_picker(api):
    api.db["audits"].docs[0]["as_of_month"] = "2025-06-30"
    api.state["adapter"] = t.FakeAdapter(replies=[recognition_reply(file_type="arr_mrr_snapshot", revenue_row=None, last_actual_column=None,
                                                                   currency="EUR", non_revenue_rows=[])])
    body = upload(api, "arr_snapshot.csv", (FIXTURES / "arr_snapshot.csv").read_bytes()).json()
    assert body["status"] == "unknown_type"
