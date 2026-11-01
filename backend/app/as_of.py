"""The one as-of month of an audit (docs/specs/dates-and-periods.md section 2, read-check-review.md section 6, PR 2).

Detected when a file is read, stored once on the audit (`as_of_month`, `as_of_by`, `as_of_file`, `as_of_evidence`, `as_of_proposal`), and read
from there by the engine, recognition and the screen. Pure: it reads stored datasets and the stored outcome of the cell checks and computes
no figure.

Detection: a spreadsheet the reader mapped gives its last actual
month, and only when the checks confirmed it (app/checks.py: the header of the column is the period the reading names, and at least one
piece of the reader's evidence for the boundary is confirmed and points at that column). The audit's month is the latest across files. A
file with an earlier boundary is no conflict: it keeps its own month on its stored reading. No month is taken from the deck date, the
file name, the upload date or the last column with a number; with no confirmed month there is none ("not determined") and the audit runs
everything that does not depend on it. A typed month wins everywhere; the reader's proposal is kept beside it.
"""
import calendar
from typing import Dict, Optional

DETECTED, ANALYST = "detected", "analyst"


def detect(reads: Optional[Dict[str, Dict]] = None) -> Optional[Dict]:
    """{"month": "YYYY-MM", "file": name, "evidence": text} from the checked readings (`reads`: file hash -> the stored outcome of the checks, with
    `file`, `month` and `evidence`): the latest confirmed last actual month of all the files, or None when no file gives one (the analyst types
    it). A file the reader mapped gives its confirmed last actual month and nothing else: no fallback reads a month from the rows, the last
    column with a number, the file name, the deck or the upload date."""
    found = [(r["month"], r.get("file"), r.get("evidence")) for r in (reads or {}).values() if r.get("month")]
    if not found:
        return None
    month, file, evidence = max(found, key=lambda x: x[0])
    return {"month": month, "file": file, "evidence": evidence}


def month_end(month: str) -> str:
    """"2021-06" -> "2021-06-30": the stored form of the audit's as-of month."""
    year, mon = int(month[:4]), int(month[5:7])
    return f"{month[:7]}-{calendar.monthrange(year, mon)[1]:02d}"
