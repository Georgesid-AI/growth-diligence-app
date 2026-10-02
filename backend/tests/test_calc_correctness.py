"""Calc-engine correctness: a shrinking base never yields a negative ratio, revenue rows
with no usable date are counted instead of dropped silently, a missing stage column lands
in Missing Data instead of crashing, and an engine error in the auto-recompute does not
fail the upload that triggered it. Stub only - no real API calls."""
import asyncio
import logging
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("motor")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_calc_correctness")

import growth_engine as ge  # noqa: E402
import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402

CFG = {"reporting_currency": "EUR", "target_arr": 5_000_000, "target_date": "2026-12-31", "fx": {"EUR": 1.0},
       "billing_terms": {}, "default_l": 1, "as_of_month": None}
SOURCES = {"revenue": {"file": "revenue.csv", "sheet": "Sheet1"}}


def _revenue(rows):
    df = pd.DataFrame(rows, columns=["customer_id", "invoice_date", "amount", "currency"])
    df["_row"] = range(2, len(df) + 2)
    return df


def _shrinking_revenue():
    """10 customers billed monthly for 2023; only 5 of them are still billed through 2024."""
    rows = []
    for c in range(10):
        last = "2024-12" if c < 5 else "2023-12"
        for m in pd.period_range("2023-01", last, freq="M"):
            rows.append((f"C{c}", f"{m}-01", 1000, "EUR"))
    return _revenue(rows)


def _missing(results, metric):
    return [m for m in results["missing_data"] if m["metric"] == metric]


def test_a_shrinking_base_gives_no_ratio_and_a_plain_reason_never_a_negative_ratio():
    results = ge.compute_all(_shrinking_revenue(), None, None, CFG, SOURCES)
    ap = results["acv_path"]
    assert ap["observed_net_new_per_year_12m"] < 0, "the fixture must be a shrinking base"
    assert ap["required_vs_observed_12m"] is None
    assert "shrinking" in ap["required_vs_observed_12m_reason"]
    item = _missing(results, "Required vs observed net-new customers (12m)")
    assert item and "ratio not meaningful" in item[0]["reason"]


def test_revenue_rows_with_an_unparseable_invoice_date_are_counted_not_dropped_silently():
    rows = [{"Customer": c, "Date": d, "Amount": a, "Currency": "EUR"}
            for c, d, a in (("C1", "2024-01-01", 1000), ("C1", "not a date", 1000),
                            ("C2", None, 500), ("C2", "2024-01-01", 500))]
    mapping = {"customer_id": "Customer", "invoice_date": "Date", "amount": "Amount", "currency": "Currency"}
    rev = server.normalize(rows, "revenue", mapping)  # unparseable dates arrive as NaT, as in a real upload
    results = ge.compute_all(rev, None, None, CFG, SOURCES)
    item = _missing(results, "Revenue rows with no usable invoice date")
    assert item, "the excluded rows must surface in Missing Data"
    assert item[0]["reason"].startswith("2 row(s)")
    assert "not a date" not in item[0]["reason"], "the row count only, never the raw cell value"


def test_crm_deals_without_a_stage_column_land_in_missing_data_instead_of_crashing():
    deals = pd.DataFrame({"deal_id": ["D1", "D2"], "created_date": ["2024-01-01", "2024-02-01"],
                          "close_date": ["2024-03-01", "2024-04-01"], "_row": [2, 3]})
    results = ge.compute_all(_shrinking_revenue(), deals, None, CFG, SOURCES)
    assert results["sales_cycle"] is None and results["win_rate"] is None
    item = _missing(results, "Sales cycle & win rate")
    assert item and "Stage column not mapped" in item[0]["reason"]


def test_an_engine_error_in_the_auto_recompute_is_logged_and_does_not_fail_the_caller(monkeypatch, caplog):
    db = t.make_db()
    audit = {"id": "aud-1", "status": "computed"}
    db["audits"].docs.append(audit)
    monkeypatch.setattr(server, "db", db)

    async def broken_compute(audit_id):
        raise KeyError("stage")

    monkeypatch.setattr(server, "_run_compute", broken_compute)
    with caplog.at_level(logging.ERROR, logger="growth"):
        asyncio.run(server._mark_stale_and_maybe_recompute("aud-1"))
    assert audit["metrics_stale"] is True, "results stay marked stale, not shown as current"
    assert "auto-recompute failed for audit aud-1" in caplog.text


def test_the_prompt_reports_a_missing_ratio_as_missing_and_names_the_segment_labels():
    from app.llm import prompt_store
    text = " ".join(prompt_store.load("growth_engine").text.split())
    assert 'A null ratio is Missing, never "within reach"' in text
    assert "Segments appear as labels (`Segment A`, `Segment B`, ...)" in text
