"""V6 compute-before-Missing: before an item stays in missing_data, every upload is
tested for the columns the analysis needs. If one can answer it, the figure is computed
from that file and management is asked to explain it, not to supply it."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import growth_engine as ge  # noqa: E402
import server  # noqa: E402
from app.llm import gateway  # noqa: E402

REV_MAPPING = {"customer_id": "Customer", "invoice_date": "Invoice date", "amount": "Amount", "currency": "Currency"}
CFG = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None, "fx": {"EUR": 1.0},
       "billing_terms": {}, "default_l": 1, "as_of_month": None}

# Two won deals (30 and 61 days) and one lost deal, carried on the first invoice of each customer.
DEALS = {"C1": ("2024-01-02", "2024-02-01", "Won"), "C2": ("2024-01-01", "2024-03-02", "Won"),
         "C3": ("2024-01-05", "2024-02-10", "Lost")}


def _revenue_rows(with_deals: bool):
    rows = []
    for cust in ("C1", "C2"):
        for i, month in enumerate(pd.period_range("2024-03", periods=6, freq="M")):
            row = {"Customer": cust, "Invoice date": f"{month}-01", "Amount": 1000, "Currency": "EUR"}
            if with_deals:
                created, won, stage = DEALS[cust] if i == 0 else (None, None, None)
                row.update({"Created date": created, "Won date": won, "Stage": stage})
            rows.append(row)
    if with_deals:
        created, closed, stage = DEALS["C3"]
        rows.append({"Customer": "C3", "Invoice date": None, "Amount": None, "Currency": None,
                     "Created date": created, "Won date": closed, "Stage": stage})
    return rows


def _upload(rows, mapping, name):
    return {"file": name, "sheet": "Sheet1", "columns": list(rows[0].keys()), "rows": rows, "mapping": mapping}


def _crm_without_dates():
    rows = [{"Deal ID": "D1", "Stage": "Won", "Amount": 12000}, {"Deal ID": "D2", "Stage": "Lost", "Amount": 9000}]
    return _upload(rows, {"deal_id": "Deal ID", "stage": "Stage", "amount": "Amount",
                          "created_date": None, "close_date": None}, "crm.xlsx")


def _run(uploads):
    norm = {t: server.normalize(u["rows"], t, u["mapping"]) for t, u in uploads.items()}
    sources = {t: {"file": u["file"], "sheet": u["sheet"]} for t, u in uploads.items()}
    return server.sanitize(ge.compute_all(
        norm["revenue"], norm.get("crm", pd.DataFrame()), norm.get("pnl", pd.DataFrame()),
        CFG, sources, files=server.candidate_views(uploads)))


def _metrics(results):
    return [m["metric"] for m in results["missing_data"]]


# ---------------------------------------------------------------------------
# A revenue file answers the sales-cycle question the CRM file cannot
# ---------------------------------------------------------------------------
def test_sales_cycle_is_computed_from_the_revenue_file_when_the_crm_file_lacks_the_dates():
    uploads = {"revenue": _upload(_revenue_rows(with_deals=True), REV_MAPPING, "revenue.xlsx"),
               "crm": _crm_without_dates()}
    r = _run(uploads)

    sc = r["sales_cycle"]
    assert sc is not None and sc["n"] == 2
    assert sc["median_days"] == 45.5, "median of 30 and 61 days; the lost deal is not a won cycle"
    assert sc["status"] == "Computed – explanation requested"
    assert sc["source"]["file"] == "revenue.xlsx" and sc["source"]["dataset"] == "revenue"
    assert sc["source"]["columns"] == {"created_date": "Created date", "close_date": "Won date", "stage": "Stage"}
    assert sc["source"]["row_numbers"], "the citation names the rows"

    assert not any("Sales cycle" in m for m in _metrics(r)), "computed, so not Missing"
    [q] = [q for q in r["questions_for_management"] if q["result_key"] == "sales_cycle"]
    assert q["status"] == "Computed – explanation requested"
    assert q["dataset"] == "revenue" and q["file"] == "revenue.xlsx" and q["replaces_missing"] == "Sales cycle"
    assert "explain" in q["question"]

    # the CRM file still answers what it can: the win rate is its own, not a management question
    assert r["win_rate"]["won"] == 1 and r["win_rate"]["lost"] == 1 and "status" not in r["win_rate"]


def test_with_no_crm_upload_both_sales_cycle_and_win_rate_come_from_the_revenue_file():
    r = _run({"revenue": _upload(_revenue_rows(with_deals=True), REV_MAPPING, "revenue.xlsx")})
    assert r["sales_cycle"]["n"] == 2
    assert r["win_rate"]["won"] == 2 and r["win_rate"]["lost"] == 1
    assert {q["result_key"] for q in r["questions_for_management"]} >= {"sales_cycle", "win_rate"}
    assert "Sales cycle & win rate" not in _metrics(r)


# ---------------------------------------------------------------------------
# A true Missing: no upload has the columns
# ---------------------------------------------------------------------------
def test_sales_cycle_stays_missing_with_the_absent_fields_when_no_file_can_answer_it():
    uploads = {"revenue": _upload(_revenue_rows(with_deals=False), REV_MAPPING, "revenue.xlsx"),
               "crm": _crm_without_dates()}
    r = _run(uploads)

    assert r["sales_cycle"] is None
    [item] = [m for m in r["missing_data"] if m["metric"] == "Sales cycle"]
    assert item["status"] == "Missing"
    assert item["absent_fields"] == {"crm": ["created_date", "close_date"],
                                     "revenue": ["created_date", "close_date", "stage"]}
    assert not any(q["result_key"] == "sales_cycle" for q in r["questions_for_management"])


def test_can_compute_checks_every_file_and_names_what_each_lacks():
    files = server.candidate_views({"revenue": _upload(_revenue_rows(with_deals=False), REV_MAPPING, "rev.xlsx"),
                                    "crm": _crm_without_dates()})
    verdict = ge.can_compute("sales_cycle", files, expected="crm")
    assert verdict["computable"] is False
    assert list(verdict["absent_fields"]) == ["crm", "revenue"], "the expected file first, then every other upload"

    files = server.candidate_views({"revenue": _upload(_revenue_rows(with_deals=True), REV_MAPPING, "rev.xlsx"),
                                    "crm": _crm_without_dates()})
    verdict = ge.can_compute("sales_cycle", files, expected="crm")
    assert verdict["computable"] is True and verdict["dataset"] == "revenue"
    assert verdict["absent_fields"] == {"crm": ["created_date", "close_date"]}


def test_columns_present_but_no_usable_rows_do_not_count_as_an_answer():
    rows = _revenue_rows(with_deals=True)
    for row in rows:
        row["Stage"] = "Open" if row.get("Stage") else row.get("Stage")
    files = server.candidate_views({"revenue": _upload(rows, REV_MAPPING, "rev.xlsx")})
    verdict = ge.can_compute("sales_cycle", files, expected="crm")
    assert verdict["computable"] is False and verdict["absent_fields"] == {"revenue": []}


def test_items_that_are_not_analyses_stay_missing_with_a_status():
    rows = _revenue_rows(with_deals=False)
    rows[0]["Amount"] = None
    r = _run({"revenue": _upload(rows, REV_MAPPING, "revenue.xlsx")})
    blank = [m for m in r["missing_data"] if m["metric"] == "Revenue rows with blank amount"]
    assert blank and blank[0]["status"] == "Missing"


# ---------------------------------------------------------------------------
# The gateway reads stored results only
# ---------------------------------------------------------------------------
def test_the_gateway_payload_carries_both_lists_from_stored_results_only():
    uploads = {"revenue": _upload(_revenue_rows(with_deals=True), REV_MAPPING, "acme_revenue.xlsx"),
               "crm": _crm_without_dates()}
    r = _run(uploads)
    computed = {"reporting_currency": "EUR", "target_arr": 0, "metrics": gateway._slice_for_step(r, "growth_engine")}
    outbound = gateway.build_outbound(computed, {})   # formats every number; raises on an unregistered one

    metrics = outbound["metrics"]
    assert [q["result_key"] for q in metrics["questions_for_management"]] == ["sales_cycle"]
    assert all(m["status"] == "Missing" for m in metrics["missing_data"])
    assert metrics["sales_cycle"]["median_days"], "the computed figure is there for the model to cite"
    blob = json.dumps(outbound)
    assert "row_numbers" not in blob, "no row references"
    for raw in ("C1", "C2", "2024-01-02"):
        assert raw not in blob, f"raw cell {raw!r} must not reach the gateway"
