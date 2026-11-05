"""The sheet reader reads sheet by sheet (George, 2026-11-05, two reading limits found on a real board pack).

One call per sheet that holds figures, each with its own input and output caps; the maps are merged into one reading, stored once. A reply cut
at the output limit loses that sheet only: the other sheets are kept and the lost one is stored with its reason. Second reads and re-reads follow
the same split. A figure that cites another sheet still resolves after the merge. Synthetic data only; the fake adapter counts calls."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import test_llm_gateway as t  # noqa: E402
from app import checks, readings  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.structures import redact  # noqa: E402

MODEL = "claude-sonnet-5-5"
HASH = "b" * 64
CUT = "output cap: sheet too large to read in one reply"
NAMES = ["Plan", "Actuals", "Big", "Cash"]


def cells_of(base):
    return [{"row": 1, "col": 1, "text": "Metric"}, {"row": 1, "col": 2, "text": "Jan-24"}, {"row": 1, "col": 3, "text": "Feb-24"},
            {"row": 2, "col": 1, "text": "Revenue"}, {"row": 2, "col": 2, "text": str(base)}, {"row": 2, "col": 3, "text": str(base + 1)}]


def book(names=NAMES, extra=()):
    sheets = [{"name": n, "cells": cells_of(100 * (i + 1))} for i, n in enumerate(names)]
    sheets += [{"name": n, "cells": [{"row": 1, "col": 1, "text": "Read me first"}, {"row": 2, "col": 1, "text": "Notes for the reader"}]} for n in extra]
    return redact.reading_text(sheets)


def sheet_map(name, figures=()):
    row = {"row": 2, "label_cell": "A2", "role": "revenue", "metric": "revenue", "basis": "monthly", "actual_plan": "mixed", "boundary_col": "B",
           "segment": None, "parent_row": None, "unit": "money", "currency": "EUR", "cells": "B2:C2", "variance_of": None, "by_column": False,
           "evidence": "Revenue row"}
    return {"map_version": 1, "kind": "sheet", "figures": list(figures), "sheets": [
        {"sheet": name, "header_row": 1, "label_col": "A", "first_period_col": "B", "last_period_col": "C", "granularity": "monthly",
         "currency": "EUR", "currency_cell": None, "last_actual": {"column": "B", "period": "2024-01", "evidence": []}, "rows": [row]}]}


def cash_figure():
    return {"metric": "revenue", "value": 400.0, "unit": "money", "currency": "EUR", "period": "2024-01", "basis": "monthly", "actual_plan": "actual",
            "segment": None, "source": {"sheet": "Cash", "cell": "B2", "page": None, "text_layer": None}, "evidence": "Cash sheet, January"}


class BySheet(t.FakeAdapter):
    """Answers a sheet reading from the one sheet it is sent; `cut` sheets meet the output limit. Plan's reply cites a cell of Cash."""

    def __init__(self, cut=(), tokens=(1200, 300)):
        super().__init__()
        self.cut, self.sent, self.tokens, self.max_tokens = set(cut), [], tokens, []

    def complete(self, **kw):
        sent = json.loads(kw["user_payload"])
        self.calls += 1
        self.sent.append(sent)
        self.max_tokens.append(kw["max_tokens"])
        names = [ln.split(": ", 1)[1] for ln in sent["text"].split("\n") if ln.startswith("sheet ")]
        assert len(names) == 1, f"one sheet to a call, got {names}"
        name = names[0]
        if name in self.cut:
            raise gateway.GatewayError("truncated", "the reply was cut at max_tokens")
        return json.dumps(sheet_map(name, [cash_figure()] if name == "Plan" else [])), *self.tokens


@pytest.fixture(autouse=True)
def reader_env(monkeypatch):
    monkeypatch.setenv("SHEET_READER_MODEL", MODEL)
    monkeypatch.delenv("READER_V1", raising=False)


def audit_db():
    db = t.FakeDB()
    db["audits"].docs.append({"id": "a1", "company_name": "Orchid Test Co", "structure_reading_consent": True, "fiscal_year_end": 12})
    return db


def read(db, adapter, text=None, **kwargs):
    if kwargs.get("recheck") and "reread_of" not in kwargs:
        kwargs["reread_of"] = next(d["key"] for d in db[readings.READINGS].docs)
    return asyncio.run(gateway.read_structure(db, "a1", text or book(), "sheet_reading", adapter=adapter, sleep=t._noop_sleep, file_hash=HASH, **kwargs))


def test_one_call_per_sheet_each_with_its_own_caps_and_the_maps_are_one_reading():
    db, adapter = audit_db(), BySheet()
    result = read(db, adapter)
    assert result.status == "read" and adapter.calls == 4
    assert [[ln for ln in s["text"].split("\n") if ln.startswith("sheet ")] for s in adapter.sent] == [[f"sheet 1: {n}"] for n in NAMES]
    assert adapter.max_tokens == [gateway.SHEET_READING_MAX_TOKENS] * 4, "every sheet has its own output cap"
    assert [s["sheet"] for s in result.file_map["sheets"]] == NAMES, "one map, the sheets in file order"
    assert len(db[readings.READINGS].docs) == 1, "stored once, as one reading"
    assert result.input_tokens == 4 * 1200 and result.output_tokens == 4 * 300
    again = read(db, BySheet())
    assert again.cache_hit and [s["sheet"] for s in again.file_map["sheets"]] == NAMES, "the file is served from the store with no call"


def test_a_sheet_with_no_figure_is_not_sent():
    adapter = BySheet()
    result = read(audit_db(), adapter, text=book(extra=["Readme"]))
    assert adapter.calls == 4 and [s["sheet"] for s in result.file_map["sheets"]] == NAMES


def test_a_reply_cut_at_the_output_limit_loses_that_sheet_only_and_says_why():
    db, adapter = audit_db(), BySheet(cut={"Big"})
    result = read(db, adapter)
    assert result.status == "read" and adapter.calls == 4, "the other sheets are kept; the cut sheet is not read again"
    assert [s["sheet"] for s in result.file_map["sheets"]] == ["Plan", "Actuals", "Cash"]
    assert result.unread_sheets == [{"sheet": "Big", "reason": CUT}]
    stored, = db[readings.READINGS].docs
    assert [s["sheet"] for s in stored["file_map"]["sheets"]] == ["Plan", "Actuals", "Cash"] and stored["unread_sheets"] == [{"sheet": "Big", "reason": CUT}]
    again = read(db, BySheet())
    assert again.cache_hit and again.unread_sheets == [{"sheet": "Big", "reason": CUT}], "the stored reason comes back with the stored reading"


def test_every_sheet_cut_is_a_truncated_read_that_names_them_all():
    result = read(audit_db(), BySheet(cut=set(NAMES)))
    assert result.status == "truncated" and result.reason == gateway.SHEET_READING_CUT
    assert [u["sheet"] for u in result.unread_sheets] == NAMES and result.file_map is None


def test_a_figure_that_cites_another_sheet_still_resolves_after_the_merge():
    result = read(audit_db(), BySheet())
    cells = checks.Cells(result.payload)
    found = checks.check_map(cells, result.file_map, 12)
    figure, = [i for i in found["items"] if i["kind"] == "figure"]
    assert (figure["sheet"], figure["cell"], figure["outcome"]) == ("Cash", "B2", checks.CONFIRMED)


def test_a_second_read_follows_the_split_and_leaves_out_the_sheet_the_first_could_not_read():
    db = audit_db()
    read(db, BySheet(cut={"Big"}))
    adapter = BySheet(cut={"Big"})
    second = read(db, adapter, second_read=True)
    assert second.status == "read" and adapter.calls == 3, "Plan, Actuals and Cash; Big was cut once and is not asked again"
    assert [s["sheet"] for s in second.file_map["sheets"]] == ["Plan", "Actuals", "Cash"]
    assert len(db[readings.SECOND_READS].docs) == 1


def test_a_re_read_asks_only_the_sheets_its_items_are_on():
    db = audit_db()
    read(db, BySheet())
    adapter = BySheet()
    result = read(db, adapter, recheck=[{"item": "row:Actuals:2", "reason": "test"}])
    assert result.status == "read" and adapter.calls == 1
    assert [ln for ln in adapter.sent[0]["text"].split("\n") if ln.startswith("sheet ")] == ["sheet 1: Actuals"]
    assert adapter.sent[0]["recheck"] == [{"item": "row:Actuals:2", "reason": "test"}]
