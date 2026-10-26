"""The API fixtures shared across test files: each sets up an audit on the in-memory Mongo stub and returns a test client.

- `api`: the chat upload and column mapping (docs/specs/chat-upload.md), with the fake adapter.
- `register_api`: the claim register (docs/specs/claim-matching.md), with run A's claims.
- `entry_api`: the claims Python enters on its own (docs/design/simplified-flow.md section 2), with a claim of each kind.
- `run_api`: the run audit stages, with a provider that echoes its payload.
- `claims_for`: a builder of an audit holding the given deck claims (test_claim_groups_api.make_db), returning (client, db).

Pytest hands them to any test here that asks for them, so no file imports them: an imported fixture is a redefinition to
the linter, and ignoring that across the test tree also hid a test defined twice in one file. A file that sets up its own
audit defines its own `api`, which wins in that file. The starting data stays in the test file each fixture came from,
where the tests read it; it is imported when the fixture runs, so this file loads nothing.
"""
import pytest


@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient

    import server
    import test_llm_gateway as t
    from app import usage as usage_mod
    from app.llm import gateway
    from test_chat_upload import AUDIT_DOC, mapping_reply

    db = t.FakeDB()
    db["audits"].docs.append({**AUDIT_DOC, "usage": usage_mod.empty()})
    monkeypatch.setattr(server, "db", db)
    server._RECOGNITION_CACHE.clear()
    state = {"adapter": t.FakeAdapter(replies=[mapping_reply()])}
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: state["adapter"])
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.state = db, state
    return client


@pytest.fixture()
def register_api(monkeypatch):
    from fastapi.testclient import TestClient

    import server
    from test_claim_register_api import starting_db

    db = starting_db()
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


@pytest.fixture()
def entry_api(monkeypatch):
    from fastapi.testclient import TestClient

    import server
    from entry_support import starting_db

    db = starting_db()
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


@pytest.fixture()
def run_api(monkeypatch):
    from fastapi.testclient import TestClient

    import server
    import test_llm_gateway as t
    from app import usage as usage_mod
    from app.llm import gateway
    from test_run_audit import AUDIT_DOC, EchoAdapter

    db = t.FakeDB()
    db["audits"].docs.append({**AUDIT_DOC, "usage": usage_mod.empty()})
    monkeypatch.setattr(server, "db", db)
    adapter = EchoAdapter()
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: adapter)
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.adapter = db, adapter
    return client


@pytest.fixture()
def claims_for(monkeypatch):
    from fastapi.testclient import TestClient

    import server
    from test_claim_groups_api import make_db

    def build(claims):
        db = make_db(claims)
        monkeypatch.setattr(server, "db", db)
        return TestClient(server.app, raise_server_exceptions=False), db
    return build
