"""The verifier: model output never becomes Verified on its own (CLAUDE.md rule 18).

Spec: docs/specs/structure-labelling.md section 4, with the period rules of deck-parser.md section 2. Pure:
no I/O, no model, no database. The orchestrator reads the STRUCTURE_UNMATCHED switch (unmatched_mode) and
passes it in.

Python lists every figure (app/structures/items.py), so every value and cell is Python's and nothing matches
a model value any more. The model labels each listed item (metric, period, unit, actual or forecast) and pairs
a roadmap's lines with its dates. Here each label is joined to its item, and

- the period is rebuilt by Python from the item's lowest period header (a month, quarter or half with the
  year cell above it in the same column range), else from a period its own cell states ("$8,000 revenue in
  2022"), else in a roadmap from its adjacent date line (the one date line directly above or below it in its
  text box). The rebuilt period replaces the model's, which the model reads without the audit's year-end;
  a difference is a "period corrected" case, kept as "model_period" and counted. A model period with
  nothing to rebuild from, or a header period Python cannot rebuild (period headers both above and beside
  the cell), is "period not rebuilt": an AI suggestion. A null period stands when no header holds a period;
- a figure in a paired roadmap line is dated by its pair's date cell, and is Verified only when its own
  period cells rebuild that same period (the pairing is the model's);
- the separator and sign readings come from the item's cell: "2.500" (thousands unless a suffix) and a
  bracketed number after text (negative after loss, deficit, negative or decline) are recorded with
  Python's default as checks.dot_reading and checks.bracket_reading, so the item can be Verified;
- total_mismatch and growth_mismatch are computed by Python over the Verified items (_flag_reproduced);
- not_a_metric items are dropped and counted; an "other" item is listed as type Other and never Verified;
- each pair is a milestone: no value, so never Verified, dated by its date cell, its claim type its
  category's (MILESTONE_TYPES).

Verified items are "verified". The others are "suggestion" (shown as "AI suggestion, not verified") or,
with the switch at "drop", removed and counted.
"""
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
OTHER, NOT_A_METRIC = "other", "not_a_metric"
# A roadmap milestone's claim type, by the category the model gives its pair (structure-labelling.md section 2).
MILESTONE_TYPES = {"launch": "product", "feature": "product", "expansion": "product", "partnership": "product",
                   "hiring": "people", "break_even": "ebitda", "funding": OTHER, "certification": "product",
                   "other": "product"}
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
    the high end's suffix or % when it has none (deck-parser.md section 2); the high end carries "range_low",
    the index of its low end."""
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
        sign, range_low = m.group("sign"), None
        if sign and out and not blanked[out[-1]["end"]:m.start("sign")].strip():
            sign, range_low = None, len(out) - 1                # a range: "12 - 13"
            low = out[-1]
            if not low["suffix"] and not low["pct"]:
                low.update(suffix=(m.group("suffix") or "").lower(), pct=bool(m.group("pct")))
        if sign:
            signs = [(-1.0, None)]
        elif m.group("open") and m.group("close"):
            signs = [(1.0, "positive"), (-1.0, "negative")] if _LETTER.search(blanked[:m.start()]) else [(-1.0, None)]
        else:
            signs = [(1.0, None)]
        # The figure as cut from the cell: its brackets when they close around it, its sign unless it is a range
        # dash; never a leading currency symbol or spaces.
        both = bool(m.group("open") and m.group("close"))
        lo = m.start() if both else m.start("sign") if sign else m.start("num")
        hi = m.end() if both else max(m.end(g) for g in ("num", "suffix", "pct") if m.group(g))
        seg = blanked[lo:hi]
        out.append({"start": lo + len(seg) - len(seg.lstrip()), "end": hi - len(seg) + len(seg.rstrip()),
                    "dots": dots, "signs": signs, "suffix": (m.group("suffix") or "").lower(),
                    "pct": bool(m.group("pct")), **({"range_low": range_low} if range_low is not None else {})})
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


def _beside(structure: Dict, cell: Dict, others: List[Dict]) -> List[Dict]:
    """In a KPI panel, those of `others` (cells of other boxes in the cell's grid row) that are directly next to it
    on the page, its "next_to" (deck-parser.md section 7): a tall box can merge two visual rows into one grid row,
    and a wrong label or scale is worse than a missing one (structure-labelling.md section 1). Elsewhere all."""
    if structure.get("type") != "kpi_panel":
        return others
    return [c for c in others if _id(c) in (cell.get("next_to") or ())]


def header_cells(structure: Dict, cell: Dict) -> List[Dict]:
    """The header cells of a value cell, nearest first: its row header (the cells left of it in its
    row that are not values) and the header stack above its column (header rows covering it). In a
    KPI panel or a roadmap, the cells left of it in its row and the top line of its own box; in a KPI
    panel only the cells left of it that are directly next to it (_beside)."""
    cells, comma = structure["cells"], decimal_comma(structure["cells"])
    left = _beside(structure, cell, sorted((c for c in cells if c["row"] == cell["row"] and c["col"] < cell["col"]
                                            and not _is_value(c, comma)), key=lambda c: -c["col"]))
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
    row (in a KPI panel one directly next to it, _beside), one of its header cells or the table's corner cell
    ("£m" -> 1e6, "'000" -> 1e3), else 1."""
    cells, comma = structure["cells"], decimal_comma(structure["cells"])
    neighbours = _beside(structure, cell, [c for c in cells if c["row"] == cell["row"]
                                           and abs(c["col"] - cell["col"]) == 1 and not _is_value(c, comma)])
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


def _date_sides(structure: Dict, cell: Dict) -> Dict[str, Dict]:
    """{"above": date line, "below": date line}: the date lines directly above and below a text line in its text box."""
    found = {}
    for c in structure["cells"]:
        if c.get("box") is not None and c.get("box") == cell.get("box") and c["col"] == cell["col"] \
                and abs(c["row"] - cell["row"]) == 1 and is_date_line(c["text"]):
            found["above" if c["row"] < cell["row"] else "below"] = c
    return found


def period_header(text: str) -> bool:
    """A period header ("Q3", "Mar", "M3", "Year 1"): a part of a period or a relative column, never a value."""
    found = claims.period_cell(text)
    return bool(found) and ("part" in found or "relative" in found)


def holds_figure(cell: Dict, comma: bool = False) -> bool:
    """Whether the item list (structure-labelling.md section 1) lists a figure in the cell."""
    return not period_header(cell["text"]) and bool(figures(cell["text"], comma))


def date_direction(structure: Dict) -> Optional[str]:
    """A roadmap's date direction, "above" or "below" (structure-labelling.md section 2, decisions of 2026-10-06), from
    its text lines with a date line on one side only: the side they all name; when they disagree, the side those that
    hold a figure all name; else None."""
    comma = decimal_comma(structure["cells"])
    one_sided = [(next(iter(sides)), c) for c in structure["cells"] if not is_date_line(c["text"])
                 for sides in [_date_sides(structure, c)] if len(sides) == 1]
    for named in ([side for side, _ in one_sided], [side for side, c in one_sided if holds_figure(c, comma)]):
        if len(set(named)) == 1:
            return named[0]
    return None


def adjacent_date_line(structure: Dict, cell: Dict) -> Optional[Dict]:
    """In a roadmap, the date line of a text line (structure-labelling.md section 2): the date line directly above or
    below it in the same text box; with one on each side, the one in the timeline's date direction (None when the
    timeline has none)."""
    if structure.get("type") != "roadmap" or is_date_line(cell["text"]):
        return None
    sides = _date_sides(structure, cell)
    if len(sides) == 1:
        return next(iter(sides.values()))
    direction = date_direction(structure) if sides else None
    return sides.get(direction) if direction else None


def lowest_period_headers(structure: Dict, value_cell: Dict) -> List[Dict]:
    """The header cells nearest the value cell that hold a period, a part of one ("Q3", "Mar") or a
    relative column ("M3"): the lowest one above it and the nearest one left of it in its row."""
    found = [h for h in header_cells(structure, value_cell) if claims.period_cell(h["text"])]
    above = [h for h in found if h["row"] < value_cell["row"]]
    left = [h for h in found if h["row"] == value_cell["row"]]
    return ([max(above, key=lambda h: h["row"])] if above else []) + \
        ([max(left, key=lambda h: h["col"])] if left else [])


def own_period(value_cell: Optional[Dict]) -> Optional[str]:
    """The period the value cell's own text states ("$8,000 revenue in 2022" -> "2022"), or None."""
    found = claims.period_cell(value_cell["text"]) if value_cell else None
    return found.get("label") if found else None


def date_period(text: str) -> Optional[str]:
    """The period a roadmap date cell gives: its one date ("Q3 2025" -> "2025-Q3"), or None for none or several."""
    dates = claims.find_dates(text or "")
    return dates[0]["date"] if len(dates) == 1 else None


def _year_above(structure: Dict, part: Dict, cell: Dict) -> Optional[Tuple[Dict, Dict]]:
    """(year cell, combined period) for a month, quarter or half cell: the nearest cell above it in the same
    column range that is a year (deck-parser.md section 2), or None."""
    above = sorted((c for c in structure["cells"] if c["row"] < cell["row"] and all(k in _cols(c) for k in _cols(cell))),
                   key=lambda c: -c["row"])
    for up in above:
        joined = claims.combine_period(part, claims.period_cell(up["text"]))
        if joined:
            return up, joined
    return None


def _from_header(structure: Dict, header: Dict, fiscal_year_end: int):
    """(label or None, (start, end), [cell ids]) from a lowest period header, or None."""
    found = claims.period_cell(header["text"])
    if not found:
        return None
    if "relative" in found:
        starts = [c for c in structure["cells"] if _START.search(c["text"])
                  and len([d for d in claims.find_dates(c["text"], table=True) if d["kind"] == "month"]) == 1]
        span = _relative_range(found, header["text"], starts[0], fiscal_year_end) if len(starts) == 1 else None
        return ((span[0][:7] if span[0][:7] == span[1][:7] else None), span, [_id(header), _id(starts[0])]) \
            if span else None
    cells = [_id(header)]
    label = found.get("label")
    if "part" in found:
        year = _year_above(structure, found, header)
        if not year:
            return None
        cells.append(_id(year[0]))
        label = year[1]["label"]
    span = _range(label, fiscal_year_end)
    return (label, span, cells) if span else None


def rebuild(structure: Dict, cell: Dict, fiscal_year_end: int = 12):
    """(label or None, (start, end), [period cell ids]) Python rebuilds for an item's cell, or None
    (structure-labelling.md section 4): from its lowest period header (a month, quarter or half with the year cell
    above it in the same column range), else from a period its own text states, else in a roadmap from its
    adjacent date line. Period headers both above it and beside it make a period the rules do not build. A
    relative column ("Year 1") counted from a start date ("Start: Jan 2025") has a label only when it is one month
    long."""
    lowest = lowest_period_headers(structure, cell)
    if len(lowest) > 1:
        return None
    if lowest:
        found = _from_header(structure, lowest[0], fiscal_year_end)
        if found:
            return found
    label = own_period(cell)
    if label and _range(label, fiscal_year_end):
        return label, _range(label, fiscal_year_end), [_id(cell)]
    date = adjacent_date_line(structure, cell)
    label = date_period(date["text"]) if date else None
    if label and _range(label, fiscal_year_end):
        return label, _range(label, fiscal_year_end), [_id(date)]
    return None


def headers_hold_a_period(structure: Dict, value_cell: Dict) -> bool:
    """True when a header of the value cell holds a period: a full period, or a part with its year cell
    above it in the same column range (see claims.combine_period)."""
    for h in header_cells(structure, value_cell):
        found = claims.period_cell(h["text"])
        if found and ("label" in found or ("part" in found and _year_above(structure, found, h))):
            return True
    return False


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
FLAGS = ("total_mismatch", "growth_mismatch")


def _checks(ok: bool, corrected: bool, values: List[Dict]) -> Dict:
    first = values[0] if values else {}
    return {"period": ok, "period_corrected": corrected, "dot_reading": first.get("dot_reading"),
            "bracket_reading": first.get("bracket_reading")}


def _dated(structure: Dict, cell: Dict, model: Optional[str], pair_date: Optional[Dict], fiscal_year_end: int):
    """(period, period cells, ok, corrected) for an item: the period Python rebuilds from the item's own period
    cells replaces the model's (a difference is a correction); a null period stands when no header holds one; a
    model period with nothing to rebuild from is not rebuilt. A figure in a paired roadmap line is dated by its
    pair, and is ok only when its own cells rebuild that same period."""
    found = rebuild(structure, cell, fiscal_year_end)
    wanted = _range(model, fiscal_year_end) if model else None
    if pair_date is not None:
        label = date_period(pair_date["text"])
        span = _range(label, fiscal_year_end) if label else None
        if span is None:
            return model, [], False, False
        ok = found is not None and found[1] == span
        return label, [_id(pair_date)], ok, ok and wanted != span
    if found is None:
        ok = model is None and not headers_hold_a_period(structure, cell)
        return model, [], ok, False
    label, span, cells = found
    if label is None:                       # a span no label names: the model's period stands if it is that span
        return model, cells, model is None or wanted == span, False
    return label, cells, True, wanted != span


def verify(structure: Dict, listed: Dict, labels: List[Dict], pairs: List[Dict] = (), fiscal_year_end: int = 12,
           mode: str = "suggest") -> Dict:
    """{"items": [checked], "dropped": n, "periods_corrected": n, "not_a_metric": n} for one structure's validated
    labels and pairs (structure-labelling.md section 4).

    `structure` is {"type", "cells", "header_rows"} as the deck parser found it (the cells before redaction:
    redaction never changes a number or a period, and the citation is to the source); `listed` is Python's item
    list for it (items.list_items, the raw text not needed). Each label is joined to its item, so a checked item
    keeps the label's fields with Python's value, values (the default reading first), cell ("value_cell"),
    position, the period cells Python rebuilt the period from, Python's flags ("proposed_flags", computed over the
    Verified items) and its "status" ("verified" or "suggestion") and "checks" ({"period", "period_corrected"}:
    booleans; "dot_reading" and "bracket_reading": the default reading's closed word, or None). A corrected period
    keeps the model's as "model_period". not_a_metric items are dropped and counted; an "other" item is never
    Verified. Each roadmap pair is a milestone (its line's cell, the claim type MILESTONE_TYPES gives its category,
    the period of its date cell, no value), never Verified. With mode "drop" the unverified are removed and
    counted.
    """
    by_id = {_id(c): c for c in structure["cells"]}
    item_of = {item["id"]: item for item in listed.get("items") or ()}
    dates = {d["id"]: by_id.get(d["cell"]) for d in listed.get("dates") or ()}
    lines = {t["id"]: t["cell"] for t in listed.get("lines") or ()}
    pair_of_cell = {lines[p["line"]]: dates.get(p["date"]) for p in pairs if p["line"] in lines}
    checked, not_a_metric, corrected_count = [], 0, 0
    for label_ in labels:
        item = item_of[label_["item"]]
        if label_["metric"] == NOT_A_METRIC:
            not_a_metric += 1
            continue
        cell = by_id[item["cell"]]
        period, cells, ok, corrected = _dated(structure, cell, label_.get("period"), pair_of_cell.get(item["cell"]),
                                              fiscal_year_end)
        corrected_count += int(corrected)
        out = {"item": item["id"], "position": item["position"],
               **{k: label_.get(k) for k in ("metric", "period", "unit", "unit_other", "actual_or_forecast")},
               "period": period, "value": item["values"][0]["value"], "values": [dict(v) for v in item["values"]],
               "value_cell": item["cell"], **({"range": item["range"]} if item.get("range") else {}),
               "period_cells": cells, "proposed_flags": [],
               "status": VERIFIED if ok and label_["metric"] != OTHER else SUGGESTION,
               "checks": _checks(ok, corrected, item["values"])}
        if corrected:
            out["model_period"] = label_.get("period")
        checked.append(out)
    verified = [c for c in checked if c["status"] == VERIFIED]
    for c in verified:
        c["proposed_flags"] = [f for f in FLAGS if _flag_reproduced(f, c, verified, structure, fiscal_year_end)]
    for p in pairs:
        line, date = lines.get(p["line"]), dates.get(p["date"])
        period = date_period(date["text"]) if date else None
        checked.append({"item": p["line"], "line": p["line"], "date": p["date"], "category": p["category"],
                        "position": None, "metric": MILESTONE_TYPES[p["category"]], "period": period, "unit": None,
                        "unit_other": None, "actual_or_forecast": "unknown", "value": None, "values": [],
                        "value_cell": line, "period_cells": [_id(date)] if date else [], "proposed_flags": [],
                        "status": SUGGESTION, "checks": _checks(period is not None, False, [])})
    kept = [c for c in checked if c["status"] == VERIFIED or mode != "drop"]
    return {"items": kept, "dropped": len(checked) - len(kept), "periods_corrected": corrected_count,
            "not_a_metric": not_a_metric}


def label(status: str) -> str:
    """The label a result row carries in the approval list."""
    return VERIFIED_LABEL if status == VERIFIED else SUGGESTION_LABEL
