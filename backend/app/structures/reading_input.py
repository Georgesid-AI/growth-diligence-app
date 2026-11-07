"""The cells a sheet reading sends, as the uploaded file holds them (docs/design/read-check-review.md section 3).

Every non-empty cell of every sheet that has a grid, with its spreadsheet reference: nothing sampled, nothing cut. No rule decides what a
sheet is (a ledger, say): the reader reads it, and a file over the token cap is refused with its message. The text is unmasked here: the
gateway masks it (name learning included) before it leaves.
Pure: no database, no model.
"""
import math
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from . import redact, workbook_facts


def cell_text(value) -> str:
    """A cell value as its line writes it: a number as a plain decimal at full precision, a date as an ISO date, a flag as TRUE or FALSE,
    text on one line with single spaces; "" for a blank."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date)):
        return (value.date() if isinstance(value, datetime) else value).isoformat()
    if hasattr(value, "to_pydatetime"):                  # a pandas Timestamp
        return value.to_pydatetime().date().isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isinf(value):
            return ""
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def sheet_cells(sheet, structure: Optional[Dict] = None) -> List[Dict]:
    """{"row", "col", "text"} of every non-empty cell of the sheet's grid (1-based; row 1 and column 1 are A1), with the span of a merged cell
    (`row_span`, `col_span`) on the cell that holds the text. With the file's structure facts (docs/specs/structure-extraction.md section 2) a
    date cell of a period row is written as an ISO period ("2023-12") and a percent-formatted number as its stored fraction and " (fmt %)"."""
    kinds = workbook_facts.cell_kinds(structure, sheet.sheet)
    period_rows = workbook_facts.period_rows(kinds) if kinds else set()
    spans = {(r1, c1): (r2 - r1 + 1, c2 - c1 + 1) for r1, c1, r2, c2 in ((sheet.fmt or {}).get("merged") or [])}
    out = []
    for r, line in enumerate(sheet.grid or [], 1):
        for c, value in enumerate(line, 1):
            text = cell_text(value)
            if text and kinds:
                kind = kinds.get(redact.cell_ref(r, c))
                if kind and kind.startswith("date/") and r in period_rows:
                    text = workbook_facts.period_text(value, kind) or text
                elif kind == "number/percent" and isinstance(value, (int, float)) and not isinstance(value, bool):
                    text += workbook_facts.PERCENT_MARKER
            if text:
                cell = {"row": r, "col": c, "text": text}
                rows, cols = spans.get((r, c), (1, 1))
                if rows > 1:
                    cell["row_span"] = rows
                if cols > 1:
                    cell["col_span"] = cols
                out.append(cell)
    return out


def recognised_sheets(sheets) -> List:
    """The sheets a reading covers: every sheet with a grid."""
    return [s for s in sheets if s.grid]


def reading_text(sheets, structure: Optional[Dict] = None) -> Optional[str]:
    """The unmasked reading text of a workbook's sheets, or None when none holds a cell."""
    parts = []
    for sheet in recognised_sheets(sheets):
        cells = sheet_cells(sheet, structure)
        if cells:
            parts.append({"name": sheet.sheet, "cells": cells})
    return redact.reading_text(parts) if parts else None


def facts_blocks(sheets, structure: Optional[Dict]) -> Optional[List[str]]:
    """The STRUCTURE FACTS block of each sheet the reading text holds, in its order ("sheet 1", "sheet 2" ...), or None for a file with no facts (a CSV)."""
    if not structure or not structure.get("sheets"):
        return None
    return [workbook_facts.facts_block(structure, s.sheet) or "" for s in recognised_sheets(sheets) if sheet_cells(s, structure)]
