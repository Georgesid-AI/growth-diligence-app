"""Access links for the tester phase (docs/specs/access-links.md; plan of 15 Oct 2026, section 6 and 7.1).

The four tests the plan requires before tester deployment. Every audit route is read from the app's own router, so a route
added later is covered without editing this file. George approved the architecture change (15 Oct 2026). No network.
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

OWNER = "owner-token-for-the-test-suite-only"
PARAMS = {"dtype": "revenue", "deck_id": "deck-1", "candidate_id": "c1", "claim_id": "c1", "stage": "engine",
          "step": "growth_engine", "page": "1", "review_id": "r1", "file_hash": "0" * 64, "card_id": "card-1"}


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
    monkeypatch.delenv("ACCESS_DISABLED", raising=False)       # the suite runs with the check off; these tests need it on
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
    created = client.post("/api/audits", json={"company_name": "BetaCo"}, headers=b)
    assert created.status_code == 200, created.text
    return {"client": client, "db": db, "owner": owner, "a": a, "b": b, "b_id": b_id, "audit_b": created.json()["id"]}


def _call(client, method, url, headers=None):
    return client.request(method, url, headers=headers or {}, json={} if method in ("POST", "PUT") else None)


def test_1_no_token_is_401_on_every_route(access):
    client = access["client"]
    assert len(audit_routes()) >= 35, "the router lists the audit routes"
    assert client.get("/api/audits").status_code == 401
    assert client.post("/api/audits", json={"company_name": "X"}).status_code == 401
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


def test_3_an_expired_or_revoked_token_is_401_on_every_route(access, monkeypatch):
    from app import access as access_mod
    client, b, audit_b = access["client"], access["b"], access["audit_b"]
    routes = [(m, fill(p, audit_b)) for m, p in audit_routes()] + [("GET", "/api/audits"), ("POST", "/api/audits"), ("GET", "/api/usage/totals")]
    assert client.get(f"/api/audits/{audit_b}", headers=b).status_code == 200
    later = datetime.now(timezone.utc) + timedelta(days=31)
    monkeypatch.setattr(access_mod, "utcnow", lambda: later)
    assert {f"{m} {u}": _call(client, m, u, b).status_code for m, u in routes if _call(client, m, u, b).status_code != 401} == {}, "expired"
    monkeypatch.setattr(access_mod, "utcnow", lambda: datetime.now(timezone.utc))
    assert client.get(f"/api/audits/{audit_b}", headers=b).status_code == 200
    assert client.post(f"/api/admin/testers/{access['b_id']}/revoke", headers=access["owner"]).status_code == 200
    assert {f"{m} {u}": _call(client, m, u, b).status_code for m, u in routes if _call(client, m, u, b).status_code != 401} == {}, "revoked"


def test_4_the_owner_token_is_404_on_every_audit_route_and_sees_usage_totals_only(access):
    client, owner, audit_b = access["client"], access["owner"], access["audit_b"]
    answers = {m + " " + p: _call(client, m, fill(p, audit_b), owner).status_code for m, p in audit_routes()}
    assert {k: v for k, v in answers.items() if v != 404} == {}
    assert client.get("/api/usage/totals", headers=owner).status_code == 200
    assert client.get("/api/audits", headers=owner).status_code == 404, "the owner token lists no audit either"


def test_a_reissued_link_replaces_the_old_one_and_keeps_the_testers_audits(access):
    client, owner, b, audit_b = access["client"], access["owner"], access["b"], access["audit_b"]
    r = client.post(f"/api/admin/testers/{access['b_id']}/reissue", headers=owner)
    assert r.status_code == 200 and r.json()["id"] == access["b_id"]
    new = {"Authorization": f"Bearer {r.json()['link'].rsplit('/t/', 1)[1]}"}
    assert client.get(f"/api/audits/{audit_b}", headers=b).status_code == 401, "the old link is dead"
    assert client.get(f"/api/audits/{audit_b}", headers=new).status_code == 200, "the tester keeps their audits"


def test_a_tester_token_cannot_reach_the_admin_routes(access):
    client, a = access["client"], access["a"]
    for method, url in (("GET", "/api/admin/testers"), ("POST", "/api/admin/testers"),
                        ("POST", f"/api/admin/testers/{access['b_id']}/revoke")):
        assert _call(client, method, url, a).status_code == 404, url


def test_the_store_holds_hashes_only_and_a_token_is_never_stored_or_listed(access):
    client, db = access["client"], access["db"]
    token = access["b"]["Authorization"].split(" ", 1)[1]
    stored = db["access_tokens"].docs
    assert len(stored) == 2 and all(set(d) >= {"id", "label", "hash", "created_at", "expires_at", "revoked_at"} for d in stored)
    assert all(token not in str(d) for d in stored) and hashlib.sha256(token.encode()).hexdigest() in [d["hash"] for d in stored]
    listed = client.get("/api/admin/testers", headers=access["owner"]).json()
    assert [t["label"] for t in listed] == ["Tester A", "Tester B"] and all("hash" not in t for t in listed)
    audit = next(d for d in db["audits"].docs if d["id"] == access["audit_b"])
    assert audit["owner"] == access["b_id"] and token not in str(audit), "the audit holds the token's id, never the token"


def test_health_and_the_field_list_are_open(access):
    client = access["client"]
    assert client.get("/api/").status_code == 200 and client.get("/api/fields").status_code == 200


def _seed_usage(access):
    """Tester A and tester B each hold one audit with a note and one model call; A's note and B's note are told apart."""
    from app import usage as usage_mod
    db, client = access["db"], access["client"]
    a_audit = client.post("/api/audits", json={"company_name": "AlphaCo"}, headers=access["a"]).json()["id"]
    for audit_id, note, cost in ((a_audit, "NOTE-OF-A", 1.0), (access["audit_b"], "NOTE-OF-B", 2.0)):
        doc = next(d for d in db["audits"].docs if d["id"] == audit_id)
        doc["usage"] = usage_mod.empty()
        usage_mod.record_other_note(doc["usage"], note) if hasattr(usage_mod, "record_other_note") else doc["usage"]["other_notes"].append(
            {"note": note, "at": "2026-10-15T10:00:00+00:00"})
        db["llm_calls"].docs.append({"run_id": audit_id, "step": "growth_engine", "input_tokens": 100, "output_tokens": 10,
                                     "estimated_cost_usd": cost, "cache_hit": False})
    return a_audit


def test_usage_totals_are_for_the_owner_token_only_and_a_tester_gets_404(access):
    client = access["client"]
    _seed_usage(access)
    for tester in (access["a"], access["b"]):
        denied = client.get("/api/usage/totals", headers=tester)
        assert denied.status_code == 404 and "NOTE-OF" not in denied.text, "no tester reads any notes, calls or counts"
    everyone = client.get("/api/usage/totals", headers=access["owner"])
    assert "NOTE-OF-A" in everyone.text and "NOTE-OF-B" in everyone.text
    assert everyone.json()["tokens_and_cost_by_step"]["growth_engine"]["cost_usd"] == 3.0 and "scope" not in everyone.json()
    assert client.get("/api/usage/totals").status_code == 401
