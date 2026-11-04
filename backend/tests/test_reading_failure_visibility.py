"""Reading-step failure visibility. A file counts as processed only if it produced a mapped row (spreadsheet) or an accepted page (deck); a
provider error that fails every call is named once in plain words; a page the provider call failed on is logged with the same reason fields
as the spreadsheet step; every log line carries an ISO UTC timestamp."""
import asyncio
import io
import logging
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

import test_llm_gateway as t  # noqa: E402
from test_deck_list_reread import decks, one_page, open_audit  # noqa: E402
from test_sheet_reader_flow import MONTHLY, Router, flow, good_map, monthly, upload  # noqa: E402,F401,F811
from upload_support import AUDIT as SHEET_AUDIT  # noqa: E402
from test_structure_reading import AUDIT  # noqa: E402

from app import readings, structures  # noqa: E402

QUEUES_SHEET_READER = True       # the upload queues the sheet reader (conftest.py)

CREDIT_TEXT = "Anthropic API: insufficient credit – add credit and re-run"
CREDIT_BODY = "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."


def credit_error():
    """The error the Anthropic SDK raises for a 400 insufficient-credit response."""
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    response = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": CREDIT_BODY}}
    return anthropic.Anthropic(api_key="test")._make_status_error(CREDIT_BODY, body=body, response=response)


class CreditRouter(Router):
    """A sheet reader whose every model call meets the 400 insufficient-credit response."""

    def complete(self, **kw):
        self.sheet_calls += 1
        raise credit_error()


def dataset_view(client):
    r = client.get(f"/api/audits/{SHEET_AUDIT}/datasets")
    assert r.status_code == 200, r.text
    views = r.json()["datasets"]
    assert len(views) == 1
    return views[0]


# ---- item 1: processed means a mapped row / an accepted page -------------------------------------------------------------------------------
def test_a_file_reports_its_mapped_rows_so_a_reading_with_none_is_not_processed(flow):  # noqa: F811
    upload(flow, MONTHLY, monthly())
    assert dataset_view(flow)["read_state"] == "done" and dataset_view(flow)["rows_mapped"] == 1
    flow.db["datasets"].docs.clear()
    flow.db[readings.READINGS].docs.clear()
    empty = good_map()
    empty["sheets"][0]["rows"] = []
    empty["figures"] = []
    flow.state["adapter"] = Router(empty)
    upload(flow, MONTHLY, monthly())
    assert dataset_view(flow)["rows_mapped"] == 0, "a reading that mapped no row is a file the page must not count as processed"


def test_a_deck_whose_every_page_failed_reports_no_page_read(monkeypatch):
    client, db, adapter = open_audit(monkeypatch, one_page(), replies=[])
    adapter._raise_with = credit_error()
    asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    d, = decks(client)
    assert (d["ai_status"], d["pages_read"], d["pages_rejected"]) == ("not_read", 0, 1)


# ---- items 2 and 3: the provider error, once, in plain words; the deck page's reason fields ---------------------------------------------
def test_a_400_insufficient_credit_fails_the_spreadsheet_with_one_plain_line_and_logs_it(flow, caplog):  # noqa: F811
    flow.state["adapter"] = CreditRouter(good_map())
    with caplog.at_level(logging.INFO):
        upload(flow, MONTHLY, monthly())
    view = dataset_view(flow)
    assert view["read_state"] == "failed" and view["read_error"] == CREDIT_TEXT
    line, = [r.getMessage() for r in caplog.records if r.getMessage().startswith("structure not read:")]
    assert "reason=provider_error status=400 type=invalid_request_error" in line and "credit balance is too low" in line


def test_a_400_insufficient_credit_on_a_deck_page_logs_the_reason_fields_and_the_deck_says_it_once(monkeypatch, caplog):
    client, db, adapter = open_audit(monkeypatch, one_page(), replies=[])
    adapter._raise_with = credit_error()
    with caplog.at_level(logging.INFO):
        asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    line, = [r.getMessage() for r in caplog.records if r.getMessage().startswith("page 1 not read:")]
    assert "reason=provider_error status=400 type=invalid_request_error" in line and "credit balance is too low" in line
    assert "reason=-" not in line
    d, = decks(client)
    assert d["read_error"] == CREDIT_TEXT


# ---- item 4: timestamps ---------------------------------------------------------------------------------------------------------------------
def test_a_log_line_carries_an_iso_utc_timestamp(monkeypatch):
    from app import logfmt
    stream = io.StringIO()
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", logging.WARNING)
    handler = logfmt.configure_logging(stream)
    logging.getLogger("growth").warning("page 1 not read")
    root.removeHandler(handler)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z WARNING:growth:page 1 not read\n", stream.getvalue())
