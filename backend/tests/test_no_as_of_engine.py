"""F4 of the review of PR 205 (read-check-review.md section 6): with no confirmed and no typed as-of month the engine computes nothing that
reads a month. Every month-dependent block is Missing with "as-of month not determined" and no period; the engine never computes to the last
month with data and never marks a source period complete. Synthetic data only (rule 15)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import growth_engine as ge  # noqa: E402
import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from test_dates_and_periods import _upload, synthetic_revenue  # noqa: E402

from app import as_of as as_of_mod  # noqa: E402
from app import run_audit  # noqa: E402

REASON = "as-of month not determined"
MONTH_BLOCKS = ("arr", "nrr", "gross_churn", "acv_path", "cac_payback", "sales_cycle", "win_rate", "won_deal_closes", "anomalies")
PNL = (b"Month,S&M Expense,Revenue,Cost of Revenue\n" + b"".join(f"2019-{m:02d}-01,20000,30000,6600.0\n".encode() for m in range(1, 7)))
CRM = (b"Deal ID,Created Date,Close Date,Stage,Amount\nD1,2019-01-05,2019-03-01,Closed Won,1000\nD2,2019-02-05,2019-04-01,Closed Lost,900\n")


def uploads():
    ups = {"revenue": _upload("revenue", "revenue.csv", synthetic_revenue("2017-07", "2019-06")),
           "pnl": _upload("pnl", "pnl.csv", PNL), "crm": _upload("crm", "crm.csv", CRM)}
    return ups, {d: server.normalize(u["rows"], d, u["mapping"]) for d, u in ups.items()}


def engine(as_of_month):
    ups, norm = uploads()
    config = {"reporting_currency": "EUR", "target_arr": 1_000_000, "target_date": "2027-12-31", "fx": {"EUR": 1.0}, "billing_terms": {},
              "default_l": 1, "as_of_month": as_of_month}
    sources = {d: {"file": u["file"], "sheet": u["sheet"]} for d, u in ups.items()}
    return server.sanitize(ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], config, sources, files=server.candidate_views(ups)))


def test_with_a_month_the_same_files_compute_every_block():
    got = engine("2019-06-30")
    assert got["source_period"]["status"] == "Complete" and got["arr"] and got["revenue_series"]["data"]


def test_with_no_month_no_block_that_reads_a_month_is_computed_and_no_source_period_is_complete():
    got = engine(None)
    assert got["as_of_month"] is None and got["source_period"] is None and got["metric_periods"] == {}
    for key in MONTH_BLOCKS:
        assert not got[key], key
    for key in ("revenue_series", "mrr_series", "customers_series", "cohort_retention"):
        assert not got[key]["data"], key
    assert not got["new_mrr_by_quarter"] and not got["revenue_reconciliation"]
    assert "Complete" not in repr(got), "no period is marked complete"


def test_every_month_dependent_block_of_the_files_held_is_missing_with_the_one_line():
    got = engine(None)
    missing = {m["metric"]: m for m in got["missing_data"]}
    assert {"ARR / MRR", "NRR (12-month)", "Gross revenue churn", "Path to Plan", "Revenue by month", "CAC payback",
            "Revenue reconciliation", "Sales cycle & win rate", "Won deals by close month"} <= set(missing)
    assert {m["reason"] for m in missing.values()} == {REASON} and all(m["status"] == "Missing" for m in missing.values())
    assert {m["file"] for m in missing.values()} == {"revenue.csv", "pnl.csv", "crm.csv"}
    assert got["questions_for_management"] == []


def test_a_dataset_the_audit_does_not_hold_is_not_listed():
    ups, norm = uploads()
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None, "fx": {"EUR": 1.0}, "billing_terms": {}, "default_l": 1,
              "as_of_month": None}
    got = server.sanitize(ge.compute_all(norm["revenue"], server.pd.DataFrame(), server.pd.DataFrame(), config,
                                         {"revenue": {"file": "revenue.csv", "sheet": "Sheet1"}}))
    metrics = {m["metric"] for m in got["missing_data"]}
    assert "ARR / MRR" in metrics and not {"CAC payback", "Sales cycle & win rate", "P&L lines"} & metrics


@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient
    ups, _ = uploads()
    db = t.FakeDB()
    db["audits"].docs.append({"id": "aud-1", "company_name": "Acme", "reporting_currency": "EUR", "status": "mapped", "target_arr": 0,
                              "target_date": None, "as_of_month": None, "as_of_by": "detected", "fiscal_year_end": 12, "fx": {}})
    for dtype, u in ups.items():
        db["datasets"].docs.append({"audit_id": "aud-1", "dtype": dtype, "file": u["file"], "sheet": u["sheet"], "rows": u["rows"],
                                    "mapping": u["mapping"], "columns": u["columns"], "mapped_at": "2026-01-01"})

    async def counts(audit_id, audit, datasets=None):
        return {"open": 0, "missing_required": 0}, True

    async def nothing(*a, **k):
        return {}

    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "_mapping_counts", counts)
    monkeypatch.setattr(server, "_enter_matched_claims", nothing)
    monkeypatch.setattr(server, "_claims_files", lambda audit_id: _async([]))
    monkeypatch.setattr(server, "_is_revenue_file", lambda *a, **k: _async(True))
    monkeypatch.setattr(server, "_usage_update", nothing)
    monkeypatch.setattr(as_of_mod, "detect", lambda *a, **k: None)         # no file gives a confirmed month
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db = db
    return client


async def _async(value):
    return value


def test_run_audit_on_files_with_no_confirmed_month_stores_missing_blocks_and_no_period(api):
    out = api.post("/api/audits/aud-1/run/engine").json()
    assert (out["status"], out["message"]) == ("done", run_audit.NO_AS_OF)
    stored = api.db["audits"].docs[0]["results"]
    assert stored["as_of_month"] is None and stored["source_period"] is None and stored["arr"] is None
    assert {m["reason"] for m in stored["missing_data"]} == {REASON}
    assert stored["revenue_series"]["data"] == [] and stored["nrr"] is None


def test_run_audit_with_a_typed_month_computes(api):
    api.db["audits"].docs[0].update(as_of_month="2019-06-30", as_of_by="analyst")
    out = api.post("/api/audits/aud-1/run/engine").json()
    assert (out["status"], out["message"]) == ("done", None)
    stored = api.db["audits"].docs[0]["results"]
    assert stored["as_of_month"] == "2019-06" and stored["arr"] and stored["source_period"]["status"] == "Complete"
