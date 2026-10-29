"""The cells a sheet reading sends, as the uploaded file holds them (docs/design/read-check-review.md section 3).

Every non-empty cell of every recognised sheet, with its spreadsheet reference: nothing sampled, nothing cut. A recognised sheet is one
that is not a ledger (see `recognised_sheets`). The text is unmasked here: the gateway masks it (name learning included) before it leaves.
Pure: no database, no model.
"""
import math
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from .. import recognition as rec
from . import redact

RECORD_LAYOUT = "records"
RECORD_ROWS = 40         # a sheet the rules read as one row per record is a ledger above this many rows: it is not sent (it would be the whole ledger)


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


def recognised_sheets(sheets, fiscal_year_end: int = 12) -> List:
    """The sheets a reading covers: those with a grid, except a ledger. The rules read a sheet they cannot place (an actual | budget | variance
    layout, say) as one row per record, so a sheet read that way is skipped only when it is long: above RECORD_ROWS rows it is an invoice
    list, which the reader would only ever refuse for its size. Short or not, a sheet the rules read as periods is always read."""
    return [s for s in sheets if s.grid and (rec.analyse(s, fiscal_year_end).get("layout") != RECORD_LAYOUT or len(s.grid) <= RECORD_ROWS)]


def reading_text(sheets, fiscal_year_end: int = 12) -> Optional[str]:
    """The unmasked reading text of a workbook's recognised sheets, or None when none is recognised or none holds a cell."""
    parts = []
    for sheet in recognised_sheets(sheets, fiscal_year_end):
        cells = sheet_cells(sheet)
        if cells:
            parts.append({"name": sheet.sheet, "cells": cells})
    return redact.reading_text(parts) if parts else None
