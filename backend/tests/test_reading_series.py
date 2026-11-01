# ruff: noqa: F811, F401
"""Stored series and the export (docs/design/read-check-review.md sections 4, 9; PR 3 step a), on the synthetic monthly report of the
sheet reader flow tests. The series are computed once, written with the reading, and never read by the checks."""
import copy
import csv
import io
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import checks, readings, reading_export, series  # noqa: E402
from upload_support import AUDIT  # noqa: E402
from test_checks import build, cells_of, row  # noqa: E402
from test_sheet_reader_flow import MONTHLY, flow, monthly, upload  # noqa: E402

QUEUES_SHEET_READER = True      # tests/conftest.py: this module lets an upload queue the reader

SMAP = {"sheet": "Report", "header_row": 3, "label_col": "A", "first_period_col": "B", "last_period_col": "M", "granularity": "monthly",
        "last_actual": {"column": "G", "period": "2024-06", "evidence": []}, "rows": [row()]}


def sheet_of(grid=None):
    return cells_of(grid or build()).sheet("Report")


def test_the_series_of_a_row_is_period_value_and_cell_with_the_plan_after_the_boundary_apart():
    got = series.row_series(SMAP, SMAP["rows"][0], sheet_of())
    assert got["series"]["periods"] == [f"2024-0{m}" for m in range(1, 7)]
    assert got["series"]["values"] == [100, 110, 120, 130, 140, 150]
    assert got["series"]["refs"] == ["B4", "C4", "D4", "E4", "F4", "G4"]
    assert got["plan_series"]["periods"][0] == "2024-07" and got["plan_series"]["refs"][0] == "H4" and len(got["plan_series"]["values"]) == 6


def test_values_keep_full_precision_and_a_text_cell_is_left_out():
    grid = build({(4, 2): "447223.43", (4, 3): "n/a"})
    got = series.row_series(SMAP, SMAP["rows"][0], sheet_of(grid))["series"]
    assert got["values"][0] == 447223.43 and "C4" not in got["refs"]


def test_an_actual_row_has_no_plan_series_and_a_plan_row_has_only_one():
    a = series.row_series(SMAP, row(actual_plan="actual"), sheet_of())
    p = series.row_series(SMAP, row(actual_plan="plan"), sheet_of())
    assert "plan_series" not in a and len(a["series"]["values"]) == 12
    assert "series" not in p and len(p["plan_series"]["values"]) == 12


def test_a_row_with_actual_budget_variance_side_by_side_has_no_series():
    r = row(variance_columns={"first_col": "B", "step": 3})
    assert series.row_series(SMAP, r, sheet_of()) == {}


def test_periods_running_down_the_sheet_take_their_period_from_the_label_column():
    grid = {(1, 1): "Month", (1, 2): "Revenue", (2, 1): "Jan-24", (2, 2): "10", (3, 1): "Feb-24", (3, 2): "20"}
    smap = {**SMAP, "header_row": 1, "first_period_col": "A", "last_period_col": "B", "last_actual": None}
    r = row(row=2, cells="B2:B3", by_column=True, boundary_col=None, actual_plan="actual")
    got = series.row_series(smap, r, cells_of(grid).sheet("Report"))
    assert got["series"] == {"periods": ["2024-01", "2024-02"], "values": [10, 20], "refs": ["B2", "B3"]}


def test_the_checks_do_not_read_the_stored_series():
    """A mutation of the stored series changes no check outcome: the checks open the file."""
    cells = cells_of(build())
    fmap = {"map_version": 1, "kind": "sheet", "figures": [], "sheets": [copy.deepcopy(SMAP)]}
    before = checks.check_map(cells, fmap)
    fmap["sheets"][0]["rows"][0]["series"] = {"periods": ["1999-01"], "values": [-1.0], "refs": ["Z99"]}
    assert checks.check_map(cells, fmap) == before
    import inspect
    assert "series" not in inspect.getsource(checks).replace("# series", ""), "app/checks.py never names a stored series"


def test_the_series_are_written_once_with_the_reading_and_equal_the_builder(flow):
    upload(flow, MONTHLY, monthly())
    stored = flow.db[readings.READINGS].docs[0]
    got = stored["file_map"]["sheets"][0]["rows"][0]
    sheet = checks.Cells(_payload(flow)).sheet("CSV")
    want = series.row_series(stored["file_map"]["sheets"][0], got, sheet)
    assert got["series"] == want["series"] and got["series"]["refs"][0] == "B4"
    assert got["plan_series"]["periods"][0] == "2025-07"
    # a second upload of the same file is served from the store: the document is the same one, not rewritten
    snapshot = copy.deepcopy(stored)
    upload(flow, MONTHLY, monthly())
    assert len(flow.db[readings.READINGS].docs) == 1 and flow.db[readings.READINGS].docs[0] == snapshot
    assert flow.state["adapter"].sheet_calls == 1


def _payload(flow):
    return flow.state["adapter"].sheet_payloads[0]["text"]


def test_the_export_round_trips_json_and_csv(flow):
    upload(flow, MONTHLY, monthly())
    file_hash = flow.db[readings.CHECKS].docs[0]["file_hash"]
    stored = flow.db[readings.READINGS].docs[0]
    j = flow.get(f"/api/audits/{AUDIT}/readings/{file_hash}/export").json()
    assert j["file_map"] == stored["file_map"] and j["overrides"] == [] and j["file"] == MONTHLY
    c = flow.get(f"/api/audits/{AUDIT}/readings/{file_hash}/export?format=csv")
    assert c.headers["content-type"].startswith("text/csv")
    lines = list(csv.DictReader(io.StringIO(c.text)))
    row_ = stored["file_map"]["sheets"][0]["rows"][0]
    want = [(p, v, r, "actual") for p, v, r in zip(*[row_["series"][k] for k in ("periods", "values", "refs")])] + [
        (p, v, r, "plan") for p, v, r in zip(*[row_["plan_series"][k] for k in ("periods", "values", "refs")])]
    got = [(ln["period"], float(ln["value"]), ln["cell"], ln["actual_plan"]) for ln in lines]
    assert got == want and len(lines) == 12 and lines[0]["row"] == "4" and lines[0]["role"] == "revenue"
    assert [ln["value"] for ln in lines][:2] == [repr(float(v)) for v in row_["series"]["values"][:2]], "full precision, never rounded"


def test_the_export_of_a_file_the_audit_has_not_read_is_404(flow):
    assert flow.get(f"/api/audits/{AUDIT}/readings/{'0' * 64}/export").status_code == 404


def test_csv_text_that_a_spreadsheet_would_run_as_a_formula_is_quoted():
    doc = {"file": "=cmd.xlsx", "file_map": {"sheets": [{"sheet": "@x", "rows": [{"row": 1, "role": "revenue", "series": {
        "periods": ["2024-01"], "values": [1.5], "refs": ["B1"]}}]}]}}
    out = reading_export.as_csv(doc, [])
    assert "'=cmd.xlsx" in out and "'@x" in out


def test_an_override_shows_in_the_csv_but_the_stored_map_is_not_touched():
    doc = {"file": "f.xlsx", "key": "k", "file_map": {"sheets": [{"sheet": "S", "rows": [{"row": 1, "role": "bookings", "series": {
        "periods": ["2024-01"], "values": [1.0], "refs": ["B1"]}}]}]}}
    ov = [{"path": "sheets.0.rows.0.role", "new": "revenue", "at": "2026-10-30T00:00:00+00:00"}]
    assert ",revenue," in reading_export.as_csv(doc, ov) and doc["file_map"]["sheets"][0]["rows"][0]["role"] == "bookings"
