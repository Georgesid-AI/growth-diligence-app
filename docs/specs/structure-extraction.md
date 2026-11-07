# Spec: structure-aware spreadsheet reading
Status: scope given by George, 2026-11-07. Location: docs/specs/structure-extraction.md. Amends read-check-review.md sections 3 and 9 and
integrity-coverage.md section 1. CLAUDE.md rules 16, 17, 23, 32 apply (see "Architecture change" at the end).

## 0. Challenge and deletions (rule 4)
- Needed: the sheet reader guesses what an .xlsx file already states (a date-typed header, a merged year over year-less months, a quarter
  subtotal, a total and its parts). The simpler version: Python reads the facts once, the model is told them, and Python (not the model)
  decides parent rows and two integrity tests from them. No new model call. The stored prompt does not change.
- Deleted first: nothing is added to the prompt text (10,000-char cap stands); no per-cell value is stored; no card is created by this work.

## 1. Extraction (`app/structures/workbook_facts.py`, openpyxl, no model)
`STRUCTURE_EXTRACTION_VERSION = 1`. `extract(content: bytes) -> dict`, run once per .xlsx upload before any reading (a CSV has none; the
facts are `None`). A file openpyxl cannot parse gives `{"version": 1, "has_formulas": false, "sheets": []}`: the read goes on as today.

Per sheet (`sheets[]`, file order): `name`; `hidden` (the sheet is hidden); `hidden_rows` (row numbers); `hidden_cols` (letters); `merged`
(ranges, "B2:M2"); `row_outline` and `col_outline` (only levels above 0); `indents` ({"A5": 2}, the cell indent level).

Per cell with a value, `cells[ref] = "<type>/<class>"`. Type: number, text, date, bool, error. Class: date ("month" when the format has no day, mmm-yy), percent, currency, integer,
general, text. To keep the record small only a cell that is **not** `number/general`, `number/integer` or `text/general` is listed; an unlisted cell
is read from the grid. `text_numbers` lists the refs of text cells that read as a plain number (a year-like or period-like header is not one).

Per formula cell, `formulas[ref] = [formula_without_equals, [refs]]`: the formula string and the cells it references (a range stays a range,
`$` removed, a reference to another sheet is listed as "Sheet!B5" and takes part in no relation). `has_formulas` is true when any sheet has one.
From formulas that are `SUM(...)`, `SUBTOTAL(9|109, ...)` or a `+` chain of single cells:
- `totals`: `[{"row", "parts": [rows], "cells": n}]`, a row where two or more formula cells (and at least half of its sum cells) are a sum of cells of
  the same column and the same set of rows (a range is expanded). A sum over a single cell (`=SUM($B$5:B5)`, the first cell of a YTD row) states no
  relation;
- `subtotal_cols`: `[{"col", "parts": [letters]}]`, the same for a column and cells of one row (a quarter or year column over its months).
When two rows claim one part, the visible row wins, then the first in the sheet (hidden rows and columns are read, as hidden sheets are). A total any
of whose parts another total has claimed is left out whole: no relation is stored for it, not the remainder.
Facts are matched to a sheet by its position in the workbook (`Sheet.workbook_index`, `sheets[i]`), never by name. The export and change paths
use the reader's own parent rows (the stored reading), not the formula parents, which only the checks and the engine apply.

Integrity findings (per sheet, `hardcoded`, `omitted`; counted in section 4). The thresholds of both are provisional pending tests on real packs, and
neither feeds Worth flagging yet:
- `hardcoded`: in a row's period columns (when the sheet shows period headers; else all numeric cells), a leading contiguous run of constants is
  pasted actuals and exempt (this includes a roll-forward or opening-balance seed, whichever row its formulas read). A row with at least 2 formula
  cells and more formula cells than the numeric constants after that run lists those constants: one finding per **row**, with the first flagged cell
  and all of them.
- `omitted`: a SUM over a range of two or more cells in one row or one column, in a cell below (or right of) the range, in a period column and not in a
  percent-formatted row. A numeric cell between the range and the total, or a numeric **constant** directly beyond the range's first cell, that is not
  itself a total, a date, a year-like header number or a percent, is skipped by the range; the walk beyond the range stops at any formula cell, a
  blank, a text or a total. One finding per SUM cell, with its range and the cells skipped.
Every cell in a hidden row or column is listed with `hidden: true`; an output cell shows "(hidden)" after its ref.

## 2. What the model receives (both reads and a re-read; one call per sheet, as today)
- A date-typed cell in a row of 3 or more date cells (a period row) is written as an ISO period "2023-12" when its format has no day, or
  its day is the 1st or the month's last day; any other date stays a full ISO date (a ledger's invoice date keeps its day). Never a serial
  number, never a locale string. A percent-formatted number is written as the stored fraction followed by " (fmt %)" ("0.125 (fmt %)").
  `to_number` (checks) and `reading_figure` (masker) read the marker, so a figure is never rewritten and never learned as a name.
- A block starts the sheet's text, after the "sheets in this file" line:
  `STRUCTURE FACTS (read from the file, not inferred):` then plain lines: `no formulas in file` (values-only workbook); `hidden rows: 12, 14-16`;
  `hidden columns: C`; `merged header spans: B2:M2`; `total rows: row 10 = rows 5-9`; `subtotal columns: E = B-D` (one line for each total row and each subtotal column); `cells stored as text: B7, C7`.
  Row and cell references and numbers only: no label, no value, no sheet name. At most 60 lines per sheet; over that, total rows and merged
  spans are kept, the rest dropped, and the last line is `truncated`.
- The block is outside the sheet's 40,000-token cell cap (it is not cells, like the "sheets in this file" line) and inside the call's cost,
  the allowance and the per-audit token cap, which count the whole call.
- The stored prompt is unchanged. If the prompt should say what the block is, the PR description proposes one line for George to paste.

## 3. Checks in code
- `checks.apply_formula_parents(file_map, structure)`: where a total row has a SUM formula, its parts (mapped rows) get `parent_row` = that
  row and a mapped row that points to it but is not a part loses the link. The stored reading is never edited; the effective map carries the
  formula's relation, so the engine, the lines and "Totals that don't add up" (`check_parts`) use the formula's parts. Every row whose
  `parent_row` changed gives one Diagnostics note on the file's outcome, `parent_rows_from_formula`: "parent rows set from formula (Sheet, row N)".
  No card.
- Cache: `readings.reading_key` includes `STRUCTURE_EXTRACTION_VERSION`; stored readings are read again once after the bump.

## 4. Two integrity tests (integrity-coverage.md rows 7 and 8; counted in "Completed x of y applicable checks")
| # | Check | Completed when | Result |
|---|---|---|---|
| 7 | Hardcoded cell in a formula row | an uploaded workbook has formulas | Green: none; Amber: 1 or more flagged rows. No Red yet |
| 8 | Total formula omits cells | an uploaded workbook has formulas | Green: none; Amber: 1 or more flagged SUM cells. No Red yet |
Not applicable (reason "No formulas in the uploaded workbooks") when no workbook has a formula; out of the denominator, no data request.
Finding: "{n} hardcoded cell(s) in formula rows" / "{n} cell(s) skipped by a total formula" ({n} counts flagged rows, and flagged SUM cells); Source: the first cells as "Sheet!F7". Neither
appears under Worth flagging in the memo until a Red threshold is agreed. The cells are `role_metrics.integrity_flags` of kind `hardcoded_in_formula_row` and
`total_omits_cells`; `role_metrics.structure_checks` ({files, files_with_formulas}) says whether the test ran. A hidden cell is marked and
a visible cell wins when a hidden and a visible cell state different relations.

## 5. Storage and logs (rule 17)
The facts are stored once on the dataset (`datasets.structure`), with the version, and go with the file (rule 22). The file's check outcome
(`readings.checks`) carries only the derived `structure_findings` (cell refs and formula strings, never values) and `parent_rows_from_formula`.
Logs name cell references and formula strings only.

## 6. Contract
Stored results change: `CONTRACT_VERSION` 26 -> 27, `role_metrics.integrity_flags[].kind` gains two values, `role_metrics.structure_checks` is
new, the golden file is regenerated.

## 7. Tests (no model)
Extraction on synthetic workbooks; both integrity tests (Green, Amber, Red, hidden); the facts block (lines, truncation, values-only line);
the date and percent rendering; the formula parents and the diagnostics note; the cache key; the data boundary; three perturbed variants of
`monthly_report` with the same expected map; one of them in the live reading-fixtures job.

## Architecture change (rule 32, for George's approval before merge)
What the model sees grows by the STRUCTURE FACTS block (references and numbers only), date headers and percent cells are written differently,
and the dataset stores the extracted facts. The prompt store and the owner page do not change.
