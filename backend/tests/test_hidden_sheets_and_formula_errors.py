# ruff: noqa: F811
"""Hidden sheets and formula errors (board-pack layout fix, items 2 and 3). Synthetic workbooks only.

A hidden sheet is read, but named "(hidden)" in the citations; when a role is mapped on a visible and on a hidden sheet the visible rows are used and
the hidden ones go in the mapping flags. A cell that holds #REF!, #DIV/0!, #N/A or #VALUE! is counted per file and listed as a data-integrity flag."""
import io
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

openpyxl = pytest.importorskip("openpyxl")

from app import column_rules as cr, ic_memo, integrity, role_engine, sheet_reader  # noqa: E402
from test_role_engine import MONTHS, file_of, metric, row, run, sheet  # noqa: E402
from test_sheet_reader_flow import flow  # noqa: E402,F401

QUEUES_SHEET_READER = True      # tests/conftest.py: this module lets an upload queue the reader


def workbook(hidden=("data_for_graphs",), errors=None):
    wb = openpyxl.Workbook()
    pnl = wb.active
    pnl.title = "PNL"
    pnl.append(["", "Jan-24", "Feb-24", "Mar-24"])
    pnl.append(["Revenue", 10, 11, 12])
    pnl.append(["R&D", 3, 3, 3])
    graphs = wb.create_sheet("data_for_graphs")
    graphs.append(["", "Jan-24", "Feb-24", "Mar-24"])
    graphs.append(["R&D", 3, 3, 3])
    cash = wb.create_sheet("CASHFLOW")
    cash.append(["", "Jan-24", "Feb-24"])
    cash.append(["Cash", 5, 6])
    for name in hidden:
        wb[name].sheet_state = "hidden"
    for (name, ref), value in (errors or {}).items():
        wb[name][ref] = value
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_a_hidden_sheet_is_read_and_named_as_hidden():
    sheets = cr.read_workbook(workbook(), "pack.xlsx")
    assert [s.sheet for s in sheets] == ["PNL", "data_for_graphs", "CASHFLOW"], "the hidden sheet is read like any other"
    facts = sheet_reader.file_facts(sheets)
    assert facts["hidden_sheets"] == ["data_for_graphs"]
    assert sheet_reader.file_facts(cr.read_workbook(workbook(hidden=()), "pack.xlsx"))["hidden_sheets"] == []


def test_formula_errors_are_counted_per_file_with_their_cells():
    errors = {("CASHFLOW", "B2"): "#REF!", ("PNL", "C3"): "#DIV/0!", ("PNL", "D3"): "#N/A", ("data_for_graphs", "B2"): "#VALUE!"}
    facts = sheet_reader.file_facts(cr.read_workbook(workbook(errors=errors), "pack.xlsx"))
    assert [(e["sheet"], e["cell"], e["error"]) for e in facts["formula_errors"]] == [
        ("PNL", "C3", "#DIV/0!"), ("PNL", "D3", "#N/A"), ("data_for_graphs", "B2", "#VALUE!"), ("CASHFLOW", "B2", "#REF!")]


def test_a_text_cell_that_only_mentions_an_error_is_no_formula_error():
    facts = sheet_reader.file_facts(cr.read_workbook(workbook(errors={("PNL", "A5"): "Check #REF! in the model", ("PNL", "A6"): "#1 customer"}), "pack.xlsx"))
    assert facts["formula_errors"] == []


def test_the_flag_names_the_file_the_count_and_the_cells():
    flags = role_engine.formula_error_flags([{"file": "[BOARD] GV Financial Report.xlsx", "formula_errors": [{"sheet": "CASHFLOW", "cell": "B4", "error": "#REF!"}]},
                                             {"file": "clean.xlsx", "formula_errors": []}])
    assert [f["text"] for f in flags] == ["[BOARD] GV Financial Report.xlsx: 1 formula error, CASHFLOW!B4"]
    many = role_engine.formula_error_flags([{"file": "f.xlsx", "formula_errors": [{"sheet": "S", "cell": f"A{n}", "error": "#N/A"} for n in range(1, 9)]}])[0]
    assert many["text"] == "f.xlsx: 8 formula errors, S!A1, S!A2, S!A3, S!A4, S!A5 and 3 more" and many["count"] == 8


def test_the_flag_reaches_the_integrity_table_and_worth_flagging():
    book = file_of("f.xlsx", [sheet("S", [row(4, "revenue", [1, 2, 3], MONTHS[:3])])])
    book["formula_errors"] = [{"sheet": "CASHFLOW", "cell": "B4", "error": "#REF!"}]
    results = run([book], as_of="2025-03")
    flag = results["role_metrics"]["integrity_flags"][0]
    assert flag["text"] == "f.xlsx: 1 formula error, CASHFLOW!B4" and flag["file"] == "f.xlsx" and flag["count"] == 1
    found = integrity.assess(results, deck_count=0, candidates=[])["statement_findings"]
    assert [f["text"] for f in found] == [flag["text"]] and found[0]["kind"] == "formula_error"
    worth = ic_memo.role_flags(results, None, "EUR", ic_memo.Notes())
    assert any(line.startswith("f.xlsx: 1 formula error, CASHFLOW!B4") for line in worth)


def two_sheets(visible_rd=True):
    visible = sheet("PNL", [row(4, "revenue", [100] * 3, MONTHS[:3]), *([row(5, "rnd", [30] * 3, MONTHS[:3])] if visible_rd else [])])
    hidden = sheet("data_for_graphs", [row(4, "rnd", [99] * 3, MONTHS[:3])])
    return [{**file_of("pack.xlsx", [visible, hidden]), "hidden_sheets": ["data_for_graphs"]}]


def test_the_visible_sheet_is_used_when_a_role_is_mapped_on_both():
    files = two_sheets()
    table = role_engine.build_table(files)
    assert [(r["sheet"], r["role"]) for r in table if r["role"] == "rnd"] == [("PNL", "rnd")]
    assert role_engine.hidden_flags(files) == [{
        "role": "rnd", "file": "pack.xlsx", "sheet": "data_for_graphs", "rows": [4], "used_row": 5, "used_sheet": "PNL", "hidden": True,
        "text": "R&D also on data_for_graphs (hidden); the calculation uses PNL"}]


def test_the_hidden_duplicate_is_listed_in_the_mapping_flags_of_the_results():
    results = run(two_sheets(), as_of="2025-03")
    texts = [f["text"] for f in results["role_metrics"]["mapping_flags"]]
    assert "R&D also on data_for_graphs (hidden); the calculation uses PNL" in texts
    assert "99" not in str(metric(results, "rnd_share")), "the calculation reads the visible row"


def test_a_role_only_a_hidden_sheet_carries_is_used_and_cited_as_hidden():
    files = two_sheets(visible_rd=False)
    results = run(files, as_of="2025-03")
    rnd = metric(results, "rnd_share")
    assert rnd["status"] == "computed" and rnd["source"]["sheet"] == "data_for_graphs (hidden)"
    assert role_engine.hidden_flags(files) == [], "nothing was left out, so nothing to flag"


# ---------------------------------------------------------------------------
# End to end: the upload stores the facts; the role inputs carry them
# ---------------------------------------------------------------------------
def test_an_upload_stores_the_hidden_sheets_and_formula_errors_and_the_role_inputs_carry_them(flow):
    import asyncio

    import server
    from app import readings
    from upload_support import AUDIT, FIXTURES, MONTHLY, upload

    rows = [line.split(",") for line in (FIXTURES / MONTHLY).read_text().split("\n")[:12]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CSV"
    for line in rows:
        ws.append([float(c) if c.replace(".", "", 1).isdigit() else (c or None) for c in line])
    notes = wb.create_sheet("Notes")
    notes["A1"], notes["B2"] = "Scratch", "#REF!"
    notes.sheet_state = "hidden"
    out = io.BytesIO()
    wb.save(out)
    assert upload(flow, "board.xlsx", out.getvalue()).status_code == 200
    doc = flow.db[readings.CHECKS].docs[0]
    assert doc["hidden_sheets"] == ["Notes"] and doc["formula_errors"] == [{"sheet": "Notes", "cell": "B2", "error": "#REF!"}]
    inputs = asyncio.new_event_loop().run_until_complete(server._role_inputs(AUDIT, flow.db["audits"].docs[0]))
    assert [f["text"] for f in inputs["flags"]["integrity"]] == ["board.xlsx: 1 formula error, Notes!B2"]
    assert inputs["table"] and all(r["hidden"] is False for r in inputs["table"])


def test_the_register_names_the_hidden_sheets_of_a_file_and_marks_their_rows(flow):
    import io as _io

    from upload_support import AUDIT, FIXTURES, MONTHLY, upload
    rows = [line.split(",") for line in (FIXTURES / MONTHLY).read_text().split("\n")[:12]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CSV"
    for line in rows:
        ws.append([float(c) if c.replace(".", "", 1).isdigit() else (c or None) for c in line])
    ws.sheet_state = "visible"
    wb.create_sheet("Notes")["A1"] = "scratch"
    wb["Notes"].sheet_state = "hidden"
    out = _io.BytesIO()
    wb.save(out)
    upload(flow, "board.xlsx", out.getvalue())
    got = flow.get(f"/api/audits/{AUDIT}/reading").json()
    assert got["files"][0]["hidden_sheets"] == ["Notes"]
    assert all("hidden" not in r["source"] for t in got["tables"].values() for r in t), "the rows of the visible sheet are not marked"


def test_a_row_read_on_a_hidden_sheet_carries_the_mark_for_the_screen():
    from app import register
    figure = {"metric": "revenue", "value": 5.0, "unit": "money", "currency": "EUR", "period": "2025-01", "basis": "monthly", "actual_plan": "actual",
              "segment": None, "source": {"sheet": "Notes", "cell": "B2", "page": None, "text_layer": None}, "evidence": "x"}
    fmap = {"map_version": 1, "kind": "sheet", "figures": [figure], "sheets": []}
    key = "figure:Notes:B2:revenue"
    doc = {"file": "f.xlsx", "file_hash": "h", "rereads": [], "hidden_sheets": ["Notes"],
           "items": [{"key": key, "kind": "figure", "outcome": "confirmed", "reason": None, "sheet": "Notes", "cell": "B2", "metric": "revenue", "value": 5.0}]}
    (row,) = register.sheet_rows(doc, fmap, {}, {})["confirmed"]
    assert row["source"] == {"file": "f.xlsx", "file_hash": "h", "sheet": "Notes", "cell": "B2", "hidden": True}
    (plain,) = register.sheet_rows({**doc, "hidden_sheets": []}, fmap, {}, {})["confirmed"]
    assert "hidden" not in plain["source"]
