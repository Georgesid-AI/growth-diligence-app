"""A period header as a period (docs/design/read-check-review.md section 5): "2025", "FY24", "Q3 2025", "Mar-25", a date, with the tag the header
itself carries ("2025F", "FY24 B"). Pure: no database, no model. The cell checks (app/checks.py) read a column's header with it."""
import re
from datetime import date, datetime
from typing import Dict, Optional, Tuple

from . import column_rules as cr

# Tags (26.2): a cell above a period header, or a tag in the header itself.
_TAG_WORDS = ((re.compile(r"(?i)\b(?:actuals?|act)\b"), "actual"),
              (re.compile(r"(?i)\b(?:forecasts?|fcst|estimates?|est|projected|projections?)\b"), "forecast"),
              (re.compile(r"(?i)\b(?:budgets?|bud|plan)\b"), "budget"))

_TAG_LETTERS = {"A": "actual", "F": "forecast", "E": "forecast", "B": "budget"}

_HEADER_TAG = re.compile(r"^(?P<body>.*\d)\s?(?P<tag>[AFBE])$")

_PTD = re.compile(r"(?i)^(?:period to date|ptd|month to date|mtd|current (?:period|month))$")

_YTD = re.compile(r"(?i)^(?:year to date|ytd)$")

_FY_SHORT = re.compile(r"(?i)^FY\s?'?(\d{2})$")

_FY_SPLIT = re.compile(r"(?i)^(?:FY\s?)?((?:19|20)\d{2})\s?/\s?(\d{2}|\d{4})$")

# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------
def _blank(v) -> bool:
    return cr._blank(v)

def _year_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() and 1900 <= v <= 2100

# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
def _add_months(year: int, month: int, n: int) -> Tuple[int, int]:
    k = year * 12 + (month - 1) + n
    return k // 12, k % 12 + 1

def _ym(ym: Tuple[int, int]) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"

def _fiscal(year: int, fye: int, first: int, months: int) -> Tuple[str, str]:
    """(first month, last month) of a part of fiscal year `year` (named by the year it ends in): `first` months after the year's
    first month, `months` long."""
    start = _add_months(year, fye, -11 + first)
    return _ym(start), _ym(_add_months(*start, months - 1))

def period_of(value, fye: int = 12) -> Optional[Dict]:
    """A period header as {"grain", "year", "start", "end", "tag"}, or None. `year` is the fiscal year (the year it ends in) of a
    year, half, quarter or month; `start` and `end` its first and last month (YYYY-MM); `tag` the tag the header itself carries
    ("2025F", "FY24 B", "2023 Actual"). Year to date and period to date have no months."""
    if _blank(value):
        return None
    if isinstance(value, (datetime, date)):
        d = value if isinstance(value, date) else value.date()
        return _month(d.year, d.month, fye, None)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _year(int(value), fye, None) if _year_number(value) else None
    text, tag = re.sub(r"\s+", " ", str(value)).strip(), None
    for rx, name in _TAG_WORDS:
        if rx.search(text):
            tag, text = name, re.sub(r"\s+", " ", rx.sub(" ", text)).strip(" -–:()")
    m = _HEADER_TAG.match(text)
    if m and (cr.parse_period(m.group("body").strip()) or _FY_SHORT.match(m.group("body").strip())):
        tag, text = tag or _TAG_LETTERS[m.group("tag")], m.group("body").strip()
    if _PTD.match(text):
        return {"grain": "period_to_date", "year": None, "start": None, "end": None, "tag": tag}
    if _YTD.match(text):
        return {"grain": "ytd", "year": None, "start": None, "end": None, "tag": tag}
    m = _FY_SHORT.match(text)
    if m:
        return _year(2000 + int(m.group(1)), fye, tag)
    m = _FY_SPLIT.match(text)
    if m:
        end = m.group(2)
        return _year(int(m.group(1)[:2] + end) if len(end) == 2 else int(end), fye, tag)
    found = cr.parse_period(text)
    if not found:
        return None
    grain, day = found
    if grain == "ytd":
        return {"grain": "ytd", "year": None, "start": None, "end": None, "tag": tag}
    if grain == "year":
        return _year(int(cr._P_YEAR.fullmatch(text).group(1)), fye, tag)
    if grain in ("quarter", "half"):
        upper = text.upper()
        q = re.search(r"[QH]([1-4])", upper)
        digits = re.search(r"\d{2,4}", upper[:q.start()] + " " + upper[q.end():]).group()
        year = int(digits) + (2000 if len(digits) == 2 else 0)
        size = 3 if grain == "quarter" else 6
        start, end = _fiscal(year, fye, size * (int(q.group(1)) - 1), size)
        return {"grain": grain, "year": year, "start": start, "end": end, "tag": tag}
    return _month(day.year, day.month, fye, tag)

def _year(year: int, fye: int, tag: Optional[str]) -> Dict:
    start, end = _fiscal(year, fye, 0, 12)
    return {"grain": "year", "year": year, "start": start, "end": end, "tag": tag}

def _month(year: int, month: int, fye: int, tag: Optional[str]) -> Dict:
    ym = _ym((year, month))
    return {"grain": "month", "year": year + (1 if month > fye else 0), "start": ym, "end": ym, "tag": tag}
