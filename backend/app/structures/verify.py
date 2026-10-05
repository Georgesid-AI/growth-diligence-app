"""The verifier: model output never becomes Verified on its own (CLAUDE.md rule 18).

Spec: docs/specs/llm-structure-reading.md section 2, with the period rules of deck-parser.md
section 2. Pure: no I/O, no model, no database. The orchestrator reads the STRUCTURE_UNMATCHED
switch (unmatched_mode) and passes it in.

An item is matched when
- its value matches its `value_cell` only: that cell exists and holds the same number after
  normalisation (currency symbols and thousands separators removed; a decimal comma read only if
  the structure writes numbers like 1.234,5; "(1,200)" is -1200; k/m/bn suffixes applied; a scale in
  a neighbouring cell, a header cell or the table's corner cell, such as "£m" or "'000", applied). The match is exact: a rounded
  number does not match. An item with no value is never matched;
- its period matches its `period_cells` only: they are header cells of the value cell (its row
  header or the header stack above its column; in a KPI panel or a roadmap, the cells left of it in
  its row and the top line of its own box), and the period rebuilt from them under the section 2
  rules has the same start and end date. A two-cell period is a month, quarter or half cell and the
  calendar year cell above it in the same column range. A null period matches only when
  `period_cells` is empty and no header of the value cell holds a period. A relative column ("M3",
  "Year 1") has no period unless its second period cell states the start date ("Start: Jan 2025");
- every proposed flag is reproduced from the matched values (see _flag_reproduced).

Matched items are "verified". The others are "suggestion" (shown as "AI suggestion, not verified")
or, with the switch at "drop", removed and counted.
"""
import math
import os
import re
from typing import Dict, List, Optional, Tuple

from ..decks import claims

VERIFIED = "verified"
SUGGESTION = "suggestion"
SUGGESTION_LABEL = "AI suggestion, not verified"
VERIFIED_LABEL = "Verified"
UNMATCHED_MODES = ("suggest", "drop")
BOX_TYPES = ("kpi_panel", "roadmap")
GROWTH_BASE = {"revenue_growth": "revenue", "user_growth": "users"}
TOTAL_TOLERANCE = 0.005         # a total and the sum of its parts differ by more than 0.5% of the total...
GROWTH_TOLERANCE = 0.5          # ...a stated growth rate and the one the values give by more than 0.5 points


def unmatched_mode() -> str:
    """The STRUCTURE_UNMATCHED switch: "suggest" (default) or "drop". Anything else is "suggest", so a
    typo shows unverified items labelled rather than silently removing them."""
    value = os.environ.get("STRUCTURE_UNMATCHED", "").strip().lower()
    return value if value in UNMATCHED_MODES else "suggest"


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
_CURRENCY = re.compile(r"US\$|[£$€¥₹]|\b(?:USD|EUR|GBP|CHF|JPY|BGN|PLN|SEK|NOK|DKK|CAD|AUD)\b")
_DECIMAL_COMMA = re.compile(r"\d{1,3}(?:\.\d{3})+,\d+")
_SCALE_WORD = {"k": 1e3, "thousand": 1e3, "thousands": 1e3, "tsd": 1e3, "хил": 1e3,
               "m": 1e6, "mn": 1e6, "mm": 1e6, "million": 1e6, "millions": 1e6, "mio": 1e6, "млн": 1e6,
               "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9, "mrd": 1e9, "млрд": 1e9}
_SUFFIX = r"(?:\s?(?P<suffix>k|K|mn|MM|m|M|bn|B|thousand|million|billion|Mio|Mrd|Tsd|млн|млрд|хил)(?![^\W\d_]))?"
_NUMBER = {
    False: re.compile(r"(?P<open>\()?\s*(?:(?<![\w.])(?P<sign>[-−–]))?\s*(?<![\d.,])"
                      r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d]|[.,]\d)"
                      + _SUFFIX + r"\s*(?P<pct>%)?\s*(?P<close>\))?"),
    True: re.compile(r"(?P<open>\()?\s*(?:(?<![\w.])(?P<sign>[-−–]))?\s*(?<![\d.,])"
                     r"(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(?![\d]|[.,]\d)"
                     + _SUFFIX + r"\s*(?P<pct>%)?\s*(?P<close>\))?"),
}
# A scale given in a cell of its own or in a header: "£m", "(£000)", "'000", "in millions", "€ Mio".
_SCALE_MARK = re.compile(
    r"(?i)(?:(?<![^\W\d_])(?P<word>thousands?|millions?|billions?|tsd|mio|mrd|млн|млрд|хил)(?![^\W\d_])"
    r"|(?:[£$€]\s?|\(\s?[£$€]?\s?|^\s*[£$€]?\s?)(?P<mark>k|mn|mm|m|bn|['’]?000s?)(?=\s*\)|\s*$|\s))")


def decimal_comma(cells: List[Dict]) -> bool:
    """True when the structure writes numbers like 1.234,5: then "," is the decimal point."""
    return any(_DECIMAL_COMMA.search(c["text"]) for c in cells)


def cell_number(text: str, comma: bool = False) -> Optional[Tuple[float, bool]]:
    """(number, has its own scale or %) for a cell that holds exactly one figure, else None. Dates
    are periods, never values, and are left out first."""
    blanked = text
    for d in reversed(claims.find_dates(text, table=True)):
        blanked = blanked[:d["start"]] + " " + blanked[d["end"]:]
    blanked = _CURRENCY.sub(" ", blanked)
    found = [m for m in _NUMBER[comma].finditer(blanked) if m.group("num")]
    if len(found) != 1:
        return None
    m = found[0]
    raw = m.group("num")
    raw = raw.replace(".", "").replace(",", ".") if comma else raw.replace(",", "")
    value = float(raw)
    suffix = (m.group("suffix") or "").lower()
    if suffix:
        value *= _SCALE_WORD[suffix]
    if (m.group("open") and m.group("close")) or m.group("sign"):
        value = -value
    return value, bool(suffix or m.group("pct"))


def scale_of(text: str) -> Optional[float]:
    """The scale a neighbouring or header cell states ("£m" -> 1e6, "'000" -> 1e3), or None."""
    m = _SCALE_MARK.search(text or "")
    if not m:
        return None
    token = (m.group("word") or m.group("mark")).lower().strip("'’")
    if token.startswith("000"):
        return 1e3
    return _SCALE_WORD.get(token.rstrip("s") if token not in _SCALE_WORD else token)


def same_number(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Cells and their headers
# ---------------------------------------------------------------------------
def _id(cell: Dict) -> str:
    return f"r{cell['row']}c{cell['col']}"


def _cols(cell: Dict) -> range:
    return range(cell["col"], cell["col"] + cell.get("col_span", 1))


def _is_value(cell: Dict, comma: bool) -> bool:
    """A cell that holds a figure and is not a period label."""
    return cell_number(cell["text"], comma) is not None and claims.period_cell(cell["text"]) is None


def header_cells(structure: Dict, cell: Dict) -> List[Dict]:
    """The header cells of a value cell, nearest first: its row header (the cells left of it in its
    row that are not values) and the header stack above its column (header rows covering it). In a
    KPI panel or a roadmap, the cells left of it in its row and the top line of its own box."""
    cells, comma = structure["cells"], decimal_comma(structure["cells"])
    left = sorted((c for c in cells if c["row"] == cell["row"] and c["col"] < cell["col"]
                   and not _is_value(c, comma)), key=lambda c: -c["col"])
    if structure.get("type") in BOX_TYPES:
        box = [c for c in cells if c.get("box") is not None and c.get("box") == cell.get("box")]
        top = min(box, key=lambda c: c["row"]) if box else None
        return left + ([top] if top is not None and top is not cell and _id(top) != _id(cell) else [])
    rows = sorted({c["row"] for c in cells})
    header_rows = set(rows[:structure.get("header_rows") or 0])
    above = sorted((c for c in cells if c["row"] in header_rows and c["row"] < cell["row"]
                    and any(k in _cols(c) for k in _cols(cell))), key=lambda c: -c["row"])
    return left + above


def _corner(structure: Dict) -> List[Dict]:
    """The table's corner: its header-row cells in the first column, where a table states its unit
    for every value ("£'000"). Used for the scale only, never for a period."""
    cells = structure["cells"]
    if structure.get("type") in BOX_TYPES or not cells:
        return []
    rows = sorted({c["row"] for c in cells})[:structure.get("header_rows") or 0]
    first = min(c["col"] for c in cells)
    return [c for c in cells if c["row"] in rows and c["col"] == first]


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
_START = re.compile(r"(?i)\b(?:start(?:s|ing)?(?: date)?|from|beginning|begins?)\b")
_RELATIVE_UNIT = re.compile(r"(?i)^\s*(?P<u>M|Month|Monat|Y|Year|Jahr|Q|Quarter)")


def _range(label: Optional[str], fiscal: bool, fiscal_year_end: int):
    return claims.period_range(label, fiscal_year_end, fiscal) if label else None


def _relative_range(relative: Dict, unit_text: str, start_cell: Optional[Dict]) -> Optional[Tuple[str, str]]:
    """The range of a relative column ("M3", "Year 2") counted from the start date a cell states."""
    if not start_cell or not _START.search(start_cell["text"]):
        return None
    dates = [d for d in claims.find_dates(start_cell["text"], table=True) if d["kind"] == "month"]
    if len(dates) != 1:
        return None
    year, month = map(int, dates[0]["date"].split("-"))
    n = relative["relative"]
    unit = _RELATIVE_UNIT.match(unit_text).group("u").lower()
    length = 12 if unit.startswith(("y", "j")) else 3 if unit.startswith("q") else 1
    first = (year * 12 + month - 1) + length * (n - 1)
    last = first + length - 1
    begin = claims.period_range(f"{first // 12}-{first % 12 + 1:02d}")[0]
    end = claims.period_range(f"{last // 12}-{last % 12 + 1:02d}")[1]
    return begin, end


def rebuild_period(structure: Dict, value_cell: Dict, period_ids: List[str], fiscal_year_end: int = 12):
    """The (start, end) the cited period cells give under the section 2 rules, or None when they do
    not make a period, or are not header cells of the value cell."""
    by_id = {_id(c): c for c in structure["cells"]}
    cited = [by_id.get(i) for i in period_ids]
    if not cited or None in cited or len(cited) > 2:
        return None
    headers = {_id(c) for c in header_cells(structure, value_cell)}
    first = cited[0]
    if _id(first) not in headers:
        return None
    found = claims.period_cell(first["text"])
    if not found:
        return None
    if len(cited) == 1:
        return _range(found.get("label"), found.get("fiscal", False), fiscal_year_end) if "label" in found else None
    second = cited[1]
    if "relative" in found:
        return _relative_range(found, first["text"], second)
    above = second["row"] < first["row"] and all(k in _cols(second) for k in _cols(first))
    joined = claims.combine_period(found, claims.period_cell(second["text"])) if above else None
    return _range(joined["label"], False, fiscal_year_end) if joined else None


def headers_hold_a_period(structure: Dict, value_cell: Dict) -> bool:
    """True when a header of the value cell holds a period: a full period, or a part with its calendar
    year cell above it in the same column range."""
    cells = structure["cells"]
    for h in header_cells(structure, value_cell):
        found = claims.period_cell(h["text"])
        if not found:
            continue
        if "label" in found:
            return True
        if "part" in found:
            for up in cells:
                if up["row"] < h["row"] and all(k in _cols(up) for k in _cols(h)) and \
                        claims.combine_period(found, claims.period_cell(up["text"])):
                    return True
    return False


def period_matches(structure: Dict, item: Dict, value_cell: Optional[Dict], fiscal_year_end: int = 12) -> bool:
    if value_cell is None:
        return False
    if item.get("period") is None:
        return not item.get("period_cells") and not headers_hold_a_period(structure, value_cell)
    wanted = claims.period_range(item["period"], fiscal_year_end)
    return wanted is not None and rebuild_period(structure, value_cell, item.get("period_cells") or [],
                                                 fiscal_year_end) == wanted


def value_matches(structure: Dict, item: Dict, value_cell: Optional[Dict]) -> bool:
    if value_cell is None or item.get("value") is None:
        return False
    cells, comma = structure["cells"], decimal_comma(structure["cells"])
    found = cell_number(value_cell["text"], comma)
    if found is None:
        return False
    number, own_scale = found
    if not own_scale:
        neighbours = [c for c in cells if c["row"] == value_cell["row"] and abs(c["col"] - value_cell["col"]) == 1
                      and not _is_value(c, comma)]
        for c in neighbours + header_cells(structure, value_cell) + _corner(structure):
            scale = scale_of(c["text"])
            if scale:
                number *= scale
                break
    return same_number(number, float(item["value"]))


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
_TOTAL = re.compile(r"(?i)\b(?:total|sum|gesamt|summe|общо)\b")


def _flag_reproduced(flag: str, item: Dict, matched: List[Dict], structure: Dict, fiscal_year_end: int) -> bool:
    by_id = {_id(c): c for c in structure["cells"]}
    cell = by_id[item["value_cell"]]
    span = claims.period_range(item["period"], fiscal_year_end) if item.get("period") else None
    if flag == "total_mismatch":
        # The total's own label says it is a total ("Total revenue" as its row header, or "Total" over
        # its column); its parts are the matched items of the same period and unit above it in its
        # column (or left of it in its row), back to the header or the previous total.
        def parts(along_column: bool):
            out = []
            for other in matched:
                c = by_id[other["value_cell"]]
                if other is item or other.get("unit") != item.get("unit") or \
                        (claims.period_range(other["period"], fiscal_year_end) if other.get("period") else None) != span:
                    continue
                if along_column and c["col"] == cell["col"] and c["row"] < cell["row"]:
                    out.append((c["row"], other))
                if not along_column and c["row"] == cell["row"] and c["col"] < cell["col"]:
                    out.append((c["col"], other))
            out.sort(key=lambda p: -p[0])
            kept = []
            for _, other in out:
                if _TOTAL.search(" ".join(h["text"] for h in header_cells(structure, by_id[other["value_cell"]]))):
                    break
                kept.append(other)
            return kept
        labels = header_cells(structure, cell)
        row_total = any(_TOTAL.search(h["text"]) for h in labels if h["row"] == cell["row"])
        col_total = any(_TOTAL.search(h["text"]) for h in labels if h["row"] != cell["row"])
        for along_column, applies in ((True, row_total), (False, col_total)):
            found = parts(along_column) if applies else []
            if len(found) >= 2:
                total = sum(float(o["value"]) for o in found)
                if abs(total - float(item["value"])) > TOTAL_TOLERANCE * abs(float(item["value"])):
                    return True
        return False
    if flag == "growth_mismatch":
        if item.get("unit") != "%" or span is None:
            return False
        base = GROWTH_BASE.get(item["metric"])
        if base is None and item["metric"] == "growth":
            others = {o["metric"] for o in matched if o["metric"] not in ("growth", "revenue_growth", "user_growth")}
            base = others.pop() if len(others) == 1 else None
        if base is None:
            return False
        prev_end = _day_before(span[0])

        def value_for(start_end):
            hits = [o for o in matched if o["metric"] == base and o.get("period")
                    and claims.period_range(o["period"], fiscal_year_end) == start_end]
            return float(hits[0]["value"]) if len(hits) == 1 else None
        current = value_for(span)
        previous = next((value_for(claims.period_range(o["period"], fiscal_year_end)) for o in matched
                         if o["metric"] == base and o.get("period")
                         and claims.period_range(o["period"], fiscal_year_end)[1] == prev_end
                         and _months(claims.period_range(o["period"], fiscal_year_end)) == _months(span)), None)
        if current is None or not previous:
            return False
        growth = (current / previous - 1) * 100
        return abs(growth - float(item["value"])) > GROWTH_TOLERANCE
    return False


def _day_before(iso: str) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()


def _months(span: Tuple[str, str]) -> int:
    (y0, m0), (y1, m1) = (tuple(map(int, s[:7].split("-"))) for s in span)
    return (y1 * 12 + m1) - (y0 * 12 + m0) + 1


# ---------------------------------------------------------------------------
# One reply
# ---------------------------------------------------------------------------
def verify(structure: Dict, items: List[Dict], fiscal_year_end: int = 12, mode: str = "suggest") -> Dict:
    """{"items": [item + "status" + "checks"], "dropped": n} for one structure's validated reply items.

    `structure` is {"type", "cells", "header_rows"} as the deck parser found it (the cells before
    redaction: redaction never changes a number or a period, and the citation is to the source).
    Every item gets "status" ("verified" or "suggestion") and "checks" ({"value", "period", "flags"}:
    booleans). With mode "drop" the unmatched items are removed and counted.
    """
    by_id = {_id(c): c for c in structure["cells"]}
    checked = []
    for item in items:
        cell = by_id.get(item.get("value_cell"))
        checked.append((item, value_matches(structure, item, cell),
                        period_matches(structure, item, cell, fiscal_year_end)))
    matched = [item for item, v, p in checked if v and p]
    out, dropped = [], 0
    for item, v, p in checked:
        flags = all(_flag_reproduced(f, item, matched, structure, fiscal_year_end)
                    for f in item.get("proposed_flags") or ()) if v and p else not item.get("proposed_flags")
        ok = v and p and flags
        if not ok and mode == "drop":
            dropped += 1
            continue
        out.append({**item, "status": VERIFIED if ok else SUGGESTION,
                    "checks": {"value": v, "period": p, "flags": flags}})
    return {"items": out, "dropped": dropped}


def label(status: str) -> str:
    """The label a result row carries in the approval list."""
    return VERIFIED_LABEL if status == VERIFIED else SUGGESTION_LABEL
