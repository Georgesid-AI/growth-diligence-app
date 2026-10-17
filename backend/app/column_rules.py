"""Column rules: reading a sheet, finding its header, detecting its type and mapping its columns by rule
(docs/specs/chat-upload.md sections 3 and 4.1). Pure Python: no database, no model, no network.

The model never decides here. A column is mapped when its header and its values agree (confidence above
MAPPING_THRESHOLD, no tie); anything else is shown to the analyst, with or without the model's
proposal (CLAUDE.md rule 18: model output is never Verified on its own).
"""
import csv
import io
import re
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Dataset field definitions (normalized names + fuzzy-match aliases)
# ---------------------------------------------------------------------------
FIELD_DEFS = {
    "revenue": {
        "required": {
            "customer_id": ["customer", "customer id", "account", "client", "cust", "contact", "contact name", "contactname",
                            "bill to"],
            "invoice_date": ["invoice date", "date", "billing date", "posted", "invoicedate", "created", "created utc",
                             "issue date"],
            "amount": ["amount", "value", "revenue", "total", "arr", "mrr"],
            "currency": ["currency", "ccy", "curr"],
        },
        "optional": {
            "service_start": ["service start", "start date", "period start", "term start"],
            "service_end": ["service end", "end date", "period end", "term end"],
            "segment": ["segment", "tier", "size", "band"],
            "revenue_type": ["revenue type", "type", "recurring", "rec/one-off"],
        },
        "dates": ["invoice_date", "service_start", "service_end"],
        "numeric": ["amount"],
    },
    "crm": {
        "required": {
            "deal_id": ["deal id", "opportunity id", "deal", "id", "record id"],
            "created_date": ["created", "create date", "created date", "open date", "deal created", "deal deal created"],
            "close_date": ["close date", "closed", "won date", "close", "deal deal closed on"],
            "stage": ["stage", "status", "outcome", "deal stage", "pipeline stage"],
            "amount": ["amount", "value", "deal value", "acv", "deal amount"],
        },
        "optional": {
            "segment": ["segment", "tier", "size"],
            "founder_involved": ["founder", "founder involved", "founder-led", "exec involved"],
        },
        "dates": ["created_date", "close_date"],
        "numeric": ["amount"],
    },
    "pnl": {
        "required": {
            "month": ["month", "period", "date", "fiscal month"],
            "sm_expense": ["sales & marketing", "s&m", "sales and marketing", "marketing expense", "sm expense"],
            "revenue": ["revenue", "total revenue", "sales", "turnover"],
            "cost_of_revenue": ["cost of revenue", "cogs", "cost of sales", "cost"],
        },
        "optional": {},
        "dates": ["month"],
        "numeric": ["sm_expense", "revenue", "cost_of_revenue"],
    },
}

MAPPING_THRESHOLD = 80          # a rule confidence above this, untied, needs no click (Q3); exactly 80 is unsure (2026-10-17)
HEADER_SCAN_ROWS = 10           # the header row is looked for in the first 10 sheet rows
DETECTION_MIN_SHARE = 0.8       # the rules detect a type at 80 or more (2026-10-16; before, half of its fields)

_UNNAMED = re.compile(r"^Unnamed: \d+$")
_DEDUPED = re.compile(r"^(.*)\.\d+$")
_YEAR = re.compile(r"^(?:19|20)\d{2}(?:\.0)?$")
_PURE_NUMBER = re.compile(r"^[-+]?\d+(?:\.\d+)?$")
# 03/04/2024, 3.4.24, 03-04-2024 (+ optional time): day and month in either order (server.parse_date_column).
_DM_DATE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?:[ T].*)?$")


def _score(field, alias, lc):
    if lc == alias:
        return 100
    if lc.startswith(alias) or alias.startswith(lc):
        return 80 if min(len(lc), len(alias)) >= 4 else 30
    if alias in lc:  # alias is a substring of the column header
        return 60
    if lc in alias and len(lc) >= 4:  # column header is a substring of the alias
        return 40
    return 0


def _all_fields(dtype: str) -> Dict[str, List[str]]:
    defs = FIELD_DEFS[dtype]
    return {**defs["required"], **defs["optional"]}


def _norm(text: str) -> str:
    """A header or alias as the scores read it: lower case, every run of punctuation one space, the underscore
    included ("Deal - ID", "*InvoiceDate" and "deal_stage" are read as "deal id", "invoicedate" and "deal stage");
    "&" stays ("S&M")."""
    return re.sub(r"(?:[^\w&]|_)+", " ", (text or "").lower()).strip()


# Deal ID (2026-10-17, chat-upload.md sections 4.1 and 21): a stage is never a deal id; a column of unique codes whose header
# holds an id word is the deal id candidate.
_NOT_AN_ID = re.compile(r"(?i)stage|status|phase")
_ID_WORDS = {"id", "opportunity", "deal", "ref", "reference"}
LABEL_SET_MAX = 12              # a stage column holds at most 12 labels (measured: 1 to 4 in sample_data/ and the fixtures)
_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-/.#:]*")
_ISO_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")


def field_score(dtype: str, field: str, header: str) -> int:
    """The best score of a header against one field's name and aliases (100, 80, 60, 40, 30 or 0). A header that
    holds stage, status or phase scores 0 as a deal id."""
    lc = _norm(header)
    if not lc or (field == "deal_id" and _NOT_AN_ID.search(header)):
        return 0
    aliases = [_norm(field.replace("_", " "))] + [_norm(a) for a in _all_fields(dtype)[field]]
    return max(_score(field, alias, lc) for alias in aliases)


def _assign(fields, columns: list, scores: Dict[Tuple[str, str], int]) -> dict:
    """{field: column} by the greedy order: best score first; equal scores in field order, then column order."""
    mapping = {f: None for f in fields}
    used = set()
    for (fld, col), s in sorted(scores.items(), key=lambda kv: -kv[1]):
        if s and mapping[fld] is None and col not in used:
            mapping[fld] = col
            used.add(col)
    return mapping


def suggest_mapping(dtype: str, columns: list, headers: Optional[list] = None) -> dict:
    """{field: column} by the greedy order of the aliases: best score first. `headers` are the header cell
    texts when they differ from the column names (a pandas-style "Customer ID.1" is scored as "Customer ID")."""
    all_fields = _all_fields(dtype)
    texts = headers if headers is not None else deduped_texts(columns)
    return _assign(all_fields, columns, {(f, c): field_score(dtype, f, t) for f in all_fields for c, t in zip(columns, texts)})


def _is_code(v) -> bool:
    """One token with a digit, or a whole number: "1C1I7A6R", "OPP-0042", 5001. Not a date, not a decimal."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return v.is_integer()
    if not isinstance(v, str):
        return False
    s = v.strip()
    if _PURE_NUMBER.match(s):
        return "." not in s
    return bool(_CODE.fullmatch(s) and re.search(r"\d", s) and not _DM_DATE.match(s) and not _ISO_DATE.match(s))


def unique_codes(values) -> bool:
    """Two or more values, every one a code and no two the same."""
    present = _non_blank(values)
    return len(present) >= 2 and all(_is_code(v) for v in present) and len({str(v).strip() for v in present}) == len(present)


def label_set(values) -> bool:
    """A small set of repeated labels (Won / Lost / Engaging / Prospecting): text with a letter, not a code, at most
    LABEL_SET_MAX distinct, each used twice on average."""
    present = _non_blank(values)
    if not present or not all(isinstance(v, str) and re.search(r"[^\W\d_]", v) and not _is_code(v) for v in present):
        return False
    distinct = len({v.strip().lower() for v in present})
    return distinct <= LABEL_SET_MAX and 2 * distinct <= len(present)


def _words(header: str) -> List[str]:
    """The words of a header, camel case split ("OpportunityID" is "opportunity id")."""
    return _norm(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", header or "")).split()


def rule_scores(dtype: str, sheet: "Sheet") -> Dict[Tuple[str, str], int]:
    """{(field, column): score}: the header score, and for the deal id the values too. A small set of repeated labels
    is a stage, never a deal id (0); a column of unique codes whose header holds id, opportunity, deal or ref is the
    deal id candidate (at least MAPPING_THRESHOLD, so it waits for a click unless its header scores 100)."""
    fields = _all_fields(dtype)
    scores = {(f, c): field_score(dtype, f, t) for f in fields for c, t in zip(sheet.columns, sheet.headers)}
    if "deal_id" in fields:
        for c, t in zip(sheet.columns, sheet.headers):
            values = sheet.frame[c].tolist()
            if label_set(values):
                scores[("deal_id", c)] = 0
            elif not _NOT_AN_ID.search(t or "") and _ID_WORDS & set(_words(t)) and unique_codes(values):
                scores[("deal_id", c)] = max(scores[("deal_id", c)], MAPPING_THRESHOLD)
    return scores


def deduped_texts(columns: list) -> list:
    """The header text of each column when only the names are known: a "Name.1" whose "Name" is also a column
    is a de-duplicated header and is read as "Name"."""
    names = set(columns)
    out = []
    for c in columns:
        m = _DEDUPED.match(str(c))
        out.append(m.group(1) if m and m.group(1) in names else str(c))
    return out


# ---------------------------------------------------------------------------
# Reading a workbook (section 3; amended 2026-10-16: every sheet, leading empty columns dropped, period headers
# melted, units read from the title rows)
# ---------------------------------------------------------------------------
@dataclass
class Sheet:
    sheet: str
    header_row: int                 # the sheet row number of the header (1 = the first row)
    columns: List[str]              # unique names; a blank header is "Unnamed: n", a repeat "Name.1"
    headers: List[str]              # the header cell text of each column, as written ("" when blank)
    frame: pd.DataFrame             # the data rows below the header, blank lines dropped
    row_numbers: List[int]          # the sheet row number of each frame row
    titles: List[Tuple[int, int, str]] = field(default_factory=list)   # (sheet row, column, text) above the header
    unit_scale: int = 1             # 1,000 when the title rows say the figures are in thousands
    unit_note: Optional[str] = None
    wide: Optional[Dict] = None     # {"periods", "monthly"} when period headers were melted into Period and Value
    raw_headers: Optional[List[str]] = None     # the header row as written, kept for a wide sheet (its columns are melted)
    first_col: int = 1              # the sheet column of the first column kept (1 = A): leading empty columns are dropped
    currency: Optional[str] = None  # the currency code the title rows name, if any (a forecast table's claims, section 20)


class SheetError(Exception):
    """The file could not be read as a sheet."""


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip())


def _grids(content: bytes, filename: str) -> Tuple[List[Tuple[str, List[List]]], bool]:
    """([(sheet name, rows as cell lists)], is_csv), every sheet of the file. Index i of a grid is sheet row i + 1."""
    name = (filename or "").lower()
    try:
        if name.endswith(".csv"):
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("latin-1")
            grid = [[None if _blank(c) else c for c in row] for row in csv.reader(io.StringIO(text))]
            return [("CSV", grid)], True
        if name.endswith(".xlsx"):
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(content), data_only=True)
            return [(ws.title, [[None if _blank(c) else c for c in row] for row in ws.iter_rows(values_only=True)])
                    for ws in wb.worksheets], False
        xls = pd.ExcelFile(io.BytesIO(content))
        return [(sheet, [[None if _blank(c) else c for c in row]
                         for row in xls.parse(sheet, header=None, dtype=object).itertuples(index=False)])
                for sheet in xls.sheet_names], False
    except SheetError:
        raise
    except Exception as exc:
        raise SheetError(type(exc).__name__)


def _filled(row: List) -> int:
    return sum(1 for c in row if not _blank(c))


def _has_number(row: List) -> bool:
    """A number other than a year: a header row holds none."""
    for c in row:
        if _blank(c) or isinstance(c, (bool, datetime, date)):
            continue
        if isinstance(c, (int, float)) and not _YEAR.match(str(c)):
            return True
        if isinstance(c, str) and _PURE_NUMBER.match(c.strip()) and not _YEAR.match(c.strip()):
            return True
    return False


def find_header_row(grid: List[List]) -> int:
    """Index in the grid of the header row: among the first 10 rows, the first that fills at least half of the
    widest row's cells and holds no number other than a year. The first row when none qualifies."""
    top = grid[:HEADER_SCAN_ROWS]
    widest = max((_filled(r) for r in top), default=0)
    for i, row in enumerate(top):
        if _filled(row) and 2 * _filled(row) >= widest and not _has_number(row):
            return i
    return 0


def _header_text(v) -> str:
    if _blank(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


# Period headers (amended 2026-10-16): the columns of a wide table. A year, a quarter, a year to date, a half, a month.
_MONTH_NAMES = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_SEP = r"[\s:\-/'’.]*"
_P_YEAR = re.compile(r"(?i)(?:FY\s?)?((?:19|20)\d{2})(?:\.0)?\s?[EFAB]?")
_P_YTD = re.compile(r"(?i)(?:(?:19|20)\d{2}\s*YTD|YTD\s*(?:19|20)\d{2}|YTD)")
_P_QUARTER = re.compile(r"(?i)(?:Q[1-4]" + _SEP + r"(?:19|20)?\d{2}|(?:19|20)?\d{2}" + _SEP + r"Q[1-4])")
_P_HALF = re.compile(r"(?i)H[12]" + _SEP + r"(?:19|20)?\d{2}")
_P_ISO_MONTH = re.compile(r"((?:19|20)\d{2})-(\d{2})(?:-\d{2})?(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?")
_P_NAMED_MONTH = re.compile(r"(?i)(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*" + _SEP + r"((?:19|20)?\d{2})")
_P_NUMERIC_MONTH = re.compile(r"(\d{1,2})[/.]((?:19|20)\d{2})")


def parse_period(text: str) -> Optional[Tuple[str, Optional[date]]]:
    """(grain, first day) of a period header, or None. Grains: year, quarter, ytd, half, month; the day is
    set for a month only ("Jan-24", "2024-01", "2024-01-31", "01/2024")."""
    t = (text or "").strip()
    if not t:
        return None
    if _P_YTD.fullmatch(t):
        return "ytd", None
    if _P_QUARTER.fullmatch(t):
        return "quarter", None
    if _P_HALF.fullmatch(t):
        return "half", None
    if _P_YEAR.fullmatch(t):
        return "year", None
    m = _P_ISO_MONTH.fullmatch(t)
    if m and 1 <= int(m.group(2)) <= 12:
        return "month", date(int(m.group(1)), int(m.group(2)), 1)
    m = _P_NAMED_MONTH.fullmatch(t)
    if m:
        y = int(m.group(2))
        return "month", date(y + (2000 if y < 100 else 0), _MONTH_NAMES[m.group(1).lower()], 1)
    m = _P_NUMERIC_MONTH.fullmatch(t)
    if m and 1 <= int(m.group(1)) <= 12:
        return "month", date(int(m.group(2)), int(m.group(1)), 1)
    return None


# Units (amended 2026-10-16): "EUR thousands", "EUR 000", "k EUR", "EURk", "in thousands" in the title rows.
_CURRENCY = r"(?:EUR|USD|GBP|CHF|SEK|NOK|DKK|PLN|BGN|€|\$|£)"
_THOUSANDS = [re.compile(p) for p in (
    rf"(?i)\b({_CURRENCY})?\s*(?:in\s+)?(?:thousands?|tsd)\b",
    rf"(?i)\b({_CURRENCY})\s?'?000s?\b|(?<![\w.,]){_CURRENCY}\s?'000",
    rf"(?i)\bk\s?({_CURRENCY})(?!\w)",
    rf"(?i)(?<![\w.,])({_CURRENCY})\s?k\b|\(\s?k\s?\)|'000s?\b")]


def read_units(titles: List[Tuple[int, int, str]]) -> Tuple[int, Optional[str]]:
    """(scale, note) from the title rows above the header: 1,000 and a note when they say the figures are in
    thousands, else (1, None). Only titles are read, never the data."""
    for _, _, text in titles:
        for pattern in _THOUSANDS:
            m = pattern.search(text)
            if m:
                code = next((g for g in m.groups() if g), "") if m.groups() else ""
                code = {"€": "EUR", "$": "USD", "£": "GBP"}.get(code, code.upper())
                return 1000, f"Title rows say {code + ' ' if code else ''}thousands: money figures are multiplied by 1,000."
    return 1, None


_TITLE_CURRENCY = re.compile(r"(?i)(?<![A-Za-z])(EUR|USD|GBP|CHF|SEK|NOK|DKK|PLN|BGN)(?![A-Za-z])|[€$£]")


def title_currency(texts) -> Optional[str]:
    """The first currency code or sign in the texts (title rows, a line label) as an ISO code, or None. Only titles and labels
    are read, never the data."""
    for text in texts:
        m = _TITLE_CURRENCY.search(str(text or ""))
        if m:
            return (m.group(1) or {"€": "EUR", "$": "USD", "£": "GBP"}[m.group(0)]).upper()
    return None


def _is_number(v) -> bool:
    if isinstance(v, bool) or _blank(v):
        return False
    if isinstance(v, (int, float)):
        return v == v
    return isinstance(v, str) and bool(_PURE_NUMBER.match(v.strip().replace(",", "")))


def _first_table(body: List[Tuple[int, List]], period_cols: List[int]) -> List[Tuple[int, List]]:
    """The rows of the first table of a wide sheet: those with a number under a period header. The table ends at
    a blank row followed by a row with no number there (the title of the next table), or at a row that repeats
    the period headers. Several tables can sit one below the other (actuals, forecast, comparison, notes)."""
    kept, last = [], None
    for n, row in body:
        has = any(_is_number(row[j]) for j in period_cols)
        repeats = sum(1 for j in period_cols if isinstance(row[j], str) and parse_period(row[j])) >= 2
        if kept and ((last is not None and n > last + 1 and not has) or repeats):
            break
        if has:
            kept.append((n, row))
        last = n
    return kept


def _melt(headers: List[str], body: List[Tuple[int, List]]) -> Optional[Tuple[List[str], List[str], List[List], List[int], Dict]]:
    """Wide to long: the period headers (2023, Q1:24, 2024 YTD, Jan-24, ...) across the columns become a Period and
    a Value column, one row per number, keeping the sheet row of its line. (columns, headers, rows, row numbers,
    wide info), or None when fewer than 3 headers are periods. With 3 or more months the months alone are kept
    (Period is a date, headed "Date"); otherwise the table is a summary or forecast by year or quarter and
    Period keeps its label."""
    periods = {j: parse_period(h) for j, h in enumerate(headers)}
    periods = {j: p for j, p in periods.items() if p}
    if len(periods) < 3:
        return None
    months = {j: p for j, p in periods.items() if p[0] == "month"}
    monthly = len(months) >= 3
    used = months if monthly else periods
    ids = [j for j in range(len(headers)) if j not in periods]
    table = _first_table(body, list(used))
    names = [headers[j] or ("Line" if k == 0 else f"Column {k + 1}") for k, j in enumerate(ids)]
    period_name = "Date" if monthly else "Period"
    rows, numbers = [], []
    for n, row in table:
        for j in used:
            if _is_number(row[j]):
                label = pd.Timestamp(used[j][1]) if monthly else headers[j]
                number = float(row[j].replace(",", "")) if isinstance(row[j], str) else row[j]
                value = int(number) if isinstance(number, float) and number.is_integer() else number
                rows.append([row[i] for i in ids] + [label, value])
                numbers.append(n)
    if not rows:
        return None
    out_headers = names + [period_name, "Value"]
    return out_headers, out_headers, rows, numbers, {"periods": len(used), "monthly": monthly}


def _unique(headers: List[str]) -> List[str]:
    columns, seen = [], {}
    for i, text in enumerate(headers):
        base = text or f"Unnamed: {i}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        columns.append(base if n == 0 else f"{base}.{n}")
    return columns


def _read_grid(grid: List[List], name: str, is_csv: bool) -> Optional[Sheet]:
    """One sheet as a header, its columns and its data rows with their sheet row numbers; None when it is empty.

    Read without a header, short rows padded, blank lines counted: a one-cell title row cannot break a CSV.
    Rows above the header (titles, blanks) are dropped and never stored; the columns before the first one with
    a header or a value are dropped too (no "Unnamed: n" for them)."""
    grid = [list(r) for r in grid]
    while grid and _filled(grid[-1]) == 0:
        grid.pop()
    if not grid:
        return None
    h = find_header_row(grid)
    body = [(i + 1, row) for i, row in enumerate(grid) if i > h and _filled(row)]
    width = max([len(grid[h])] + [len(r) for _, r in body])
    pad = lambda r: list(r) + [None] * (width - len(r))  # noqa: E731
    head, rows = pad(grid[h]), [(n, pad(r)) for n, r in body]
    lead = 0
    while lead < width and _blank(head[lead]) and all(_blank(r[lead]) for _, r in rows):
        lead += 1
    head, rows = head[lead:], [(n, r[lead:]) for n, r in rows]
    width -= lead
    titles = [(i + 1, max(j + 1 - lead, 1), str(c).strip()) for i, row in enumerate(grid[:h])
              for j, c in enumerate(row) if isinstance(c, str) and c.strip()]
    scale, note = read_units(titles)
    headers = [_header_text(c) for c in head]
    while width and not headers[width - 1] and all(_blank(r[width - 1]) for _, r in rows):
        width -= 1
        headers.pop()
    rows = [(n, r[:width]) for n, r in rows]
    melted = _melt(headers, rows)
    if melted:
        long_headers, texts, data, numbers, wide = melted
        columns = _unique(long_headers)
        frame = pd.DataFrame(data, columns=columns, dtype=object)
        return Sheet(name, h + 1, columns, texts, frame, numbers, titles, scale, note, wide, headers, lead + 1,
                     title_currency(t for _, _, t in titles))
    columns = _unique(headers)
    frame = pd.DataFrame([r for _, r in rows], columns=columns, dtype=object)
    if is_csv:                                   # CSV cells are text: a column that is all numbers is numeric
        for c in columns:
            col = frame[c]
            present = col.notna()
            if present.any():
                conv = pd.to_numeric(col, errors="coerce")
                if conv.notna().sum() == present.sum():
                    frame[c] = conv
    return Sheet(name, h + 1, columns, headers, frame, [n for n, _ in rows], titles, scale, note, None, None, lead + 1,
                 title_currency(t for _, _, t in titles))


def read_workbook(content: bytes, filename: str) -> List[Sheet]:
    """Every sheet of a file that holds anything, in workbook order (a CSV is one sheet). Raises SheetError
    when none does."""
    grids, is_csv = _grids(content, filename)
    sheets = [s for name, grid in grids if (s := _read_grid(grid, name, is_csv))]
    if not sheets:
        raise SheetError("empty")
    return sheets


def read_sheet(content: bytes, filename: str) -> Sheet:
    """The first sheet of a file (see read_workbook)."""
    return read_workbook(content, filename)[0]


# ---------------------------------------------------------------------------
# Value fit (section 4.1)
# ---------------------------------------------------------------------------
KIND_WORDS = {"date": "dates", "numeric": "numbers", "currency": "currency codes"}


def field_kind(dtype: str, field: str) -> str:
    defs = FIELD_DEFS[dtype]
    if field in defs["dates"]:
        return "date"
    if field in defs["numeric"]:
        return "numeric"
    return "currency" if field == "currency" else "text"


def _non_blank(values) -> list:
    return [v for v in values if not _blank(v)]


def _reads_as_date(values: list) -> int:
    ok, text = 0, []
    for v in values:
        if isinstance(v, (datetime, date, pd.Timestamp)):
            ok += 1
        elif isinstance(v, str):
            s = v.strip()
            m = _DM_DATE.match(s)
            if m:                                     # a day/month order it cannot settle still counts as a date
                a, b = int(m.group(1)), int(m.group(2))
                ok += 1 if 1 <= a <= 31 and 1 <= b <= 31 and (a <= 12 or b <= 12) else 0
            elif not _PURE_NUMBER.match(s):
                text.append(s)
    if text:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ok += int(pd.to_datetime(pd.Series(text), errors="coerce").notna().sum())
    return ok


def _reads_as_number(values: list) -> int:
    ok, text = 0, []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            ok += 1 if v == v else 0
        elif isinstance(v, str):
            text.append(v)
    if text:
        ok += int(pd.to_numeric(pd.Series(text), errors="coerce").notna().sum())
    return ok


def value_fit(kind: str, values) -> Tuple[float, int, int]:
    """(fit, readable, total): the share of the column's non-blank values the engine can read as the field's
    kind. A text field accepts any non-blank value; a column with no non-blank value has a fit of 0."""
    present = _non_blank(values)
    if not present:
        return 0.0, 0, 0
    if kind == "date":
        ok = _reads_as_date(present)
    elif kind == "numeric":
        ok = _reads_as_number(present)
    elif kind == "currency":
        ok = sum(1 for v in present if isinstance(v, str) and re.fullmatch(r"[A-Za-z]{3}", v.strip()))
    else:
        ok = len(present)
    return ok / len(present), ok, len(present)


def fit_note(kind: str, ok: int, total: int) -> Optional[str]:
    """S9: "0 of 20 values are numbers", shown when the fit lowers the confidence."""
    if kind == "text" or ok == total:
        return None
    if total == 0:
        return "no values"
    return f"{ok} of {total} values are {KIND_WORDS[kind]}"


# ---------------------------------------------------------------------------
# Mapping rule, step 1 (section 4.1)
# ---------------------------------------------------------------------------
@dataclass
class Proposal:
    column: str
    field: Optional[str]
    score: int
    confidence: Optional[int]
    note: Optional[str]
    state: str                      # "auto" | "unsure" | "undecided" | "unused"
    tie: bool = False
    tie_fields: tuple = ()          # the fields this column is tied for


def analyse(dtype: str, sheet: Sheet) -> Tuple[List[Proposal], List[str]]:
    """(one Proposal per column, the fields still open). The rules propose one column per field, in the greedy
    order of suggest_mapping over rule_scores. Auto: confidence above the threshold and no tie. Unsure: at or below
    it, or tied (two columns share a field's best score, or one column shares its best score between two fields).
    Undecided: no proposal while a field is still open. Unused: no proposal and no open field."""
    fields = _all_fields(dtype)
    scores = rule_scores(dtype, sheet)
    mapping = _assign(fields, sheet.columns, scores)
    by_col = {c: f for f, c in mapping.items() if c}
    tied, tie_fields = set(), {c: [] for c in sheet.columns}
    for f in fields:                                 # two columns share a field's best score
        best = max((scores[(f, c)] for c in sheet.columns), default=0)
        same = [c for c in sheet.columns if best and scores[(f, c)] == best]
        if len(same) > 1:
            tied |= set(same)
            for c in same:
                tie_fields[c].append(f)
    for c in sheet.columns:                          # one column shares its best score between two fields
        best = max((scores[(f, c)] for f in fields), default=0)
        same = [f for f in fields if best and scores[(f, c)] == best]
        if len(same) > 1:
            tied.add(c)
            tie_fields[c] += [f for f in same if f not in tie_fields[c]]
    out = []
    for c in sheet.columns:
        field = by_col.get(c)
        if field is None:
            out.append(Proposal(c, None, 0, None, None, "undecided", c in tied, tuple(tie_fields[c])))
            continue
        fit, ok, total = value_fit(field_kind(dtype, field), sheet.frame[c].tolist())
        conf = round(scores[(field, c)] * fit)
        note = fit_note(field_kind(dtype, field), ok, total)
        accepted = conf > MAPPING_THRESHOLD and c not in tied
        out.append(Proposal(c, field, scores[(field, c)], conf, note, "auto" if accepted else "unsure", c in tied,
                            tuple(tie_fields[c])))
    held = {p.field for p in out if p.state == "auto"}
    open_fields = [f for f in fields if f not in held]
    for p in out:
        if p.state == "undecided" and not open_fields:
            p.state = "unused"
    return out, open_fields


def customer_columns(sheet: Sheet, proposals: List[Proposal]) -> List[str]:
    """Every column whose header matches a customer alias at any score, and every column tied for
    customer_id: these send a profile only, even when their values are numbers (section 4.2)."""
    out = [c for c, t in zip(sheet.columns, sheet.headers) if field_score("revenue", "customer_id", t) > 0]
    out += [p.column for p in proposals if "customer_id" in p.tie_fields]
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# Type detection (section 3; amended 2026-10-16)
# ---------------------------------------------------------------------------
# Rules first, by the headers (and, in a wide table, the line labels): a type is detected when its share is the unique
# highest and at least DETECTION_MIN_SHARE. Revenue needs all three of customer, date and amount, each header
# at 80 or more: an "MRR" or "ARR" header alone never makes a revenue file. A CRM file needs four of the five
# signature columns (deal, created, closed or won, stage or status, owner). A P&L is the share of its fields the
# headers match, or cost lines (cost of sales, payroll, EBITDA ...) among its headers or line labels. Headers and line
# labels are read as the mapping reads them, punctuation as one space ("deal_id" is "deal id"; 2026-10-17).
REVENUE_KEY = ("customer_id", "invoice_date", "amount")
_CRM_SIGNATURE = {
    "deal": re.compile(r"(?i)\b(?:deal|opportunit\w*)\b"),
    "created": re.compile(r"(?i)\b(?:created?|opened?)\b"),
    "closed": re.compile(r"(?i)\b(?:close[ds]?|won)\b"),
    "stage": re.compile(r"(?i)\b(?:stage|status|outcome)\b"),
    "owner": re.compile(r"(?i)\b(?:owner|sales\s?rep|rep)\b"),
}
_COST_LINES = [re.compile(p) for p in (
    r"(?i)\bcost of (?:sales|goods|revenue)\b|\bcogs\b", r"(?i)\bpayroll\b|\bsalar(?:y|ies)\b|\bpersonnel\b|\bstaff costs?\b",
    r"(?i)\bebitda\b", r"(?i)\bopex\b|\boperating (?:expenses|costs|profit|income|result)\b",
    r"(?i)\bgross (?:profit|margin)\b", r"(?i)\bsales (?:&|and) marketing\b|\bs&m\b",
    r"(?i)\bgeneral (?:&|and) administrative\b|\bg&a\b", r"(?i)\br&d\b|\bresearch and development\b",
    r"(?i)\bdepreciation\b|\bamorti[sz]ation\b", r"(?i)\bnet (?:income|profit|loss)\b")]


def _line_labels(sheet: Sheet) -> List[str]:
    """The text a P&L's cost lines can stand in: the headers, and in a wide table the labels of the lines."""
    labels = list(sheet.headers)
    if sheet.wide:
        labels += [str(v) for v in sheet.frame[sheet.columns[0]].tolist() if isinstance(v, str)]
    return labels


def type_shares(sheet: Sheet) -> Dict[str, float]:
    """{type: share 0..1} by the rules above."""
    shares = {}
    key_hits = {f: max([field_score("revenue", f, t) for t in sheet.headers] or [0]) >= 80 for f in REVENUE_KEY}
    shares["revenue"] = sum(key_hits.values()) / len(REVENUE_KEY)
    heads = [_norm(t) for t in sheet.headers]
    groups = sum(1 for rx in _CRM_SIGNATURE.values() if any(rx.search(t) for t in heads))
    shares["crm"] = groups / len(_CRM_SIGNATURE)
    defs = FIELD_DEFS["pnl"]
    mapping = suggest_mapping("pnl", sheet.columns, sheet.headers)
    by_fields = sum(1 for f in defs["required"] if mapping.get(f)) / len(defs["required"])
    labels = [_norm(t) for t in _line_labels(sheet)]
    lines = len({i for i, rx in enumerate(_COST_LINES) if any(rx.search(t) for t in labels)})
    shares["pnl"] = max(by_fields, 1.0 if lines >= 3 else 0.8 if lines == 2 else 0.0)
    return shares


def detect_type(sheet: Sheet) -> Tuple[Optional[str], Dict[str, float]]:
    """(type, share per type). The type with the unique highest share wins when that share is at least 80%;
    otherwise None (the model is asked once, or the analyst chooses)."""
    shares = type_shares(sheet)
    best = max(shares.values())
    winners = [t for t, s in shares.items() if s == best]
    return (winners[0] if len(winners) == 1 and best >= DETECTION_MIN_SHARE else None), shares


def detect_workbook(sheets: List[Sheet]) -> Tuple[Optional[str], Optional[Sheet], Dict[str, float]]:
    """(type, sheet, shares) over every sheet of a file: the sheet whose detected type has the highest share
    (the earlier sheet on a tie, then the one with more rows). (None, None, shares of the first sheet) when no
    sheet is detected."""
    found = []
    for i, sheet in enumerate(sheets):
        dtype, shares = detect_type(sheet)
        if dtype:
            found.append((-shares[dtype], i, dtype, sheet, shares))
    if not found:
        return None, None, type_shares(sheets[0])
    _, _, dtype, sheet, shares = min(found, key=lambda f: (f[0], f[1]))
    return dtype, sheet, shares


def best_sheet(sheets: List[Sheet], dtype: str) -> Sheet:
    """The sheet that best fits a role: the most required fields its headers match at 80 or more, then the
    higher type share, then the one with more rows, then the earlier sheet."""
    required = FIELD_DEFS[dtype]["required"]

    def fit(item):
        i, sheet = item
        hits = sum(1 for f in required if max([field_score(dtype, f, t) for t in sheet.headers] or [0]) >= MAPPING_THRESHOLD)
        return (-hits, -type_shares(sheet)[dtype], -len(sheet.frame), i)
    return min(enumerate(sheets), key=fit)[1]


def describe(sheet: Sheet) -> Dict:
    """What a sheet looks like, in closed words and counts (no cell text): {"shape", "rows", "columns"}. A table
    with periods across its columns is a monthly table, or a summary or forecast table when the periods are years,
    quarters or years to date."""
    shape = "table"
    if sheet.wide:
        shape = "monthly_wide" if sheet.wide["monthly"] else "summary"
    return {"shape": shape, "rows": len(sheet.frame), "columns": len(sheet.columns)}


def is_miss(dtype: str, mapping: Dict[str, Optional[str]], looks: Optional[Dict]) -> bool:
    """True when the file cannot supply the type's required fields: a summary or forecast table, or no more than
    half of the required fields mapped (counting proposals that still wait for a click)."""
    required = FIELD_DEFS[dtype]["required"]
    if looks and looks.get("shape") == "summary":
        return True
    return sum(1 for f in required if mapping.get(f)) * 2 <= len(required)


def months_found(dtype: str, sheet: Sheet, mapping: Dict[str, str]) -> Optional[Dict]:
    """The distinct months of the date column (invoice date for revenue, close date for CRM, month for the P&L):
    {"count", "first", "last"} as YYYY-MM, or None before that column is mapped or when none reads."""
    field = {"revenue": "invoice_date", "crm": "close_date", "pnl": "month"}[dtype]
    col = mapping.get(field)
    if not col or col not in sheet.frame.columns:
        return None
    return months_of(sheet.frame[col].tolist())


def months_of(values: list) -> Optional[Dict]:
    """The distinct months of a date column, as the engine reads it: {"count", "first", "last"} (YYYY-MM), or None
    when no value reads. A day/month order the data cannot settle is not guessed: those values are left out."""
    present = _non_blank(values)
    parsed, text = [], []
    for v in present:
        if isinstance(v, (datetime, date, pd.Timestamp)):
            parsed.append(pd.Timestamp(v))
        elif isinstance(v, str):
            s = v.strip()
            m = _DM_DATE.match(s)
            if m:
                a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
                year = int(y) + (2000 if len(y) == 2 else 0)
                if a > 12 >= b:
                    parsed.append(pd.Timestamp(year, b, a))
                elif b > 12 >= a:
                    parsed.append(pd.Timestamp(year, a, b))
            elif not _PURE_NUMBER.match(s):
                text.append(s)
    if text:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed += [t for t in pd.to_datetime(pd.Series(text), errors="coerce") if not pd.isna(t)]
    months = sorted({t.strftime("%Y-%m") for t in parsed})
    return {"count": len(months), "first": months[0], "last": months[-1]} if months else None


# ---------------------------------------------------------------------------
# Column states: what the mapping table shows and what the analyst still owes (sections 4.1-4.3, 5)
# ---------------------------------------------------------------------------
# The fixed list of reasons for a correction (S11). Anything else is refused.
REASONS = ("header_misleading", "other_column_right", "values_do_not_fit", "wrong_kind_of_date", "not_needed", "other")
PENDING = ("unsure", "ai", "needs")           # states that wait for a click
MAPPED = ("auto", "unsure", "ai", "confirmed", "corrected")
# Amount columns named turnover, volume, GMV or TPV: revenue or value of transactions processed? (chat-upload.md section 15)
MONEY_FIELDS = ("amount", "revenue")
MONEY_KINDS = ("revenue", "volume")
_MONEY_HEADER = re.compile(r"(?i)turnover|volume|gmv|tpv")


def asks_money(state: Dict) -> bool:
    """A mapped amount column whose header says turnover, volume, GMV or TPV: the analyst is asked once what the money is."""
    return state.get("state") in MAPPED and state.get("field") in MONEY_FIELDS and bool(_MONEY_HEADER.search(str(state.get("column"))))


def needs_money(state: Dict) -> bool:
    return asks_money(state) and state.get("money_kind") not in MONEY_KINDS


def _is_volume(state: Dict) -> bool:
    return state.get("money_kind") == "volume"


class DecisionError(Exception):
    """A decision that cannot be applied; `code` is a closed word, `column` the column it names (if any)."""

    def __init__(self, code: str, column: Optional[str] = None):
        super().__init__(code)
        self.code, self.column = code, column


def new_state(column: str, field: Optional[str], source: Optional[str], state: str, confidence: Optional[int] = None,
              fit_note: Optional[str] = None) -> Dict:
    return {"column": column, "field": field, "source": source, "state": state, "confidence": confidence,
            "fit_note": fit_note, "decision": None, "reason": None, "money_kind": None}


def states_from_rules(proposals: List[Proposal]) -> List[Dict]:
    out = []
    for p in proposals:
        if p.state in ("auto", "unsure"):
            out.append(new_state(p.column, p.field, "rules", p.state, p.confidence, p.note))
        elif p.state == "undecided":
            out.append(new_state(p.column, None, "needs", "needs"))
        else:
            out.append(new_state(p.column, None, None, "unused"))
    return out


def undecided(states: List[Dict]) -> List[str]:
    """The columns the rules alone leave unsure or undecided: they need a decision when the model cannot be read."""
    return [s["column"] for s in states if s["state"] in ("unsure", "needs")]


def apply_model(dtype: str, sheet: Sheet, proposals: List[Proposal], proposed: Dict[str, str]) -> List[Dict]:
    """The model's proposals ({field: column}) for a sheet whose every column was sent (section 4.2, 2026-10-17).
    A rule confidence of 100, untied, wins. Otherwise the model's proposal is shown with its confidence, the rules'
    formula (header score x value fit) on the model's field: it needs no click when the rules proposed the same field,
    untied, at MAPPING_THRESHOLD or more, and waits for one otherwise. A column only the rules map waits for a click
    with their proposal (it needs a decision when the model gave that field to another column); a column neither maps
    is not used."""
    scores = rule_scores(dtype, sheet)
    won = {p.column: p.field for p in proposals if p.state == "auto" and p.confidence == 100}
    by_col = {c: f for f, c in proposed.items() if c not in won and f not in won.values()}
    out = []
    for p in proposals:
        f = by_col.get(p.column)
        if p.column in won:
            out.append(new_state(p.column, p.field, "rules", "auto", p.confidence, p.note))
        elif f:
            fit, ok, total = value_fit(field_kind(dtype, f), sheet.frame[p.column].tolist())
            conf, note = round(scores[(f, p.column)] * fit), fit_note(field_kind(dtype, f), ok, total)
            agreed = f == p.field and not p.tie and conf >= MAPPING_THRESHOLD
            out.append(new_state(p.column, f, "rules", "auto", conf, note) if agreed else
                       new_state(p.column, f, "ai", "ai", conf, note))
        elif p.field and p.field not in by_col.values():
            out.append(new_state(p.column, p.field, "rules", "unsure", p.confidence, p.note))
        elif p.field:
            out.append(new_state(p.column, None, "needs", "needs"))
        else:
            out.append(new_state(p.column, None, None, "unused"))
    return out


def apply_model_failure(states: List[Dict], open_columns: List[str]) -> List[Dict]:
    """The model could not be read: the rules' outcome stands, and every column they left open needs the analyst's
    decision."""
    return [new_state(s["column"], None, "needs", "needs") if s["column"] in open_columns else s for s in states]


def states_from_saved(dtype: str, sheet: Sheet, saved: List[Dict], scale: bool) -> List[Dict]:
    """A saved mapping applied to a sheet. The same bytes: every mapped column is accepted. The same headers on
    other data (`scale`): each mapped column counts as confidence 100 scaled by its value fit on the new data."""
    by_col = {c["column"]: c for c in saved}
    out = []
    for col in sheet.columns:
        entry = by_col.get(col) or {}
        field = entry.get("field")
        if not field or field not in _all_fields(dtype):
            out.append(new_state(col, None, None, "unused"))
            continue
        conf, note = 100, None
        if scale:
            kind = field_kind(dtype, field)
            fit, ok, total = value_fit(kind, sheet.frame[col].tolist())
            conf, note = round(100 * fit), fit_note(kind, ok, total)
        out.append({**new_state(col, field, "saved", "auto" if conf >= MAPPING_THRESHOLD else "unsure", conf, note),
                    "money_kind": entry.get("money_kind") if entry.get("money_kind") in MONEY_KINDS else None})
    return out


def mapping_of(dtype: str, states: List[Dict]) -> Dict[str, Optional[str]]:
    """{field: column} of every mapped column, pending proposals included (they are shown, not yet confirmed)."""
    mapping = {f: None for f in _all_fields(dtype)}
    for s in states:
        if s["state"] in MAPPED and s["field"] and not _is_volume(s):       # only revenue columns feed the engine
            mapping[s["field"]] = s["column"]
    return mapping


def pending_count(states: List[Dict]) -> int:
    return sum(1 for s in states if s["state"] in PENDING or needs_money(s))


def missing_required(dtype: str, states: List[Dict]) -> List[str]:
    mapping = mapping_of(dtype, states)
    return [f for f in FIELD_DEFS[dtype]["required"] if not mapping.get(f)]


def apply_decisions(dtype: str, states: List[Dict], decisions: List[Dict]) -> List[Dict]:
    """The analyst's decisions, one by one. Confirm accepts the proposal (a row that needs a decision takes the
    field chosen, or "Not used"). Correct takes a field or "Not used" and a reason from the fixed list. A field
    another column holds is refused and names that column. Raises DecisionError."""
    fields = _all_fields(dtype)
    states = [dict(s) for s in states]
    for d in decisions:
        state = next((s for s in states if s["column"] == d.get("column")), None)
        if state is None:
            raise DecisionError("unknown_column")
        if d.get("money_kind") is not None:                     # the answer to the money question (section 15)
            if d["money_kind"] not in MONEY_KINDS or not asks_money(state):
                raise DecisionError("bad_money_kind", state["column"])
            state["money_kind"] = d["money_kind"]
            continue
        action, field = d.get("action"), (d.get("field") or None)
        if action not in ("confirm", "correct"):
            raise DecisionError("bad_action", state["column"])
        if field is not None and field not in fields:
            raise DecisionError("unknown_field", state["column"])
        if action == "correct" and d.get("reason") not in REASONS:
            raise DecisionError("bad_reason", state["column"])
        if action == "confirm":
            if state["state"] in ("auto", "confirmed", "corrected", "unused") and field is None:
                continue                                       # nothing to accept
            if state["state"] != "needs":
                field = state["field"]
        if field:
            holder = next((s for s in states if s["field"] == field and s["column"] != state["column"]
                           and s["state"] in MAPPED and not _is_volume(s)), None)
            if holder:
                raise DecisionError("field_held", holder["column"])
        was_needs = state["state"] == "needs"
        state["field"] = field
        state["state"] = ("confirmed" if action == "confirm" else "corrected") if field else "unused"
        state["decision"] = action
        state["reason"] = d.get("reason") if action == "correct" else None
        if was_needs:
            state["source"] = "decision"
    return states
