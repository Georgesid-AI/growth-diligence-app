"""Unexpected endpoint errors are logged (with credentials masked) and reach the browser as a
readable 500 that carries CORS headers - not as a bare network failure."""
import logging
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")
pytest.importorskip("pandas")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "endpoint_errors_test")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from app import logsafety  # noqa: E402

KEY = "sk-ant-api03-ABCDEFGHIJKLMNOP1234567890"
ORIGIN = {"Origin": "https://app.example.com"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(server, "db", t.make_db())
    return TestClient(server.app, raise_server_exceptions=False)


def _boom(*args, **kwargs):
    raise RuntimeError(f"provider exploded while sending x-api-key: {KEY}")


async def _aboom(*args, **kwargs):
    _boom()


def test_an_unexpected_error_in_generation_is_a_readable_500_with_cors_headers(client, monkeypatch, caplog):
    monkeypatch.setattr(server.llm_gateway, "generate_narrative", _aboom)
    with caplog.at_level(logging.ERROR, logger="growth"):
        r = client.post("/api/runs/run-abc/narrative/growth_engine", headers=ORIGIN)
    assert r.status_code == 500
    assert r.json() == {"detail": "Unexpected server error (RuntimeError); the details are in the server log"}
    assert "access-control-allow-origin" in r.headers, "without CORS headers the browser cannot read the 500"
    assert KEY not in r.text and "exploded" not in r.text, "only the exception's class name goes to the client"


def test_the_failure_is_logged_with_its_traceback_and_without_the_key(client, monkeypatch, caplog):
    monkeypatch.setattr(server.llm_gateway, "generate_narrative", _aboom)
    with caplog.at_level(logging.ERROR, logger="growth"):
        client.post("/api/runs/run-abc/narrative/growth_engine", headers=ORIGIN)
    records = [r for r in caplog.records if "unexpected error handling" in r.getMessage()]
    assert records, "the unexpected error must be logged"
    text = caplog.text
    assert "POST /api/runs/run-abc/narrative/growth_engine" in text
    assert "RuntimeError" in text and "Traceback" in text
    assert KEY not in text and "ABCDEFGHIJKLMNOP" not in text
    assert "[redacted]" in text


def test_every_endpoint_gets_the_same_treatment(client, monkeypatch):
    monkeypatch.setattr(server.llm_gateway, "read_cached_narrative", _aboom)
    monkeypatch.setattr(server.llm_gateway, "narratives_for_run", _aboom)
    monkeypatch.setattr(server.llm_gateway, "usage_for_run", _aboom)
    for url in ("/api/runs/run-abc/narrative/growth_engine", "/api/runs/run-abc/disclosure", "/api/runs/run-abc/llm-usage"):
        r = client.get(url, headers=ORIGIN)
        assert r.status_code == 500 and r.json()["detail"].startswith("Unexpected server error (RuntimeError)"), url
        assert "access-control-allow-origin" in r.headers, url


def test_the_export_endpoint_reports_its_failures_too(client, monkeypatch):
    monkeypatch.setattr(server, "build_export_workbook", _boom)
    server.db["audits"].docs[0]["company_name"] = "Acme"
    r = client.get("/api/audits/run-abc/export", headers=ORIGIN)
    assert r.status_code == 500 and "RuntimeError" in r.json()["detail"]


def test_errors_the_endpoints_already_handle_keep_their_own_status_and_text(client):
    r = client.post("/api/runs/does-not-exist/narrative/growth_engine", headers=ORIGIN)
    assert r.status_code == 404 and r.json() == {"detail": "Run not found"}
    r = client.get("/api/audits/does-not-exist/export", headers=ORIGIN)
    assert r.status_code == 404


def test_a_healthy_request_is_untouched(client):
    r = client.get("/api/runs/run-abc/narrative/growth_engine", headers=ORIGIN)
    assert r.status_code == 200 and r.json()["narrative_status"] == "not_generated"


# ---------------------------------------------------------------------------
# The redaction itself
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw", [
    f"key {KEY} leaked",
    f"x-api-key: {KEY}",
    f'{{"x-api-key": "{KEY}"}}',
    "Authorization: Bearer abcdefgh12345678xyz",
    "ANTHROPIC_API_KEY=abcdefghijk1234567",
    "api_key='shhhhhhhhhhhh'",
])
def test_redact_secrets_masks_credentials(raw):
    out = logsafety.redact_secrets(raw)
    for secret in (KEY, "abcdefgh12345678xyz", "abcdefghijk1234567", "shhhhhhhhhhhh"):
        assert secret not in out, out
    assert "[redacted]" in out


def test_the_literal_environment_key_is_masked_whatever_it_looks_like(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-shaped-like-a-key-99887766")
    assert "not-shaped-like-a-key-99887766" not in logsafety.redact_secrets("boom not-shaped-like-a-key-99887766 boom")


def test_ordinary_text_is_left_alone():
    text = "GET /api/runs/abc/narrative/growth_engine took 33.1s (HTTP 200)"
    assert logsafety.redact_secrets(text) == text


def test_log_arguments_and_tracebacks_are_masked_in_every_handler(caplog):
    logger = logging.getLogger("growth.llm")
    with caplog.at_level(logging.INFO, logger="growth"):
        logger.info("calling provider with %s", f"x-api-key: {KEY}")
        try:
            raise ValueError(f"bad request for key {KEY}")
        except ValueError:
            logger.exception("provider call failed")
    assert KEY not in caplog.text and "ABCDEFGHIJKLMNOP" not in caplog.text
    assert "provider call failed" in caplog.text and "ValueError" in caplog.text


def test_installing_twice_is_harmless():
    logsafety.install_secret_redaction()
    logsafety.install_secret_redaction()
    logging.getLogger("growth").info("still works %s", 1)
