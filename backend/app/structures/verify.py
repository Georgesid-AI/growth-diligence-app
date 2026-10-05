"""The verifier: model output never becomes Verified on its own (CLAUDE.md rule 18).

Spec: docs/specs/llm-structure-reading.md section 2, with the period rules of deck-parser.md
section 2. Pure: no I/O, no model, no database. The orchestrator reads the STRUCTURE_UNMATCHED
switch (unmatched_mode) and passes it in.

An item is matched when
- its value matches its `value_cell` only: that cell exists and holds the same number after
  normalisation (currency symbols and thousands separators removed; a decimal comma read only if
  the structure writes numbers like 1.234,5; otherwise a dot before exactly three digits, "2.500",
  is read as 2500 or 2.5, whichever matches, and the item records which in checks.dot_reading;
  brackets around the whole figure make a negative, so "(1,200)" is -1200, while a bracketed number
  after text ("Net loss (1,200)", "Telegram(30K)") matches either sign, recorded in
  checks.bracket_reading; k/m/bn suffixes applied; a scale in a neighbouring cell, a header cell or
  the table's corner cell, such as "£m" or "'000", applied). The match is exact: a rounded number
  does not match. An item with no value is never matched;
- its period matches its `period_cells` only: they are header cells of the value cell (its row
  header or the header stack above its column; in a KPI panel or a roadmap, the cells left of it in
  its row and the top line of its own box), the first is the value cell's lowest period header (a
  year header alone verifies a yearly value only), and the period rebuilt from them under the section 2
  rules has the same start and end date under the audit's year-end (a year, quarter or half is
  fiscal when it is not December; a month is a calendar month, and a month under a year header
  falls inside that year). A two-cell period is a month, quarter or half cell and the year cell
  above it in the same column range. A null period matches only when
  `period_cells` is empty and no header of the value cell holds a period. A relative column ("M3",
  "Year 1") has no period unless its second period cell states the start date ("Start: Jan 2025").
  A period the value cell's own text states ("$8,000 revenue in 2022") rebuilds from that cell, with
  `period_cells` empty or citing the cell itself;
- every proposed flag is reproduced from the matched values (see _flag_reproduced).

When the value matches and Python rebuilds a period from the cited period cells, the rebuilt period
replaces the model's and the period counts as matched: the model is not told the year-end, so it
reads "Apr" under "FY2025" as 2025-04. A model period that differed is a "period corrected" case: it
stays in the stored reading, is counted per structure and per deck, and rides on the item as
"model_period".

Matched items are "verified". The others are "suggestion" (shown as "AI suggestion, not verified")
or, with the switch at "drop", removed and counted.
"""
import math
import os
import re
from typing import Dict, List, Optional, Tuple

from ..decks import claims, parser
from . import redact

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
_DOT_THOUSANDS = re.compile(r"[1-9]\d{0,2}\.\d{3}")     # "2.500": 2,500 written with a dot, or 2.5
_DECIMAL_COMMA = re.compile(r"\d{1,3}(?:\.\d{3})+,\d+")
_LETTER = re.compile(r"[^\W\d_]")
_SCALE_WORD = {"k": 1e3, "thousand": 1e3, "thousands": 1e3, "tsd": 1e3, "хил": 1e3,
               "m": 1e6, "mn": 1e6, "mm": 1e6, "million": 1e6, "millions": 1e6, "mio": 1e6, "млн": 1e6,
               "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9, "mrd": 1e9, "млрд": 1e9}
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
    found = _cell_figure(text, comma)
    return (found[0][0][0], found[1]) if found else None


Reading = Tuple[float, Optional[str], Optional[str]]      # number, dot reading, bracket reading


def _cell_figure(text: str, comma: bool = False) -> Optional[Tuple[List[Reading], bool]]:
    """([(number, dot reading, bracket reading), ...], has its own scale or %) for a cell that holds exactly
    one figure, else None; the first reading is cell_number's. A dot before exactly three digits with no
    decimal comma ("2.500") reads as 2.5 ("decimal") or 2500 ("thousands"). Brackets around the whole
    figure ("(1,200)") make a negative; a bracketed number after text ("Net loss (1,200)",
    "Telegram(30K)") reads as either sign ("positive" or "negative"). Otherwise a reading is None."""
    found = figures(text, comma)
    if len(found) != 1:
        return None
    return found[0]["readings"], found[0]["own_scale"]


def _blank(text: str, spans) -> str:
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + " " * (end - start) + text[end:]
    return text


def figures(text: str, comma: bool = False) -> List[Dict]:
    """Every figure in a cell's text, in order: [{"start", "end", "readings", "own_scale", "suffix"}]. start and
    end cut the figure from the text as written; "readings" are (number, dot reading, bracket reading) as for
    _cell_figure, before any scale from another cell; "own_scale" is True when the figure carries a k/m/bn
    suffix or %. Dates are periods, never values, and a scale mark ("'000") is no figure: both are left out
    first. A range ("$12 -$13 million", "5 – 10%") is two figures: the dash is no sign, and the low end takes
    the high end's suffix or % when it has none (deck-parser.md section 2)."""
    marks = [m.span() for m in _SCALE_MARK.finditer(text) if m.group("mark") and "000" in m.group("mark")]
    blanked = redact.blank_currency(_blank(text, [(d["start"], d["end"]) for d in claims.find_dates(text, table=True)]
                                           + marks))
    out = []
    for m in redact.NUMBER[comma].finditer(blanked):
        if not m.group("num"):
            continue
        raw = m.group("num")
        dots = [(float(raw.replace(",", "")), "decimal"), (float(raw.replace(".", "")), "thousands")] \
            if not comma and _DOT_THOUSANDS.fullmatch(raw) else \
            [(float(raw.replace(".", "").replace(",", ".") if comma else raw.replace(",", "")), None)]
        sign = m.group("sign")
        if sign and out and not blanked[out[-1]["end"]:m.start("sign")].strip():
            sign = None                                         # a range: "12 - 13"
            low = out[-1]
            if not low["suffix"] and not low["pct"]:
                low.update(suffix=(m.group("suffix") or "").lower(), pct=bool(m.group("pct")))
        if sign:
            signs = [(-1.0, None)]
        elif m.group("open") and m.group("close"):
            signs = [(1.0, "positive"), (-1.0, "negative")] if _LETTER.search(blanked[:m.start()]) else [(-1.0, None)]
        else:
            signs = [(1.0, None)]
        seg = blanked[m.start():m.end()]                         # a leading currency symbol is left out too
        out.append({"start": m.start() + len(seg) - len(seg.lstrip()), "end": m.end() - len(seg) + len(seg.rstrip()),
                    "dots": dots, "signs": signs, "suffix": (m.group("suffix") or "").lower(),
                    "pct": bool(m.group("pct"))})
    for f in out:
        scale = _SCALE_WORD[f["suffix"]] if f["suffix"] else 1.0
        dots, signs = f.pop("dots"), f.pop("signs")
        f["readings"] = [(sign * value * scale, dot, bracket) for value, dot in dots for sign, bracket in signs]
        f["own_scale"] = bool(f["suffix"] or f.pop("pct"))
    return out


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


def scale_factor(structure: Dict, cell: Dict) -> float:
    """The scale a figure with no suffix or % of its own takes: the first stated in a neighbouring cell of its
    row, one of its header cells or the table's corner cell ("£m" -> 1e6, "'000" -> 1e3), else 1."""
    cells, comma = structure["cells"], decimal_comma(structure["cells"])
    neighbours = [c for c in cells if c["row"] == cell["row"] and abs(c["col"] - cell["col"]) == 1
                  and not _is_value(c, comma)]
    for c in neighbours + header_cells(structure, cell) + _corner(structure):
        scale = scale_of(c["text"])
        if scale:
            return scale
    return 1.0


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
_START = re.compile(r"(?i)\b(?:start(?:s|ing)?(?: date)?|from|beginning|begins?)\b")
_RELATIVE_UNIT = re.compile(r"(?i)^\s*(?P<u>M|Month|Monat|Y|Year|Jahr|Q|Quarter)")


def _range(label: Optional[str], fiscal_year_end: int):
    return claims.period_range(label, fiscal_year_end) if label else None


def _relative_range(relative: Dict, unit_text: str, start_cell: Optional[Dict],
                    fiscal_year_end: int = 12) -> Optional[Tuple[str, str]]:
    """The range of a relative column ("M3", "Year 2") counted from the start date a cell states."""
    if not start_cell or not _START.search(start_cell["text"]):
        return None
    dates = [d for d in claims.find_dates(start_cell["text"], table=True) if d["kind"] == "month"]
    if len(dates) != 1:
        return None
    year, month = map(int, claims.period_range(dates[0]["date"], fiscal_year_end)[0].split("-")[:2])
    n = relative["relative"]
    unit = _RELATIVE_UNIT.match(unit_text).group("u").lower()
    length = 12 if unit.startswith(("y", "j")) else 3 if unit.startswith("q") else 1
    first = (year * 12 + month - 1) + length * (n - 1)
    last = first + length - 1
    begin = claims.period_range(f"{first // 12}-{first % 12 + 1:02d}")[0]
    end = claims.period_range(f"{last // 12}-{last % 12 + 1:02d}")[1]
    return begin, end


def is_date_line(text: str) -> bool:
    """A date label as deck-parser.md section 7 counts one for a roadmap: a date with at most two other words
    ("Nov. 2007", "Launch Q3 2024"); not a sentence that holds a date."""
    return bool(parser._date_labels(text or "", claims))


def adjacent_date_line(structure: Dict, cell: Dict) -> Optional[Dict]:
    """In a roadmap, the date line of a text line (structure-labelling.md section 2): the one date line directly
    above or below it in the same text box, or None when there is none or one on each side."""
    if structure.get("type") != "roadmap" or is_date_line(cell["text"]):
        return None
    found = [c for c in structure["cells"] if c.get("box") is not None and c.get("box") == cell.get("box")
             and c["col"] == cell["col"] and abs(c["row"] - cell["row"]) == 1 and is_date_line(c["text"])]
    return found[0] if len(found) == 1 else None


def lowest_period_headers(structure: Dict, value_cell: Dict) -> List[Dict]:
    """The header cells nearest the value cell that hold a period, a part of one ("Q3", "Mar") or a
    relative column ("M3"): the lowest one above it and the nearest one left of it in its row."""
    found = [h for h in header_cells(structure, value_cell) if claims.period_cell(h["text"])]
    above = [h for h in found if h["row"] < value_cell["row"]]
    left = [h for h in found if h["row"] == value_cell["row"]]
    return ([max(above, key=lambda h: h["row"])] if above else []) + \
        ([max(left, key=lambda h: h["col"])] if left else [])


def rebuild_period(structure: Dict, value_cell: Dict, period_ids: List[str], fiscal_year_end: int = 12):
    """The (start, end) the cited period cells give under the section 2 rules, or None when they do
    not make a period, or the first is not the value cell's lowest period header: a quarterly or
    monthly value cited against its year header alone is unmatched, so a year header verifies a
    yearly value only. A value with period headers both above it and left of it in its row has a
    period the rules do not build, so it is never matched with one."""
    found = _rebuild(structure, value_cell, period_ids, fiscal_year_end)
    return found[1] if found else None


def rebuilt_label(structure: Dict, value_cell: Dict, period_ids: List[str], fiscal_year_end: int = 12) -> Optional[str]:
    """The period label the cited cells give ("2025", "2025-Q3", "FY2025-04"; "2025-02" for a relative
    column one month long), or None when they give no period or a span no label names."""
    found = _rebuild(structure, value_cell, period_ids, fiscal_year_end)
    return found[0] if found else None


def own_period(value_cell: Optional[Dict]) -> Optional[str]:
    """The period the value cell's own text states ("$8,000 revenue in 2022" -> "2022"), or None."""
    found = claims.period_cell(value_cell["text"]) if value_cell else None
    return found.get("label") if found else None


def _rebuild(structure: Dict, value_cell: Dict, period_ids: List[str], fiscal_year_end: int):
    """(label or None, (start, end)) for rebuild_period and rebuilt_label. A period in the value cell's own
    text rebuilds from that cell when `period_ids` is empty or cites the cell itself."""
    own = own_period(value_cell) if list(period_ids) in ([], [_id(value_cell)]) else None
    if own:
        span = _range(own, fiscal_year_end)
        return (own, span) if span else None
    by_id = {_id(c): c for c in structure["cells"]}
    cited = [by_id.get(i) for i in period_ids]
    if not cited or None in cited or len(cited) > 2:
        return None
    first = cited[0]
    lowest = lowest_period_headers(structure, value_cell)
    if len(lowest) != 1 or _id(first) != _id(lowest[0]):
        return None
    found = claims.period_cell(first["text"])
    if not found:
        return None
    if len(cited) == 1:
        label = found.get("label")
    else:
        second = cited[1]
        if "relative" in found:
            span = _relative_range(found, first["text"], second, fiscal_year_end)
            return (span[0][:7] if span[0][:7] == span[1][:7] else None, span) if span else None
        above = second["row"] < first["row"] and all(k in _cols(second) for k in _cols(first))
        joined = claims.combine_period(found, claims.period_cell(second["text"])) if above else None
        label = joined["label"] if joined else None
    span = _range(label, fiscal_year_end)
    return (label, span) if span else None


def headers_hold_a_period(structure: Dict, value_cell: Dict) -> bool:
    """True when a header of the value cell holds a period: a full period, or a part with its year cell
    above it in the same column range (see claims.combine_period)."""
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
    return match_value(structure, item, value_cell)[0]


def match_value(structure: Dict, item: Dict, value_cell: Optional[Dict]) \
        -> Tuple[bool, Optional[str], Optional[str]]:
    """(matched, dot reading, bracket reading) for the reading of the cell's number the value matched (see
    _cell_figure); both readings are None when the cell's number has one reading or nothing matched."""
    if value_cell is None or item.get("value") is None:
        return False, None, None
    cells, comma = structure["cells"], decimal_comma(structure["cells"])
    found = _cell_figure(value_cell["text"], comma)
    if found is None:
        return False, None, None
    readings, own_scale = found
    factor = 1.0 if own_scale else scale_factor(structure, value_cell)
    wanted = float(item["value"])
    for number, dot, bracket in readings:
        if same_number(number * factor, wanted):
            return True, dot, bracket
    return False, None, None


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
    """{"items": [item + "status" + "checks"], "dropped": n, "periods_corrected": n} for one structure's
    validated reply items.

    `structure` is {"type", "cells", "header_rows"} as the deck parser found it (the cells before
    redaction: redaction never changes a number or a period, and the citation is to the source).
    Every item gets "status" ("verified" or "suggestion") and "checks" ({"value", "period",
    "period_corrected", "flags"}: booleans; "dot_reading": "decimal" or "thousands" when the value
    matched a "2.500"-style number, and "bracket_reading": "positive" or "negative" when it matched a
    bracketed number after text, else None). When the value matches and its period cells rebuild a
    period, that period replaces the model's; if the model's differed, the item carries it as
    "model_period" and counts as a correction. With mode "drop" the unmatched items are removed and
    counted.
    """
    by_id = {_id(c): c for c in structure["cells"]}
    checked = []
    for item in items:
        cell = by_id.get(item.get("value_cell"))
        v, dot, bracket = match_value(structure, item, cell)
        p = period_matches(structure, item, cell, fiscal_year_end)
        # A matched value takes the period Python rebuilds from its cited cells, or from its own text when
        # the model gives a period; when the model's own period differs (it does not know the year-end),
        # that is a correction, and the model's is kept.
        label = rebuilt_label(structure, cell, item["period_cells"], fiscal_year_end) \
            if v and (item.get("period_cells") or item.get("period") is not None) else None
        corrected = bool(label) and not p
        if label:
            item = {**item, "period": label, **({"model_period": item.get("period")} if corrected else {})}
        checked.append((item, v, p or corrected, corrected, dot, bracket))
    matched = [item for item, v, p, *_ in checked if v and p]
    out, dropped = [], 0
    for item, v, p, corrected, dot, bracket in checked:
        flags = all(_flag_reproduced(f, item, matched, structure, fiscal_year_end)
                    for f in item.get("proposed_flags") or ()) if v and p else not item.get("proposed_flags")
        ok = v and p and flags
        if not ok and mode == "drop":
            dropped += 1
            continue
        out.append({**item, "status": VERIFIED if ok else SUGGESTION,
                    "checks": {"value": v, "period": p, "period_corrected": corrected, "flags": flags,
                               "dot_reading": dot, "bracket_reading": bracket}})
    return {"items": out, "dropped": dropped, "periods_corrected": sum(1 for *_, c, _, _ in checked if c)}


def label(status: str) -> str:
    """The label a result row carries in the approval list."""
    return VERIFIED_LABEL if status == VERIFIED else SUGGESTION_LABEL
