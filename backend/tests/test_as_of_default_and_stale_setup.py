"""The as-of month default and stale results after a set-up change (George, 2026-10-24; docs/specs/chat-upload.md section 30):
synthetic files only. Python only, no network, no model.

5 the as-of month defaults to the revenue file's last actual month once it is mapped; a month the analyst set is kept; the revenue
dataset's months reach the screen for the warning line · 6 a change of Target ARR, Target date, As-of month, fiscal year-end or FX marks
the stored results "Stale – re-run audit" (no automatic recompute), and Run audit clears it."""
import asyncio
import copy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import contract_fixtures as cf  # noqa: E402
import growth_engine as ge  # noqa: E402
import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from test_dates_and_periods import _upload, run_engine, synthetic_revenue  # noqa: E402
from test_zero_division import SPEC  # noqa: E402

from app import run_audit  # noqa: E402

STALE = "Stale – re-run audit"


def pnl_to(last: str) -> bytes:
    """A synthetic P&L whose months run to `last`, past the revenue (a plan's months)."""
    rows = ["Month,S&M Expense,Revenue,Cost of Revenue"]
    y, m = 2018, 1
    while f"{y}-{m:02d}" <= last:
        rows.append(f"{y}-{m:02d}-01,20000,30000,6600.0")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return "\n".join(rows).encode("utf-8")


def run(as_of_month=None, revenue=None, pnl_last="2019-12"):
    uploads = {"revenue": _upload("revenue", "revenue.csv", revenue or synthetic_revenue("2017-07", "2019-06"))}
    if pnl_last:
        uploads["pnl"] = _upload("pnl", "pnl.csv", pnl_to(pnl_last))
    return run_engine(uploads, as_of_month)






def test_an_as_of_month_the_analyst_set_is_kept_before_and_after_the_revenue_files_last_month():
    assert run("2019-03-31")["as_of_month"] == "2019-03"
    later = run("2026-06-30")
    assert later["as_of_month"] == "2026-06" and later["source_period"]["month"] == "2019-06"


def test_the_engine_takes_the_stored_month_only_and_never_picks_one_from_the_data():
    """PR 196 review, finding 1: the old fallback chain (last revenue month, last P&L month, last MRR month) is gone."""
    import inspect
    assert str(ge._resolve_as_of("2019-03-31")) == "2019-03" and ge._resolve_as_of(None) is None
    assert ge._resolve_as_of.__code__.co_argcount == 1, "the engine reads no frame for it"
    source = inspect.getsource(ge._resolve_as_of)
    assert "revenue_months" not in source and "mrr" not in source and "pnl" not in source
    uploads = {"revenue": _upload("revenue", "revenue.csv", synthetic_revenue("2017-07", "2019-06"))}
    norm = {d: server.normalize(u["rows"], d, u["mapping"]) for d, u in uploads.items()}
    config = {"reporting_currency": "EUR", "target_arr": 0, "target_date": None, "fx": {"EUR": 1.0}, "billing_terms": {},
              "default_l": 1, "as_of_month": None}
    results = server.sanitize(ge.compute_all(norm["revenue"], server.pd.DataFrame(), server.pd.DataFrame(), config, {}))
    assert results["as_of_month"] is None, "no as-of month passed: none in the results, nothing cut (the server always passes one)"


def _fake_db(*datasets, audit=None):
    db = t.FakeDB()
    db["audits"].docs.append({"id": "aud-1", "company_name": "Acme", "reporting_currency": "EUR", **(audit or {})})
    db["datasets"].docs.extend({"audit_id": "aud-1", **d} for d in datasets)
    return db




def test_the_screen_gets_the_months_of_the_revenue_file(monkeypatch):
    months = {"count": 24, "first": "2017-07", "last": "2019-06"}
    monkeypatch.setattr(server, "db", _fake_db({"dtype": "revenue", "file": "revenue.csv", "months": months}))
    audit = asyncio.run(server.audit_public(copy.deepcopy(server.db["audits"].docs[0])))
    assert audit["datasets"]["revenue"]["months"] == months


@pytest.mark.parametrize("value,expected", [(None, False), ("", False), ("false", False), ("yes", False), ("true", True), (" TRUE ", True)])
def test_the_screen_gets_provider_zdr_as_one_boolean_that_is_off_unless_the_flag_says_true(monkeypatch, value, expected):
    """The Upload page text picks its deck sentence from this flag (docs/specs/chat-upload.md section 23); default off."""
    monkeypatch.setattr(server, "db", _fake_db())
    if value is None:
        monkeypatch.delenv("PROVIDER_ZDR", raising=False)
    else:
        monkeypatch.setenv("PROVIDER_ZDR", value)
    audit = asyncio.run(server.audit_public(copy.deepcopy(server.db["audits"].docs[0])))
    assert audit["provider_zdr"] is expected


# 6 --------------------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient
    db = t.FakeDB()
    db["audits"].docs.append({"id": "aud-1", "company_name": "Acme", "reporting_currency": "EUR", "status": "computed",
                              "target_arr": 1_000_000, "target_date": "2027-12-31", "as_of_month": "2024-02-29", "fiscal_year_end": 12,
                              "fx": {"USD": 0.9}, "results": cf.stored(nrr=cf.nrr(1.0641, 100), arr=cf.arr())})
    monkeypatch.setattr(server, "db", db)
    calls = []

    async def recompute(audit_id):
        calls.append(audit_id)

    async def remap(audit_id, fiscal_year_end):
        calls.append(("remap", fiscal_year_end))

    monkeypatch.setattr(server, "_run_compute", recompute)
    monkeypatch.setattr(server, "_remap_periods", remap)
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.calls = db, calls
    return client


def assert_stale(api):
    got = api.get("/api/audits/aud-1").json()
    assert got["results_stale"] is True and got["results"] is None, "no stored figure is shown as current"
    r = api.get("/api/audits/aud-1/results")
    assert r.status_code == 409 and r.json()["detail"] == {"code": "results_stale", "message": STALE}
    assert api.get("/api/audits/aud-1/claims").json()["results_stale"] is True
    assert not [c for c in api.calls if c == "aud-1"], "no automatic recompute: Run audit calculates again"
    assert run_audit.engine_stale(api.db["audits"].docs[0]) is True


def assert_current(api):
    assert api.get("/api/audits/aud-1").json()["results_stale"] is False
    assert api.get("/api/audits/aud-1/results").status_code == 200


@pytest.mark.parametrize("patch", [{"target_arr": 5_000_000}, {"target_date": "2028-12-31"}, {"as_of_month": "2024-03-31"},
                                   {"fiscal_year_end": 6}, {"reporting_currency": "USD"}])
def test_a_change_of_a_set_up_field_marks_the_stored_results_stale(api, patch):
    assert_current(api)
    assert api.put("/api/audits/aud-1", json=patch).status_code == 200
    assert_stale(api)


def test_clearing_the_as_of_month_marks_the_results_stale(api):
    assert api.put("/api/audits/aud-1", json={"as_of_month": None}).status_code == 200
    assert_stale(api)


def test_a_change_of_the_fx_rates_marks_the_stored_results_stale(api):
    assert api.put("/api/audits/aud-1/fx", json={"fx": {"USD": 0.95}}).status_code == 200
    assert_stale(api)
    api.db["audits"].docs[0].pop("setup_stale")
    assert api.put("/api/audits/aud-1/fx", json={"fx": {"USD": 0.95, "GBP": 1.15}}).status_code == 200
    assert_stale(api)


@pytest.mark.parametrize("patch", [{"target_arr": 1_000_000}, {"target_date": "2027-12-31"}, {"as_of_month": "2024-02-29"},
                                   {"fiscal_year_end": 12}, {"reporting_currency": "EUR"}, {"company_name": "Acme Ltd"}, {"analysis_date": "2026-10-24"}])
def test_the_same_value_or_another_field_leaves_the_results_current(api, patch):
    assert api.put("/api/audits/aud-1", json=patch).status_code == 200
    assert_current(api)


def test_the_same_fx_rates_leave_the_results_current(api):
    assert api.put("/api/audits/aud-1/fx", json={"fx": {"usd": 0.9}}).status_code == 200
    assert_current(api)


def test_an_audit_with_no_results_has_nothing_to_mark(api):
    api.db["audits"].docs[0].update(results=None, status="draft")
    assert api.put("/api/audits/aud-1", json={"target_arr": 5_000_000}).status_code == 200
    assert not api.db["audits"].docs[0].get("setup_stale")


def test_no_set_up_change_recomputes_on_its_own(api):
    """George, 2026-10-24 (PR 177): reporting currency and the as-of month mark the results stale like the rest; nothing recomputes."""
    for patch in ({"reporting_currency": "USD"}, {"as_of_month": "2024-03-31"}, {"target_arr": 5_000_000}):
        assert api.put("/api/audits/aud-1", json=patch).status_code == 200
    assert api.calls == []


def test_run_audit_calculates_again_and_clears_the_mark(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({"id": "aud-z", "reporting_currency": "EUR", "target_arr": SPEC["target_arr"], "target_date": SPEC["target_date"],
                              "as_of_month": None, "setup_stale": True, "results": cf.stored(arr=cf.arr())})
    import demo_data
    datasets, meta = demo_data.build(SPEC)
    for dtype, (df, mapping) in datasets.items():
        db["datasets"].docs.append({"audit_id": "aud-z", "dtype": dtype, "file": meta[dtype]["file"], "sheet": meta[dtype]["sheet"],
                                    "columns": list(df.columns), "rows": server.df_to_records(df), "mapping": mapping,
                                    "fx": meta.get("fx", {}), "billing_terms": {}})
    monkeypatch.setattr(server, "db", db)
    assert run_audit.results_stale(db["audits"].docs[0]) is True
    asyncio.run(server.compute_audit("aud-z"))
    audit = db["audits"].docs[0]
    assert audit["setup_stale"] is False and run_audit.results_stale(audit) is False and run_audit.engine_stale(audit) is False


def test_the_mark_alone_decides_for_results_of_the_current_contract():
    audit = {"results": cf.stored(arr=cf.arr()), "setup_stale": True}
    assert run_audit.results_stale(audit) is True
    assert run_audit.results_stale({**audit, "setup_stale": False}) is False
    assert run_audit.results_stale({"results": None, "setup_stale": True}) is False, "no results: nothing is stale"
