"""Forecast tables read as claims (docs/specs/chat-upload.md section 20). Pure Python: no database, no model, no network.

A file the mapping cannot read (a miss, section 19) whose periods run across the columns is read here as claims: one plan line
(revenue, ARR, MRR, bookings, gross margin, EBITDA, cash balance, headcount, installed units, customers) and one year each, in
the table-row shape of a deck candidate (deck-parser.md section 2: one candidate per line, its values by period). Python reads
every value from its cell; nothing here reaches the gateway, and the register keeps every such claim Unverified, with no value at
stake and no overlaps (claim_matching). The list is computed on read from the stored file rows: nothing is stored until the
analyst confirms (server.py).
"""
import re
from datetime import date
from typing import Dict, List, Optional

from openpyxl.utils import get_column_letter

from . import column_rules as cr
from .decks import claims as deck_claims

MAX_CLAIMS = 60                 # per file; claims past it, in row order, are dropped and the bubble says so (20.2)
ORIGIN = "forecast_file"        # the candidate's origin; the register reads it (claim_matching.FORECAST_FILE)
SOURCE_KIND = "sheet"
SHAPES = ("summary", "monthly_wide")        # the misses with periods across the columns (column_rules.describe)
SNIPPET_MAX = deck_claims.SNIPPET_MAX

# 20.1: the plan lines, by header synonyms as in column_rules.FIELD_DEFS, first match in this order. "words" count as whole words
# anywhere in the label, "whole" only as the whole label ("Sales" is revenue, "Sales headcount" is not).
LINE_DEFS = (
    ("arr", {"words": ("arr", "annual recurring revenue")}),
    ("mrr", {"words": ("mrr", "monthly recurring revenue")}),
    ("gross_margin", {"words": ("gross margin", "gross profit")}),
    ("ebitda", {"words": ("ebitda",)}),
    ("bookings", {"words": ("booking", "bookings")}),
    ("revenue", {"words": ("revenue", "revenues", "net sales"), "whole": ("sales", "total sales")}),
    ("cash_balance", {"words": ("cash balance", "closing cash", "ending cash", "cash at end of period", "cash at end of year",
                                "cash at year end", "cash position", "cash on hand", "cash and cash equivalents"), "whole": ("cash",)}),
    ("headcount", {"words": ("headcount", "head count", "fte", "ftes", "employees", "team size")}),
    ("installed_units", {"words": ("installed units", "installed base", "units installed", "installations")}),
    ("customers", {"words": ("customer", "customers", "client", "clients", "subscribers")}),
)
# Not claims: the cost sub-lines, and a change or a per-unit figure of a plan line.
NOT_CLAIMS = frozenset(("cost", "costs", "cogs", "expense", "expenses", "opex", "capex", "spend", "marketing", "payroll", "salaries",
                        "growth", "yoy", "cagr", "change", "variance", "per", "average", "arpu", "churn", "churned", "new", "lost",
                        "added", "flow", "burn", "deferred", "ltv", "cac", "lifetime", "retention"))
_RATE = re.compile(r"%|\b(?:margin|ratio|rate)\b")      # a rate: only gross margin may be one
_BRACKETS = re.compile(r"[(\[][^)\]]*[)\]]")
FLOWS = ("revenue", "bookings", "gross_margin", "ebitda")     # summed over a year; the other lines are balances or counts
MONEY = ("revenue", "arr", "mrr", "bookings", "gross_margin", "ebitda", "cash_balance")
COUNT_UNITS = {"headcount": "people", "installed_units": "units", "customers": "customers"}
CLAIM_TYPES = {"revenue": "revenue", "arr": "revenue", "mrr": "revenue", "bookings": "revenue", "gross_margin": "gross_profit",
               "ebitda": "ebitda", "cash_balance": "cash", "headcount": "people", "installed_units": deck_claims.INSTALLED_UNITS,
               "customers": "customers"}
RATE_TYPE = "gross_margin"      # a gross margin line read as a rate
PARTS = {"quarter": 4, "half": 2, "month": 12}      # the parts of a year a missing year column is rolled up from


def metric_of(label) -> Optional[str]:
    """The plan line a label names (20.1), or None: a cost sub-line, a change, a per-unit figure, a rate other than gross margin
    and a line no synonym names are no claims."""
    raw = str(label or "").strip()
    text = cr._norm(_BRACKETS.sub(" ", raw))
    words = text.split()
    if not words or NOT_CLAIMS.intersection(words):
        return None
    padded = f" {text} "
    for metric, defs in LINE_DEFS:
        if text in defs.get("whole", ()) or any(f" {w} " in padded for w in defs["words"]):
            if metric != "gross_margin" and _RATE.search(raw.lower()):
                return None
            return metric
    return None


def _part(text: str, monthly_day: Optional[date], fiscal_year_end: int) -> Optional[tuple]:
    """(fiscal year, grain, index in the year) of one period: a year column, a quarter or half label (its year is the fiscal year,
    deck-parser.md section 2) or a month (grouped by the audit's year-end). None for a year to date or anything else."""
    if monthly_day is not None:
        d = monthly_day
        return d.year + (1 if d.month > fiscal_year_end else 0), "month", (d.month - fiscal_year_end - 1) % 12
    found = cr.parse_period(text)
    if not found:
        return None
    grain = found[0]
    if grain == "year":
        return int(cr._P_YEAR.fullmatch(text.strip()).group(1)), "year", 0
    if grain in ("quarter", "half"):
        t = text.strip().upper()
        m = re.search(r"[QH]([1-4])", t)
        year = re.search(r"\d{2,4}", t[:m.start()] + " " + t[m.end():]).group()
        return int(year) + (2000 if len(year) == 2 else 0), grain, int(m.group(1)) - 1
    if grain == "month" and found[1]:
        d = found[1]
        return d.year + (1 if d.month > fiscal_year_end else 0), "month", (d.month - fiscal_year_end - 1) % 12
    return None


def _number(v) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v if v == v else None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _clean(v: float):
    v = round(v, 6)
    return int(v) if float(v).is_integer() else v


def _cell(first_col: int, j: int, row: int) -> str:
    return f"{get_column_letter(first_col + j)}{row}"


def read(ds: Dict, fiscal_year_end: int = 12) -> Optional[Dict]:
    """The claims of a stored file whose periods run across the columns: {"sheet", "range", "count", "total", "capped", "lines"}, the
    lines in sheet-row order, each {"row", "label", "metric", "claim_type", "unit", "currency", "values"} with per year {"target_date",
    "period", "period_text", "value", "cell"}; at most MAX_CLAIMS values in all, the first by row order. `ds` is the stored dataset
    with its rows. None when it is no such table or names no plan line."""
    wide, columns = ds.get("wide"), ds.get("columns") or []
    if not wide or len(columns) < 3 or columns[-1] != "Value" or columns[-2] not in ("Period", "Date"):
        return None
    monthly = bool(wide.get("monthly"))
    headers = ds.get("raw_headers") or []
    col_of: Dict = {}
    for j, h in enumerate(headers):
        found = cr.parse_period(h) if h else None
        key = (found[1] if found and found[0] == "month" else None) if monthly else h
        if key is not None:
            col_of.setdefault(key, j)
    label_col, period_col = columns[0], columns[-2]
    lines: Dict[int, Dict] = {}
    for row, n in zip(ds.get("rows") or [], ds.get("row_numbers") or []):
        if n not in lines:
            label = row.get(label_col)
            lines[n] = {"row": n, "label": str(label).strip() if label is not None else "", "metric": metric_of(label), "parts": []}
        line, value = lines[n], _number(row.get("Value"))
        if not line["metric"] or value is None:
            continue
        text = str(row.get(period_col) or "")
        day = date.fromisoformat(text[:10]) if monthly else None
        part = _part(text, day, fiscal_year_end)
        j = col_of.get(day if monthly else text)
        if part and j is not None:
            line["parts"].append({"fy": part[0], "grain": part[1], "index": part[2], "value": value, "j": j, "header": headers[j]})
    return assemble(lines, ds, fiscal_year_end)


def assemble(lines: Dict[int, Dict], ds: Dict, fiscal_year_end: int = 12) -> Optional[Dict]:
    """The claims of `lines` ({sheet row: {"row", "label", "metric", "parts"}}, each part {"fy", "grain", "index", "value", "j",
    "header"} and, from a statement read by structures/sheet.py, its column's "tag"): one claim per line and fiscal year, capped,
    with the range they cite. None when no line has a claim."""
    first = int(ds.get("first_col") or 1)
    out, total = [], 0
    for n in sorted(lines):
        line = lines[n]
        if not line["metric"] or not line["parts"]:
            continue
        values = _years(line, fiscal_year_end, first, n, float(ds.get("unit_scale") or 1))
        if not values:
            continue
        metric = line["metric"]
        rate = metric == "gross_margin" and line["is_rate"]
        out.append({"row": n, "label": line["label"], "metric": metric,
                    "claim_type": RATE_TYPE if rate else CLAIM_TYPES[metric],
                    "unit": "%" if rate else COUNT_UNITS.get(metric),
                    "currency": None if rate or metric not in MONEY else (ds.get("title_currency") or cr.title_currency([line["label"]])),
                    "values": values})
        total += len(values)
    kept, room = [], MAX_CLAIMS
    for line in out:
        if room <= 0:
            break
        kept.append({**line, "values": line["values"][:room]})
        room -= len(kept[-1]["values"])
    if not kept:
        return None
    cells = [(line["row"], v["cols"]) for line in kept for v in line["values"]]
    low, high = min(c[0] for _, c in cells), max(c[1] for _, c in cells)
    span = f"{_cell(first, low, min(r for r, _ in cells))}:{_cell(first, high, max(r for r, _ in cells))}"
    for line in kept:
        for v in line["values"]:
            v.pop("cols")
    count = sum(len(line["values"]) for line in kept)
    return {"sheet": ds.get("sheet") or "", "range": span, "count": count, "total": total, "capped": total > count, "lines": kept}


def _years(line: Dict, fiscal_year_end: int, first: int, row: int, scale: float) -> List[Dict]:
    """A line's claims, one per fiscal year (20.2): a year column as stated; else its quarters, halves or months rolled up, a flow
    summed when every part is there, a balance or a count read at the year's last part. A rate is read from year columns only."""
    metric, parts = line["metric"], line["parts"]
    rate = metric == "gross_margin" and ("%" in line["label"] or all(-1 <= p["value"] <= 1 for p in parts))
    line["is_rate"] = rate
    by_year: Dict[int, List[Dict]] = {}
    for p in parts:
        by_year.setdefault(p["fy"], []).append(p)
    out = []
    for fy in sorted(by_year):
        found = by_year[fy]
        stated = next((p for p in found if p["grain"] == "year"), None)
        if stated:
            value, used, period, text = stated["value"], [stated], stated["header"], stated["header"]
        elif rate:
            continue
        else:
            grain = next((g for g in PARTS if any(p["grain"] == g for p in found)), None)
            if grain is None:
                continue
            by_index = {}
            for p in found:
                if p["grain"] == grain:
                    by_index.setdefault(p["index"], p)
            if metric in FLOWS:
                if len(by_index) < PARTS[grain]:
                    continue                                # a part of the year is not in the table: no annual figure
                used = [by_index[i] for i in range(PARTS[grain])]
                value = sum(p["value"] for p in used)
            else:
                last = by_index.get(PARTS[grain] - 1)
                if last is None:
                    continue                                # the year-end is not in the table
                used, value = [last], last["value"]
            text = None
            period = used[0]["header"] if len(used) == 1 else f"{used[0]['header']}–{used[-1]['header']}"
        if rate:
            value = value * 100 if all(-1 <= p["value"] <= 1 for p in parts) else value
        elif metric in MONEY:
            value = value * scale
        cols = sorted(p["j"] for p in used)
        cell = _cell(first, cols[0], row) if len(cols) == 1 else f"{_cell(first, cols[0], row)}:{_cell(first, cols[-1], row)}"
        claim = {"target_date": str(fy), "period": period, "period_text": text, "value": _clean(value), "cell": cell,
                 "cols": (cols[0], cols[-1])}
        tags = {p["tag"] for p in used if p.get("tag")}
        if tags:                                    # a statement's column tag (chat-upload.md section 26.6)
            claim["tag"] = tags.pop() if len(tags) == 1 else "unknown"
        out.append(claim)
    return out


def candidates(found: Dict, rows: List[int], ds: Dict, fiscal_year_end: int = 12) -> List[Dict]:
    """The ticked lines of `found` (by sheet row) as deck candidates in the table-row shape (deck-parser.md section 2): one per line,
    its values by period, each citing its file, sheet and cell. The server adds the audit, the id, the order and the status."""
    out = []
    for line in found["lines"]:
        if line["row"] not in rows:
            continue
        by_period = []
        for v in line["values"]:
            source = {"file": ds.get("file"), "sheet": found["sheet"], "cell": v["cell"], "kind": SOURCE_KIND}
            item = {"value": v["value"], "value_high": None, "target_date": v["target_date"], "period": v["period"],
                    "period_text": v["period_text"], "source": source, "_stated": v["period_text"] is not None}
            if v.get("tag"):
                item["tag"] = v["tag"]
            by_period.append(deck_claims.resolve_period(item, fiscal_year_end))
        out.append({
            "claim_type": line["claim_type"], "value": None, "value_high": None, "unit": line["unit"], "currency": line["currency"],
            "target_date": None, "period_text": None, "period_start": None, "period_end": None,
            "snippet": line["label"][:SNIPPET_MAX], "label_from": None, "date_from": None, "type_from": "line",
            "sources": [i["source"] for i in by_period], "by_period": by_period, "inconsistent_dates": [], "claim_direction": None,
            "origin": ORIGIN, "file_hash": ds.get("file_hash"), "dtype": ds.get("dtype"), "sheet_row": line["row"]})
    return out
