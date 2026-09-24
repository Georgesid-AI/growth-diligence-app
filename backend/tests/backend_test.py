"""Backend API tests for Growth Diligence engine (Phase 1)."""
import os
import io
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip()
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"

SAMPLES = {
    "revenue": "/app/sample_data/revenue.csv",
    "crm": "/app/sample_data/crm.csv",
    "pnl": "/app/sample_data/pnl.csv",
}


@pytest.fixture(scope="module")
def session():
    return requests.Session()


# --- Demo seeded audits ---
def test_list_audits_has_two_demos(session):
    r = session.get(f"{API}/audits", timeout=30)
    assert r.status_code == 200
    data = r.json()
    computed = [a for a in data if a.get("status") == "computed"]
    assert len(computed) >= 2, f"Expected >=2 computed demo audits, got {len(computed)}"


def test_demo_audit_results_endpoint(session):
    r = session.get(f"{API}/audits", timeout=30)
    demos = [a for a in r.json() if a.get("status") == "computed"]
    assert demos
    aid = demos[0]["id"]
    rr = session.get(f"{API}/audits/{aid}/results", timeout=30)
    assert rr.status_code == 200
    body = rr.json()
    assert "audit" in body and "results" in body
    assert "arr" in body["results"]


# --- CRUD ---
@pytest.fixture(scope="module")
def new_audit(session):
    payload = {"company_name": "TEST_Acme", "reporting_currency": "EUR",
               "target_arr": 500000, "target_date": "2025-12-31"}
    r = session.post(f"{API}/audits", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["status"] == "draft" and a["company_name"] == "TEST_Acme"
    yield a
    session.delete(f"{API}/audits/{a['id']}", timeout=30)


def test_get_audit_has_datasets_field(session, new_audit):
    r = session.get(f"{API}/audits/{new_audit['id']}", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "datasets" in body and isinstance(body["datasets"], dict)


def test_results_409_when_not_computed(session, new_audit):
    r = session.get(f"{API}/audits/{new_audit['id']}/results", timeout=30)
    assert r.status_code == 409


# --- Upload flow ---
REQUIRED_FIELDS = {
    "revenue": ["customer_id", "invoice_date", "amount", "currency"],
    "crm": ["deal_id", "created_date", "close_date", "stage", "amount"],
    "pnl": ["month", "sm_expense", "revenue", "cost_of_revenue"],
}


@pytest.fixture(scope="module")
def uploaded(session, new_audit):
    result = {}
    for dtype, path in SAMPLES.items():
        with open(path, "rb") as f:
            files = {"file": (os.path.basename(path), f, "text/csv")}
            r = session.post(f"{API}/audits/{new_audit['id']}/datasets/{dtype}/upload",
                             files=files, timeout=60)
        assert r.status_code == 200, f"{dtype} upload: {r.status_code} {r.text}"
        result[dtype] = r.json()
    return result


def test_revenue_upload_mapping(uploaded):
    body = uploaded["revenue"]
    assert body["row_count"] > 0
    sm = body["suggested_mapping"]
    for f in REQUIRED_FIELDS["revenue"]:
        assert sm.get(f), f"revenue missing required mapping: {f} -> {sm}"


def test_crm_upload_mapping(uploaded):
    body = uploaded["crm"]
    sm = body["suggested_mapping"]
    for f in REQUIRED_FIELDS["crm"]:
        assert sm.get(f), f"crm missing required mapping: {f} -> {sm}"


def test_pnl_upload_mapping_cost_of_revenue_correct(uploaded):
    body = uploaded["pnl"]
    sm = body["suggested_mapping"]
    for f in REQUIRED_FIELDS["pnl"]:
        assert sm.get(f), f"pnl missing required mapping: {f} -> {sm}"
    # Critical: cost_of_revenue must map to 'Cost of Revenue', not 'Revenue'
    assert sm["cost_of_revenue"] == "Cost of Revenue", (
        f"pnl cost_of_revenue mismapped to {sm['cost_of_revenue']}")
    assert sm["revenue"] == "Revenue"


# --- Save mapping + compute ---
def test_save_mapping_and_compute(session, new_audit, uploaded):
    aid = new_audit["id"]
    for dtype, body in uploaded.items():
        payload = {"mapping": body["suggested_mapping"], "fx": {}, "billing_terms": {}}
        r = session.put(f"{API}/audits/{aid}/datasets/{dtype}/mapping",
                        json=payload, timeout=30)
        assert r.status_code == 200, r.text

    r = session.post(f"{API}/audits/{aid}/compute", timeout=120)
    assert r.status_code == 200, r.text
    res = r.json()

    # arr, nrr, sales_cycle, win_rate present with values
    assert res["arr"]["value"] > 0
    assert 100 < res["nrr"]["overall_pct"] < 120, f"NRR expected ~112 got {res['nrr']['overall_pct']}"
    assert 40 < res["sales_cycle"]["median_days"] < 90, f"sales cycle expected ~60 got {res['sales_cycle']['median_days']}"
    assert res["win_rate"]["win_rate_pct"] > 0

    # missing_data empty when all mapped
    assert res.get("missing_data") == [], f"missing_data: {res.get('missing_data')}"

    # every metric has source with file/sheet
    for key in ("arr", "nrr", "sales_cycle", "win_rate"):
        m = res[key]
        assert "source" in m and m["source"].get("file") and m["source"].get("sheet"), \
            f"{key} missing source metadata: {m.get('source')}"


# --- Delete ---
def test_delete_audit_cleans_datasets(session):
    r = session.post(f"{API}/audits", json={"company_name": "TEST_Del", "reporting_currency": "EUR"}, timeout=30)
    aid = r.json()["id"]
    with open(SAMPLES["revenue"], "rb") as f:
        session.post(f"{API}/audits/{aid}/datasets/revenue/upload",
                     files={"file": ("revenue.csv", f, "text/csv")}, timeout=30)
    d = session.delete(f"{API}/audits/{aid}", timeout=30)
    assert d.status_code == 200
    g = session.get(f"{API}/audits/{aid}", timeout=30)
    assert g.status_code == 404
