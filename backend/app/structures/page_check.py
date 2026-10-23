"""page_check: Python checks each claim the model read from a page, at cell level (CLAUDE.md rule 18).

Design: docs/design/ai-reads-rules-check.md section 2, decisions 2a and 3a (George, 2026-10-22, PR #158). Pure: no I/O, no
model, no database. The model reads the redacted lines of a page (app/decks/pages.py gives every line a cell id) and returns
claims: a metric, a value, a unit, a period and three cell ids (value, label, period). Rules extract nothing. Python checks each
claim against the page grid, which it reads unredacted (redaction never changes a figure or a period, and the citation is to
the source):

1. Figure present: the value cell holds the value, after today's normalisation (verify.figures through items.list_items, a
   scale from an adjacent cell: "1.5M" is 1,500,000, "€", "EUR", "K", "MM" as the item list reads them). The model's value may
   also be the number as written ("1.5" for "1.5M"); a matched row's value is Python's, read from the cell. A range's high
   end is checked the same way. A cell with several figures gives the position. When the check fails, the row shows the model's
   value and range, with no readings and no position, labelled "AI suggestion, not matched"; never the cell's first figure
   ("€2 7K" claimed as 27,000 is one row 27,000 to confirm or reject, not "revenue €2"; George, 2026-10-22, decision 2a on the
   review of PR #159).
2. Unit present: the currency (its symbol or code: "€" or "EUR"), "%", "x", a time word or a count noun is in the value cell or
   one directly next to it. A null unit passes only when the figure in the cell carries no currency, "%", "x" or time word.
3. Period present: null, and no date source of the cell holds a period; or rebuilt by Python from the cited period cell, which
   must be a date source of the value cell: its own text, a column header of its table (a month, quarter or half with the year
   cell above it), the top line or an adjacent line of its own text box, a line of another box directly next to it, or the year
   label of its bar by place (bar_year). A sentence is no source (#154): a cited cell other than the value cell must be a date
   label or a period header. The rebuilt period replaces the model's; a difference is counted as a correction.

Matched (amended 2026-10-23, George): the figure is in the cited cell (check 1) and the claim has a value. The unit and the period no longer
gate the match: a failed unit or period check is a flag the checker adds (checker.py), and the confidence label reads the flags (claims.confidence). A
period cited from a title cell of the page, far from the figure, is rebuilt too (`period_heading` in the checks); a metric "other" is matched like any other.
Otherwise (the figure is not
there, or the claim has no value) "unmatched" ("AI suggestion, not matched"), listed collapsed, approved by a click (decision 3a). The metric is never checked
(it stays the analyst's); the label cell is kept only when it is adjacent to the value cell (the value cell itself, a line of
its own box, a header cell, a line directly next to it or the page title), else the row has no "Label from" and its confidence
reads "no heading". With `drop` (the default), a claim on an axis tick or on a line about funds raised, tokens, the industry and
the like (claims._NOT_PLAN_LINE) is dropped and counted, as the rules read drops them; the checker (checker.py, the live path since
2026-10-22) calls with drop=False and flags such a claim instead, since a failed check never deletes a claim. A claim with no value
is a milestone: never matched, dated from its source.

Adjacency, headers, scales, figures and periods are the verifier's own rules (verify.py, items.py) run on two views of the
grid: the page's text lines as one KPI-panel-like structure (box, next_to) and each table as a table structure (header rows).
"""
import math
import re
from typing import Dict, List, Optional, Tuple

from ..decks import claims
from . import items, redact, verify

MATCHED, UNMATCHED = "matched", "unmatched"
MATCHED_LABEL = "Matched to page"
UNMATCHED_LABEL = "AI suggestion, not matched"
OTHER = "other"
# A unit's marks in the value cell or next to it: a currency by its symbol or code, the rest by their sign or word.
CURRENCY_SYMBOLS = {"EUR": ("€",), "USD": ("$", "US$"), "GBP": ("£",), "JPY": ("¥",), "CNY": ("¥",), "INR": ("₹",)}
_SCALE_WORDS = frozenset("k m mm mn bn b thousand thousands million millions billion billions mio mrd tsd".split())
_WORD = re.compile(r"[^\W\d_]{3,}")
_TIMES = re.compile(r"\d\s?[xX](?![^\W\d_])")
_PERCENT = re.compile(r"%|(?i:\bpercent\b|\bper cent\b)")
_LEVELS = verify.LEVELS


# ---------------------------------------------------------------------------
# The two views of a page grid
# ---------------------------------------------------------------------------
def views(grid: Dict) -> Dict:
    """{"boxes": the text lines as a kpi_panel-like structure, "tables": {table: a table structure}}, sharing the grid's cells
    and ids, so verify.header_cells, items.list_items and verify.scale_factor apply as they do to a structure."""
    cells = grid["cells"]
    header_rows = {t["table"]: t["header_rows"] for t in grid.get("tables") or ()}
    tables = {}
    for c in cells:
        if c.get("table") is not None:
            tables.setdefault(c["table"], []).append(c)
    return {"boxes": {"type": "kpi_panel", "header_rows": 0, "cells": [c for c in cells if c.get("table") is None]},
            "tables": {t: {"type": "table", "header_rows": header_rows.get(t, 0), "cells": tcells} for t, tcells in tables.items()}}


def view_of(grid_views: Dict, cell: Dict) -> Dict:
    return grid_views["tables"][cell["table"]] if cell.get("table") is not None else grid_views["boxes"]


def _id(cell: Dict) -> str:
    return redact.cell_id(cell)


def _same_box(structure: Dict, cell: Dict) -> List[Dict]:
    """The other lines of the cell's own text box."""
    return [c for c in structure["cells"] if c.get("box") is not None and c.get("box") == cell.get("box") and c is not cell]


def adjacent(structure: Dict, cell: Dict) -> List[Dict]:
    """The cells directly next to a value cell: its header cells (verify.header_cells: in a table its row header and the header
    stack above its column; for a text line the top line of its box and the cells of other boxes directly left of it), the lines
    directly above and below it in its own box, every line of another box directly next to it (next_to) and, in a table, its row
    neighbours that are not values."""
    by_id = {_id(c): c for c in structure["cells"]}
    comma = verify.decimal_comma(structure["cells"])
    found = list(verify.header_cells(structure, cell))
    found += [c for c in _same_box(structure, cell) if abs(c["row"] - cell["row"]) == 1]
    found += [by_id[n] for n in cell.get("next_to") or () if n in by_id]
    if cell.get("table") is not None:
        found += [c for c in structure["cells"] if c["row"] == cell["row"] and abs(c["col"] - cell["col"]) == 1
                  and not verify._is_value(c, comma)]
    out, seen = [], {_id(cell)}
    for c in found:
        if _id(c) not in seen:
            seen.add(_id(c))
            out.append(c)
    return out


def label_cells(structure: Dict, cell: Dict) -> List[Dict]:
    """Where a label may stand: the value cell itself, any line of its own box, every adjacent cell and the page title (the
    heading of the whole page, as the KPI panel and the rules read take it; it only names the type, which stays the analyst's)."""
    return [cell] + _same_box(structure, cell) + adjacent(structure, cell) + [c for c in structure["cells"] if c.get("title")]


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
def _is_date_source(text: str) -> bool:
    """A date label (a date with at most two other words) or a period header ("Q3", "Mar", "FY2025"); never a sentence."""
    return verify.is_date_line(text) or verify.period_header(text)


def date_sources(structure: Dict, cell: Dict) -> List[Dict]:
    """The adjacent cells a period may come from."""
    return [c for c in adjacent(structure, cell) if _is_date_source(c["text"]) and not verify.figures(c["text"])]


def _from_source(structure: Dict, source: Dict, fiscal_year_end: int):
    """(label, (start, end), [cell ids]) Python rebuilds from a date source: its one date, or its month, quarter or half with
    the year cell above it in the same column range; None for a relative header or a cell that gives no period."""
    found = claims.period_cell(source["text"])
    if not found or "relative" in found:
        return None
    cells = [_id(source)]
    label = found.get("label")
    if "part" in found:
        year = verify._year_above(structure, found, source)
        if not year:
            return None
        cells.append(_id(year[0]))
        label = year[1]["label"]
    span = claims.period_range(label, fiscal_year_end) if label else None
    return (label, span, cells) if span else None


def _bar_cell(structure: Dict, cell: Dict, cited: Dict) -> bool:
    """Whether the cited cell is the year label of the value's bar by place (issue #148)."""
    return bool(cell.get("bar_year")) and cited["text"].strip() == str(cell["bar_year"]).strip()


def holds_period(structure: Dict, cell: Dict, fiscal_year_end: int) -> bool:
    """Whether any date source of the cell gives a period: its own text, an adjacent date source or its bar's year label."""
    if verify.own_period(cell) and claims.period_range(verify.own_period(cell), fiscal_year_end):
        return True
    if cell.get("bar_year") and claims.period_range((claims.period_cell(cell["bar_year"]) or {}).get("label"), fiscal_year_end):
        return True
    return any(_from_source(structure, s, fiscal_year_end) for s in date_sources(structure, cell))


def period_check(structure: Dict, cell: Dict, model: Optional[str], cited: Optional[Dict], fiscal_year_end: int):
    """(period label, period cells, ok, corrected, heading): the period Python rebuilds from the cited cell when it is a date source
    of the value cell (its own text, an adjacent date label or header, its bar's year label), or the page's heading (a title cell
    of the page, `heading` True: the period stands on no line or block of the figure); a null period with nothing cited stands
    only when no source holds a period. The period never gates the match (George, 2026-10-23): ok only decides the flags. `heading` is "heading" (title cell or top 20% of the page), "other" (any other cell
    outside the figure's block that states the period) or False."""
    wanted = claims.period_range(model, fiscal_year_end) if model else None
    if cited is None and model is None:
        return None, [], not holds_period(structure, cell, fiscal_year_end), False, False
    if cited is None:
        bar = (claims.period_cell(cell["bar_year"]) or {}).get("label") if cell.get("bar_year") else None
        span = claims.period_range(bar, fiscal_year_end) if bar else None
        if span and span == wanted:             # the bar's year by place: Python's, with no cell of its own (issue #148)
            return bar, [], True, False, False
        return model, [], False, False, False
    heading = False
    if _id(cited) == _id(cell):
        label = verify.own_period(cell)
        span = claims.period_range(label, fiscal_year_end) if label else None
        found = (label, span, [_id(cell)]) if span else None
    elif any(_id(cited) == _id(s) for s in date_sources(structure, cell)) or _bar_cell(structure, cell, cited):
        found = _from_source(structure, cited, fiscal_year_end)
    elif cited.get("title") or cited.get("top_band"):
        found = _from_source(structure, cited, fiscal_year_end)         # the page heading (title cell or top 20% of the page)
        heading = "heading" if found is not None else False
    elif any(_id(cited) == _id(s) for s in _same_box(structure, cell)):
        found = None                            # a sentence in the figure's own block is no source (#154)
    else:
        found = _from_source(structure, cited, fiscal_year_end)         # any other cell of the page that states the period
        heading = "other" if found is not None else False
    if found is None:
        return model, [], False, False, False
    label, span, cells = found
    return label, cells, True, wanted != span, heading


# ---------------------------------------------------------------------------
# Figures and units
# ---------------------------------------------------------------------------
def _close(a, b) -> bool:
    return a is not None and b is not None and math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)


def _written(raw: str, comma: bool) -> Optional[float]:
    """The number as the cell writes it, before any scale ("1.5" for "1.5M"), with its sign."""
    m = redact.NUMBER[comma].search(redact.blank_currency(raw))
    if not m or not m.group("num"):
        return None
    num = m.group("num")
    value = float(num.replace(".", "").replace(",", ".")) if comma else float(num.replace(",", ""))
    return -value if m.group("sign") else value


def _item_values(item: Dict, metric: str) -> List[Dict]:
    """The item's readings, Python's default first; a level keeps its positive reading only (verify.LEVELS)."""
    return [v for v in item["values"] if metric not in _LEVELS or v.get("bracket_reading") != "negative"] or list(item["values"])


def own_figure(cell: Dict, position: int, comma: bool) -> Optional[Dict]:
    """The figure at an item's position as the claims reader sees it (currency, unit, counted noun), by its place in the text."""
    spans = verify.figures(cell["text"], comma)
    if position - 1 >= len(spans):
        return None
    start = spans[position - 1]["start"]
    found = claims.find_numbers(cell["text"], claims.find_dates(cell["text"]))
    return next((f for f in found if f["start"] <= start < f["end"]), None)


def _own_unit(figure: Optional[Dict]) -> Optional[str]:
    """What the figure's own text says its unit is: a currency code, "%", "x", a time word, "count" for a counted noun, or None."""
    if not figure:
        return None
    if figure.get("currency"):
        return figure["currency"]
    if figure.get("unit") in ("%", "x", "days", "months", "years"):
        return figure["unit"]
    return "count" if figure.get("count") else None


def _unit_agrees(figure: Optional[Dict], unit: Optional[str], unit_other: Optional[str]) -> Optional[bool]:
    """True or False when the figure's own text states a unit, None when it states none."""
    own = _own_unit(figure)
    if own is None:
        return None
    return own == (unit_other if unit == OTHER else unit)


def figure_check(listed: Dict, cell: Dict, value, value_high, metric: str, comma: bool, unit=None, unit_other=None):
    """(item, values, ok): the item of the cell whose readings or written number is the model's value; a reading in full units
    is preferred to the written number ("15" is the 15% before the €15K), and among equal values the figure whose own unit
    agrees with the claim's; for a range the high end must match the item's range too. No match (a title, a period header, no
    figure, or a figure the cell does not hold) gives (None, [], False): the row then shows the model's value."""
    own = [i for i in listed["items"] if i["cell"] == _id(cell)]
    hits = []
    for pass_ in ("full", "written"):
        for item in own:
            values = _item_values(item, metric)
            hit = any(_close(v["value"], value) for v in values) if pass_ == "full" else _close(_written(item["raw"], comma), value)
            if not hit:
                continue
            span = item.get("range")
            if value_high is not None:
                if not span or item["id"] != span["items"][0]:
                    continue
                high = next((i for i in own if i["id"] == span["items"][1]), None)
                if high is None or not (any(_close(v["value"], value_high) for v in high["values"])
                                        or _close(_written(high["raw"], comma), value_high)):
                    continue
            hits.append((item, values))
    for item, values in hits:
        if _unit_agrees(own_figure(cell, item["position"], comma), unit, unit_other) is not False:
            return item, values, True
    if hits:
        return hits[0][0], hits[0][1], True
    return None, [], False


def _marks(structure: Dict, cell: Dict) -> List[str]:
    return [cell["text"]] + [c["text"] for c in adjacent(structure, cell)]


def unit_check(structure: Dict, cell: Dict, item: Optional[Dict], unit: Optional[str], unit_other: Optional[str],
               comma: bool = False) -> bool:
    """Whether the unit is where the model says it is (rule 2 above): when the figure's own text states one (a currency symbol or
    code, "%", "x", a time word, a counted noun) the claim's unit must be that one; otherwise its mark must stand in the value cell
    or one directly next to it. A null unit passes only when the figure carries no currency, "%", "x" or time word."""
    figure = own_figure(cell, item["position"], comma) if item is not None else None
    stated = _unit_agrees(figure, unit, unit_other)
    if unit is None:
        return figure is None or (figure.get("currency") is None and (figure.get("unit") is None or bool(figure.get("count"))))
    if stated is not None:
        return stated
    texts = _marks(structure, cell)
    joined = " ".join(texts)
    if unit == "%":
        return bool(_PERCENT.search(joined))
    if unit == "x":
        return bool(_TIMES.search(joined))
    if unit in ("days", "months", "years"):
        return bool(re.search(r"(?i)\b" + unit[:-1] + r"s?\b", joined))
    if unit == "count":
        words = {w.lower() for w in _WORD.findall(redact.blank_currency(joined))}
        return bool(words - _SCALE_WORDS)
    code = unit_other if unit == OTHER else unit
    if not code:
        return False
    marks = CURRENCY_SYMBOLS.get(code, ()) + (code,)
    return any(mark in text if not mark.isalpha() else re.search(r"(?<![A-Za-z])" + re.escape(mark) + r"(?![A-Za-z])", text)
               for text in texts for mark in marks)


# ---------------------------------------------------------------------------
# One page
# ---------------------------------------------------------------------------
def _checks(value_ok: bool, unit_ok: bool, period_ok: bool, label_ok: bool, corrected: bool, values: List[Dict],
            heading: bool = False) -> Dict:
    first = values[0] if values else {}
    return {"value": value_ok, "unit": unit_ok, "period": period_ok, "label": label_ok, "period_corrected": corrected,
            "period_heading": heading == "heading", "period_other": heading == "other",
            "dot_reading": first.get("dot_reading"), "bracket_reading": first.get("bracket_reading")}


def _distance(grid_views: Dict, cited: Dict, other: Dict) -> Tuple[int, int, int]:
    """How far another cell stands from the cited one: another table or the text lines last, then the rows and columns between."""
    same = view_of(grid_views, cited) is view_of(grid_views, other)
    return (0 if same else 1, abs(cited["row"] - other["row"]), abs(cited["col"] - other["col"]))


def find_elsewhere(grid: Dict, grid_views: Dict, listed: Dict, cited: Dict, claim: Dict):
    """(cell, item, values) of the nearest other cell of the page that holds the claim's value (and the high end of a range), the
    cell tolerance (George, 2026-10-23): the figure check of figure_check on each cell, page furniture (header or footer band, the
    page's own number) never counting. None when no other cell holds it. Ties keep the grid's order."""
    others = sorted((c for c in grid["cells"] if c is not cited and not c.get("furniture")), key=lambda c: _distance(grid_views, cited, c))
    for other in others:
        structure = view_of(grid_views, other)
        item, values, ok = figure_check(listed[id(structure)], other, claim["value"], claim.get("value_high"), claim["metric"],
                                        verify.decimal_comma(structure["cells"]), claim.get("unit"), claim.get("unit_other"))
        if ok:
            return other, item, values
    return None


def _dropped(cell: Dict) -> Optional[str]:
    """Why a claim on this cell is dropped before any check: an axis tick, or a line the rules read drops as no plan claim."""
    if cell.get("tick"):
        return "tick"
    if claims._NOT_PLAN_LINE.search(cell["text"]):
        return "not_plan"
    return None


def check(grid: Dict, page_claims: List[Dict], fiscal_year_end: int = 12, drop: bool = True) -> Dict:
    """{"items": [checked], "matched": n, "unmatched": n, "dropped": n, "periods_corrected": n} for one page grid and the
    model's claims on it (cell ids without the page prefix: "r3c2"). A claim on a cell the page does not have is always dropped;
    an axis tick or a no-plan line only with `drop`.

    Each checked item keeps the claim's metric, unit, unit_other, basis and scenario with Python's value and values (the
    default reading first), value_high (Python's range), value_cell and position, the period Python rebuilt and its period
    cells, the label cell when adjacent, "status" (matched or unmatched) and "checks" ({"value", "unit", "period", "label",
    "period_corrected"}: booleans; "dot_reading" and "bracket_reading": the default reading's closed word, or None). A
    corrected period keeps the model's as "model_period".
    """
    by_id = {_id(c): c for c in grid["cells"]}
    grid_views = views(grid)
    listed = {id(s): items.list_items(s, titles=True) for s in [grid_views["boxes"], *grid_views["tables"].values()]}
    checked, dropped, corrected_count = [], 0, 0
    for claim in page_claims:
        cell = by_id.get(claim["value_cell"])
        if cell is None or (drop and _dropped(cell)):
            dropped += 1
            continue
        structure = view_of(grid_views, cell)
        comma = verify.decimal_comma(structure["cells"])
        metric = claim["metric"]
        item, values, value_ok = (None, [], False) if claim.get("value") is None else \
            figure_check(listed[id(structure)], cell, claim["value"], claim.get("value_high"), metric, comma, claim.get("unit"),
                         claim.get("unit_other"))
        model_cell = None
        if claim.get("value") is not None and not value_ok:
            found = find_elsewhere(grid, grid_views, listed, cell, claim)
            if found:
                model_cell, (cell, item, values), value_ok = cell, found, True
                structure = view_of(grid_views, cell)
                comma = verify.decimal_comma(structure["cells"])
        unit_ok = unit_check(structure, cell, item, claim.get("unit"), claim.get("unit_other"), comma) \
            if claim.get("value") is not None else claim.get("unit") is None
        cited = by_id.get(claim["period_cell"]) if claim.get("period_cell") else None
        period, period_cells, period_ok, corrected, heading = period_check(structure, cell, claim.get("period"), cited, fiscal_year_end)
        corrected_count += int(corrected)
        label = by_id.get(claim["label_cell"]) if claim.get("label_cell") else None
        label_ok = label is None or any(_id(label) == _id(c) for c in label_cells(structure, cell))
        span = item.get("range") if item else None
        ok = value_ok and claim.get("value") is not None          # the figure is in the cited cell; unit and period only flag
        out = {"metric": metric, "unit": claim.get("unit"), "unit_other": claim.get("unit_other"),
               "basis": claim.get("basis"), "scenario": claim.get("scenario", "none"),
               # Python's value and range when the figure check passes; the model's when it fails (decision 2a, review of PR #159).
               "value": values[0]["value"] if value_ok and values else claim.get("value"), "values": [dict(v) for v in values],
               "value_high": (span["high"] if span and item["id"] == span["items"][0] else None) if value_ok else claim.get("value_high"),
               "value_cell": _id(cell), "position": item["position"] if item else None,
               "period": period, "period_cells": period_cells,
               "label_cell": _id(label) if label is not None and label_ok else None,
               "status": MATCHED if ok else UNMATCHED,
               "checks": _checks(value_ok, unit_ok, period_ok, label_ok, corrected, values, heading)}
        if corrected:
            out["model_period"] = claim.get("period")
        if model_cell is not None:
            out["cell_corrected"], out["model_cell"] = True, _id(model_cell)
        checked.append(out)
    matched = sum(1 for c in checked if c["status"] == MATCHED)
    return {"items": checked, "matched": matched, "unmatched": len(checked) - matched, "dropped": dropped,
            "periods_corrected": corrected_count}


def label(status: str) -> str:
    """The badge a page-read row carries."""
    return MATCHED_LABEL if status == MATCHED else UNMATCHED_LABEL


def split_cell_id(page_cell: str) -> Tuple[int, str]:
    """("p5r2c1") -> (5, "r2c1")."""
    m = re.fullmatch(r"p(\d+)(r\d+c\d+)", page_cell or "")
    return (int(m.group(1)), m.group(2)) if m else (0, page_cell)


def by_page(reply_claims: List[Dict]) -> Dict[int, List[Dict]]:
    """The claims of a batch reply grouped by page, each cell id without its page prefix."""
    out: Dict[int, List[Dict]] = {}
    for claim in reply_claims:
        page, cell = split_cell_id(claim["value_cell"])
        row = dict(claim, value_cell=cell)
        for key in ("label_cell", "period_cell"):
            if row.get(key):
                other, local = split_cell_id(row[key])
                row[key] = local if other == page else None       # a label or period cited on another page is none
        out.setdefault(page, []).append(row)
    return out
