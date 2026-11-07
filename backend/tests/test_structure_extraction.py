"""Structure-aware spreadsheet reading (docs/specs/structure-extraction.md). Synthetic workbooks only (rule 15); no model.

Extraction, the facts block, the date and percent rendering, the formula parents, the cache key and the two integrity tests."""
import copy
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

openpyxl = pytest.importorskip("openpyxl")
from openpyxl.styles import Alignment  # noqa: E402

from xlsx_support import to_bytes  # noqa: E402
from app import checks, column_rules as cr, integrity, readings, role_engine  # noqa: E402
from app.structures import reading_input, redact, workbook_facts as wf  # noqa: E402


def pl_book(bad_total=False):
    """A small P&L: a merged FY header, date-typed month headers, a total row and a quarter column made of SUMs, a percent row, a hidden row, a
    hidden column, a number stored as text, an indent and an outline level."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P&L"
    ws["A1"] = "Fixture Co P&L"
    ws["B2"] = "FY2023"
    ws.merge_cells("B2:D2")
    ws["A3"] = "Line"
    for col, d in zip("BCD", (datetime(2023, 10, 31), datetime(2023, 11, 30), datetime(2023, 12, 31))):
        ws[f"{col}3"] = d
        ws[f"{col}3"].number_format = "mmm-yy"
    ws["E3"] = "Q4"
    for r, label, vals in ((4, "Product", (100, 110, 120)), (5, "Services", (10, 11, 12))):
        ws.cell(r, 1, label)
        for i, v in enumerate(vals):
            ws.cell(r, 2 + i, v)
        ws.cell(r, 5, f"=SUM(B{r}:D{r})")
    ws["A6"] = "Total revenue"
    for col in "BCDE":
        ws[f"{col}6"] = f"=SUM({col}4:{col}5)"
    ws["A7"] = "Margin"
    for col, v in zip("BCD", (0.25, 0.3, 0.35)):
        ws[f"{col}7"] = v
        ws[f"{col}7"].number_format = "0.0%"
    ws["A8"], ws["B8"] = "Memo", 5
    ws.row_dimensions[8].hidden = True
    ws["F4"] = 9
    ws.column_dimensions["F"].hidden = True
    ws["B9"] = "1200"
    ws["A5"].alignment = Alignment(indent=1)
    ws.row_dimensions[5].outlineLevel = 1
    cached = {("P&L", "E4"): 330, ("P&L", "E5"): 33, ("P&L", "B6"): 110, ("P&L", "C6"): 999 if bad_total else 121, ("P&L", "D6"): 132, ("P&L", "E6"): 363}
    return to_bytes(wb, cached)


def facts_of(content=None):
    return wf.extract(content or pl_book())


def sheet0(facts):
    return facts["sheets"][0]


# --- 1. extraction ---
def test_the_version_is_one_and_a_file_that_cannot_be_read_gives_empty_facts():
    assert wf.STRUCTURE_EXTRACTION_VERSION == 1 and facts_of()["version"] == 1
    assert wf.extract(b"not a workbook") == {"version": 1, "has_formulas": False, "sheets": []}


def test_hidden_rows_columns_merged_ranges_outline_levels_and_indents_are_read():
    s = sheet0(facts_of())
    assert s["hidden_rows"] == [8] and s["hidden_cols"] == ["F"] and s["merged"] == ["B2:D2"]
    assert s["row_outline"] == {"5": 1} and s["indents"] == {"A5": 1} and s["hidden"] is False


def test_each_cell_has_a_type_and_a_number_format_class_and_a_number_stored_as_text_is_listed():
    s = sheet0(facts_of())
    assert s["cells"]["B3"] == "date/month" and s["cells"]["B7"] == "number/percent"
    assert "B4" not in s["cells"], "number / general is the default and is not listed"
    assert s["text_numbers"] == ["B9"], "a text cell that reads as a number; the year-like and period-like headers are not"


def test_every_formula_is_kept_with_the_cells_it_references():
    s = sheet0(facts_of())
    assert s["formulas"]["E4"] == ["SUM(B4:D4)", ["B4:D4"]] and s["formulas"]["B6"] == ["SUM(B4:B5)", ["B4:B5"]]
    assert wf.references("B5+'Other sheet'!C7*$D$2+SUM(Z1:Z9)") == ["B5", "Other sheet!C7", "D2", "Z1:Z9"]
    assert wf.references('IF(A1="B2",LOG10(C3),0)') == ["A1", "C3"], "text and function names are no cells"
    assert facts_of()["has_formulas"] is True


def test_total_rows_and_subtotal_columns_come_from_the_sum_formulas():
    s = sheet0(facts_of())
    assert s["totals"] == [{"row": 6, "parts": [4, 5], "cells": 4}]
    assert s["subtotal_cols"] == [{"col": "E", "parts": ["B", "C", "D"]}]


def test_a_plus_chain_and_a_subtotal_nine_are_sums_too_and_a_product_is_not():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "T"
    for r in (1, 2, 3):
        ws[f"A{r}"] = r
        ws[f"B{r}"] = r * 2
    ws["A4"], ws["B4"] = "=A1+A2+A3", "=SUBTOTAL(9,B1:B3)"
    ws["A5"], ws["B5"] = "=A1*A2", "=B1-B2"
    s = sheet0(wf.extract(to_bytes(wb)))
    assert s["totals"] == [{"row": 4, "parts": [1, 2, 3], "cells": 2}]


def test_when_two_rows_claim_the_same_parts_the_visible_row_wins():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "T"
    for r in (4, 5):
        ws[f"B{r}"], ws[f"C{r}"] = r, r
    ws["B6"], ws["B7"], ws["C6"], ws["C7"] = "=SUM(B4:B5)", "=SUM(B4:B5)", "=SUM(C4:C5)", "=SUM(C4:C5)"
    ws.row_dimensions[6].hidden = True
    s = sheet0(wf.extract(to_bytes(wb)))
    assert [t["row"] for t in s["totals"]] == [7], "row 6 is hidden: row 7 states the relation"
    assert wf.parent_relations(wf.extract(to_bytes(wb))) == {"T": {7: [4, 5]}}


def test_a_values_only_file_has_no_formulas_and_says_so():
    wb = openpyxl.Workbook()
    wb.active["A1"] = 1
    facts = wf.extract(to_bytes(wb))
    assert facts["has_formulas"] is False and wf.facts_block(facts, 0).splitlines()[:2] == [wf.BLOCK_HEAD, "no formulas in file"]


# --- 2. the facts block ---
def test_the_facts_block_lists_the_facts_in_plain_lines_with_references_only():
    block = wf.facts_block(facts_of(), 0)
    assert block.splitlines() == [
        "STRUCTURE FACTS (read from the file, not inferred):", "merged header spans: B2:D2", "total rows: row 6 = rows 4-5",
        "subtotal columns: E = B-D", "hidden rows: 8", "hidden columns: F", "cells stored as text: B9"]
    for word in ("Product", "Services", "Margin", "Fixture", "100", "1200"):
        assert word not in block, "no label, no value, no name"


def test_a_sheet_with_nothing_to_report_says_so_and_a_csv_has_no_block():
    wb = openpyxl.Workbook()
    wb.active["A1"], wb.active["A2"], wb.active["B2"] = "x", 1, "=A2*2"
    facts = wf.extract(to_bytes(wb))
    assert wf.facts_block(facts, 0).splitlines() == [wf.BLOCK_HEAD, "nothing to report"]
    assert wf.facts_block(None, 0) is None


def test_a_block_over_sixty_lines_keeps_the_totals_and_the_merged_spans_and_says_truncated():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Big"
    ws.merge_cells("B1:D1")
    for i in range(70):
        r = 3 + i * 3
        for col in "BC":
            ws[f"{col}{r}"], ws[f"{col}{r + 1}"], ws[f"{col}{r + 2}"] = 1, 2, f"=SUM({col}{r}:{col}{r + 1})"
    ws.row_dimensions[3].hidden = True
    lines = wf.facts_block(wf.extract(to_bytes(wb)), 0).splitlines()
    assert len(lines) <= wf.BLOCK_MAX_LINES and lines[-1] == "truncated" and lines[1] == "merged header spans: B1:D1"
    assert sum(1 for ln in lines if ln.startswith("total rows:")) >= 50 and not any(ln.startswith("hidden rows") for ln in lines)


# --- 3. what the model reads: ISO periods and percent ---
def reading_of(content, facts=None):
    return reading_input.reading_text(cr.read_workbook(content, "pl.xlsx"), facts)


def test_date_headers_of_a_period_row_are_written_as_iso_periods_never_serial_numbers():
    content = pl_book()
    with_facts = reading_of(content, wf.extract(content))
    assert "B3: 2023-10\n" in with_facts and "C3: 2023-11\n" in with_facts and "D3: 2023-12\n" in with_facts
    assert "B3: 2023-10-31" in reading_of(content), "without facts the text is as it was"


def test_a_date_of_a_ledger_keeps_its_day_and_a_mid_month_date_in_a_period_row_keeps_its_day():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ledger"
    ws["A1"], ws["B1"], ws["C1"] = "Invoice", "Date", "Amount"
    for r, d in ((2, datetime(2024, 1, 31)), (3, datetime(2024, 2, 15)), (4, datetime(2024, 3, 1))):
        ws.cell(r, 1, f"INV-{r}")
        ws.cell(r, 2, d)
        ws.cell(r, 3, r * 10)
    ws["A6"] = "Deal dates"
    for col, d in zip("BCD", (datetime(2024, 1, 15), datetime(2024, 2, 15), datetime(2024, 3, 15))):
        ws[f"{col}6"] = d
    content = to_bytes(wb)
    text = reading_of(content, wf.extract(content))
    assert "B2: 2024-01-31" in text and "B3: 2024-02-15" in text, "one date a row is no period row"
    assert "B6: 2024-01-15" in text and "D6: 2024-03-15" in text


def test_a_percent_cell_is_the_stored_fraction_with_the_fmt_marker_and_the_marker_is_read_as_a_figure():
    content = pl_book()
    text = reading_of(content, wf.extract(content))
    assert "B7: 0.25 (fmt %)" in text and "D7: 0.35 (fmt %)" in text
    assert checks.to_number("0.25 (fmt %)") == 0.25 and checks.to_number("12%") == 0.12
    assert redact.reading_figure("0.25 (fmt %)"), "a figure is never rewritten and never learned as a name"
    sheets = redact.parse_reading_text(text)
    assert dict((c["row"], c["text"]) for c in sheets[0]["cells"] if c["col"] == 2)[7] == "0.25 (fmt %)"


# --- 4. the formula decides the parent rows ---
def ledger_map(parents, rows=(4, 5, 6, 7)):
    rows = [{"row": r, "label_cell": f"A{r}", "role": "revenue", "metric": "revenue", "basis": "monthly", "actual_plan": "actual", "boundary_col": None,
             "segment": None, "parent_row": parents.get(r), "unit": "money", "currency": "EUR", "cells": f"B{r}:D{r}", "variance_of": None,
             "by_column": False, "evidence": "e"} for r in rows]
    return {"map_version": 1, "kind": "sheet", "figures": [], "sheets": [{"sheet": "P&L", "header_row": 3, "label_col": "A", "first_period_col": "B",
                                                                          "last_period_col": "D", "granularity": "monthly", "currency": "EUR",
                                                                          "currency_cell": "A1", "last_actual": None, "rows": rows}]}


def test_the_sum_formula_sets_the_parent_rows_and_each_change_is_one_note_never_a_card():
    stored = ledger_map({4: 7, 5: None, 7: 6})            # the reader guessed row 4 under row 7, and row 7 under row 6 (it is no part)
    kept = copy.deepcopy(stored)
    effective, notes = checks.apply_formula_parents(stored, facts_of())
    parents = {r["row"]: r["parent_row"] for r in effective["sheets"][0]["rows"]}
    assert parents == {4: 6, 5: 6, 6: None, 7: None}
    assert stored == kept, "the stored reading is kept as it was"
    assert notes == [{"sheet": "P&L", "row": 4}, {"sheet": "P&L", "row": 5}, {"sheet": "P&L", "row": 7}]
    assert checks.parent_note(notes[0]) == "parent rows set from formula (P&L, row 4)"


def test_a_reading_that_already_agrees_with_the_formula_gives_no_note_and_a_sheet_without_formulas_is_left_alone():
    _, notes = checks.apply_formula_parents(ledger_map({4: 6, 5: 6}), facts_of())
    assert notes == []
    plain = openpyxl.Workbook()
    plain.active["A1"] = 1
    unchanged, notes = checks.apply_formula_parents(ledger_map({4: 7}), wf.extract(to_bytes(plain)))
    assert notes == [] and unchanged["sheets"][0]["rows"][0]["parent_row"] == 7
    assert checks.apply_formula_parents(ledger_map({4: 7}), None)[1] == []


# --- 5. the reading is keyed on the extraction version ---
def test_the_extraction_version_is_part_of_the_reading_key(monkeypatch):
    first = readings.reading_key("acct", "f" * 64, "p" * 16, "claude-sonnet-5-5")
    monkeypatch.setattr(wf, "STRUCTURE_EXTRACTION_VERSION", 2)
    assert readings.reading_key("acct", "f" * 64, "p" * 16, "claude-sonnet-5-5") != first


# --- 6. the two integrity tests: findings ---
def book(fill):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plan"
    fill(ws)
    return wf.extract(to_bytes(wb))


def test_a_constant_among_the_formulas_of_a_row_is_a_hardcoded_cell():
    def fill(ws):
        for col in "BCDE":
            ws[f"{col}4"] = 10
            ws[f"{col}5"] = f"={col}4*2"
        ws["D5"] = 99
    found = wf.findings(book(fill))
    assert found["ran"] and found["hardcoded"] == [{"sheet": "Plan", "row": 5, "cell": "D5", "cells": ["D5"], "hidden": False}] and found["omitted"] == []


def test_a_roll_forward_seed_a_row_of_constants_and_a_row_of_mostly_constants_are_no_findings():
    def fill(ws):
        ws["B4"] = 50                                      # the seed
        ws["C4"], ws["D4"], ws["E4"] = "=B4*1.1", "=C4*1.1", "=D4*1.1"
        for col in "BCDE":
            ws[f"{col}5"] = 7                              # all constants
        for col, v in zip("BCDE", (1, 2, 3, "=B7*2")):     # one formula among constants, and the quarter column of a monthly row
            ws[f"{col}6"] = v
        ws["F6"] = "=SUM(B6:E6)"
    found = wf.findings(book(fill))
    assert found["hardcoded"] == []


def test_a_hardcoded_cell_in_a_hidden_row_or_column_is_marked_hidden():
    def fill(ws):
        for col in "BCD":
            ws[f"{col}4"] = f"={col}3*2"
        ws["E4"] = 5
        ws.column_dimensions["E"].hidden = True
    assert wf.findings(book(fill))["hardcoded"] == [{"sheet": "Plan", "row": 4, "cell": "E4", "cells": ["E4"], "hidden": True}]


def test_a_sum_that_skips_a_numeric_cell_next_to_its_range_is_an_omission():
    def fill(ws):
        for r, v in ((4, 1), (5, 2), (6, 3)):
            ws[f"B{r}"] = v
        ws["B7"] = "=SUM(B4:B5)"                           # B6 is skipped
        for col, v in zip("BCD", (1, 2, 3)):
            ws[f"{col}20"] = v
        ws["E20"] = "=SUM(C20:D20)"                        # B20 is left of the range
    omitted = wf.findings(book(fill))["omitted"]
    assert omitted == [{"sheet": "Plan", "cell": "B7", "range": "B4:B5", "skipped": ["B6"], "hidden": False, "hidden_cells": []},
                       {"sheet": "Plan", "cell": "E20", "range": "C20:D20", "skipped": ["B20"], "hidden": False, "hidden_cells": []}]


def test_a_sum_over_its_own_section_a_header_year_and_a_hidden_skip():
    def fill(ws):
        ws["B2"] = 2023                                    # a year header directly above the first part
        for r, v in ((3, 1), (4, 2)):
            ws[f"B{r}"] = v
        ws["B5"] = "=SUM(B3:B4)"
        for r, v in ((6, 3), (7, 4)):
            ws[f"B{r}"] = v
        ws["B8"] = "=SUM(B6:B7)"                           # B5 above is a total: its section ends there
        for r, v in ((11, 1), (12, 2), (13, 3)):
            ws[f"B{r}"] = v
        ws["B14"] = "=SUM(B11:B12)"
        ws.row_dimensions[13].hidden = True
    found = wf.findings(book(fill))["omitted"]
    assert found == [{"sheet": "Plan", "cell": "B14", "range": "B11:B12", "skipped": ["B13"], "hidden": True, "hidden_cells": ["B13"]}]


# --- 7. the two integrity tests: the table ---
def flag_files(hard=0, omit=0, workbooks=1):
    files = [{"file": "pack.xlsx", "structure_findings": {
        "ran": True, "hardcoded": [{"sheet": "Plan", "row": i + 4, "cell": f"D{i + 4}", "cells": [f"D{i + 4}"], "hidden": i == 1} for i in range(hard)],
        "omitted": [{"sheet": "Plan", "cell": f"B{20 + i}", "range": "B4:B5", "skipped": [f"B{6 + i}"], "hidden": False} for i in range(omit)]}}]
    return files + [{"file": f"v{i}.xlsx", "structure_findings": {"ran": False, "hardcoded": [], "omitted": []}} for i in range(workbooks - 1)]


def assess_flags(files):
    flags = role_engine.file_flags(files)
    results = {"role_metrics": {"integrity_flags": flags["integrity"], "structure_checks": flags["structure"]}}
    return flags, integrity.assess(results, 0, [])


def row_of(assessed, check):
    return next(r for r in assessed["coverage"] if r["check"] == check)


@pytest.mark.parametrize("hard,omit,result", [(0, 0, "Green"), (1, 0, "Amber"), (2, 0, "Amber"), (3, 0, "Amber"), (0, 1, "Amber"), (0, 3, "Amber")])
def test_the_hardcoded_check_and_the_omission_check_are_green_or_amber_by_the_count_never_red(hard, omit, result):
    flags, assessed = assess_flags(flag_files(hard, omit))
    for check, n in ((integrity.HARDCODED, hard), (integrity.OMITS, omit)):
        row = row_of(assessed, check)
        assert row["status"] == integrity.COMPLETED, "ran on a workbook with formulas, whatever the result"
        assert row["result"] == (result if n else "Green")
    assert flags["structure"] == {"files": 1, "files_with_formulas": 1}
    block_a = {r["check"]: r for r in assessed["results"]}
    assert integrity.HARDCODED in block_a and integrity.OMITS in block_a, "completed checks are in Block A, Green included"


def test_the_flags_carry_sheet_and_cell_evidence_and_a_hidden_cell_is_marked():
    flags, _ = assess_flags(flag_files(hard=3, omit=2))
    hard = next(f for f in flags["integrity"] if f["kind"] == "hardcoded_in_formula_row")
    assert hard["count"] == 3 and hard["cells"] == ["Plan!D4", "Plan!D5 (hidden)", "Plan!D6"] and hard["file"] == "pack.xlsx"
    omit = next(f for f in flags["integrity"] if f["kind"] == "total_omits_cells")
    assert omit["count"] == 2 and omit["cells"] == ["Plan!B20", "Plan!B21"] and "Plan!B20" in omit["text"]


def test_with_no_formula_in_any_workbook_both_checks_are_not_applicable_and_out_of_the_denominator():
    before = integrity.assess({}, 0, [])["applicable"]
    files = [{"file": "values.xlsx", "structure_findings": {"ran": False, "hardcoded": [], "omitted": []}}, {"file": "revenue.csv"}]
    flags, assessed = assess_flags(files)
    assert flags["structure"] == {"files": 2, "files_with_formulas": 0} and flags["integrity"] == []
    for check in (integrity.HARDCODED, integrity.OMITS):
        row = row_of(assessed, check)
        assert row["status"] == integrity.NOT_APPLICABLE and row["reason"] == integrity.NO_FORMULAS
    assert assessed["applicable"] == before and assessed["blocked"] == integrity.assess({}, 0, [])["blocked"], "no data request is added"


def test_a_completed_check_counts_toward_the_x_of_y():
    _, assessed = assess_flags(flag_files(1, 0))
    assert assessed["completed"] == 2 and assessed["applicable"] == 7


def test_neither_formula_check_is_under_worth_flagging_in_this_pr():
    from app import ic_memo
    for hard in (1, 3, 9):
        flags, assessed = assess_flags(flag_files(hard, hard))
        results = {"role_metrics": {"integrity_flags": flags["integrity"], "reconciliation": [], "mapping_flags": []}}
        lines = ic_memo.role_flags(results, assessed, "EUR", ic_memo.Notes())
        assert not any(integrity.HARDCODED in ln or integrity.OMITS in ln for ln in lines), lines


# --- 8. the follow-up to the Opus review of PR 250: relations, the two heuristics, matching by sheet index ---
def period_header(ws, cols="BCDEFGH"):
    for col, month in zip(cols, range(1, 13)):
        ws[f"{col}3"] = datetime(2024, month, 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31)
        ws[f"{col}3"].number_format = "mmm-yy"


def test_a_ytd_row_with_a_single_cell_range_in_its_first_column_states_no_relation():
    def fill(ws):
        for col in "BCDE":
            ws[f"{col}5"] = 10
        for col, last in zip("BCDE", "BCDE"):
            ws[f"{col}6"] = f"=SUM($B$5:{last}5)"          # year to date; the first cell sums one cell
        for col in "BCDE":                                 # control: a real total of two rows, in two columns
            ws[f"{col}8"], ws[f"{col}9"] = 1, 2
        ws["B10"], ws["C10"] = "=SUM(B8:B9)", "=SUM(C8:C9)"
    s = book(fill)["sheets"][0]
    assert [t["row"] for t in s["totals"]] == [10], "row 6 is no total of row 5, row 10 is a total of 8-9"
    assert s["subtotal_cols"] == []


def test_a_total_with_a_part_another_total_has_claimed_is_left_out_whole():
    def fill(ws):
        for col in "BC":
            ws[f"{col}4"], ws[f"{col}5"], ws[f"{col}7"], ws[f"{col}8"] = 1, 2, 3, 4
            ws[f"{col}6"] = f"=SUM({col}4:{col}5)"         # claims rows 4-5
            ws[f"{col}9"] = f"=SUM({col}5:{col}8)"         # row 5 is claimed: no relation for row 9, not even rows 6-8
    s = book(fill)["sheets"][0]
    assert s["totals"] == [{"row": 6, "parts": [4, 5], "cells": 2}]


def test_facts_are_matched_to_a_sheet_by_its_position_in_the_workbook_not_by_its_masked_name():
    from app import sheet_reader
    wb = openpyxl.Workbook()
    wb.active.title = "Empty cover"                       # no cell: the reader drops it, so the P&L is the first parsed sheet but the second worksheet
    ws = wb.create_sheet("Acme P&L")
    for col in "BC":
        ws[f"{col}4"], ws[f"{col}5"] = 1, 2
        ws[f"{col}6"] = f"=SUM({col}4:{col}5)"
    content = to_bytes(wb)
    facts = wf.extract(content)
    sheets = cr.read_workbook(content, "pl.xlsx")
    assert [s.workbook_index for s in sheets] == [1]
    assert "total rows: row 6 = rows 4-5" in reading_input.facts_blocks(sheets, facts)[0]
    payload = redact.reading_text([{"name": "Client-01 P&L", "cells": reading_input.sheet_cells(sheets[0], facts)}])
    masked = sheet_reader._masked_structure(facts, sheets, payload)
    assert wf.parent_relations(masked) == {"Client-01 P&L": {6: [4, 5]}}, "the cover sheet's facts are not given the masked name"


def test_pasted_actuals_an_opening_cash_seed_and_a_hardcode_in_a_forecast_are_judged_as_rows():
    def fill(ws):
        period_header(ws)
        for col in "BCD":
            ws[f"{col}5"] = 100                            # pasted actuals ...
        for col in "EFH":
            ws[f"{col}5"] = f"={chr(ord(col) - 1)}5*1.1"   # ... then a formula forecast
        ws["G5"] = 150                                     # a typed number inside the forecast: the one finding of this row
        ws["B6"] = 500                                     # opening cash: the seed is exempt although it reads another row, not its own
        for col in "CDEFGH":
            ws[f"{col}6"] = f"={chr(ord(col) - 1)}9"
        for col in "BCDEFGH":
            ws[f"{col}9"] = f"={col}6+1"
        for col in "BCDE":
            ws[f"{col}8"] = f"={col}9*2"
        ws["F8"], ws["G8"] = 7, 8                          # two typed numbers in one row: one finding
    found = wf.findings(book(fill))["hardcoded"]
    assert found == [{"sheet": "Plan", "row": 5, "cell": "G5", "cells": ["G5"], "hidden": False},
                     {"sheet": "Plan", "row": 8, "cell": "F8", "cells": ["F8", "G8"], "hidden": False}]


def test_a_compact_pl_with_gross_profit_above_opex_is_no_omission_and_a_walk_stops_at_a_formula_a_blank_or_a_percent_row():
    def fill(ws):
        period_header(ws, "BCD")
        for col in "BCD":
            ws[f"{col}4"], ws[f"{col}5"] = 100, 40
            ws[f"{col}6"] = f"={col}4-{col}5"              # gross profit, a formula, directly above the opex lines
            ws[f"{col}7"], ws[f"{col}8"] = 20, 10
            ws[f"{col}9"] = f"=SUM({col}7:{col}8)"         # total opex: the walk up meets gross profit and stops
        for col in "BC":
            ws[f"{col}11"], ws[f"{col}12"], ws[f"{col}13"], ws[f"{col}14"] = 5, 6, 1, 2
            ws[f"{col}15"] = f"=SUM({col}13:{col}14)"      # control: two constants above the range are skipped
        ws["B17"] = "=SUM(B17:B17)"                        # a single-cell range is never a finding (the cell sits above its own range here)
        ws["B18"], ws["B19"], ws["B20"] = 1, 2, "=SUM(B19:B19)"
        for col in "BC":                                   # a percent row above the range is not a skipped part
            for r, v in ((25, 0.1), (26, 0.2), (27, 0.3)):
                ws[f"{col}{r}"] = v
                ws[f"{col}{r}"].number_format = "0%"
            ws[f"{col}28"] = f"=SUM({col}26:{col}27)"
    found = wf.findings(book(fill))["omitted"]
    assert [o["cell"] for o in found] == ["B15", "C15"], "two flagged SUM cells, each skipping the two constants above its range"
    assert all(o["skipped"] == [o["cell"][0] + "11", o["cell"][0] + "12"] for o in found)


def test_the_finding_strings_say_what_is_counted_rows_and_total_formulas():
    findings = {}
    for hard, omit in ((1, 1), (3, 2), (0, 0)):
        _, assessed = assess_flags(flag_files(hard, omit))
        findings[(hard, omit)] = {r["check"]: r["finding"] for r in assessed["results"]}
    assert findings[(1, 1)][integrity.HARDCODED] == "1 formula row with hardcoded cells"
    assert findings[(1, 1)][integrity.OMITS] == "1 total formula that omits cells"
    assert findings[(3, 2)][integrity.HARDCODED] == "3 formula rows with hardcoded cells"
    assert findings[(3, 2)][integrity.OMITS] == "2 total formulas that omit cells"
    flags, _ = assess_flags(flag_files(hard=2, omit=1))
    texts = {f["kind"]: f["text"] for f in flags["integrity"]}
    assert "2 formula rows with hardcoded cells" in texts["hardcoded_in_formula_row"] and "Plan!D4" in texts["hardcoded_in_formula_row"]
    assert "1 total formula that omits cells" in texts["total_omits_cells"] and "Plan!B20 sums B4:B5" in texts["total_omits_cells"]
