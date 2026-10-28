"""The one as-of month of an audit (docs/specs/dates-and-periods.md section 2, amended 2026-10-28).

Detected when a file is mapped, stored once on the audit (`as_of_month`, `as_of_by`, `as_of_file`), and read from there by the
engine, recognition and the screen. Pure: it reads stored datasets and computes no figure.

Detection: the last period with a non-zero revenue value across the revenue file and the P&L. The revenue file gives its last
month with a non-zero amount. A P&L column counts as actual when its header is not marked budget, plan or forecast and its
period ends on or before that month (with no revenue file: when it is not marked); the P&L gives the end month of its last
actual column with non-zero revenue, else of its last unmarked column with non-zero revenue. A yearly column ends in the fiscal year-end
month of its year.
"""
import calendar
from typing import Dict, List, Optional

from app import column_rules as cr
from app.structures import sheet as sheet_mod

DETECTED, ANALYST = "detected", "analyst"
EXCLUDED_TAGS = ("forecast", "budget")


def _amount(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def revenue_last(ds: Optional[Dict]) -> Optional[str]:
    """YYYY-MM of the last month of a mapped revenue file with a valid date and a non-zero amount."""
    if not ds:
        return None
    mapping, rows = ds.get("mapping") or {}, ds.get("rows") or []
    date_col, amount_col = mapping.get("invoice_date"), mapping.get("amount")
    if date_col and rows:
        if amount_col:
            rows = [r for r in rows if _amount(r.get(amount_col)) not in (None, 0.0)]
        found = cr.months_of([r.get(date_col) for r in rows])
        return found["last"] if found else None
    return ((ds.get("months") or {}).get("last")) or None      # a recognised report with no customer rows: its months as stored


def _pick(columns: List[Dict], revenue_month: Optional[str]) -> Optional[str]:
    """The end month of the last actual column with non-zero revenue, else of the last column with non-zero revenue.
    `columns`: {"end", "tag", "revenue"} in file order."""
    live = [c for c in columns if c["end"] and c["revenue"] and c["tag"] not in EXCLUDED_TAGS]
    actual = [c for c in live if revenue_month is None or c["end"] <= revenue_month]
    return (actual or live)[-1]["end"] if live else None


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


def pnl_month(ds: Optional[Dict], fiscal_year_end: int, revenue_month: Optional[str]) -> Optional[str]:
    if not ds:
        return None
    if ds.get("sheet_map"):
        return _pick(statement_columns(ds["sheet_map"], fiscal_year_end), revenue_month)
    mapping, rows = ds.get("mapping") or {}, ds.get("rows") or []
    month_col, revenue_col = mapping.get("month"), mapping.get("revenue")
    if not month_col:
        return None
    columns = []
    for r in rows:
        found = cr.months_of([r.get(month_col)])
        if found:
            columns.append({"end": found["last"], "tag": None, "revenue": _amount(r.get(revenue_col)) if revenue_col else 1.0})
    return _pick(sorted(columns, key=lambda c: c["end"]), revenue_month)


def detect(datasets: Dict[str, Dict], fiscal_year_end: int = 12) -> Optional[Dict]:
    """{"month": "YYYY-MM", "file": name} from the stored datasets by dtype, or None when no file holds a revenue figure."""
    rev, pnl = datasets.get("revenue"), datasets.get("pnl")
    revenue_month = revenue_last(rev)
    pnl_found = pnl_month(pnl, fiscal_year_end, revenue_month)
    found = [(m, d) for m, d in ((revenue_month, rev), (pnl_found, pnl)) if m]
    if not found:
        return None
    month, ds = max(found, key=lambda x: x[0])
    return {"month": month, "file": ds.get("file")}


def last_actual_column(sheet_map: Dict, fiscal_year_end: int, as_of: Optional[str]) -> Optional[Dict]:
    """The last actual column of a statement P&L under the audit's as-of month: not marked budget, plan or forecast, ending on or
    before it; with no such column, None."""
    cols = [c for c in statement_columns(sheet_map, fiscal_year_end) if c["tag"] not in EXCLUDED_TAGS
            and (as_of is None or c["end"] <= as_of[:7])]
    return cols[-1] if cols else None


def month_end(month: str) -> str:
    """"2021-06" -> "2021-06-30": the stored form of the audit's as-of month."""
    year, mon = int(month[:4]), int(month[5:7])
    return f"{month[:7]}-{calendar.monthrange(year, mon)[1]:02d}"
