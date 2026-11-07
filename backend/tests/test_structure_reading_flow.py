"""Structure-aware reading, through the reader and the gateway (docs/specs/structure-extraction.md sections 2, 3 and 5). A scripted model; synthetic
workbooks only. The facts block heads the call of every sheet, in the first read, the second read and a re-read; the formula decides the parent
rows; the file's check outcome carries the findings; the cache is keyed on the extraction version."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import test_llm_gateway as t  # noqa: E402
from test_reading_fixtures import Ideal  # noqa: E402
from test_structure_extraction import ledger_map, pl_book  # noqa: E402
from app import column_rules as cr, sheet_reader  # noqa: E402
from app.structures import workbook_facts as wf  # noqa: E402

HASH = "a" * 64


@pytest.fixture(autouse=True)
def reader_env(monkeypatch):
    monkeypatch.setenv("SHEET_READER_MODEL", "claude-sonnet-5-5")


def read(content, file_map, structure="facts", db=None, adapter=None, file_hash=HASH):
    db = db or t.FakeDB()
    if not db["audits"].docs:
        db["audits"].docs.append({"id": "fx", "company_name": "Fixture Co", "structure_reading_consent": True})
    adapter = adapter or Ideal(file_map)
    sheets = cr.read_workbook(content, "pl.xlsx")
    facts = wf.extract(content) if structure == "facts" else None
    doc = asyncio.run(sheet_reader.read_file(db, {"id": "fx"}, sheets, file_hash, "pl.xlsx", 12, adapter=adapter, structure=facts))
    return doc, adapter, db


def texts(adapter):
    return [json.loads(p)["text"] for p in adapter.payloads]


def test_the_facts_block_comes_after_the_sheets_line_in_every_call_of_the_first_and_the_second_read():
    _, adapter, _ = read(pl_book(), ledger_map({}, rows=(4, 5, 6)))
    sent = texts(adapter)
    assert len(sent) >= 2, "the reading and the consistency read"
    for text in sent:
        lines = text.split("\n")
        assert lines[0].startswith("sheets in this file: ") and lines[1] == wf.BLOCK_HEAD
        assert "total rows: row 6 = rows 4-5" in lines and "subtotal columns: E = B-D" in lines and "sheet 1: P&L" in lines


def test_a_file_with_no_structure_facts_sends_no_block():
    _, adapter, _ = read(pl_book(), ledger_map({}, rows=(4, 5, 6)), structure=None)
    assert all("STRUCTURE FACTS" not in text for text in texts(adapter))


def test_the_formula_total_row_is_checked_against_its_formula_parts_even_when_the_reading_names_no_parent():
    good, _, _ = read(pl_book(), ledger_map({}, rows=(4, 5, 6)))
    assert good["totals"] == [], "110 = 100 + 10, 121 = 110 + 11 ..."
    bad, _, _ = read(pl_book(bad_total=True), ledger_map({}, rows=(4, 5, 6)), file_hash="b" * 64)
    assert [(x["row"], x["sheet"]) for x in bad["totals"]] == [(6, "P&L")], "Totals that don't add up: the formula's parts, not the reader's"
    assert bad["parent_rows_from_formula"] == [{"sheet": "P&L", "row": 4}, {"sheet": "P&L", "row": 5}]


def test_the_stored_reading_keeps_the_readers_parent_row_and_the_outcome_names_what_the_formula_changed():
    guessed = ledger_map({4: 7, 5: 6, 6: None}, rows=(4, 5, 6))
    doc, _, db = read(pl_book(), guessed)
    stored = next(r for r in db["readings"].docs if r.get("file_hash") == HASH)
    assert {r["row"]: r["parent_row"] for r in stored["file_map"]["sheets"][0]["rows"]} == {4: 7, 5: 6, 6: None}
    assert doc["parent_rows_from_formula"] == [{"sheet": "P&L", "row": 4}]
    assert doc["structure_findings"] == {"ran": True, "hardcoded": [], "omitted": []}


def test_the_findings_and_the_facts_of_a_values_only_file_say_no_formulas():
    import openpyxl
    from xlsx_support import to_bytes
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P&L"
    for r in (4, 5, 6):
        ws.cell(r, 1, f"Line {r}")
        for c in (2, 3, 4):
            ws.cell(r, c, r * c)
    doc, adapter, _ = read(to_bytes(wb), ledger_map({}, rows=(4, 5, 6)), file_hash="c" * 64)
    assert doc["structure_findings"]["ran"] is False and "no formulas in file" in texts(adapter)[0].split("\n")


def test_no_log_line_and_no_llm_call_record_holds_the_block_or_a_formula():
    _, _, db = read(pl_book(), ledger_map({}, rows=(4, 5, 6)))
    logged = json.dumps(db["llm_calls"].docs, default=str)
    assert "STRUCTURE FACTS" not in logged and "SUM(" not in logged and "total rows" not in logged


def test_a_stored_reading_is_served_with_no_call_until_the_extraction_version_changes(monkeypatch):
    db = t.FakeDB()
    first, adapter, _ = read(pl_book(), ledger_map({}, rows=(4, 5, 6)), db=db)
    calls = adapter.reads
    again, adapter2, _ = read(pl_book(), ledger_map({}, rows=(4, 5, 6)), db=db)
    assert adapter2.reads == 0 and again["cache_hit"] is True and first["reading_key"] == again["reading_key"]
    monkeypatch.setattr(wf, "STRUCTURE_EXTRACTION_VERSION", 2)
    third, adapter3, _ = read(pl_book(), ledger_map({}, rows=(4, 5, 6)), db=db)
    assert adapter3.reads == calls and third["reading_key"] != first["reading_key"], "read once more under the new version"
