"""The one as-of month of an audit (docs/specs/dates-and-periods.md section 2, read-check-review.md section 6, PR 2).

Detected when a file is read, stored once on the audit (`as_of_month`, `as_of_by`, `as_of_file`, `as_of_evidence`, `as_of_proposal`), and read
from there by the engine, recognition and the screen. Pure: it reads stored datasets and the stored outcome of the cell checks and computes
no figure.

Detection: a revenue file of invoices gives its last month with a non-zero amount. A spreadsheet the reader mapped gives its last actual
month, and only when the checks confirmed it (app/checks.py: the header of the column is the period the reading names, and at least one
piece of the reader's evidence for the boundary is confirmed and points at that column). The audit's month is the latest across files. A
file with an earlier boundary is no conflict: it keeps its own month on its stored reading. No month is taken from the deck date, the
file name, the upload date or the last column with a number; with no confirmed month there is none ("not determined") and the audit runs
everything that does not depend on it. A typed month wins everywhere; the reader's proposal is kept beside it.
"""
import calendar
from typing import Dict, Optional

from app import column_rules as cr

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


def detect(datasets: Dict[str, Dict], fiscal_year_end: int = 12, reads: Optional[Dict[str, Dict]] = None) -> Optional[Dict]:
    """{"month": "YYYY-MM", "file": name, "evidence": text or None} from the stored datasets by dtype and from the checked readings
    (`reads`: file hash -> the stored outcome of the checks, with `month` and `evidence`), the latest month of them all, or None when no
    file gives one (the analyst types it). A file of rows gives its last month with revenue (a P&L of rows up to the revenue file's month);
    a file the reader mapped gives its confirmed last actual month and nothing else."""
    found = []
    revenue_month = revenue_last(datasets.get("revenue"))
    for dtype in ("revenue", "pnl"):
        ds = datasets.get(dtype)
        if not ds:
            continue
        rows = revenue_month if dtype == "revenue" else pnl_month(ds, revenue_month)
        if rows:
            found.append((rows, ds, None))
        read = (reads or {}).get(ds.get("file_hash"))
        if read and read.get("month"):
            found.append((read["month"], ds, read.get("evidence")))
    if not found:
        return None
    month, ds, evidence = max(found, key=lambda x: x[0])
    return {"month": month, "file": ds.get("file"), "evidence": evidence}


def month_end(month: str) -> str:
    """"2021-06" -> "2021-06-30": the stored form of the audit's as-of month."""
    year, mon = int(month[:4]), int(month[5:7])
    return f"{month[:7]}-{calendar.monthrange(year, mon)[1]:02d}"
