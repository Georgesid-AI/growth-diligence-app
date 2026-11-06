"""The cell checks (docs/design/read-check-review.md section 5; PR 2).

The reader returns a file map (schemas/metrics.FileMap); this module opens every cell the map cites, in the masked text the reader was
sent, and gives each item one of three outcomes, and only three. Code never reads, never decides what a row means and never corrects.

    confirmed     the cited cell holds the value within tolerance: money 0.5 %, rates 1 point, counts exact, text exact after whitespace,
                  dates exact to the month.
    rejected      the cell exists but does not hold what the reading says. The reason is written here, from a template, the same wording
                  every time.
    cannot_check  nothing to compare against: five cases, each explicit below. Anything else that fails is a rejection.

A structural claim the reader gives as evidence (a row ends at a column, a range equals another range, a label contains a word, a range
repeats one value, a range is round) is checked where there is a test for it, else it is a layout description and cannot be checked. There
is no check that changes a citation: a rejected item is read once more by the model, with its reason (gateway.read_structure, recheck).

The as-of month of a file stands only if at least one piece of evidence for its last actual column is confirmed and supports that column
(section 6). Pure: no database, no model, no file.
"""
import copy
import re
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from .structures import redact
from . import periods as sheet_mod

CONFIRMED, REJECTED, CANNOT = "confirmed", "rejected", "cannot_check"
OUTCOMES = (CONFIRMED, REJECTED, CANNOT)

# Tolerances (section 5).
MONEY_TOLERANCE = 0.005        # money within 0.5 %
RATE_TOLERANCE = 0.01          # rates within 1 point; a rate is a fraction (0.045 is 4.5 %), the reader's unit decides, no scale is guessed
EXACT = 1e-9                   # counts and dates: exact

# --- The reasons of a rejection, as the design note lists them (section 5). Same wording every time, formatted from code. ---
R_VALUE = "Reading says {value}; cell {ref} holds {cell}."
R_PERIOD = "Reading says {period}; cell {ref} is the header for {header}."
R_COLUMN = "Reading cites {ref}; the sheet ends at column {last}."
R_VARIANCE = "Variance row {ref} does not equal actual minus budget in {n} of {m} periods."
R_PARTS = "Parts {refs} sum to {sum}; the reading names {ref} as their total, which holds {value}."
# --- The five cannot-check cases (section 5). ---
C_LAYOUT = "This describes the layout, not a value; no cell to open."
C_NO_TEXT = "Page {n} has no text layer; figure read from the image."
C_SCALE = "Cell {ref} holds {cell}; reading says {value}. Unit or scale differs; not compared."
C_NO_REF = "No cell reference given."
C_MASKED = "Depends on a name that was masked before reading."
R_FORMULA_ERROR = "cell {ref} holds {error}"
FORMULA_ERRORS = ("#REF!", "#DIV/0!", "#N/A", "#VALUE!", "#NAME?", "#NUM!", "#NULL!")      # a cell that holds exactly one of these is a formula error
PARTS_TOLERANCE = 0.01          # parts that add up to their total within 1 %; beyond it the total row is kept as read and the sums are an integrity finding
# --- Two more "nothing to compare against" cases (review of PR 205, F2): the arithmetic input the reading did not give. ---
C_VARIANCE_ROWS = "variance row without its two source rows"
C_SEGMENT_TOTAL = "segment row without its total row"
R_WEAK_EVIDENCE = "weak evidence only"
# A plan word in the name or title of another sheet of the file (George, 2026-11-06): with it, a row's end at the sheet's last period column is strong
# evidence (the actuals sit on a sheet of their own, which ends where they do).
TITLE_ROWS = 3                      # the rows at the top of a sheet that count as its title
WEAK_EVIDENCE = ("row_ends", "repeated_values", "round_values", "layout")      # kinds that show a pattern, not a plan or an actual label
C_NO_UNIT = "No unit given; not compared."
C_DATE_ONLY = "No value to compare; date only."
# --- Wording for rejections the note does not list (for the owner's approval; same discipline: a template, formatted from code). ---
R_ROW = "Reading cites {ref}; the sheet ends at row {last}."
R_NO_SHEET = "Reading cites sheet {name}; the file has no such sheet."
R_ROW_ENDS = "Reading says row {row} ends at column {column}; cell {ref} holds {cell}."
R_EQUALS = "Reading says {a} equals {b}; cell {ref} holds {cell} against {other}."
R_SHAPE = "Reading says {a} equals {b}; the ranges differ in shape."
R_CONTAINS = "Reading says cell {ref} contains \"{word}\"; it holds {cell}."
R_REPEATS = "Reading says {cells} repeats one value; cell {ref} holds {cell} against {first}."
R_ROUND = "Reading says {cells} are multiples of {multiple}; cell {ref} holds {cell}."
R_EMPTY = "Reading says {cells} is empty; cell {ref} holds {cell}."
R_NUMBER = "Reading says a number; cell {ref} holds {cell}."
R_ACTUAL_PLAN = "Figure marked {marked}; column {column} is {found} for this row."
NOTHING = "nothing"

# The plan words a `label_contains` piece of evidence may cite (budget, plan, forecast, reforecast, FC, estimate, projection, outlook, pro forma
# and their plain forms; and a year followed by E, F, B or P: FY24E, 2025F, 2024B). This list decides only whether a confirmed title supports the
# boundary (the word is read from the cell the reader cited, which must hold it: any word passes that test). It verifies the word the reader
# cited: it never finds a boundary, a column or a title of its own.
# The one list of plan words, used by both rules: a title that supports the boundary, and another sheet named or titled for a plan.
PLAN_WORDS = (r"(?<![^\W\d_])(?:budget(?:ed|s)?|plan(?:ned|s)?|(?:re)?forecast(?:s|ed)?|fc|estimates?|estimated|projections?|projected|"
              r"outlooks?|pro[\s-]?forma|aop|lrp)(?![^\W\d_])")
_YEAR_MARK = r"(?<![^\W_])(?:FY\s?\d{2}|(?:19|20)\d{2})[EFBP](?![^\W_])"      # a year followed by E, F, B or P: a title only, never a sheet's name
PLAN_WORD = re.compile("(?i)" + PLAN_WORDS)
PLAN_WORD_CHECK = re.compile("(?i)" + PLAN_WORDS + "|" + _YEAR_MARK)
_PLACEHOLDER = re.compile("|".join(re.escape(p) for p in redact.PLACEHOLDERS))
_NUMBER = re.compile(r"^\(?[-+−]?\s*[£$€¥]?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*%?\)?$|^[-+]?\.\d+$|^[-+]?\d+\.?\d*[eE][-+]?\d+$")
_RANGE = re.compile(r"^([A-Z]{1,3})([1-9]\d*)(?::([A-Z]{1,3})([1-9]\d*))?$")


# ---------------------------------------------------------------------------
# The cells the reader was sent
# ---------------------------------------------------------------------------
class SheetCells:
    """One sheet's cells as the reader was sent them (masked): text by (row, column)."""

    def __init__(self, name: str, cells: List[Dict]):
        self.name = name
        self.cells = {(c["row"], c["col"]): c["text"] for c in cells}
        self.spans = [(c["row"], c["col"], c["row"] + c.get("row_span", 1) - 1, c["col"] + c.get("col_span", 1) - 1)
                      for c in cells if c.get("row_span", 1) > 1 or c.get("col_span", 1) > 1]
        self.max_row = max((r for r, _ in self.cells), default=0)
        self.max_col = max((c for _, c in self.cells), default=0)
        self.dated: Dict = {}            # dated_headers, by header row and column span

    def get(self, row: int, col: int) -> Optional[str]:
        return self.cells.get((row, col))

    def span_end(self, row: int, col: int) -> int:
        """The last column of the merged cell that covers (row, col), or the column itself: a month header over its actual, budget and
        variance columns ends at the variance column."""
        for r1, c1, r2, c2 in self.spans:
            if r1 <= row <= r2 and c1 <= col <= c2:
                return c2
        return col

    def header(self, row: int, col: int) -> Optional[str]:
        """The text a header cell shows: its own, or that of the merged cell that covers it (a month over its three columns, a quarter over
        its three months)."""
        own = self.cells.get((row, col))
        if own is not None and own.strip():
            return own
        for r1, c1, r2, c2 in self.spans:
            if r1 <= row <= r2 and c1 <= col <= c2:
                return self.cells.get((r1, c1))
        return own


class Cells:
    """The cells of a file: parse the masked reading text the gateway sent, so the checks open exactly what the reader read."""

    def __init__(self, text: str):
        self.sheets = {s["name"]: SheetCells(s["name"], s["cells"]) for s in (redact.parse_reading_text(text) or [])}

    def sheet(self, name: str) -> Optional[SheetCells]:
        return self.sheets.get(name)


def to_number(text: Optional[str]) -> Optional[float]:
    """A cell's text as a number, or None: plain decimals, thousands commas, a currency symbol, a minus or brackets, a percent (as a
    fraction)."""
    t = (text or "").strip()
    if not t or not _NUMBER.match(t):
        return None
    negative = t.startswith("(") or t[:1] in "-−"
    percent = t.endswith("%") or t.endswith("%)")
    body = re.sub(r"[()£$€¥%,\s+−-]", "", t)
    try:
        value = float(body)
    except ValueError:
        return None
    value = -value if negative else value
    return value / 100 if percent else value


def shown(value: Optional[float]) -> str:
    """A number as a reason writes it: no exponent, no trailing zero."""
    return redact.number_text(value) if value is not None else NOTHING


def cell_shown(text: Optional[str]) -> str:
    return NOTHING if text is None or not str(text).strip() else str(text).strip()


def ref_of(row: int, col: int) -> str:
    return redact.cell_ref(row, col)


def parse_ref(ref: Optional[str]) -> Optional[Tuple[int, int]]:
    return redact.split_ref(ref or "")


def parse_range(rng: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    """(row1, col1, row2, col2) of "C5" or "C5:N5", or None."""
    m = _RANGE.match(rng or "")
    if not m:
        return None
    r1, c1 = int(m.group(2)), redact.col_number(m.group(1))
    r2, c2 = (int(m.group(4)), redact.col_number(m.group(3))) if m.group(3) else (r1, c1)
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def range_cells(rng: Tuple[int, int, int, int]) -> List[Tuple[int, int]]:
    r1, c1, r2, c2 = rng
    return [(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]


def _outside(sheet: SheetCells, row: int, col: int) -> Optional[str]:
    """The rejection reason when a cited cell lies past the last row or column of the sheet, else None."""
    if col > sheet.max_col:
        return R_COLUMN.format(ref=ref_of(row, col), last=redact.col_letters(sheet.max_col))
    if row > sheet.max_row:
        return R_ROW.format(ref=ref_of(row, col), last=sheet.max_row)
    return None


def _masked(text: Optional[str]) -> bool:
    return bool(text and _PLACEHOLDER.search(text))


def _item(key: str, kind: str, outcome: str, reason: Optional[str] = None, sheet: Optional[str] = None, cell: Optional[str] = None,
          **extra) -> Dict:
    return {"key": key, "kind": kind, "outcome": outcome, "reason": reason, "sheet": sheet, "cell": cell, **extra}


# ---------------------------------------------------------------------------
# Periods: the header of a column, in the form the reading wrote its period
# ---------------------------------------------------------------------------
_MONTH_FORM = re.compile(r"^\d{4}-\d{2}$")
_QUARTER_FORM = re.compile(r"^\d{4}-Q[1-4]$")
_YEAR_FORM = re.compile(r"^\d{4}$")


def header_period(text: Optional[str], fye: int = 12) -> Optional[Dict]:
    """The period a header cell names ({"grain", "year", "start", "end", "tag"}), or None. An ISO date is a date."""
    t = (text or "").strip()
    if not t:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        try:
            return sheet_mod.period_of(date.fromisoformat(t), fye)
        except ValueError:
            return None
    if _MONTH_FORM.match(t):
        return sheet_mod.period_of(date(int(t[:4]), int(t[5:7]), 1), fye) if 1 <= int(t[5:7]) <= 12 else None
    return sheet_mod.period_of(t, fye)


def _quarter_label(end: str) -> str:
    return f"{end[:4]}-Q{(int(end[5:7]) - 1) // 3 + 1}"


def period_in_form(period: Optional[Dict], like: str) -> Optional[str]:
    """A parsed header period written in the form the reading used for its period: a month (2024-06), a quarter (2024-Q2) or a year."""
    if not period or not period.get("end"):
        return None
    if _QUARTER_FORM.match(like):
        return _quarter_label(period["end"])
    if _YEAR_FORM.match(like):
        return str(period["year"])
    return period["end"]


_MONTH_NAMES = {name: n for n, names in enumerate((("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
                                                       ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
                                                       ("dec", "december")), 1) for name in names}


def _month_word(text: Optional[str]) -> Optional[int]:
    """The month number of a header that is a month's name alone ("Nov", "November", "Nov."), else None."""
    return _MONTH_NAMES.get((text or "").strip().rstrip(".").lower())


def _year_cell(text: Optional[str], fye: int) -> Optional[int]:
    """The year a cell states when it is a year and nothing else ("2024", "FY2024", "FY24"), else None."""
    found = header_period(text, fye)
    return found["year"] if found and found["grain"] == "year" and found["tag"] is None else None


def _months_between(start: str, end: str) -> List[str]:
    """The months from `start` to `end` (YYYY-MM), both included."""
    k, stop = int(start[:4]) * 12 + int(start[5:]) - 1, int(end[:4]) * 12 + int(end[5:]) - 1
    return [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(k, stop + 1)]


_CLOSERS = ("quarter", "half", "year")      # the headers that close a block of year-less months: "Q4 2023", "H1 2023", "TOTAL 2023"


def _title_year(sheet: "SheetCells", row: int, col: int, block_start: int, fye: int) -> Optional[int]:
    """The year title above a block of months: a year cell in the rows above the header, over the month's own column (a merged title counts) or in
    a column to its left that is still inside the block. Never a year of another block."""
    for r in range(row - 1, 0, -1):
        for c in range(col, block_start - 1, -1):
            year = _year_cell(sheet.header(r, c) if c == col else sheet.get(r, c), fye)
            if year:
                return year
    return None


def dated_headers(sheet: "SheetCells", row: int, first_col: int, last_col: int, fye: int = 12) -> Tuple[Dict[int, Dict], List[Tuple[int, str]]]:
    """({column: month period}, [(column, text)]) of the year-less month headers of a header row ("December"). A month takes its year from the
    quarter, half or year header that closes its block (the first one to its right with no dated month between: "Q4 2023", "TOTAL 2023"), else from
    a year title above its block; never from the year seen in another block or from a date-typed header elsewhere. Periods must increase left to
    right: a month that goes back (or repeats) is undated, as is one the closing header does not contain, or one no header or title dates. An
    undated month is in the second list and is read by nothing."""
    key = (row, first_col, last_col, fye)
    if key in sheet.dated:
        return sheet.dated[key]
    heads = {c: sheet.header(row, c) for c in range(first_col, last_col + 1)}
    explicit = {c: header_period(t, fye) for c, t in heads.items()}
    dated: Dict[int, Dict] = {}
    undated: List[Tuple[int, str]] = []
    last_ym, block_start = None, first_col
    lead = None                 # (column, year) of a year cell that opens the header row's months: "2024 | January | February ..."
    for c in range(first_col, last_col + 1):
        found = explicit[c]
        if found is not None:
            if found["grain"] == "month":
                last_ym, block_start = found["start"], c + 1
            elif found["grain"] in _CLOSERS:
                if found["grain"] == "year" and found["tag"] is None and last_ym is None and lead is None and c + 1 <= last_col:
                    lead = (c, found["year"])
                block_start = c + 1
            continue
        month = _month_word(heads[c])
        if month is None:
            continue
        closer = None
        for d in range(c + 1, last_col + 1):
            other = explicit[d]
            if other is None or other["start"] is None:
                continue
            if other["grain"] == "month":
                break
            if other["grain"] in _CLOSERS:
                closer = other
                break
        ym = None
        if closer is not None:
            ym = next((p for p in _months_between(closer["start"], closer["end"]) if int(p[5:]) == month), None)
        else:
            year = _title_year(sheet, row, c, block_start, fye) or (lead[1] if lead and lead[0] == block_start - 1 else None)
            if year:
                ym = f"{year - (1 if month > fye else 0):04d}-{month:02d}"
        if ym is None or (last_ym is not None and ym <= last_ym):
            undated.append((c, (heads[c] or "").strip()))
            continue
        dated[c] = sheet_mod.period_of(date(int(ym[:4]), month, 1), fye)
        last_ym = ym
    sheet.dated[key] = (dated, undated)
    return dated, undated


def resolve_header(sheet: "SheetCells", row: int, col: int, fye: int = 12, down: bool = False) -> Optional[Dict]:
    """The period a header cell names, as `header_period` reads it, else (a month's name alone) the month `dated_headers` gives it. `down`: the
    periods run down the sheet, the header is a row label and only a year title above it can date it."""
    text = sheet.header(row, col)
    found = header_period(text, fye)
    if found or _month_word(text) is None:
        return found
    return dated_headers(sheet, row, col if down else 1, col if down else max(sheet.max_col, col), fye)[0].get(col)


def same_period(found: Optional[Dict], written: Optional[str], fye: int = 12) -> bool:
    """Whether the period a header names is the period the reading wrote, whatever the form it was written in: "2024-Q3" and "Q3 2024" are one quarter."""
    if not found or not written:
        return False
    if period_in_form(found, written) == written:
        return True
    other = header_period(written, fye)
    return bool(other) and (other["grain"], other["start"], other["end"]) == (found["grain"], found["start"], found["end"])


def describe_header(text: Optional[str], like: str, fye: int) -> str:
    """The header period for a reason: in the reading's own form, or the header's own text when it names no period."""
    shown_period = period_in_form(header_period(text, fye), like)
    return shown_period or cell_shown(text)


# ---------------------------------------------------------------------------
# One figure: the value cell, then the period of its column
# ---------------------------------------------------------------------------
def _scale_check(reading: float, cell: float) -> bool:
    """True when the reading would match the cell within the money tolerance if it were written in another power of ten (thousands
    against units, a percent against a fraction): the unit or scale differs, not the value."""
    if reading == 0 or cell == 0:
        return False
    return any(compare("money", reading * 10.0 ** power, cell) for power in (-6, -3, -2, 2, 3, 6))


def compare(unit: str, reading: float, cell: float) -> bool:
    """The tolerance of a unit (section 5)."""
    if unit == "rate":
        return abs(reading - cell) <= RATE_TOLERANCE + EXACT        # a reading on another scale than its cell is not compared: C_SCALE (_scale_check)
    if unit == "count":
        return abs(reading - cell) <= EXACT
    return abs(reading - cell) <= MONEY_TOLERANCE * abs(cell) + EXACT


def _clash(figure: Dict, pos: Tuple[int, int], smap: Dict, boundaries: Dict[str, int]) -> Optional[str]:
    """The rejection reason when a figure's actual/plan disagrees with the boundary of its row (a column after the boundary marked actual,
    a column up to it marked plan), else None. The boundary is the row's own, else the sheet's last actual column when its month stands.
    Only "actual" and "plan" are compared. A row that holds actual, budget and variance side by side per period has no one boundary."""
    marked = figure.get("actual_plan")
    if marked not in ("actual", "plan"):
        return None
    row = next((r for r in smap.get("rows") or [] if r["row"] == pos[0] and not r.get("by_column")), None)
    if row is None or row.get("variance_columns"):
        return None
    boundary = redact.col_number(row["boundary_col"]) if row.get("boundary_col") else boundaries.get(smap["sheet"])
    if boundary is None:
        return None
    found = "actual" if pos[1] <= boundary else "plan"
    if found == marked:
        return None
    return R_ACTUAL_PLAN.format(marked=marked, column=redact.col_letters(pos[1]), found=found)


def check_figure(index: int, figure: Dict, cells: Cells, sheet_maps: Dict[str, Dict], fye: int, boundaries: Optional[Dict[str, int]] = None) -> Dict:
    source = figure.get("source") or {}
    sheet_name, cell_ref = source.get("sheet"), source.get("cell")
    key = f"figure:{sheet_name}:{cell_ref}:{figure.get('metric')}" if cell_ref else f"figure:#{index}"
    base = {"key": key, "kind": "figure", "sheet": sheet_name, "cell": cell_ref, "metric": figure.get("metric"), "value": figure.get("value")}
    if figure.get("value") is None and figure.get("period") and not cell_ref:
        return {**base, "outcome": CANNOT, "reason": C_DATE_ONLY}
    if source.get("page") is not None and not cell_ref:
        if source.get("text_layer") is False:
            return {**base, "outcome": CANNOT, "reason": C_NO_TEXT.format(n=source["page"])}
        return {**base, "outcome": CANNOT, "reason": C_NO_REF}
    pos = parse_ref(cell_ref)
    if not cell_ref or pos is None or figure.get("value") is None:
        return {**base, "outcome": CANNOT, "reason": C_NO_REF if not cell_ref or pos is None else C_LAYOUT}
    sheet = cells.sheet(sheet_name) if sheet_name else None
    if sheet is None:
        return {**base, "outcome": REJECTED, "reason": R_NO_SHEET.format(name=sheet_name or "(none)")}
    row, col = pos
    past = _outside(sheet, row, col)
    if past:
        return {**base, "outcome": REJECTED, "reason": past}
    text = sheet.get(row, col)
    reading = figure["value"]
    if _masked(text):
        return {**base, "outcome": CANNOT, "reason": C_MASKED}
    number = to_number(text)
    base["found_value"] = number            # what the code found when it opened the cell (the register's "Cell holds")
    unit = figure.get("unit")
    if (text or "").strip() in FORMULA_ERRORS:        # the file's own error, not a disagreement: counted in the formula-error flag
        return {**base, "outcome": CANNOT, "reason": R_FORMULA_ERROR.format(ref=cell_ref, error=text.strip()), "formula_error": text.strip()}
    if number is None:
        return {**base, "outcome": REJECTED, "reason": R_VALUE.format(value=shown(reading), ref=cell_ref, cell=cell_shown(text))}
    if unit not in ("money", "count", "rate"):
        return {**base, "outcome": CANNOT, "reason": C_NO_UNIT}          # the reader states the unit; the metric name does not choose it
    dropped_percent = unit == "rate" and "%" in (text or "") and compare(unit, reading, number * 100)        # the reading dropped the % sign: 93 for "93%"
    if not dropped_percent and not compare(unit, reading, number):
        if _scale_check(reading, number):
            return {**base, "outcome": CANNOT, "reason": C_SCALE.format(ref=cell_ref, cell=cell_shown(text), value=shown(reading))}
        return {**base, "outcome": REJECTED, "reason": R_VALUE.format(value=shown(reading), ref=cell_ref, cell=cell_shown(text))}
    period, smap = figure.get("period"), sheet_maps.get(sheet_name)
    if period and smap:
        down = periods_down(smap)
        head_row, head_col = (row, redact.col_number(smap["label_col"])) if down else (smap["header_row"], col)
        head_ref = ref_of(head_row, head_col)
        head_text = sheet.header(head_row, head_col)
        header = resolve_header(sheet, head_row, head_col, fye, down)
        found = period if same_period(header, period, fye) else period_in_form(header, period)
        base["found_period"] = found
        if found != period:
            return {**base, "outcome": REJECTED, "reason": R_PERIOD.format(period=period, ref=head_ref, header=describe_header(head_text, period, fye))}
    clash = _clash(figure, pos, smap, boundaries or {}) if smap else None
    if clash:
        return {**base, "outcome": REJECTED, "reason": clash}
    return {**base, "outcome": CONFIRMED, "reason": None}


# ---------------------------------------------------------------------------
# One row, and the structural claims of rows: variance and parts
# ---------------------------------------------------------------------------
def periods_down(smap: Dict) -> bool:
    """True when the periods run down the sheet (one row per month, a metric per column): every mapped row is a column of figures
    (`by_column`), and the period of a figure is the label-column cell of its own row."""
    rows = smap.get("rows") or []
    return bool(rows) and all(r.get("by_column") for r in rows)


def _period_cols(smap: Dict) -> List[int]:
    return list(range(redact.col_number(smap["first_period_col"]), redact.col_number(smap["last_period_col"]) + 1))


def numbers_expected_check(row: Dict) -> bool:
    """Whether the reading's own claim about a row means its cells are numbers: it gave a unit, or a role that is a measure (every role but
    "other"). The reader made the claim; a text cell in the range then contradicts it."""
    return row.get("unit") in ("money", "count", "rate") or row.get("role") not in ("other", None)


def check_row(smap: Dict, row: Dict, sheet: SheetCells) -> Dict:
    key = f"row:{smap['sheet']}:{row['row']}"
    base = {"key": key, "kind": "row", "sheet": smap["sheet"], "cell": row.get("label_cell") or row.get("cells"), "row": row["row"],
            "role": row.get("role")}
    cited = [parse_ref(row["label_cell"])] if row.get("label_cell") else []
    rng = parse_range(row.get("cells"))
    if rng is None and not cited:
        return {**base, "outcome": CANNOT, "reason": C_LAYOUT}
    for pos in cited + ([(rng[0], rng[1]), (rng[2], rng[3])] if rng else []):
        past = _outside(sheet, *pos)
        if past:
            return {**base, "outcome": REJECTED, "reason": past}
    if rng is None:
        return {**base, "outcome": CANNOT, "reason": C_LAYOUT}
    numeric = numbers_expected_check(row)
    seen = 0
    errors: List[Tuple[str, str]] = []
    for r, c in range_cells(rng):
        text = sheet.get(r, c)
        if text is None or not text.strip():
            continue
        if _masked(text):
            return {**base, "outcome": CANNOT, "reason": C_MASKED}
        if text.strip() in FORMULA_ERRORS:
            errors.append((ref_of(r, c), text.strip()))        # a formula error is the file's, counted in its flag: not a text cell
            continue
        if numeric and to_number(text) is None:
            return {**base, "outcome": REJECTED, "reason": R_NUMBER.format(ref=ref_of(r, c), cell=cell_shown(text))}
        seen += 1
    if errors:
        base["formula_errors"] = [{"cell": ref, "error": err} for ref, err in errors]
    if numeric and seen == 0 and errors:
        return {**base, "outcome": CANNOT, "reason": R_FORMULA_ERROR.format(ref=errors[0][0], error=errors[0][1])}
    if numeric and seen == 0:
        return {**base, "outcome": REJECTED, "reason": R_NUMBER.format(ref=ref_of(rng[0], rng[1]), cell=NOTHING)}
    if row.get("role") == "variance" and not row.get("variance_of") and not row.get("variance_columns"):
        return {**base, "outcome": CANNOT, "reason": C_VARIANCE_ROWS}
    if row.get("segment") and not row.get("parent_row"):
        return {**base, "outcome": CANNOT, "reason": C_SEGMENT_TOTAL}
    return {**base, "outcome": CONFIRMED, "reason": None}


def _values_in_column(sheet: SheetCells, rows: List[int], col: int) -> Optional[List[float]]:
    out = []
    for r in rows:
        n = to_number(sheet.get(r, col))
        if n is None:
            return None
        out.append(n)
    return out


def _variance_tolerated(variance: float, actual: float, plan: float) -> bool:
    return abs(variance - (actual - plan)) <= MONEY_TOLERANCE * max(abs(actual), abs(plan)) + EXACT


def check_variance(smap: Dict, row: Dict, sheet: SheetCells) -> Dict:
    """A variance equals actual minus plan, period by period, over the periods where all three hold a number: a variance row against its
    two source rows (`variance_of`), or the variance columns of a row against its actual and plan columns (`variance_columns`: actual |
    budget | variance per period)."""
    key = f"variance:{smap['sheet']}:{row['row']}"
    ref = row.get("label_cell") or row["row"]
    compared = wrong = 0
    v, vc = row.get("variance_of"), row.get("variance_columns")
    if v:
        for col in _period_cols(smap):
            vals = _values_in_column(sheet, [row["row"], v["actual_row"], v["plan_row"]], col)
            if vals is None:
                continue
            compared += 1
            wrong += not _variance_tolerated(*vals)
    if vc:
        first = [redact.col_number(vc[k]) for k in ("variance", "actual", "plan")]
        ref = ref_of(row["row"], first[0])
        for col in range(first[0], max(sheet.max_col, redact.col_number(smap["last_period_col"])) + 1, vc["step"]):
            vals = [to_number(sheet.get(row["row"], col + c - first[0])) for c in first]
            if None in vals:
                continue
            compared += 1
            wrong += not _variance_tolerated(*vals)
    base = {"key": key, "kind": "variance", "sheet": smap["sheet"], "cell": row.get("cells"), "row": row["row"]}
    if compared == 0:
        return {**base, "outcome": CANNOT, "reason": C_LAYOUT}
    if wrong:
        return {**base, "outcome": REJECTED, "reason": R_VARIANCE.format(ref=ref, n=wrong, m=compared)}
    return {**base, "outcome": CONFIRMED, "reason": None}


def check_parts(smap: Dict, parent: int, children: List[Dict], parent_row: Optional[Dict], sheet: SheetCells) -> Dict:
    """Parts that name a row as their total sum to it, column by column, within PARTS_TOLERANCE. Absolute values are compared: a total with the
    opposite sign to its parts (costs printed as negatives under positive parts) is not a disagreement. Parts that do not add up are no
    rejection: the total row stays as read and the first column that does not add up comes back as `mismatch` (sheet, total row and cell,
    total, parts sum, difference and its share of the total), an integrity finding with no re-read and no card."""
    key = f"parts:{smap['sheet']}:{parent}"
    base = {"key": key, "kind": "parts", "sheet": smap["sheet"], "cell": (parent_row or {}).get("cells"), "row": parent}
    part_rows = [c["row"] for c in children]
    compared = 0
    for col in _period_cols(smap):
        vals = _values_in_column(sheet, part_rows + [parent], col)
        if vals is None:
            continue
        compared += 1
        total, parts = abs(vals[-1]), abs(sum(vals[:-1]))
        if abs(parts - total) > PARTS_TOLERANCE * total + EXACT:
            diff = abs(total - parts)
            return {**base, "outcome": CONFIRMED, "reason": None,
                    "mismatch": {"sheet": smap["sheet"], "row": parent, "cell": ref_of(parent, col), "column": redact.col_letters(col),
                                 "parts": [ref_of(r, col) for r in part_rows], "total": total, "parts_sum": parts, "difference": diff,
                                 "pct": diff / total if total else 1.0}}
    return {**base, "outcome": CONFIRMED if compared else CANNOT, "reason": None if compared else C_LAYOUT}


# ---------------------------------------------------------------------------
# The evidence for the last actual column
# ---------------------------------------------------------------------------
def _empty(text: Optional[str]) -> bool:
    return text is None or not text.strip()


def check_evidence(smap: Dict, index: int, piece: Dict, sheet: SheetCells, boundary_col: int) -> Dict:
    """One piece of evidence: the fact it states is opened and tested. `supports` is whether a confirmed fact points at this boundary."""
    key = f"evidence:{smap['sheet']}:{index}"
    kind = piece["kind"]
    base = {"key": key, "kind": "evidence", "evidence_kind": kind, "sheet": smap["sheet"], "cell": None, "text": piece.get("text"), "supports": False}
    last_col = redact.col_number(smap["last_period_col"])
    next_col = sheet.span_end(smap["header_row"], boundary_col) + 1      # the column right after the boundary period's header

    def rejected(reason, cell=None):
        return {**base, "outcome": REJECTED, "reason": reason, "cell": cell}

    def confirmed(supports, cell=None):
        return {**base, "outcome": CONFIRMED, "reason": None, "supports": supports, "cell": cell}

    if kind == "layout":
        return {**base, "outcome": CANNOT, "reason": C_LAYOUT}
    if kind == "row_ends":
        if not piece.get("row") or not piece.get("column"):
            return {**base, "outcome": CANNOT, "reason": C_NO_REF}
        row, col = piece["row"], redact.col_number(piece["column"])
        past = _outside(sheet, row, col)
        if past:
            return rejected(past)
        here = sheet.get(row, col)
        if _empty(here):
            return rejected(R_ROW_ENDS.format(row=row, column=piece["column"], ref=ref_of(row, col), cell=NOTHING), ref_of(row, col))
        for c in range(col + 1, max(last_col, sheet.max_col) + 1):
            if not _empty(sheet.get(row, c)):
                return rejected(R_ROW_ENDS.format(row=row, column=piece["column"], ref=ref_of(row, c), cell=cell_shown(sheet.get(row, c))),
                                ref_of(row, c))
        return confirmed(col == boundary_col, ref_of(row, col))
    if kind == "label_contains":
        pos = parse_ref(piece.get("cell"))
        if pos is None or not piece.get("word"):
            return {**base, "outcome": CANNOT, "reason": C_NO_REF}
        past = _outside(sheet, *pos)
        if past:
            return rejected(past)
        text = sheet.get(*pos)
        if _masked(text):
            return {**base, "outcome": CANNOT, "reason": C_MASKED, "cell": piece["cell"]}
        if " ".join(piece["word"].lower().split()) not in " ".join((text or "").lower().split()):
            return rejected(R_CONTAINS.format(ref=piece["cell"], word=piece["word"], cell=cell_shown(text)), piece["cell"])
        row, col = pos
        # A title points at one column, the one right after the boundary period (a merged title holds its text in its first column). A row label points at none.
        above = row <= smap["header_row"] and col == boundary_col + 1
        return confirmed(bool(PLAN_WORD_CHECK.search(piece["word"])) and above, piece["cell"])
    rng = parse_range(piece.get("cells"))
    if rng is None:
        return {**base, "outcome": CANNOT, "reason": C_NO_REF}
    for pos in ((rng[0], rng[1]), (rng[2], rng[3])):
        past = _outside(sheet, *pos)
        if past:
            return rejected(past)
    after = rng[1] == next_col                                         # the range starts in the column right after the boundary period
    if kind == "equals_range":
        other = parse_range(piece.get("other_cells"))
        if other is None:
            return {**base, "outcome": CANNOT, "reason": C_NO_REF}
        for pos in ((other[0], other[1]), (other[2], other[3])):
            past = _outside(sheet, *pos)
            if past:
                return rejected(past)
        a, b = range_cells(rng), range_cells(other)
        if (rng[2] - rng[0], rng[3] - rng[1]) != (other[2] - other[0], other[3] - other[1]):
            return rejected(R_SHAPE.format(a=piece["cells"], b=piece["other_cells"]))
        for (ra, ca), (rb, cb) in zip(a, b):
            ta, tb = sheet.get(ra, ca), sheet.get(rb, cb)
            na, nb = to_number(ta), to_number(tb)
            if na is None or nb is None or not compare("money", na, nb):
                return rejected(R_EQUALS.format(a=piece["cells"], b=piece["other_cells"], ref=ref_of(ra, ca), cell=cell_shown(ta),
                                                other=cell_shown(tb)), ref_of(ra, ca))
        return confirmed(after, piece["cells"])
    values = [(r, c, sheet.get(r, c)) for r, c in range_cells(rng) if not _empty(sheet.get(r, c))]
    if kind == "range_empty":
        if values:
            return rejected(R_EMPTY.format(cells=piece["cells"], ref=ref_of(values[0][0], values[0][1]), cell=cell_shown(values[0][2])),
                            ref_of(values[0][0], values[0][1]))
        return confirmed(after, piece["cells"])
    if kind == "repeated_values":
        first = values[0][2] if values else None
        for r, c, t in values[1:]:
            if to_number(t) is None or to_number(first) is None or abs(to_number(t) - to_number(first)) > EXACT:
                return rejected(R_REPEATS.format(cells=piece["cells"], ref=ref_of(r, c), cell=cell_shown(t), first=cell_shown(first)), ref_of(r, c))
        if len(values) < 2:
            return rejected(R_REPEATS.format(cells=piece["cells"], ref=ref_of(rng[0], rng[1]), cell=cell_shown(first), first=NOTHING),
                            ref_of(rng[0], rng[1]))
        return confirmed(after, piece["cells"])
    if kind == "round_values":
        multiple = piece.get("multiple")
        if not multiple:
            return {**base, "outcome": CANNOT, "reason": C_NO_REF}
        for r, c, t in values:
            n = to_number(t)
            if n is None or abs(n / multiple - round(n / multiple)) > 1e-9:
                return rejected(R_ROUND.format(cells=piece["cells"], multiple=shown(multiple), ref=ref_of(r, c), cell=cell_shown(t)), ref_of(r, c))
        if len(values) < 2:
            return rejected(R_ROUND.format(cells=piece["cells"], multiple=shown(multiple), ref=ref_of(rng[0], rng[1]),
                                           cell=cell_shown(values[0][2]) if values else NOTHING), ref_of(rng[0], rng[1]))
        return confirmed(after, piece["cells"])
    return {**base, "outcome": CANNOT, "reason": C_LAYOUT}


def _plan_sheet_named(name: str, cells: Optional["Cells"], others: bool = True) -> Optional[str]:
    """The name of the first sheet with a plan word in its name or in a text cell of its title rows: a sheet other than `name` (`others`), or
    `name` alone (not `others`). None when there is none."""
    for other, sheet in (cells.sheets if cells else {}).items():
        if (other == name) == others:
            continue
        title = [t for (r, _), t in sheet.cells.items() if r <= TITLE_ROWS and to_number(t) is None]
        if PLAN_WORD.search(other) or any(PLAN_WORD.search(t) for t in title):
            return other
    return None


def _plan_sheet_elsewhere(name: str, cells: Optional["Cells"]) -> bool:
    """Whether a sheet other than `name` has a plan word in its name or in a text cell of its title rows."""
    return _plan_sheet_named(name, cells) is not None


_FORM_OF = {"monthly": "2000-01", "quarterly": "2000-Q1", "yearly": "2000"}
R_BY_CODE = "Every mapped row on {sheet} ends at column {column}, and sheet {plan} is the plan: last actual column set by code."


def plan_fallback(fmap: Dict, cells: "Cells", fye: int = 12) -> Dict:
    """A copy of the file map in which a sheet whose reading has no last actual column gets one from code (George, 2026-11-06). The rule: another
    sheet of the file has a plan word (PLAN_WORDS) in its name or its first three rows, this sheet has none, and every mapped row of this sheet
    that holds values ends at the sheet's last period column. The column is that column; its period is what its header names; the one piece of
    evidence is a row_ends that names the plan sheet and says it was set by code. The checks then open it like any other piece. A sheet that
    does not meet the rule, or whose header names no period, is left as it was."""
    out = copy.deepcopy(fmap)
    for smap in out.get("sheets") or []:
        sheet = cells.sheet(smap["sheet"])
        if smap.get("last_actual") or sheet is None or periods_down(smap) or _plan_sheet_named(smap["sheet"], cells, others=False):
            continue
        plan = _plan_sheet_named(smap["sheet"], cells)
        last = redact.col_number(smap["last_period_col"])
        ends = {}
        for row in smap.get("rows") or []:
            cols = [c for (r, c), t in sheet.cells.items() if r == row["row"] and c > redact.col_number(smap["label_col"]) and not _empty(t)]
            if cols:
                ends[row["row"]] = max(cols)
        parsed = header_period(sheet.header(smap["header_row"], last), fye)
        if not plan or not ends or any(c != last for c in ends.values()) or not parsed or not parsed.get("end"):
            continue
        text = R_BY_CODE.format(sheet=smap["sheet"], column=smap["last_period_col"], plan=plan)[:300]    # the schema's MAP_TEXT_MAX
        smap["last_actual"] = {"column": smap["last_period_col"], "period": period_in_form(parsed, _FORM_OF.get(smap["granularity"], "2000-01")),
                               "evidence": [{"kind": "row_ends", "text": text, "row": min(ends), "column": smap["last_period_col"], "cell": None,
                                             "cells": None, "other_cells": None, "word": None, "multiple": None}]}
    return out


def _weak(smap: Dict, piece: Dict, cells: Optional["Cells"]) -> bool:
    """Whether a piece of evidence for the last actual column shows a pattern only. A row's end is strong when it ends at the sheet's last period
    column and another sheet of the file is named or titled for a plan; every other row end, and the other pattern kinds, are weak."""
    if piece["kind"] not in WEAK_EVIDENCE:
        return False
    if piece["kind"] == "row_ends":
        return not (piece.get("column") == smap["last_period_col"] and _plan_sheet_elsewhere(smap["sheet"], cells))
    return True


def check_last_actual(smap: Dict, sheet: SheetCells, fye: int, cells: Optional["Cells"] = None) -> Tuple[List[Dict], Optional[Dict]]:
    """(the items of the last actual column and its evidence, the file's month for this sheet or None).

    The column's header is opened and must be the period the reading names; the month stands only if at least one piece of evidence is
    confirmed and supports that column."""
    la = smap.get("last_actual")
    if not la:
        return [], None
    key = f"last_actual:{smap['sheet']}"
    col = redact.col_number(la["column"])
    head_ref = ref_of(smap["header_row"], col)
    items: List[Dict] = []
    past = _outside(sheet, smap["header_row"], col)
    head_text = sheet.header(smap["header_row"], col)
    parsed = header_period(head_text, fye)
    if past:
        items.append(_item(key, "last_actual", REJECTED, past, smap["sheet"], head_ref))
    elif period_in_form(parsed, la["period"]) != la["period"]:
        items.append(_item(key, "last_actual", REJECTED, R_PERIOD.format(period=la["period"], ref=head_ref,
                                                                       header=describe_header(head_text, la["period"], fye)), smap["sheet"], head_ref))
    else:
        items.append(_item(key, "last_actual", CONFIRMED, None, smap["sheet"], head_ref))
    pieces = [check_evidence(smap, i, p, sheet, col) for i, p in enumerate(la["evidence"])]
    if pieces and items[0]["outcome"] == CONFIRMED and all(_weak(smap, p, cells) for p in la["evidence"]):
        # Nothing but a pattern in the cells (a row's end, repeated or round values, a layout remark): the boundary is not evidenced (prompt v5).
        items[0] = _item(key, "last_actual", REJECTED, R_WEAK_EVIDENCE, smap["sheet"], head_ref)
    items += pieces
    standing = [p for p in pieces if p["outcome"] == CONFIRMED and p["supports"]]
    if items[0]["outcome"] != CONFIRMED or not standing or not parsed or not parsed.get("end"):
        return items, None
    return items, {"sheet": smap["sheet"], "month": parsed["end"], "column": la["column"], "header": cell_shown(head_text),
                   "evidence": standing[0]["text"], "confirmed": len(standing)}


# ---------------------------------------------------------------------------
# The whole map
# ---------------------------------------------------------------------------
_CURRENCY_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$", "JPY": "¥"}


def check_currency(smap: Dict, sheet: SheetCells) -> Optional[Dict]:
    code = smap.get("currency")
    if not code:
        return None
    key = f"currency:{smap['sheet']}"
    if not smap.get("currency_cell"):
        return _item(key, "currency", CANNOT, C_NO_REF, smap["sheet"])
    pos = parse_ref(smap["currency_cell"])
    past = _outside(sheet, *pos)
    if past:
        return _item(key, "currency", REJECTED, past, smap["sheet"], smap["currency_cell"])
    text = sheet.get(*pos)
    if _masked(text):
        return _item(key, "currency", CANNOT, C_MASKED, smap["sheet"], smap["currency_cell"])
    if re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])", text or "", re.I) or (_CURRENCY_SYMBOLS.get(code) and _CURRENCY_SYMBOLS[code] in (text or "")):
        return _item(key, "currency", CONFIRMED, None, smap["sheet"], smap["currency_cell"])
    return _item(key, "currency", REJECTED, R_VALUE.format(value=code, ref=smap["currency_cell"], cell=cell_shown(text)), smap["sheet"],
                 smap["currency_cell"])


def check_periods(smap: Dict, sheet: SheetCells, fye: int) -> Dict:
    """The first and last period columns: both headers are opened and each must name a period."""
    key = f"periods:{smap['sheet']}"
    if periods_down(smap):
        # Periods down the sheet: the first and last cells of the first mapped column's range, in the label column, each name a period.
        rng = parse_range(smap["rows"][0].get("cells"))
        if rng is None:
            return _item(key, "periods", CANNOT, C_NO_REF, smap["sheet"])
        for row_ in (rng[0], rng[2]):
            ref = ref_of(row_, redact.col_number(smap["label_col"]))
            past = _outside(sheet, row_, redact.col_number(smap["label_col"]))
            if past:
                return _item(key, "periods", REJECTED, past, smap["sheet"], ref)
            text = sheet.header(row_, redact.col_number(smap["label_col"]))
            if header_period(text, fye) is None:
                return _item(key, "periods", REJECTED, R_PERIOD.format(period=smap["granularity"], ref=ref, header=cell_shown(text)),
                             smap["sheet"], ref)
        return _item(key, "periods", CONFIRMED, None, smap["sheet"])
    for letters in (smap["first_period_col"], smap["last_period_col"]):
        col = redact.col_number(letters)
        ref = ref_of(smap["header_row"], col)
        past = _outside(sheet, smap["header_row"], col)
        if past:
            return _item(key, "periods", REJECTED, past, smap["sheet"], ref)
        text = sheet.header(smap["header_row"], col)
        if header_period(text, fye) is None:
            return _item(key, "periods", REJECTED, R_PERIOD.format(period=smap["granularity"], ref=ref, header=cell_shown(text)), smap["sheet"], ref)
    return _item(key, "periods", CONFIRMED, None, smap["sheet"])


def check_map(cells: Cells, fmap: Dict, fye: int = 12) -> Dict:
    """Every item of the map checked against the cells: {"items": [...], "counts": {...}, "months": [per-sheet confirmed months]}."""
    items: List[Dict] = []
    totals: List[Dict] = []                               # parts that do not add up to their total: findings, not items
    months: List[Dict] = []
    boundaries: Dict[str, int] = {}                       # the last actual column of each sheet whose month stands
    smaps = {s["sheet"]: s for s in fmap.get("sheets") or []}
    for smap in smaps.values():
        sheet = cells.sheet(smap["sheet"])
        if sheet is None:
            items.append(_item(f"periods:{smap['sheet']}", "periods", REJECTED, R_NO_SHEET.format(name=smap["sheet"]), smap["sheet"]))
            continue
        cur = check_currency(smap, sheet)
        if cur:
            items.append(cur)
        items.append(check_periods(smap, sheet, fye))
        rows = smap.get("rows") or []
        for row in rows:
            got = check_row(smap, row, sheet)
            has_arithmetic = bool(row.get("variance_of") or row.get("variance_columns"))
            if row.get("role") == "variance" and has_arithmetic and got["outcome"] == CONFIRMED:
                items.append(check_variance(smap, row, sheet))        # a variance row is confirmed by its arithmetic, as one item
                continue
            items.append(got)
            if has_arithmetic and row.get("role") != "variance":
                items.append(check_variance(smap, row, sheet))
        by_parent: Dict[int, List[Dict]] = {}
        for row in rows:
            if row.get("parent_row"):
                by_parent.setdefault(row["parent_row"], []).append(row)
        for parent, children in by_parent.items():
            got = check_parts(smap, parent, children, next((r for r in rows if r["row"] == parent), None), sheet)
            if got.get("mismatch"):
                totals.append(got["mismatch"])
            else:
                items.append(got)
        extra, month = check_last_actual(smap, sheet, fye, cells)
        items += extra
        if month:
            months.append(month)
            boundaries[smap["sheet"]] = redact.col_number(month["column"])
    for i, figure in enumerate(fmap.get("figures") or []):
        items.append(check_figure(i, figure, cells, smaps, fye, boundaries))
    counts = {o: sum(1 for i in items if i["outcome"] == o) for o in OUTCOMES}
    return {"items": items, "counts": counts, "months": months, "totals": totals}




def recheck_stored(doc: Dict, fmap: Dict, cells: Cells, fye: int = 12, skip: Iterable[str] = ()) -> Dict:
    """The stored outcome of a file with its rejected figures and rejected parts checks run again by today's rules, on the stored cells and the
    effective map (no model call, nothing written): a figure whose only difference was the written form of its period or a dropped % sign is now
    confirmed, a cell that holds a formula error is now that, and parts that do not add up are now a total finding. Every other item stands as
    stored; so does an item in `skip` (one the analyst decided on a card). Returns {"items", "totals", "cleared"}: `cleared` are the keys of the items that
    are no longer rejected."""
    smaps = {s["sheet"]: s for s in fmap.get("sheets") or []}
    boundaries = {m["sheet"]: redact.col_number(m["column"]) for m in doc.get("months") or [] if m.get("column")}
    figures = {_figure_key(i, f): (i, f) for i, f in enumerate(fmap.get("figures") or [])}
    items: List[Dict] = []
    totals = list(doc.get("totals") or [])
    cleared: List[str] = []
    for it in doc.get("items") or []:
        new = None
        if it.get("key") in skip:
            pass
        elif it.get("outcome") == REJECTED and it.get("kind") == "figure" and it["key"] in figures:
            i, figure = figures[it["key"]]
            new = check_figure(i, figure, cells, smaps, fye, boundaries)
        elif it.get("outcome") == REJECTED and it.get("kind") == "parts" and it.get("sheet") in smaps and cells.sheet(it["sheet"]) is not None:
            smap = smaps[it["sheet"]]
            rows = smap.get("rows") or []
            children = [r for r in rows if r.get("parent_row") == it.get("row")]
            new = check_parts(smap, it["row"], children, next((r for r in rows if r["row"] == it["row"]), None), cells.sheet(it["sheet"])) if children else None
        if new is None:
            items.append(it)
            continue
        if new.get("mismatch"):
            totals.append(new["mismatch"])
            cleared.append(it["key"])
            continue
        if new["outcome"] != REJECTED:
            cleared.append(it["key"])
        items.append({**it, **new})
    return {"items": items, "totals": totals, "cleared": cleared}


def formula_errors_of(doc: Dict) -> List[Dict]:
    """The formula errors of a stored file outcome: those the workbook scan found (sheet order), then any the checks met in a cited cell that the scan
    did not list (an outcome stored before the check named them). One entry per cell: [{"sheet", "cell", "error"}]."""
    out = list(doc.get("formula_errors") or [])
    seen = {(e["sheet"], e["cell"]) for e in out}
    for it in doc.get("items") or []:
        cells = ([{"cell": it.get("cell"), "error": it["formula_error"]}] if it.get("formula_error") else []) + list(it.get("formula_errors") or [])
        for e in cells:
            if e.get("cell") and (it.get("sheet"), e["cell"]) not in seen:
                seen.add((it.get("sheet"), e["cell"]))
                out.append({"sheet": it.get("sheet"), "cell": e["cell"], "error": e["error"]})
    return out


def _figure_key(index: int, figure: Dict) -> str:
    source = figure.get("source") or {}
    cell = source.get("cell")
    return f"figure:{source.get('sheet')}:{cell}:{figure.get('metric')}" if cell else f"figure:#{index}"


SHEET_LEVEL = ("currency", "periods", "last_actual")


def rereadable(item: Dict) -> bool:
    """A rejected item is read again, whatever it is: a cell, a row, a column, a piece of evidence."""
    return item["outcome"] == REJECTED


def reread_keys(items: List[Dict]) -> List[str]:
    """What to ask the reader about: the rejected items, an evidence piece or a boundary header by its sheet's last actual column."""
    keys = []
    for i in items:
        if not rereadable(i):
            continue
        key = f"last_actual:{i['sheet']}" if i["kind"] == "evidence" else i["key"]
        if key not in keys:
            keys.append(key)
    return keys


def merge_reread(first: Dict, second: Dict, keys: List[str]) -> Dict:
    """The first reading with the items the second reading answered for, by key; nothing else of the second reading is taken. A row, a
    figure, a sheet's last actual column, currency and period columns are replaced as wholes. Returns a new map."""
    out = copy.deepcopy(first)
    asked = set(keys)
    new_sheets = {s["sheet"]: s for s in second.get("sheets") or []}
    for smap in out.get("sheets") or []:
        again = new_sheets.get(smap["sheet"])
        if not again:
            continue
        if f"currency:{smap['sheet']}" in asked:
            smap["currency"], smap["currency_cell"] = again.get("currency"), again.get("currency_cell")
        if f"periods:{smap['sheet']}" in asked:
            for field in ("header_row", "label_col", "first_period_col", "last_period_col", "granularity"):
                smap[field] = again[field]
        if f"last_actual:{smap['sheet']}" in asked and again.get("last_actual"):
            smap["last_actual"] = again["last_actual"]
        replaced = {r["row"]: r for r in again.get("rows") or []}
        wanted = set()
        for key in asked:
            m = re.fullmatch(rf"(?:row|variance):{re.escape(smap['sheet'])}:(\d+)", key)
            if m:
                wanted.add(int(m.group(1)))
            m = re.fullmatch(rf"parts:{re.escape(smap['sheet'])}:(\d+)", key)
            if m:
                parent = int(m.group(1))
                wanted |= {parent} | {r["row"] for r in smap.get("rows") or [] if r.get("parent_row") == parent}
        smap["rows"] = [replaced[r["row"]] if r["row"] in wanted and r["row"] in replaced else r for r in smap.get("rows") or []]
    answers = {_figure_key(i, f): f for i, f in enumerate(second.get("figures") or [])}
    out["figures"] = [answers[_figure_key(i, f)] if _figure_key(i, f) in asked and _figure_key(i, f) in answers else f
                      for i, f in enumerate(out.get("figures") or [])]
    return out


def reading_of(file_map: Optional[Dict], key: str) -> Optional[Dict]:
    """The part of a reading an item key names, as the reader gave it: a figure, a row (a variance row, a parent with its parts) or a sheet's
    currency, period columns or last actual column. None when the reading holds nothing for the key."""
    if not file_map:
        return None
    if key.startswith("figure:"):
        return next((f for i, f in enumerate(file_map.get("figures") or []) if _figure_key(i, f) == key), None)
    kind, _, rest = key.partition(":")
    for smap in file_map.get("sheets") or []:
        name = smap["sheet"]
        if not rest.startswith(f"{name}"):
            continue
        tail = rest[len(name):]
        if kind in ("row", "variance") and re.fullmatch(r":\d+", tail):
            return next((r for r in smap.get("rows") or [] if r["row"] == int(tail[1:])), None)
        if kind == "parts" and re.fullmatch(r":\d+", tail):
            parent = int(tail[1:])
            return {"rows": [r for r in smap.get("rows") or [] if r["row"] == parent or r.get("parent_row") == parent]}
        if kind == "last_actual" and not tail:
            return smap.get("last_actual")
        if kind == "currency" and not tail:
            return {"currency": smap.get("currency"), "currency_cell": smap.get("currency_cell")}
        if kind == "periods" and not tail:
            return {f: smap.get(f) for f in ("header_row", "label_col", "first_period_col", "last_period_col", "granularity")}
    return None


REREAD_AGREES, REREAD_SAME, REREAD_THIRD = "agrees with the cell", "repeats the first reading", "gives a third value"


def classify_reread(before: Dict, after: Dict) -> str:
    """The result of the second reading of a rejected item (section 11.3): it now agrees with the cell, it repeats the first reading, or it
    gives something else that is still rejected."""
    if after["outcome"] == CONFIRMED:
        return REREAD_AGREES
    return REREAD_SAME if after.get("reason") == before.get("reason") else REREAD_THIRD
