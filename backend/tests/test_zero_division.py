"""No division by zero reaches the user as "Unexpected server error (ZeroDivisionError)".

Each zero base returns None with a plain reason that lands in Missing Data, and a metric
whose calculation still raises is reported as Missing while the others compute. The log
carries the error type, run id and engine step only. Stub only - no real API calls."""
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
os.environ.setdefault("DB_NAME", "test_zero_division")

import demo_data  # noqa: E402
import growth_engine as ge  # noqa: E402
import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402

SPEC = demo_data.DEMO_AUDITS[0]  # Apex Cloud demo: EUR, target ARR 40M


def _missing(results, metric):
    return [m for m in results["missing_data"] if m["metric"] == metric]


def _demo(as_of, target_date):
    datasets, meta = demo_data.build(SPEC)
    norm = {d: server.normalize(server.df_to_records(df), d, m) for d, (df, m) in datasets.items()}
    fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
    fx["EUR"] = 1.0
    config = {"reporting_currency": "EUR", "target_arr": SPEC["target_arr"], "target_date": target_date,
              "fx": fx, "billing_terms": {}, "default_l": 1, "as_of_month": as_of}
    sources = {d: {"file": meta[d]["file"], "sheet": meta[d]["sheet"]} for d in datasets}
    return ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], config, sources)


# ---------------------------------------------------------------------------
# The reproduced cases (demo data)
# ---------------------------------------------------------------------------
def test_demo_nrr_zero_segment_with_a_target_under_a_year_away_computes():
    """Reproduced: as-of 2024-01, target 2024-06-30 -> '0.0 cannot be raised to a negative power'."""
    results = _demo("2024-01", "2024-06-30")
    seg = results["segment_paths"]["stage_one"]["segments"]
    zero = [s for s, row in seg.items() if row["nrr_pct"] == 0]
    assert zero, "the fixture must have a segment at NRR 0%"
    for s in zero:
        assert seg[s]["arr_change_per_nrr_point"] is None
        item = _missing(results, f"ARR change per NRR point ({s})")
        assert item and "less than a year away" in item[0]["reason"]
    assert results["arr"]["value"] > 0, "the other metrics still compute"


def test_demo_target_date_on_the_first_of_the_next_month_computes():
    """Reproduced: as-of 2024-06, target 2024-07-01 -> 0 years -> 'float division by zero'."""
    results = _demo("2024-06", "2024-07-01")
    assert results["acv_path"]["required_net_new_per_year"] is None
    item = _missing(results, "Path to Plan (required net-new)")
    assert item and "less than a full day after the as-of month" in item[0]["reason"]
    assert _missing(results, "Segment paths to target ARR")


# ---------------------------------------------------------------------------
# One zero-base case per guarded division
# ---------------------------------------------------------------------------
def test_years_to_target_is_none_with_a_reason_when_the_horizon_is_under_a_day():
    years, error = ge._years_to_target(pd.Period("2024-06", "M"), "2024-07-01")
    assert years is None
    assert "less than a full day" in error
    assert ge._years_to_target(pd.Period("2024-06", "M"), "2024-07-02")[0] == pytest.approx(1 / 365)


def test_arr_change_per_nrr_point_at_nrr_zero_and_under_a_year_is_none_with_a_reason():
    """Segment A: its only customer a year ago has gone (NRR 0%); a newer customer is active."""
    rows = [("C1", f"{m}-01", 1000, "EUR", "A") for m in pd.period_range("2023-01", "2023-12", freq="M")]
    rows += [("C2", f"{m}-01", 500, "EUR", "A") for m in pd.period_range("2024-06", "2024-12", freq="M")]
    rev = pd.DataFrame(rows, columns=["customer_id", "invoice_date", "amount", "currency", "segment"])
    rev["_row"] = range(2, len(rev) + 2)
    cfg = {"reporting_currency": "EUR", "target_arr": 1_000_000, "target_date": "2025-06-30", "fx": {"EUR": 1.0},
           "billing_terms": {}, "default_l": 1, "as_of_month": None}
    results = ge.compute_all(rev, None, None, cfg, {"revenue": {"file": "revenue.csv", "sheet": "Sheet1"}})
    row = results["segment_paths"]["stage_one"]["segments"]["A"]
    assert row["nrr_pct"] == 0 and row["projected_arr"] == 0
    assert row["arr_change_per_nrr_point"] is None
    item = _missing(results, "ARR change per NRR point (A)")
    assert item and "NRR is 0%" in item[0]["reason"]


def test_reverse_solve_with_zero_years_is_not_computable_with_a_reason():
    landed = {"computable": True, "gross_new_per_year": 5.0, "segments": {"A": {"landed_acv": 1000.0}}}
    out = ge._reverse_solve(12, landed, gap=100_000.0, years=0.0, active_by_seg={"A": 3})
    assert out["computable"] is False
    assert out.get("required_vs_observed_gross") is None
    assert "no time" in out["reason"]


def _reconcile_inputs(current_mix_landed_acv):
    sp = {"available": True, "target_arr": 1_000_000.0, "gap_arr": 100_000.0,
          "reverse_solve": {"12": {"required_vs_observed_gross": 2.0,
                                   "current_mix_landed_acv": current_mix_landed_acv}},
          "landed": {"12": {"computable": True, "gross_new_per_year": 5.0}}}
    acv_path = {"observed_net_new_per_year_12m": 3.0, "total_customers_at_target": 100.0, "current_customers": 50}
    return acv_path, sp


def test_reconcile_with_zero_years_is_unavailable_with_a_reason():
    acv_path, sp = _reconcile_inputs(1000.0)
    out = ge._reconcile(12, acv_path, sp, years=0.0)
    assert out["available"] is False and out["reason"]


def test_reconcile_with_zero_landed_acv_at_the_current_mix_is_unavailable_with_a_reason():
    acv_path, sp = _reconcile_inputs(0.0)
    out = ge._reconcile(12, acv_path, sp, years=1.0)
    assert out["available"] is False and "landed ACV" in out["reason"]


# ---------------------------------------------------------------------------
# One failing metric: Missing with its reason, the rest still compute
# ---------------------------------------------------------------------------
def _break_cohort_retention(monkeypatch):
    """An error raised inside the real engine function (a first month it has no column for)."""
    real = ge.compute_cohort_retention
    monkeypatch.setattr(ge, "compute_cohort_retention",
                        lambda mrr, fm: real(mrr, {**fm, "ghost": pd.Period("1990-01", "M")}))


def test_one_failing_metric_is_missing_and_the_others_compute(monkeypatch):
    _break_cohort_retention(monkeypatch)
    errors = []
    datasets, meta = demo_data.build(SPEC)
    norm = {d: server.normalize(server.df_to_records(df), d, m) for d, (df, m) in datasets.items()}
    config = {"reporting_currency": "EUR", "target_arr": SPEC["target_arr"], "target_date": SPEC["target_date"],
              "fx": {**{k.upper(): v for k, v in meta["fx"].items()}, "EUR": 1.0}, "billing_terms": {},
              "default_l": 1, "as_of_month": None}
    results = ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], config,
                             {"revenue": {"file": "revenue.csv", "sheet": "Sheet1"}}, on_error=errors.append)
    assert [type(e).__name__ for e in errors] == ["KeyError"]
    assert results["cohort_retention"] == {"cohorts": [], "max_offset": 0, "data": []}
    item = _missing(results, "Cohort retention (calculation error)")
    assert item and "unexpected KeyError" in item[0]["reason"] and item[0]["file"] == "revenue.csv"
    for key in ("arr", "nrr", "gross_churn", "cac_payback", "win_rate", "acv_path"):
        assert results[key] is not None, key
    assert results["segment_paths"]["available"] is True


def test_the_compute_endpoint_survives_a_failing_metric_and_logs_type_run_id_and_step(monkeypatch, caplog):
    _break_cohort_retention(monkeypatch)
    datasets, meta = demo_data.build(SPEC)
    db = t.FakeDB()
    db["audits"].docs.append({"id": "aud-z", "reporting_currency": "EUR", "target_arr": SPEC["target_arr"],
                              "target_date": SPEC["target_date"], "as_of_month": None})
    for dtype, (df, mapping) in datasets.items():
        recs = server.df_to_records(df)
        db["datasets"].docs.append({"audit_id": "aud-z", "dtype": dtype, "file": meta[dtype]["file"],
                                    "sheet": meta[dtype]["sheet"], "columns": list(df.columns), "rows": recs,
                                    "mapping": mapping, "fx": meta.get("fx", {}), "billing_terms": {}})
    monkeypatch.setattr(server, "db", db)
    with caplog.at_level(logging.DEBUG):
        results = asyncio.run(server.compute_audit("aud-z"))
    assert results["arr"]["value"] > 0
    assert any(m["metric"] == "Cohort retention (calculation error)" for m in results["missing_data"])
    assert db["audits"].docs[0]["status"] == "computed"
    assert "metric failed: error=KeyError run_id=aud-z step=compute_cohort_retention" in caplog.text
    assert "1990" not in caplog.text, "the exception message is never logged"
    assert all(r.exc_info is None for r in caplog.records), "no traceback text in the log"
