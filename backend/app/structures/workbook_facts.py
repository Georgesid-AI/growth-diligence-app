"""What an .xlsx file states about its own structure (docs/specs/structure-extraction.md; STRUCTURE_EXTRACTION_VERSION 1).

Read once per file with openpyxl, before any reading: hidden rows and columns, merged ranges, outline levels, indents, each cell's type and number
format class, the formulas with the cells they reference, and from SUM / SUBTOTAL(9) / `+` formulas the total rows with their part rows and the
subtotal columns with their part columns; two integrity findings (a constant among the formulas of a row, a SUM that skips a numeric cell next to its
range). Pure: no database, no model, no network. Nothing here keeps a cell value; the model is told references and numbers only (`facts_block`).
"""
import calendar
import re
from collections import Counter
from datetime import date, datetime
from io import BytesIO
from typing import Dict, List, Optional, Tuple

STRUCTURE_EXTRACTION_VERSION = 1
BLOCK_HEAD = "STRUCTURE FACTS (read from the file, not inferred):"
BLOCK_MAX_LINES = 60                    # per sheet, the head line included; over it totals and merged spans are kept and the rest dropped
NO_FORMULAS = "no formulas in file"
PERCENT_MARKER = " (fmt %)"           # follows the stored fraction of a percent-formatted cell
TRUNCATED = "truncated"
PERIOD_ROW_MIN = 3                      # a row of this many date cells is a period row: its dates are written as ISO periods
TEXT_REFS_SHOWN = 30
HEADER_ROWS = 12                        # a merged span in these rows is a header span
FORMULA_ROW_MIN = 2                     # a row needs this many formula cells before a constant among them is a finding

_CELL = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9]\d*)$")
_REF_TOKEN = re.compile(r"(?<![A-Za-z0-9_.])((?:'[^']+'|[A-Za-z_][\w.]*)!)?\$?([A-Z]{1,3})\$?([1-9]\d*)(?::\$?([A-Z]{1,3})\$?([1-9]\d*))?(?![A-Za-z0-9_(])")
_SUM = re.compile(r"(?is)^\s*(?:SUM|SUBTOTAL\(\s*(?:9|109)\s*,)\s*\(?(.*)\)\s*$")
_PLUS = re.compile(r"^\s*\$?[A-Z]{1,3}\$?\d+(?:\s*\+\s*\$?[A-Z]{1,3}\$?\d+)+\s*$")
_PURE_NUMBER = re.compile(r"^[-+]?\d+(?:[.,]\d+)?$")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_CURRENCY_FORMAT = re.compile(r"[$€£¥]|\[\$")


def col_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def col_letters(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def ref_of(row: int, col: int) -> str:
    return f"{col_letters(col)}{row}"


def _split(ref: str) -> Tuple[int, int]:
    m = _CELL.match(ref)
    return int(m.group(2)), col_number(m.group(1))


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------
def references(formula: str) -> List[str]:
    """The cells and ranges a formula reads, in order of first appearance, `$` removed; another sheet's cell as "Sheet!B5"."""
    text = re.sub(r'"[^"]*"', '""', formula or "")
    out: List[str] = []
    for m in _REF_TOKEN.finditer(text):
        sheet = (m.group(1) or "")[:-1].strip("'")
        ref = f"{m.group(2)}{m.group(3)}" + (f":{m.group(4)}{m.group(5)}" if m.group(4) else "")
        ref = f"{sheet}!{ref}" if sheet else ref
        if ref not in out:
            out.append(ref)
    return out


def _rects(formula: str) -> Optional[List[Tuple[int, int, int, int]]]:
    """The (row1, col1, row2, col2) rectangles of a formula that is a plain sum (SUM, SUBTOTAL 9 or 109, or cells joined by `+`) on this sheet, else None."""
    f = (formula or "").strip()
    if _PLUS.match(f):
        args = [a.strip() for a in f.split("+")]
    else:
        m = _SUM.match(f)
        if not m:
            return None
        args = [a.strip() for a in m.group(1).split(",")]
    out = []
    for arg in args:
        parts = arg.split(":")
        if len(parts) > 2 or not all(_CELL.match(p) for p in parts):
            return None
        (r1, c1), (r2, c2) = _split(parts[0]), _split(parts[-1])
        out.append((min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)))
    return out or None


def _one_line(rects, row: Optional[int] = None, col: Optional[int] = None) -> Optional[List[int]]:
    """The rows (when every rectangle sits in column `col`) or the columns (when every rectangle sits in row `row`) a sum covers, else None."""
    if col is not None and all(c1 == c2 == col for _, c1, _, c2 in rects):
        return sorted({r for r1, _, r2, _ in rects for r in range(r1, r2 + 1)})
    if row is not None and all(r1 == r2 == row for r1, _, r2, _ in rects):
        return sorted({c for _, c1, _, c2 in rects for c in range(c1, c2 + 1)})
    return None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def _format_class(number_format: str, value) -> Tuple[str, str]:
    """(type, class) of a constant cell. Class "month" is a date format with no day (mmm-yy)."""
    from openpyxl.styles.numbers import is_date_format
    nf = number_format or "General"
    if isinstance(value, bool):
        return "bool", "general"
    if isinstance(value, (datetime, date)):
        return "date", ("month" if not re.search(r"(?i)d", re.sub(r'"[^"]*"|\[[^\]]*\]', "", nf)) else "date")
    if isinstance(value, str):
        return "text", ("text" if nf == "@" else "general")
    if isinstance(value, (int, float)):
        if is_date_format(nf):
            return "date", "date"
        bare = re.sub(r'"[^"]*"', "", nf)
        if "%" in bare:
            return "number", "percent"
        if _CURRENCY_FORMAT.search(nf):
            return "number", "currency"
        if re.fullmatch(r"[#0,_ ]+", bare) and "." not in bare:
            return "number", "integer"
        return "number", "general"
    return "text", "general"


def _empty(has_formulas: bool = False) -> Dict:
    return {"version": STRUCTURE_EXTRACTION_VERSION, "has_formulas": has_formulas, "sheets": []}


def extract(content: bytes) -> Dict:
    """The facts of an .xlsx file's bytes. A file openpyxl cannot read gives the empty facts (the read goes on as it did)."""
    try:
        from openpyxl import load_workbook
        book = load_workbook(BytesIO(content), data_only=False)
        cached = load_workbook(BytesIO(content), data_only=True)
    except Exception:
        return _empty()
    sheets = []
    for ws in book.worksheets:
        try:
            sheets.append(_sheet(ws, cached[ws.title] if ws.title in cached.sheetnames else None))
        except Exception:
            sheets.append({"name": ws.title, "hidden": False, "hidden_rows": [], "hidden_cols": [], "merged": [], "row_outline": {},
                           "col_outline": {}, "indents": {}, "cells": {}, "text_numbers": [], "formulas": {}, "totals": [], "subtotal_cols": [],
                           "hardcoded": [], "omitted": []})
    return {"version": STRUCTURE_EXTRACTION_VERSION, "has_formulas": any(s["formulas"] for s in sheets), "sheets": sheets}


def _formula_text(value) -> Optional[str]:
    if isinstance(value, str) and value.startswith("=") and len(value) > 1:
        return value[1:]
    text = getattr(value, "text", None)          # an array formula
    return text[1:] if isinstance(text, str) and text.startswith("=") else None


def _sheet(ws, cached) -> Dict:
    hidden_rows = sorted(r for r, d in ws.row_dimensions.items() if getattr(d, "hidden", False))
    hidden_cols, col_outline = set(), {}
    for key, d in ws.column_dimensions.items():
        lo, hi = (getattr(d, "min", None) or col_number(key)), (getattr(d, "max", None) or col_number(key))
        for n in range(lo, min(hi, lo + 200) + 1):
            if getattr(d, "hidden", False):
                hidden_cols.add(n)
            if getattr(d, "outlineLevel", 0):
                col_outline[col_letters(n)] = int(d.outlineLevel)
    row_outline = {str(r): int(d.outlineLevel) for r, d in ws.row_dimensions.items() if getattr(d, "outlineLevel", 0)}
    cells, text_numbers, formulas, indents, numeric, years = {}, [], {}, {}, {}, set()          # numeric: (row, col) -> "const" | "formula"
    for row in ws.iter_rows():
        for c in row:
            v = c.value
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            ref = c.coordinate
            f = _formula_text(v)
            if f is not None:
                formulas[ref] = [f, references(f)]
                got = cached[ref].value if cached is not None else None
                kind = _format_class(c.number_format, got)[0] if got is not None else "number"
                cls = _format_class(c.number_format, 0.5 if kind == "number" else got)[1] if kind != "text" else "general"
                numeric[(c.row, c.column)] = "formula"
                if (kind, cls) not in (("number", "general"), ("number", "integer")):
                    cells[ref] = f"{kind}/{cls}"
                continue
            kind, cls = _format_class(c.number_format, v)
            if c.data_type == "e":
                kind, cls = "error", "general"
            if (kind, cls) not in (("number", "general"), ("number", "integer"), ("text", "general")):
                cells[ref] = f"{kind}/{cls}"
            if kind == "number":
                numeric[(c.row, c.column)] = "const"
                if float(v).is_integer() and 1900 <= v <= 2100:
                    years.add((c.row, c.column))          # a year-like number is a header, not a part
            if kind == "text" and _PURE_NUMBER.match(v.strip()) and not _YEAR.match(v.strip()):
                text_numbers.append(ref)
            n = int(getattr(getattr(c, "alignment", None), "indent", 0) or 0)
            if n:
                indents[ref] = n
    sheet = {"name": ws.title, "hidden": ws.sheet_state != "visible", "hidden_rows": hidden_rows, "hidden_cols": [col_letters(n) for n in sorted(hidden_cols)],
             "merged": sorted(str(m) for m in ws.merged_cells.ranges), "row_outline": row_outline, "col_outline": col_outline, "indents": indents,
             "cells": cells, "text_numbers": text_numbers, "formulas": formulas}
    sheet["totals"], sheet["subtotal_cols"] = _relations(sheet, formulas)
    sheet["hardcoded"], sheet["omitted"] = _findings(sheet, numeric, formulas, years)
    return sheet


def _relations(sheet: Dict, formulas: Dict) -> Tuple[List[Dict], List[Dict]]:
    """(total rows with their part rows, subtotal columns with their part columns) from the sheet's sum formulas. A row (column) is a total when at
    least half of its vertical (horizontal) sum cells name the same parts. When two rows claim one part, the visible row wins, then the first."""
    vertical: Dict[int, List[Tuple[int, ...]]] = {}
    horizontal: Dict[int, List[Tuple[int, ...]]] = {}
    for ref, (f, _) in formulas.items():
        rects = _rects(f)
        if not rects:
            continue
        r, c = _split(ref)
        rows, cols = _one_line(rects, col=c), _one_line(rects, row=r)
        if rows and r not in rows:
            vertical.setdefault(r, []).append(tuple(rows))
        elif cols and c not in cols:
            horizontal.setdefault(c, []).append(tuple(cols))
    hidden_rows = set(sheet["hidden_rows"])
    claimed: Dict[int, int] = {}
    totals = []
    for r in sorted(vertical, key=lambda r: (r in hidden_rows, r)):
        parts, k = Counter(vertical[r]).most_common(1)[0]
        if k * 2 < len(vertical[r]):
            continue
        parts = [p for p in parts if p not in claimed]
        if parts:
            claimed.update({p: r for p in parts})
            totals.append({"row": r, "parts": parts, "cells": k})
    hidden_cols = {col_number(c) for c in sheet["hidden_cols"]}
    claimed_c: Dict[int, int] = {}
    subtotals = []
    for c in sorted(horizontal, key=lambda c: (c in hidden_cols, c)):
        parts, k = Counter(horizontal[c]).most_common(1)[0]
        if k * 2 < len(horizontal[c]):
            continue
        parts = [p for p in parts if p not in claimed_c]
        if parts:
            claimed_c.update({p: c for p in parts})
            subtotals.append({"col": col_letters(c), "parts": [col_letters(p) for p in parts]})
    return sorted(totals, key=lambda t: t["row"]), sorted(subtotals, key=lambda t: col_number(t["col"]))


def _findings(sheet: Dict, numeric: Dict, formulas: Dict, years: set) -> Tuple[List[Dict], List[Dict]]:
    hidden_rows, hidden_cols = set(sheet["hidden_rows"]), {col_number(c) for c in sheet["hidden_cols"]}
    hid = lambda r, c: r in hidden_rows or c in hidden_cols      # noqa: E731
    by_row: Dict[int, List[int]] = {}
    for (r, c) in numeric:
        by_row.setdefault(r, []).append(c)
    hardcoded = []
    for r, cols in sorted(by_row.items()):
        cols.sort()
        f = [c for c in cols if numeric[(r, c)] == "formula"]
        k = [c for c in cols if numeric[(r, c)] == "const"]
        if len(f) < FORMULA_ROW_MIN or not k or len(f) <= len(k):
            continue
        own = any(_split(x.split("!")[-1].split(":")[0])[0] == r for c in f for x in formulas[ref_of(r, c)][1] if "!" not in x)
        if own and numeric[(r, cols[0])] == "const":          # a roll-forward row: its first cell is the seed
            k = k[1:]
        hardcoded += [{"cell": ref_of(r, c), "hidden": hid(r, c)} for c in k]
    totals = {t["row"] for t in sheet["totals"]}
    subs = {col_number(t["col"]) for t in sheet["subtotal_cols"]}
    omitted = []

    def skipped(r, c) -> bool:          # a numeric constant or plain formula cell that is not a total, a date or a year-like header number
        return (r, c) in numeric and r not in totals and c not in subs and (r, c) not in years and not _is_date(sheet, r, c)

    for ref, (f, _) in sorted(formulas.items(), key=lambda kv: _split(kv[0])):
        rects = _rects(f)
        if not rects or len(rects) != 1 or not f.strip().upper().startswith(("SUM", "SUBTOTAL")):
            continue
        r, c = _split(ref)
        r1, c1, r2, c2 = rects[0]
        gone: List[Tuple[int, int]] = []
        if c1 == c2 == c and r2 < r:
            gone = [(x, c) for x in range(r2 + 1, r) if skipped(x, c)]
            x = r1 - 1
            while x >= 1 and skipped(x, c):
                gone.append((x, c))
                x -= 1
        elif r1 == r2 == r and c2 < c:
            gone = [(r, x) for x in range(c2 + 1, c) if skipped(r, x)]
            x = c1 - 1
            while x >= 1 and skipped(r, x):
                gone.append((r, x))
                x -= 1
        if gone:
            omitted.append({"cell": ref, "range": f"{ref_of(r1, c1)}:{ref_of(r2, c2)}" if (r1, c1) != (r2, c2) else ref_of(r1, c1),
                            "skipped": [ref_of(*p) for p in sorted(gone)], "hidden": any(hid(*p) for p in gone),
                            "hidden_cells": [ref_of(*p) for p in sorted(gone) if hid(*p)]})
    return hardcoded, omitted


def _is_date(sheet: Dict, r: int, c: int) -> bool:
    return sheet["cells"].get(ref_of(r, c), "").startswith("date/")


# ---------------------------------------------------------------------------
# Reading the facts
# ---------------------------------------------------------------------------
def sheet_facts(facts: Optional[Dict], name: str) -> Optional[Dict]:
    return next((s for s in (facts or {}).get("sheets") or [] if s["name"] == name), None)


def cell_kinds(facts: Optional[Dict], name: str) -> Dict[str, str]:
    """{ref: "type/class"} of the listed cells of a sheet (see the spec for the default); {} without facts."""
    return (sheet_facts(facts, name) or {}).get("cells") or {}


def parent_relations(facts: Optional[Dict]) -> Dict[str, Dict[int, List[int]]]:
    """{sheet name: {total row: [part rows]}} of the file's sum formulas."""
    return {s["name"]: {t["row"]: list(t["parts"]) for t in s.get("totals") or []} for s in (facts or {}).get("sheets") or [] if s.get("totals")}


def findings(facts: Optional[Dict]) -> Dict:
    """The integrity findings of the file: {"ran": a workbook with formulas was read, "hardcoded": [{"sheet", "cell", "hidden"}],
    "omitted": [{"sheet", "cell", "range", "skipped", "hidden"}]}. A cell in a hidden row or column is marked; the output carries refs only."""
    out = {"ran": bool((facts or {}).get("has_formulas")), "hardcoded": [], "omitted": []}
    for s in (facts or {}).get("sheets") or []:
        out["hardcoded"] += [{"sheet": s["name"], **h} for h in s.get("hardcoded") or []]
        out["omitted"] += [{"sheet": s["name"], **o} for o in s.get("omitted") or []]
    return out


def period_text(value, kind: str) -> Optional[str]:
    """A date cell of a period row as an ISO period "2023-12": its format has no day (kind "date/month"), or its day is the 1st or the month's last
    day. Any other date is None (the caller keeps the full ISO date)."""
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        return None
    if kind == "date/month" or value.day in (1, calendar.monthrange(value.year, value.month)[1]):
        return f"{value.year:04d}-{value.month:02d}"
    return None


def period_rows(kinds: Dict[str, str]) -> set:
    """The rows with PERIOD_ROW_MIN or more date cells."""
    count: Counter = Counter()
    for ref, kind in kinds.items():
        if kind.startswith("date/"):
            count[_split(ref)[0]] += 1
    return {r for r, n in count.items() if n >= PERIOD_ROW_MIN}


def _runs(numbers: List[int], fmt) -> str:
    out, i = [], 0
    nums = sorted(set(numbers))
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(fmt(nums[i]) if i == j else f"{fmt(nums[i])}-{fmt(nums[j])}")
        i = j + 1
    return ", ".join(out)


def facts_block(facts: Optional[Dict], name: str) -> Optional[str]:
    """The STRUCTURE FACTS block of one sheet, or None when the file has no facts (a CSV). References and numbers only: no label, no value, no sheet name."""
    s = sheet_facts(facts, name)
    if s is None:
        return None
    must = []
    spans = [m for m in s["merged"] if _is_header_span(m)]
    if spans:
        must.append("merged header spans: " + ", ".join(spans))
    must += [f"total rows: row {t['row']} = rows {_runs(t['parts'], str)}" for t in s["totals"]]
    must += [f"subtotal columns: {t['col']} = {_runs([col_number(p) for p in t['parts']], col_letters)}" for t in s["subtotal_cols"]]
    rest = []
    if not facts.get("has_formulas"):
        rest.append(NO_FORMULAS)
    if s["hidden_rows"]:
        rest.append("hidden rows: " + _runs(s["hidden_rows"], str))
    if s["hidden_cols"]:
        rest.append("hidden columns: " + _runs([col_number(c) for c in s["hidden_cols"]], col_letters))
    if s["text_numbers"]:
        shown = s["text_numbers"][:TEXT_REFS_SHOWN]
        rest.append("cells stored as text: " + ", ".join(shown) + (f" and {len(s['text_numbers']) - len(shown)} more" if len(s["text_numbers"]) > len(shown) else ""))
    lines = must + rest
    if len(lines) > BLOCK_MAX_LINES - 2:
        lines = must[:BLOCK_MAX_LINES - 2] + [TRUNCATED]
    return "\n".join([BLOCK_HEAD, *(lines or ["nothing to report"])])


def _is_header_span(span: str) -> bool:
    a, _, b = span.partition(":")
    if not b:
        return False
    (r1, c1), (r2, c2) = _split(a), _split(b)
    return r1 == r2 and c2 > c1 and r1 <= HEADER_ROWS
