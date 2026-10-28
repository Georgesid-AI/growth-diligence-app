"""The one as-of month of an audit (docs/specs/dates-and-periods.md section 2, amended 2026-10-28).

Detected when a file is mapped, stored once on the audit (`as_of_month`, `as_of_by`, `as_of_file`, `as_of_cue`), and read from there by
the engine, recognition and the screen. Pure: it reads stored datasets and computes no figure.

Detection: a revenue file of invoices gives its last month with a non-zero amount. A file read as a sheet of period columns (a P&L, a
monthly report, a revenue summary) gives the end month of the last actual column the model suggested (`last_actual_column`), and only
when Python's check of its cue holds: the cue cell exists on the sheet with the cue's text, the text holds a plan word (budget, plan,
forecast, FC, estimate, projection) and the cell is a row label or sits above or in the header row of a column after the suggested one.
A suggestion that fails the check, or none, gives nothing: no month is taken from the last column with a number. The later month of
the two files wins.
"""
import calendar
import re
from typing import Dict, List, Optional

from app import column_rules as cr
from app import recognition as rec
from app.structures import sheet as sheet_mod

DETECTED, ANALYST = "detected", "analyst"


def _amount(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace(" ", ""))
    except ValueError:
        return None


PLAN_WORD = re.compile(r"(?i)(?<![^\W\d_])(?:budget(?:ed|s)?|plan(?:ned|s)?|forecast(?:s|ed)?|fc|estimates?|estimated|projections?|projected)(?![^\W\d_])")
_A1, _RC, _ROW = re.compile(r"^([A-Z]{1,3})([1-9]\d*)$"), re.compile(r"^r([1-9]\d*)c([1-9]\d*)$"), re.compile(r"^r([1-9]\d*)$")


def revenue_last(ds: Optional[Dict]) -> Optional[str]:
    """YYYY-MM of the last month of a mapped revenue file with a valid date and a non-zero amount."""
    mapping, rows = (ds or {}).get("mapping") or {}, (ds or {}).get("rows") or []
    date_col, amount_col = mapping.get("invoice_date"), mapping.get("amount")
    if not (date_col and rows):
        return None
    if amount_col:
        rows = [r for r in rows if _amount(r.get(amount_col)) not in (None, 0.0)]
    found = cr.months_of([r.get(date_col) for r in rows])
    return found["last"] if found else None


def _address(cell: str) -> Optional[tuple]:
    """(row, column or None for a row label) of a cue address: D3, r3c4 or r12."""
    cell = (cell or "").strip()
    if m := _A1.match(cell):
        return int(m.group(2)), sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(m.group(1))))
    if m := _RC.match(cell):
        return int(m.group(1)), int(m.group(2))
    if m := _ROW.match(cell):
        return int(m.group(1)), None
    return None


def _same_text(a, b) -> bool:
    return " ".join(str(a).split()).casefold() == " ".join(str(b).split()).casefold()


def _frame(ds: Dict, sheet, fiscal_year_end: int) -> Optional[Dict]:
    """{"header_row", "label_col", "ends": {column: end month}} of the sheet a suggestion names: the statement's map when the file has one,
    else the sheet as recognition reads it (a labels layout; any other has no period columns)."""
    if ds.get("sheet_map"):
        m = ds["sheet_map"]
        return {"header_row": m["header_row"], "label_col": m["label_col"],
                "ends": {c["col"]: c["end"] for c in statement_columns(m, fiscal_year_end)}}
    info = rec.analyse(sheet, fiscal_year_end)
    if info["layout"] != "labels":
        return None
    return {"header_row": info["header_row"], "label_col": info["label_col"],
            "ends": {p["col"]: p["end"] for p in info["periods"] if p["end"]}}


def suggestion(ds: Optional[Dict], fiscal_year_end: int = 12) -> Optional[Dict]:
    """{"month": "YYYY-MM", "cue": text} when the model's suggested last actual column (`recognition_proposal`) passes Python's check, else
    None: the cue cell is on the sheet with the cue's text, that text holds a plan word, the cell is a row label or sits above or in the
    header row of a column after the suggested one, and the suggested column is a dated period column of the sheet."""
    prop = (ds or {}).get("recognition_proposal") or {}
    column, cue = prop.get("last_actual_column"), prop.get("boundary_cue")
    if isinstance(column, bool) or not isinstance(column, int) or not isinstance(cue, dict):
        return None
    where, text = _address(cue.get("cell")), cue.get("text")
    sheets = rec.unpack_sheets(ds.get("recognition_sheets"))
    position = prop.get("sheet")
    if where is None or not isinstance(text, str) or not isinstance(position, int) or not 1 <= position <= len(sheets):
        return None
    sheet = sheets[position - 1]
    frame = _frame(ds, sheet, fiscal_year_end)
    end = (frame or {}).get("ends", {}).get(column)
    if not end:
        return None
    row, col = where
    col = frame["label_col"] if col is None else col
    cell = rec._cell(sheet.grid or [], row, col)
    if cr._blank(cell) or not _same_text(cell, text) or not PLAN_WORD.search(str(cell)):
        return None
    reach = max([col] + [c2 for r1, c1, r2, c2 in (sheet.fmt or {}).get("merged", []) if r1 <= row <= r2 and c1 <= col <= c2])
    label_row = col == frame["label_col"] and row > frame["header_row"]
    if not label_row and not (row <= frame["header_row"] and reach > column):
        return None
    return {"month": end, "cue": str(cell).strip()}


def statement_columns(sheet_map: Dict, fiscal_year_end: int) -> List[Dict]:
    """The dated columns of a statement P&L with the revenue each holds: {"col", "header", "grain", "end", "tag", "revenue"}."""
    periods = sheet_mod.with_periods(sheet_map["periods"], fiscal_year_end)
    chosen = sheet_mod.pick(sheet_map["lines"], "revenue")
    out = []
    for k, p in enumerate(periods):
        if p["grain"] not in ("month", "quarter", "half", "year") or not p.get("end"):
            continue
        value = sheet_mod._field_values(chosen, k, 1, "revenue") if chosen else None
        out.append({"col": p["col"], "header": p["header"], "grain": p["grain"], "end": p["end"], "tag": p.get("tag"),
                    "revenue": value})
    return out


def pnl_month(ds: Optional[Dict], revenue_month: Optional[str] = None) -> Optional[str]:
    """YYYY-MM of the last month of a P&L mapped as one row per month (month and revenue columns) that has a non-zero revenue, up to the
    revenue file's month (a later row is plan); with none up to it, the last such month."""
    mapping, rows = (ds or {}).get("mapping") or {}, (ds or {}).get("rows") or []
    month_col, revenue_col = mapping.get("month"), mapping.get("revenue")
    if not (month_col and not (ds or {}).get("sheet_map")):
        return None
    found = [cr.months_of([r.get(month_col)]) for r in rows if not revenue_col or _amount(r.get(revenue_col)) not in (None, 0.0)]
    months = sorted(f["last"] for f in found if f)
    return ([m for m in months if revenue_month is None or m <= revenue_month] or months or [None])[-1]


def detect(datasets: Dict[str, Dict], fiscal_year_end: int = 12) -> Optional[Dict]:
    """{"month": "YYYY-MM", "file": name, "cue": text or None} from the stored datasets by dtype, the later month of the two files, or
    None when no file gives one (the analyst types it). A file of rows gives its last month with revenue (a P&L of rows up to the revenue
    file's month); a file read as a sheet gives its checked suggestion (`suggestion`) and nothing else."""
    found = []
    revenue_month = revenue_last(datasets.get("revenue"))
    for dtype in ("revenue", "pnl"):
        ds = datasets.get(dtype)
        if not ds:
            continue
        rows = revenue_month if dtype == "revenue" else pnl_month(ds, revenue_month)
        if rows:
            found.append((rows, ds, None))
        elif not ds.get("rows") or not (ds.get("mapping") or {}):
            got = suggestion(ds, fiscal_year_end)
            if got:
                found.append((got["month"], ds, got["cue"]))
    if not found:
        return None
    month, ds, cue = max(found, key=lambda x: x[0])
    return {"month": month, "file": ds.get("file"), "cue": cue}


def last_actual_column(sheet_map: Dict, fiscal_year_end: int, as_of: Optional[str]) -> Optional[Dict]:
    """The last actual column of a statement P&L under the audit's as-of month: not marked budget, plan or forecast, ending on or
    before it (the statement feed's rule, sheet.is_actual); with no such column, None."""
    cols = [c for c in statement_columns(sheet_map, fiscal_year_end) if sheet_mod.is_actual(c, as_of)]
    return cols[-1] if cols else None


def month_end(month: str) -> str:
    """"2021-06" -> "2021-06-30": the stored form of the audit's as-of month."""
    year, mon = int(month[:4]), int(month[5:7])
    return f"{month[:7]}-{calendar.monthrange(year, mon)[1]:02d}"
