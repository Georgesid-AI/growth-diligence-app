"""Access links for the tester phase (docs/specs/access-links.md; plan of 15 Oct 2026, section 6 and 7.1).

The four tests the plan requires before tester deployment. Every audit route is read from the app's own router, so a route
added later is covered without editing this file. They run the real access guard (marker `real_access`, conftest.py); every
other API test runs as one fixed tester. No network.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402

pytestmark = pytest.mark.real_access

OWNER = "owner-token-for-the-test-suite-only"
PARAMS = {"dtype": "revenue", "deck_id": "deck-1", "candidate_id": "c1", "claim_id": "c1", "stage": "engine",
          "step": "growth_engine", "page": "1"}


def audit_routes():
    """(method, path) of every route that reads or changes one audit: /api/audits/{audit_id}/... and /api/runs/{run_id}/..."""
    out = set()
    for route in server.app.routes:
        path = getattr(route, "path", "")
        if path.startswith(("/api/audits/{audit_id}", "/api/runs/{run_id}")):
            out |= {(m, path) for m in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}}
    return sorted(out)


def fill(path: str, audit_id: str) -> str:
    path = path.replace("{audit_id}", audit_id).replace("{run_id}", audit_id)
    return re.sub(r"\{(\w+)\}", lambda m: PARAMS[m.group(1)], path)


@pytest.fixture()
def access(monkeypatch):
    db = t.FakeDB()
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setenv("OWNER_TOKEN_SHA256", hashlib.sha256(OWNER.encode()).hexdigest())
    client = TestClient(server.app, raise_server_exceptions=False)
    owner = {"Authorization": f"Bearer {OWNER}"}

    def issue(label):
        r = client.post("/api/admin/testers", json={"label": label}, headers=owner)
        assert r.status_code == 200, r.text
        body = r.json()
        return body["id"], {"Authorization": f"Bearer {body['link'].rsplit('/t/', 1)[1]}"}

    a_id, a = issue("Tester A")
    b_id, b = issue("Tester B")
    created = client.post("/api/audits", json={"company_name": "BetaCo", "client_name": "Fund B"}, headers=b)
    assert created.status_code == 200, created.text
    return {"client": client, "db": db, "owner": owner, "a": a, "b": b, "b_id": b_id, "audit_b": created.json()["id"]}


def _call(client, method, url, headers=None):
    return client.request(method, url, headers=headers or {}, json={} if method in ("POST", "PUT") else None)


def test_1_no_token_is_401_on_every_route(access):
    client = access["client"]
    assert len(audit_routes()) >= 35, "the router lists the audit routes"
    assert client.get("/api/audits").status_code == 401
    assert client.post("/api/audits", json={"company_name": "X", "client_name": "Y"}).status_code == 401
    wrong = {m + " " + p: _call(client, m, fill(p, access["audit_b"])).status_code for m, p in audit_routes()}
    assert {k: v for k, v in wrong.items() if v != 401} == {}
    invalid = {"Authorization": "Bearer not-a-token"}
    assert client.get(f"/api/audits/{access['audit_b']}", headers=invalid).status_code == 401


def test_2_tester_a_on_tester_bs_audit_is_404_on_every_route_including_file_download_memo_and_export(access):
    client, a, audit_b = access["client"], access["a"], access["audit_b"]
    answers = {m + " " + p: _call(client, m, fill(p, audit_b), a).status_code for m, p in audit_routes()}
    assert {k: v for k, v in answers.items() if v != 404} == {}
    for url in (f"/api/audits/{audit_b}/memo.md", f"/api/audits/{audit_b}/export", f"/api/audits/{audit_b}/claims.csv"):
        assert client.get(url, headers=a).status_code == 404
    assert client.get(f"/api/audits/{audit_b}", headers=a).json() == client.get("/api/audits/no-such-audit", headers=a).json(), \
        "the same body as a missing audit"
    assert all(x["id"] != audit_b for x in client.get("/api/audits", headers=a).json()), "A's list holds A's audits only"
    assert client.get(f"/api/audits/{audit_b}", headers=access["b"]).status_code == 200


def test_3_an_expired_or_revoked_token_is_401(access, monkeypatch):
    from app import access as access_mod
    client, b, audit_b = access["client"], access["b"], access["audit_b"]
    later = datetime.now(timezone.utc) + timedelta(days=31)
    monkeypatch.setattr(access_mod, "utcnow", lambda: later)
    assert client.get(f"/api/audits/{audit_b}", headers=b).status_code == 401, "expired after 30 days"
    monkeypatch.setattr(access_mod, "utcnow", lambda: datetime.now(timezone.utc))
    assert client.get(f"/api/audits/{audit_b}", headers=b).status_code == 200
    assert client.post(f"/api/admin/testers/{access['b_id']}/revoke", headers=access["owner"]).status_code == 200
    assert client.get(f"/api/audits/{audit_b}", headers=b).status_code == 401, "revoked"


def test_4_the_owner_token_is_404_on_every_audit_route_and_sees_usage_totals_only(access):
    client, owner, audit_b = access["client"], access["owner"], access["audit_b"]
    answers = {m + " " + p: _call(client, m, fill(p, audit_b), owner).status_code for m, p in audit_routes()}
    assert {k: v for k, v in answers.items() if v != 404} == {}
    assert client.get("/api/usage/totals", headers=owner).status_code == 200
    assert client.get("/api/audits", headers=owner).json() == []
