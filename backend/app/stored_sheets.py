"""The sheets of a stored file, as the dataset keeps them to read the file again (the sheet reader's re-read, the reviewer's re-read, the cell
window of a Source link). Pure: no database, no model. Every value is one MongoDB can store."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Dict, List

import pandas as pd

from . import column_rules as cr


def storable(value):
    """A cell as MongoDB can keep it: a number, text, a boolean, a datetime or nothing. A time of day or a duration (not BSON) becomes
    text or seconds, a date a datetime, a decimal or a numpy number a plain number, anything else text (review H8)."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, datetime):
        return value.to_pydatetime() if isinstance(value, pd.Timestamp) else value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if hasattr(value, "item") and not isinstance(value, (int, float)):
        try:
            return storable(value.item())
        except (ValueError, TypeError):
            return str(value)
    if isinstance(value, int):
        return value if -2 ** 63 <= value < 2 ** 63 else float(value)
    if isinstance(value, (float, Decimal)):
        return float(value)
    return str(value)


def pack_sheets(sheets) -> List[Dict]:
    """The sheets of a file as the dataset keeps them to read the file again: name, whether it was a CSV, every row (the caller refuses a dataset over the size limit; nothing is cut),
    each cell's indent and the merged spans. Every value is one MongoDB can store (review H8)."""
    out = []
    for s in sheets:
        fmt = s.fmt or {}
        out.append({"name": s.sheet, "csv": s.raw_headers is None and not fmt, "grid": [[storable(c) for c in r] for r in (s.grid or [])],
                    "indents": [[r, c, n] for (r, c), n in (fmt.get("indents") or {}).items()],
                    "merged": [list(m) for m in fmt.get("merged") or []]})
    return out


def unpack_sheets(stored: List[Dict]):
    """The sheets of pack_sheets, read again by the same rules that read the file."""
    out = []
    for item in stored or []:
        fmt = {"indents": {(r, c): n for r, c, n in item.get("indents") or []}, "merged": [tuple(m) for m in item.get("merged") or []]} \
            if (item.get("indents") or item.get("merged")) else {}
        sheet = cr._read_grid([list(r) for r in item["grid"]], item["name"], bool(item.get("csv")), fmt)
        if sheet is not None:
            out.append(sheet)
    return out
