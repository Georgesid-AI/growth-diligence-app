"""Uploaded dates: day/month order is never guessed.

pandas infers the order of a whole column from its first value, so 03/04/2024 first
made every row month-first and silently dropped 13/04/2024. Now one day above 12 fixes
the order for the column (with a note); with none, the rows stay unread and Missing Data
asks management for the format, with the row count only."""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

pytest.importorskip("motor")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_date_order")

import growth_engine as ge  # noqa: E402
import server  # noqa: E402

CFG = {"reporting_currency": "EUR", "target_arr": 5_000_000, "target_date": "2026-12-31", "fx": {"EUR": 1.0},
       "billing_terms": {}, "default_l": 1, "as_of_month": None}
SOURCES = {"revenue": {"file": "revenue.csv", "sheet": "Sheet1"}}
MAPPING = {"customer_id": "Customer", "invoice_date": "Date", "amount": "Amount", "currency": "Currency"}


def _rev(dates):
    rows = [{"Customer": f"C{i}", "Date": d, "Amount": 100, "Currency": "EUR"} for i, d in enumerate(dates)]
    return server.normalize(rows, "revenue", MAPPING)


def _ts(*ymd):
    return [pd.Timestamp(*x) for x in ymd]


@pytest.mark.parametrize("bad", ["2027-1-5", "2027-01-5"])
def test_target_date_is_iso_only(bad):
    with pytest.raises(ValidationError):
        server.AuditCreate(company_name="Acme", target_date=bad)
    with pytest.raises(ValidationError):
        server.AuditUpdate(target_date=bad)


def test_one_day_above_12_sets_day_first_for_the_whole_column():
    df = _rev(["03/04/2024", "13/04/2024"])
    assert list(df["invoice_date"]) == _ts((2024, 4, 3), (2024, 4, 13))
    assert df.attrs["date_formats"] == {"invoice_date": {"order": "DD/MM/YYYY", "rows": 2}}


def test_one_day_above_12_in_second_place_sets_month_first():
    df = _rev(["03/04/2024", "04/13/2024"])
    assert list(df["invoice_date"]) == _ts((2024, 3, 4), (2024, 4, 13))
    assert df.attrs["date_formats"] == {"invoice_date": {"order": "MM/DD/YYYY", "rows": 2}}


def test_ambiguous_column_is_not_read():
    df = _rev(["03/04/2024", "05/06/2024", "2024-07-01T00:00:00"])
    assert df["invoice_date"].iloc[:2].isna().all()
    assert df["invoice_date"].iloc[2] == pd.Timestamp(2024, 7, 1)  # ISO is never ambiguous
    assert df.attrs["date_formats"]["invoice_date"]["order"] is None
    assert df.attrs["date_formats"]["invoice_date"]["rows"] == 2


def test_iso_and_day_first_values_mix():
    df = _rev(["2024-03-04T00:00:00", "13/04/2024"])
    assert list(df["invoice_date"]) == _ts((2024, 3, 4), (2024, 4, 13))


def test_ambiguous_dates_land_in_missing_data_with_the_row_count_only():
    res = ge.compute_all(_rev(["03/04/2024", "05/06/2024", "2024-07-01T00:00:00"]), None, None, CFG, SOURCES)
    items = [m for m in res["missing_data"] if m["metric"] == "Date format of invoice_date (revenue)"]
    assert len(items) == 1
    item = items[0]
    assert item["reason"].startswith("2 row(s)") and "management" in item["unlocked_by"].lower()
    text = " ".join(str(v) for v in item.values())
    assert "03/04" not in text and "05/06" not in text and "C0" not in text


def test_order_set_from_data_is_noted():
    res = ge.compute_all(_rev(["03/04/2024", "13/04/2024"]), None, None, CFG, SOURCES)
    assert res["anomalies"]["date_order_from_data"] == [
        {"dataset": "revenue", "field": "invoice_date", "order": "DD/MM/YYYY", "rows": 2}]
    assert not [m for m in res["missing_data"] if m["metric"].startswith("Date format")]


def test_ambiguous_rows_are_not_also_counted_as_missing_invoice_date():
    res = ge.compute_all(_rev(["03/04/2024", "05/06/2024", "", "2024-07-01T00:00:00"]), None, None, CFG, SOURCES)
    by_metric = {m["metric"]: m for m in res["missing_data"]}
    assert by_metric["Date format of invoice_date (revenue)"]["reason"].startswith("2 row(s)")
    assert by_metric["Revenue rows with no usable invoice date"]["reason"].startswith("1 row(s)")


@pytest.mark.parametrize("dates", [["03/04/2024", "05/06/2024", "2024-07-01T00:00:00"],   # ambiguous
                                   ["03/04/2024", "13/04/2024", "2024-07-01T00:00:00"]])  # order from data
def test_date_findings_reach_the_gateway_by_engine_field_name_only(dates):
    import json
    import asyncio
    import test_llm_gateway as t
    from app.llm import gateway

    header = "Acme Datum"
    rows = [{"Customer": f"C{i}", header: d, "Amount": 100, "Currency": "EUR"} for i, d in enumerate(dates)]
    rev = server.normalize(rows, "revenue", {**MAPPING, "invoice_date": header})
    results = server.sanitize(ge.compute_all(rev, None, None, CFG, SOURCES))
    assert results["missing_data"] or results["anomalies"]["date_order_from_data"], "fixture made no finding"

    db = t.FakeDB()
    db["audits"].docs.append({"id": t.RUN_ID, "results": results, "reporting_currency": "EUR",
                              "target_arr": CFG["target_arr"], "target_date": CFG["target_date"]})
    adapter = t.FakeAdapter()
    asyncio.run(gateway.generate_narrative(db, t.RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))
    sent = adapter.payloads[0]
    assert header.lower() not in sent.lower()
    if "13/04/2024" in dates:
        assert "date_order_from_data" not in sent  # anomalies are not in any step's slice
    else:
        item = [m for m in json.loads(sent)["metrics"]["missing_data"] if m["metric"].startswith("Date format")]
        assert item and item[0]["metric"] == "Date format of invoice_date (revenue)"
