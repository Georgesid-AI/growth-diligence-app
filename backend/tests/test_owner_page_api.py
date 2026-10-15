"""The owner routes (docs/specs/prompt-store.md section 3; docs/specs/access-links.md section 2).

Prompts: list by name, version and date; upload a new version; nothing deleted; the text never comes back. Tester links: issue
(the link is shown once), list with status, revoke, re-issue (the tester keeps their id and so their audits). Owner token only:
no token or an unknown one is 401, a tester's token is 404. These run the real access guard. No network.
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402

pytestmark = pytest.mark.real_access

OWNER = "owner-token-for-the-test-suite-only"
SECRET = "SECRET-METHODOLOGY-SENTINEL-4471"
ADMIN_ROUTES = [("GET", "/api/admin/prompts"), ("POST", "/api/admin/prompts"), ("GET", "/api/admin/testers"),
                ("POST", "/api/admin/testers"), ("POST", "/api/admin/testers/x/revoke"), ("POST", "/api/admin/testers/x/reissue")]


@pytest.fixture()
def owner(monkeypatch):
    db = t.FakeDB()
    db["prompts"].docs.clear()
    monkeypatch.setattr(server, "db", db)
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


def test_a_link_is_shown_once_the_list_has_status_and_never_a_token_or_hash(owner):
    issued = owner.post("/api/admin/testers", json={"label": "  Tester   One "}, headers=owner.headers_owner)
    assert issued.status_code == 200
    body = issued.json()
    token = token_of(body)
    assert body["label"] == "Tester One" and body["status"] == "active" and len(token) >= 43, "32 bytes, URL-safe base64"
    stored = owner.db["access_tokens"].docs[0]
    assert stored["token_hash"] == hashlib.sha256(token.encode()).hexdigest() and token not in json.dumps(stored)
    listed = owner.get("/api/admin/testers", headers=owner.headers_owner)
    assert token not in listed.text and "token_hash" not in listed.text and stored["token_hash"] not in listed.text
    row = listed.json()["testers"][0]
    assert set(row) == {"id", "label", "status", "created_at", "expires_at", "revoked_at"} and row["status"] == "active"
    days = (datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["created_at"])).days
    assert days == 29 or days == 30, "30 days"
    assert owner.get("/api/audits", headers=bearer(token)).status_code == 200


def test_the_link_is_built_on_the_app_address_when_one_is_set(owner, monkeypatch):
    monkeypatch.setenv("APP_URL", "https://app.example/")
    body = owner.post("/api/admin/testers", json={"label": "T"}, headers=owner.headers_owner).json()
    assert body["link"].startswith("https://app.example/t/")
    monkeypatch.delenv("APP_URL")
    body = owner.post("/api/admin/testers", json={"label": "T"}, headers={**owner.headers_owner, "Origin": "https://web.example"}).json()
    assert body["link"].startswith("https://web.example/t/")


@pytest.mark.parametrize("payload", [{"label": ""}, {"label": "   "}, {"label": "x" * 81}, {"label": "T", "expires_in_days": 0},
                                     {"label": "T", "expires_in_days": 31}, {}])
def test_a_tester_needs_a_name_and_an_expiry_of_one_to_thirty_days(owner, payload):
    assert owner.post("/api/admin/testers", json=payload, headers=owner.headers_owner).status_code == 422
    assert owner.db["access_tokens"].docs == []


def test_an_expiry_shorter_than_thirty_days_is_kept_and_the_token_stops_working_then(owner, monkeypatch):
    from app import access
    body = owner.post("/api/admin/testers", json={"label": "T", "expires_in_days": 2}, headers=owner.headers_owner).json()
    token = token_of(body)
    assert owner.get("/api/audits", headers=bearer(token)).status_code == 200
    later = datetime.now(timezone.utc) + timedelta(days=3)
    monkeypatch.setattr(access, "utcnow", lambda: later)
    assert owner.get("/api/audits", headers=bearer(token)).status_code == 401
    status = {r["id"]: r["status"] for r in owner.get("/api/admin/testers", headers=owner.headers_owner).json()["testers"]}
    assert status[body["id"]] == "expired"


def test_revoke_lists_the_tester_as_revoked_and_the_token_is_refused_on_every_route(owner):
    body = owner.post("/api/admin/testers", json={"label": "T"}, headers=owner.headers_owner).json()
    token = token_of(body)
    audit = owner.post("/api/audits", json={"company_name": "Co", "client_name": "F"}, headers=bearer(token)).json()["id"]
    revoked = owner.post(f"/api/admin/testers/{body['id']}/revoke", headers=owner.headers_owner)
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked" and revoked.json()["revoked_at"]
    assert owner.get("/api/audits", headers=bearer(token)).status_code == 401
    assert owner.get(f"/api/audits/{audit}", headers=bearer(token)).status_code == 401
    assert owner.post("/api/admin/testers/no-such-tester/revoke", headers=owner.headers_owner).status_code == 404


def test_reissue_gives_a_new_link_the_old_one_stops_and_the_tester_keeps_their_audits(owner):
    body = owner.post("/api/admin/testers", json={"label": "T"}, headers=owner.headers_owner).json()
    old = token_of(body)
    audit = owner.post("/api/audits", json={"company_name": "Co", "client_name": "F"}, headers=bearer(old)).json()["id"]
    owner.post(f"/api/admin/testers/{body['id']}/revoke", headers=owner.headers_owner)
    again = owner.post(f"/api/admin/testers/{body['id']}/reissue", headers=owner.headers_owner)
    assert again.status_code == 200 and again.json()["id"] == body["id"] and again.json()["status"] == "active"
    new = token_of(again.json())
    assert new != old
    assert owner.get(f"/api/audits/{audit}", headers=bearer(old)).status_code == 401, "the old link is dead"
    assert owner.get(f"/api/audits/{audit}", headers=bearer(new)).status_code == 200, "the same tester, the same audits"
    assert len(owner.db["access_tokens"].docs) == 1
    assert owner.post("/api/admin/testers/no-such-tester/reissue", headers=owner.headers_owner).status_code == 404


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
