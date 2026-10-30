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

from . import redact


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


def sheet_cells(sheet) -> List[Dict]:
    """{"row", "col", "text"} of every non-empty cell of the sheet's grid (1-based; row 1 and column 1 are A1), with the span of a merged cell
    (`row_span`, `col_span`) on the cell that holds the text."""
    spans = {(r1, c1): (r2 - r1 + 1, c2 - c1 + 1) for r1, c1, r2, c2 in ((sheet.fmt or {}).get("merged") or [])}
    out = []
    for r, line in enumerate(sheet.grid or [], 1):
        for c, value in enumerate(line, 1):
            text = cell_text(value)
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


def reading_text(sheets) -> Optional[str]:
    """The unmasked reading text of a workbook's sheets, or None when none holds a cell."""
    parts = []
    for sheet in recognised_sheets(sheets):
        cells = sheet_cells(sheet)
        if cells:
            parts.append({"name": sheet.sheet, "cells": cells})
    return redact.reading_text(parts) if parts else None
