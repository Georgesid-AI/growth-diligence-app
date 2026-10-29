"""The cells a sheet reading sends, as the uploaded file holds them (docs/design/read-check-review.md section 3).

Every non-empty cell of every recognised sheet, with its spreadsheet reference: nothing sampled, nothing cut. A recognised sheet is one
whose layout has period structure (a statement, a monthly report, a snapshot, a table of columns); a sheet of one row per invoice is
not read, it would be the whole ledger. The text is unmasked here: the gateway masks it (name learning included) before it leaves.
Pure: no database, no model.
"""
import math
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from .. import recognition as rec
from . import redact

RECORD_LAYOUT = "records"


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
    """{"row", "col", "text"} of every non-empty cell of the sheet's grid (1-based; row 1 and column 1 are A1)."""
    out = []
    for r, line in enumerate(sheet.grid or [], 1):
        for c, value in enumerate(line, 1):
            text = cell_text(value)
            if text:
                out.append({"row": r, "col": c, "text": text})
    return out


def recognised_sheets(sheets, fiscal_year_end: int = 12) -> List:
    """The sheets a reading covers: those with a grid whose layout is not one row per invoice."""
    return [s for s in sheets if s.grid and rec.analyse(s, fiscal_year_end).get("layout") != RECORD_LAYOUT]


def reading_text(sheets, fiscal_year_end: int = 12) -> Optional[str]:
    """The unmasked reading text of a workbook's recognised sheets, or None when none is recognised or none holds a cell."""
    parts = []
    for sheet in recognised_sheets(sheets, fiscal_year_end):
        cells = sheet_cells(sheet)
        if cells:
            parts.append({"name": sheet.sheet, "cells": cells})
    return redact.reading_text(parts) if parts else None
