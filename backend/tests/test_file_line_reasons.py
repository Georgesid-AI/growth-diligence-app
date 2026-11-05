"""The per-file line says why a file was not read, in plain words (George, 2026-11-05), from the reason the server stored: a reply cut at the
output limit names the sheet, a timeout names the seconds. The words are read_reasons.py's; the page side is in test_page_clock.py."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from test_reading_failure_visibility import dataset_view  # noqa: E402
from test_sheet_reader_flow import MONTHLY, Router, flow, good_map, monthly, upload  # noqa: E402,F401,F811

from app import read_reasons, sheet_reader  # noqa: E402
from app.llm import gateway  # noqa: E402


QUEUES_SHEET_READER = True       # the upload queues the sheet reader (conftest.py)


class Cut(Router):
    """A sheet reader whose every reply is cut at the output limit."""

    def complete(self, **kw):
        self.sheet_calls += 1
        raise gateway.GatewayError("truncated", "the reply was cut at max_tokens")


def test_a_reply_cut_at_the_output_limit_is_named_on_the_file_line(flow):  # noqa: F811
    flow.state["adapter"] = Cut(good_map())
    upload(flow, MONTHLY, monthly())
    view = dataset_view(flow)
    assert view["read_state"] == "failed"
    assert view["read_reason"] == "Reply cut at the output limit – read sheet by sheet failed on sheet CSV"
    assert flow.state["adapter"].sheet_calls == 1, "a cut sheet is not asked again"


def test_a_read_that_times_out_says_after_how_many_seconds(flow, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sheet_reader, "READ_SECONDS", 0.2)

    class Slow(Router):
        def complete(self, **kw):
            import time
            time.sleep(1.0)
            return super().complete(**kw)
    flow.state["adapter"] = Slow(good_map())
    upload(flow, MONTHLY, monthly())
    view = dataset_view(flow)
    assert view["read_state"] == "failed" and view["read_reason"] == "Timed out after 0 s"


def test_a_file_read_in_full_has_no_reason(flow):  # noqa: F811
    upload(flow, MONTHLY, monthly())
    view = dataset_view(flow)
    assert view["read_state"] == "done" and view["read_reason"] is None


def test_the_sentences():
    cut = [{"sheet": "Big", "reason": gateway.SHEET_CUT_REASON}, {"sheet": "Wide", "reason": gateway.SHEET_CUT_REASON}]
    assert read_reasons.sheets_line(cut) == "Reply cut at the output limit – read sheet by sheet failed on sheets Big, Wide"
    assert read_reasons.sheets_line([]) is None
    assert read_reasons.not_sent_line(64.4) == "Page reads were not sent (waited 64 s)"
    assert read_reasons.timeout_line(60) == "Timed out after 60 s"
