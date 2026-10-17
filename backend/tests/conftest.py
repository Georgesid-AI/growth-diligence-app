"""The chat-upload `api` fixture (docs/specs/chat-upload.md), shared by every test file that drives the upload and mapping
endpoints.

Pytest hands it to any test here that asks for `api`, so no file imports it: an imported fixture is a redefinition to the
linter, and ignoring that across the test tree also hid a test defined twice in one file. A file that sets up its own audit
defines its own `api`, which wins in that file. The audit document and the model reply the fixture starts from stay in
test_chat_upload.py, where the tests read them; they are imported when the fixture runs, so this file loads nothing.
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
    state = {"adapter": t.FakeAdapter(replies=[mapping_reply()])}
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: state["adapter"])
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.state = db, state
    return client
