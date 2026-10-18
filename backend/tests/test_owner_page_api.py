"""The owner routes (docs/specs/prompt-store.md section 3).

Prompts: list by name, version and date; upload a new version; nothing deleted; the text never comes back. Owner token only: no
token or an unknown one is 401, a tester's token is 404 (the guard of docs/specs/access-links.md; the tester links themselves are
tested in test_access_links.py). These run the real access guard. No network.
"""
import hashlib
import logging

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402

OWNER = "owner-token-for-the-test-suite-only"
SECRET = "SECRET-METHODOLOGY-SENTINEL-4471"
ADMIN_ROUTES = [("GET", "/api/admin/prompts"), ("POST", "/api/admin/prompts"), ("GET", "/api/admin/testers"),
                ("POST", "/api/admin/testers"), ("POST", "/api/admin/testers/x/revoke"), ("POST", "/api/admin/testers/x/reissue"),
                ("GET", "/api/admin/usage"), ("POST", "/api/admin/testers/x/allowance")]


@pytest.fixture()
def owner(monkeypatch):
    db = t.FakeDB()
    db["prompts"].docs.clear()
    monkeypatch.setattr(server, "db", db)
    monkeypatch.delenv("ACCESS_DISABLED", raising=False)          # the suite runs with the check off; these tests need it on
    monkeypatch.setenv("OWNER_TOKEN_SHA256", hashlib.sha256(OWNER.encode()).hexdigest())
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.headers_owner = db, {"Authorization": f"Bearer {OWNER}"}
    return client


def token_of(body):
    assert body["link"].count("/t/") == 1
    return body["link"].rsplit("/t/", 1)[1]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_the_admin_routes_are_the_routes_this_file_lists():
    listed = {(m, p) for r in server.app.routes if getattr(r, "path", "").startswith("/api/admin/")
              for p in [r.path] for m in r.methods - {"HEAD", "OPTIONS"}}
    assert {(m, p.replace("{tester_id}", "x")) for m, p in listed} == set(ADMIN_ROUTES), "a new admin route is tested here too"


def test_no_token_or_an_unknown_one_is_401_and_a_tester_token_is_404_on_every_admin_route(owner):
    tester = owner.post("/api/admin/testers", json={"label": "Tester"}, headers=owner.headers_owner).json()
    for method, path in ADMIN_ROUTES:
        body = {} if method == "POST" else None
        assert owner.request(method, path, json=body).status_code == 401, (method, path)
        assert owner.request(method, path, json=body, headers=bearer("not-a-token")).status_code == 401, (method, path)
        assert owner.request(method, path, json=body, headers=bearer(token_of(tester))).status_code == 404, (method, path)


def test_the_owner_uploads_a_prompt_and_lists_it_by_name_version_and_date_without_its_text(owner):
    empty = owner.get("/api/admin/prompts", headers=owner.headers_owner).json()
    assert empty["prompts"] == [] and empty["missing"] == empty["names"] and "growth_engine" in empty["names"]
    first = owner.post("/api/admin/prompts", json={"name": "growth_engine", "text": f"{SECRET} one"}, headers=owner.headers_owner)
    second = owner.post("/api/admin/prompts", json={"name": "growth_engine", "text": f"{SECRET} two"}, headers=owner.headers_owner)
    assert first.status_code == second.status_code == 200
    assert (first.json()["version"], second.json()["version"]) == ("v1", "v2")
    listed = owner.get("/api/admin/prompts", headers=owner.headers_owner).json()
    assert [(r["name"], r["version"]) for r in listed["prompts"]] == [("growth_engine", "v2"), ("growth_engine", "v1")]
    assert all(set(r) == {"name", "version", "uploaded_at", "sha256"} for r in listed["prompts"])
    assert "growth_engine" not in listed["missing"] and "data_integrity" in listed["missing"]
    for response in (first, second, owner.get("/api/admin/prompts", headers=owner.headers_owner)):
        assert SECRET not in response.text, "prompt text never comes back"
    assert owner.db["prompts"].docs[1]["text"] == f"{SECRET} two"


@pytest.mark.parametrize("payload", [{"name": "nope", "text": "x"}, {"name": "growth_engine", "text": "  "},
                                     {"name": "growth_engine"}, {"text": "x"}])
def test_a_refused_upload_is_422_and_stores_nothing(owner, payload):
    assert owner.post("/api/admin/prompts", json=payload, headers=owner.headers_owner).status_code == 422
    assert owner.db["prompts"].docs == []


def test_there_is_no_route_to_delete_change_or_read_a_prompt(owner):
    for method in ("DELETE", "PUT", "PATCH"):
        assert owner.request(method, "/api/admin/prompts", headers=owner.headers_owner).status_code == 405
    for path in ("/api/admin/prompts/growth_engine", "/api/admin/prompts/growth_engine/v1"):
        assert owner.get(path, headers=owner.headers_owner).status_code == 404


def test_the_owner_page_calls_show_no_audit_data(owner):
    audit = owner.post("/api/admin/testers", json={"label": "T"}, headers=owner.headers_owner).json()
    created = owner.post("/api/audits", json={"company_name": "AuditedCo", "client_name": "Fund"}, headers=bearer(token_of(audit)))
    assert created.status_code == 200
    seen = [owner.get(p, headers=owner.headers_owner).text for p in ("/api/admin/prompts", "/api/admin/testers")]
    assert "AuditedCo" not in "".join(seen) and "Fund" not in "".join(seen)
    assert owner.get(f"/api/audits/{created.json()['id']}", headers=owner.headers_owner).status_code == 404


def test_the_owner_token_alone_opens_the_admin_routes_and_an_unset_owner_hash_opens_none(owner, monkeypatch):
    monkeypatch.delenv("OWNER_TOKEN_SHA256")
    assert owner.get("/api/admin/prompts", headers=owner.headers_owner).status_code == 401
    monkeypatch.setenv("OWNER_TOKEN_SHA256", "")
    assert owner.get("/api/admin/prompts", headers=bearer("")).status_code == 401
    assert owner.get("/api/admin/prompts", headers={"Authorization": "Bearer"}).status_code == 401


def test_the_health_check_and_the_field_list_stay_open(owner):
    assert owner.get("/api/").status_code == 200 and owner.get("/api/fields").status_code == 200


def test_no_log_line_holds_a_token_or_prompt_text(owner, caplog):
    with caplog.at_level(logging.DEBUG):
        body = owner.post("/api/admin/testers", json={"label": "Private Name"}, headers=owner.headers_owner).json()
        token = token_of(body)
        owner.post("/api/admin/prompts", json={"name": "growth_engine", "text": SECRET}, headers=owner.headers_owner)
        owner.post(f"/api/admin/testers/{body['id']}/revoke", headers=owner.headers_owner)
        owner.post(f"/api/admin/testers/{body['id']}/reissue", headers=owner.headers_owner)
        owner.get("/api/audits", headers=bearer(token))
        owner.get("/api/audits", headers=bearer("a-wrong-token-value"))
    text = "\n".join(r.getMessage() for r in caplog.records)
    for needle in (OWNER, token, "a-wrong-token-value", SECRET, "Private Name", hashlib.sha256(token.encode()).hexdigest()):
        assert needle not in text, needle
    assert "prompt uploaded: name=growth_engine version=v1" in text


def test_the_admin_routes_stay_locked_when_access_is_disabled_for_development(owner, monkeypatch):
    """ACCESS_DISABLED switches the check off for the audit routes only: a deployment that set it by mistake must not hand the
    prompt store and the tester links to every visitor."""
    tester = owner.post("/api/admin/testers", json={"label": "T"}, headers=owner.headers_owner).json()
    monkeypatch.setenv("ACCESS_DISABLED", "1")
    assert owner.get("/api/audits").status_code == 200, "the audit routes are open, as in the test session"
    for method, path in ADMIN_ROUTES:
        body = {} if method == "POST" else None
        assert owner.request(method, path, json=body).status_code == 401, (method, path)
        assert owner.request(method, path, json=body, headers=bearer(token_of(tester))).status_code == 404, (method, path)
    assert owner.get("/api/admin/prompts", headers=owner.headers_owner).status_code == 200
    assert owner.db["prompts"].docs == []
