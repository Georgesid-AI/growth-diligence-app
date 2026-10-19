"""Redaction of deck structure cells, and the structure text the model reads (pure, no I/O).

Spec: docs/specs/llm-structure-reading.md section 3; CLAUDE.md rule 16. Nothing here reads a
database or a file, and nothing here calls a model: the gateway runs these same functions again
on the text it is given and refuses the call if anything changes. Names are matched as whole
words, in any case; a word ends at a space, punctuation, a hyphen or a change of case. The client
name becomes [redacted]; customer names their pseudonyms.

The text is one line per cell, `r<row>c<col>: <cell text>`, with no file name, slide number or
prose. A merged cell carries its span after its text, `r1c3: FY2025 (r1c3:r1c14)`, so the model
receives the full header stack (deck-parser.md section 2). A slide title a KPI panel takes as the label
of a value is marked, `r1c1 title: 2011 Estimated Revenue` (deck-parser.md section 7): a label, never a
value, so no item line may cite it. Below a deck structure's cells comes its
item list (structure-labelling.md section 3): the lines are written and checked here, so the
gateway checks them with no link to the deck package.
"""
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from ..llm.schemas import MAPPING_FIELDS

_LINE = re.compile(r"^r(?P<row>\d+)c(?P<col>\d+)(?P<title> title)?: (?P<text>.*?)"
                   r"(?: \(r(?P=row)c(?P=col):r(?P<row2>\d+)c(?P<col2>\d+)\))?$")
TITLE = " title"           # after a title cell's id in its line: the slide title, a KPI value's label


def cell_id(cell: Dict) -> str:
    return f"r{cell['row']}c{cell['col']}"


def cell_text(cell: Dict) -> str:
    """A cell's text as its line writes it: on one line, single spaces. Item raw text is cut from this too."""
    return re.sub(r"\s+", " ", str(cell["text"])).strip()


def structure_text(cells: List[Dict]) -> str:
    """The structure as the model reads it: one `r<row>c<col>: <text>` line per cell, in reading order; a title
    cell's id is followed by its mark (`r1c1 title: <text>`)."""
    lines = []
    for c in sorted(cells, key=lambda c: (c["row"], c["col"])):
        text = cell_text(c)
        if not text:
            continue
        rows, cols = c.get("row_span", 1), c.get("col_span", 1)
        span = f" ({cell_id(c)}:r{c['row'] + rows - 1}c{c['col'] + cols - 1})" if rows > 1 or cols > 1 else ""
        lines.append(f"{cell_id(c)}{TITLE if c.get('title') else ''}: {text}{span}")
    return "\n".join(lines)


def parse_structure_text(text: str) -> Optional[List[Dict]]:
    """The cells of a structure text, or None when a line is not a cell line."""
    cells = []
    for line in (text or "").split("\n"):
        m = _LINE.match(line)
        if not m:
            return None
        cell = {"row": int(m.group("row")), "col": int(m.group("col")), "text": m.group("text")}
        if m.group("title"):
            cell["title"] = True
        if m.group("row2"):
            rows, cols = int(m.group("row2")) - cell["row"] + 1, int(m.group("col2")) - cell["col"] + 1
            if rows > 1:
                cell["row_span"] = rows
            if cols > 1:
                cell["col_span"] = cols
        cells.append(cell)
    return cells


# ---------------------------------------------------------------------------
# The item list (docs/specs/structure-labelling.md section 3): below a deck structure's cell lines,
# the line "items:", then one line per figure Python listed, its raw text cut from its cell:
#     i3 r3c2#2 "(30K)" 30000 or -30000 h r3c1 r1c2
# (id, cell and "#position" when the cell holds several figures, raw text, values with Python's
# default first, "h" and the header cells). A roadmap adds its date cells and text lines, "d1 r2c1",
# "t1 r1c1". The figure patterns live here so the gateway checks a line without the deck package.
# ---------------------------------------------------------------------------
ITEMS_HEADER = "items:"
CURRENCY = re.compile(r"US\$|[£$€¥₹]|\b(?:USD|EUR|GBP|CHF|JPY|BGN|PLN|SEK|NOK|DKK|CAD|AUD)\b")
# A scale word is read in any case ("Million"), as in the parser's reader (issue #65).
SUFFIX = (r"(?:\s?(?P<suffix>k|K|mn|MM|m|M|bn|B|(?i:thousand|million|billion)|Mio|Mrd|Tsd|млн|млрд|хил)"
          r"(?![^\W\d_]))?")
# A figure, keyed by whether the structure writes a decimal comma (1.234,5). A digit inside a word is no figure, as
# in the parser's reader (claims.figures): no letter directly before it ("zero2hero", "Web3"), no ordinal ending
# ("1st") (structure-labelling.md section 1).
NUMBER = {
    False: re.compile(r"(?P<open>\()?\s*(?:(?<![\w.])(?P<sign>[-−–]))?\s*(?<![\d.,])(?<![^\W\d_])"
                      r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d]|[.,]\d|st|nd|rd|th)"
                      + SUFFIX + r"\s*(?P<pct>%)?\s*(?P<close>\))?"),
    True: re.compile(r"(?P<open>\()?\s*(?:(?<![\w.])(?P<sign>[-−–]))?\s*(?<![\d.,])(?<![^\W\d_])"
                     r"(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(?![\d]|[.,]\d|st|nd|rd|th)"
                     + SUFFIX + r"\s*(?P<pct>%)?\s*(?P<close>\))?"),
}
_VALUE = r"-?\d+(?:\.\d+)?"
_CELL = r"r[1-9]\d*c[1-9]\d*"
_ITEM_LINE = re.compile(rf'^(?P<id>i[1-9]\d*) (?P<cell>{_CELL})(?:#(?P<position>[1-9]\d*))? "(?P<raw>[^"]{{1,60}})" '
                        rf'(?P<values>{_VALUE}(?: or {_VALUE}){{0,3}})(?: h(?P<headers>(?: {_CELL})+))?$')
_LISTED_LINE = re.compile(rf"^(?P<id>[dt][1-9]\d*) (?P<cell>{_CELL})$")


def blank_currency(text: str) -> str:
    """The text with each currency symbol or code turned into as many spaces, so positions still hold."""
    return CURRENCY.sub(lambda m: " " * len(m.group(0)), text)


def is_figure(raw: str) -> bool:
    """True when the text is one figure and nothing else ("(30K)", "-$13 million", "1.234,5")."""
    blanked = blank_currency(raw).strip()
    return any(NUMBER[comma].fullmatch(blanked) for comma in (False, True))


def number_text(value: float) -> str:
    """A value as an item line writes it: 30000, -2.5, never an exponent."""
    value = float(value)
    if value.is_integer():
        return str(int(value))
    text = repr(value)
    return format(value, "f").rstrip("0").rstrip(".") if "e" in text else text


def item_lines(listed: Dict) -> List[str]:
    """The lines below "items:" for {"items", "dates", "lines"} (see structures.items.list_items)."""
    out, per_cell = [], Counter(item["cell"] for item in listed.get("items") or ())
    for item in listed.get("items") or ():
        cell = f"{item['cell']}#{item['position']}" if per_cell[item["cell"]] > 1 else item["cell"]
        values = " or ".join(number_text(v["value"]) for v in item["values"])
        heads = (" h " + " ".join(item["headers"])) if item.get("headers") else ""
        out.append(f'{item["id"]} {cell} "{item["raw"]}" {values}{heads}')
    out += [f"{d['id']} {d['cell']}" for d in listed.get("dates") or ()]
    out += [f"{t['id']} {t['cell']}" for t in listed.get("lines") or ()]
    return out


def split_items(text: str) -> Tuple[str, Optional[List[str]]]:
    """(the cell lines, the lines below "items:" or None when the text has no item list)."""
    lines = (text or "").split("\n")
    if ITEMS_HEADER not in lines:
        return text, None
    at = lines.index(ITEMS_HEADER)
    return "\n".join(lines[:at]), lines[at + 1:]


def parse_item_lines(lines: List[str]) -> Optional[Dict]:
    """{"items": [{"id", "cell", "position", "raw", "values", "headers"}], "dates": [...], "lines": [...]}, or None
    when a line is neither an item line nor a date or text line."""
    out = {"items": [], "dates": [], "lines": []}
    for line in lines:
        item, listed = _ITEM_LINE.match(line), _LISTED_LINE.match(line)
        if item:
            out["items"].append({"id": item.group("id"), "cell": item.group("cell"),
                                 "position": int(item.group("position") or 1), "raw": item.group("raw"),
                                 "values": [float(v) for v in item.group("values").split(" or ")],
                                 "headers": (item.group("headers") or "").split()})
        elif listed:
            out["dates" if listed.group("id")[0] == "d" else "lines"].append(
                {"id": listed.group("id"), "cell": listed.group("cell")})
        else:
            return None
    return out


def items_in_format(lines: List[str], cells: List[Dict], roadmap: bool) -> bool:
    """True when every line below "items:" is in format (CLAUDE.md rule 16): ids numbered in order, every cited
    cell sent, each item's raw text a figure inside its cell and never in a title cell, date and text lines on a
    roadmap only."""
    parsed = parse_item_lines(lines)
    if parsed is None:
        return False
    by_id = {cell_id(c): c["text"] for c in cells}
    titles = {cell_id(c) for c in cells if c.get("title")}
    for key, prefix in (("items", "i"), ("dates", "d"), ("lines", "t")):
        if [x["id"] for x in parsed[key]] != [f"{prefix}{n}" for n in range(1, len(parsed[key]) + 1)]:
            return False
        if any(x["cell"] not in by_id for x in parsed[key]):
            return False
    if (parsed["dates"] or parsed["lines"]) and not roadmap:
        return False
    return all(item["raw"] in by_id[item["cell"]] and is_figure(item["raw"]) and item["cell"] not in titles
               and all(h in by_id for h in item["headers"]) for item in parsed["items"])


# ---------------------------------------------------------------------------
# The column-mapping text: a spreadsheet's header rows (at most 3, the 3 nearest the data), up to
# 3 sample values per numeric or date column, a profile instead of values per text column, and the
# rules' proposal per column as a hint (a field of the closed list and its confidence, 0 to 100).
#     r1c2: Invoice Date
#     c2 sample: 2025-01-31
#     c1 profile: distinct 42, typical length 12, shape Aa a
#     c2 rule: invoice_date 100
# No text cell value is ever on this path: a sample is a number or an ISO date, nothing else.
# ---------------------------------------------------------------------------
MAX_HEADER_ROWS = 3
MAX_SAMPLES = 3
_SAMPLE_LINE = re.compile(r"^c(?P<col>\d+) sample: (?P<value>.+)$")
_HINT_LINE = re.compile(r"^c(?P<col>\d+) rule: (?P<field>.+?) (?P<confidence>\d+)$")
_PROFILE_LINE = re.compile(r"^c(?P<col>\d+) profile: distinct (?P<distinct>\d+), typical length (?P<length>\d+), "
                           r"shape (?P<shape>[Aa0 \-_./@:,#()+&']{1,20})$")
# A sample value: a number (sign, currency symbol, separators, %) or an ISO date or date-time.
SAMPLE_VALUE = re.compile(r"^(?:[-+(]?\s?(?:[£$€¥]\s?)?\d[\d,]*(?:\.\d+)?\s?%?\)?"
                          r"|\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?)$")


def column_text(headers: List[Dict], samples: Dict[int, List[str]], profiles: Dict[int, Dict],
                hints: Optional[Dict[int, Tuple[str, int]]] = None) -> str:
    """The column-mapping text: header cells, then samples, then profiles, then the rules' hints, each in column order."""
    lines = [structure_text(headers)] if headers else []
    lines += [f"c{col} sample: {value}" for col in sorted(samples) for value in samples[col]]
    lines += [f"c{col} profile: distinct {p['distinct']}, typical length {p['length']}, shape {p['shape']}"
              for col, p in sorted(profiles.items())]
    lines += [f"c{col} rule: {field} {confidence}" for col, (field, confidence) in sorted((hints or {}).items())]
    return "\n".join(line for line in lines if line)


def parse_column_text(text: str) -> Optional[Dict]:
    """{"headers": cells, "samples": {col: [values]}, "profiles": {col: {...}}, "hints": [(col, field, confidence)]},
    or None when a line is neither a header cell, a sample, a profile nor a hint."""
    headers, samples, profiles, hints = [], {}, {}, []
    for line in (text or "").split("\n"):
        sample, profile, hint = _SAMPLE_LINE.match(line), _PROFILE_LINE.match(line), _HINT_LINE.match(line)
        if hint:
            hints.append((int(hint.group("col")), hint.group("field"), int(hint.group("confidence"))))
        elif sample:
            samples.setdefault(int(sample.group("col")), []).append(sample.group("value"))
        elif profile:
            profiles[int(profile.group("col"))] = {"distinct": int(profile.group("distinct")),
                                                   "length": int(profile.group("length")), "shape": profile.group("shape")}
        else:
            cells = parse_structure_text(line)
            if not cells:
                return None
            headers += cells
    return {"headers": headers, "samples": samples, "profiles": profiles, "hints": hints}


def column_text_problem(text: str) -> Optional[str]:
    """Why a column-mapping text may not reach the model, or None: more than 3 header rows, more than
    3 samples for a column, a sample that is not a number or a date (a text cell value), a column
    with both samples and a profile, or a hint that is not one field of the closed list and a
    confidence from 0 to 100, once per column."""
    parsed = parse_column_text(text)
    if parsed is None:
        return "not_cells"
    if len({c["row"] for c in parsed["headers"]}) > MAX_HEADER_ROWS or \
            any(c["row"] + c.get("row_span", 1) - 1 > MAX_HEADER_ROWS for c in parsed["headers"]):
        return "too_many_header_rows"
    if any(len(v) > MAX_SAMPLES for v in parsed["samples"].values()):
        return "too_many_samples"
    if any(not SAMPLE_VALUE.match(v) for values in parsed["samples"].values() for v in values):
        return "text_value"
    if set(parsed["samples"]) & set(parsed["profiles"]):
        return "text_value"
    hinted = [col for col, _, _ in parsed["hints"]]
    if len(set(hinted)) != len(hinted) or \
            any(field not in MAPPING_FIELDS or confidence > 100 for _, field, confidence in parsed["hints"]):
        return "bad_hint"
    return None


# ---------------------------------------------------------------------------
# The file-type text (chat-upload.md section 19): what the model reads to tell revenue, CRM and P&L files apart when the
# rules cannot. Per sheet: its name, the title rows above its header, its header row, and the masked sample of the
# column-mapping text (up to 3 numbers or dates per numeric or date column, a profile per text column). One line each:
#     s1: Revenue
#     s1 title r2c3: Revenue through 31 December 2028
#     s1 header r5c3: 2023
#     s1 c3 sample: 1200
#     s1 c1 profile: distinct 8, typical length 11, shape Aa a
# No text cell value of a data row is ever on this path.
# ---------------------------------------------------------------------------
FILE_MAX_SHEETS = 6
FILE_MAX_TITLE_ROWS = 6
FILE_MAX_COLUMNS = 40
_FT_SHEET = re.compile(r"^s(?P<s>\d+): (?P<text>.+)$")
_FT_TITLE = re.compile(r"^s(?P<s>\d+) title r(?P<row>\d+)c(?P<col>\d+): (?P<text>.+)$")
_FT_HEADER = re.compile(r"^s(?P<s>\d+) header r(?P<row>\d+)c(?P<col>\d+): (?P<text>.+)$")
_FT_SAMPLE = re.compile(r"^s(?P<s>\d+) c(?P<col>\d+) sample: (?P<value>.+)$")
_FT_PROFILE = re.compile(r"^s(?P<s>\d+) c(?P<col>\d+) profile: distinct (?P<distinct>\d+), typical length (?P<length>\d+), "
                         r"shape (?P<shape>[Aa0 \-_./@:,#()+&']{1,20})$")


def file_type_text(sheets: List[Dict]) -> str:
    """The text for [{"name", "titles": [cell], "headers": [cell], "samples": {col: [v]}, "profiles": {col: {...}}}]."""
    lines = []
    for k, sheet in enumerate(sheets, 1):
        lines.append(f"s{k}: {cell_text({'text': sheet['name']})}")
        lines += [f"s{k} title r{c['row']}c{c['col']}: {cell_text(c)}" for c in sheet["titles"] if cell_text(c)]
        lines += [f"s{k} header r{c['row']}c{c['col']}: {cell_text(c)}" for c in sheet["headers"] if cell_text(c)]
        lines += [f"s{k} c{col} sample: {v}" for col in sorted(sheet["samples"]) for v in sheet["samples"][col]]
        lines += [f"s{k} c{col} profile: distinct {p['distinct']}, typical length {p['length']}, shape {p['shape']}"
                  for col, p in sorted(sheet["profiles"].items())]
    return "\n".join(lines)


def parse_file_type_text(text: str) -> Optional[List[Dict]]:
    """The sheets of a file-type text, or None when a line is of no kind above or a sheet line is out of order."""
    sheets: Dict[int, Dict] = {}
    for line in (text or "").split("\n"):
        for kind, rx in (("name", _FT_SHEET), ("titles", _FT_TITLE), ("headers", _FT_HEADER), ("sample", _FT_SAMPLE),
                         ("profile", _FT_PROFILE)):
            m = rx.match(line)
            if m:
                break
        else:
            return None
        k = int(m.group("s"))
        if kind == "name":
            if k in sheets or k != len(sheets) + 1:
                return None
            sheets[k] = {"name": m.group("text"), "titles": [], "headers": [], "samples": {}, "profiles": {}}
            continue
        if k not in sheets:
            return None
        if kind in ("titles", "headers"):
            sheets[k][kind].append({"row": int(m.group("row")), "col": int(m.group("col")), "text": m.group("text")})
        elif kind == "sample":
            sheets[k]["samples"].setdefault(int(m.group("col")), []).append(m.group("value"))
        else:
            sheets[k]["profiles"][int(m.group("col"))] = {"distinct": int(m.group("distinct")),
                                                           "length": int(m.group("length")), "shape": m.group("shape")}
    return list(sheets.values()) or None


def file_type_cells(sheet: Dict) -> List[Dict]:
    """The text cells of one sheet in the order redaction reads them: the name (row 0, column 0), titles, headers."""
    return [{"row": 0, "col": 0, "text": sheet["name"]}] + list(sheet["titles"]) + list(sheet["headers"])


def file_type_text_problem(text: str) -> Optional[str]:
    """Why a file-type text may not reach the model, or None: a line of no kind, more than 6 sheets, 6 title rows
    or 40 columns, a sample that is not a number or a date, or a column with both a sample and a profile."""
    sheets = parse_file_type_text(text)
    if sheets is None:
        return "not_cells"
    if len(sheets) > FILE_MAX_SHEETS or any(len({c["row"] for c in s["titles"]}) > FILE_MAX_TITLE_ROWS for s in sheets):
        return "too_many_header_rows"
    if any(len({c["col"] for c in s["headers"]}) > FILE_MAX_COLUMNS or len({c["row"] for c in s["headers"]}) > 1
           for s in sheets):
        return "too_many_header_rows"
    if any(len(v) > MAX_SAMPLES for s in sheets for v in s["samples"].values()):
        return "too_many_samples"
    if any(not SAMPLE_VALUE.match(v) for s in sheets for values in s["samples"].values() for v in values):
        return "text_value"
    if any(set(s["samples"]) & set(s["profiles"]) for s in sheets):
        return "text_value"
    return None


# ---------------------------------------------------------------------------
# The recognition text (docs/specs/revenue-file-recognition.md section 5): the file-type text above, plus a labels line per sheet and
# one label line per row label. A sheet whose labels the rules read as metric names sends them as written (after redaction); any other
# sheet sends "Row 1", "Row 2" ...; a records layout has no labels line at all. The gateway checks these lines with no link to the sheet reader.
#     s1 labels: metric                      (or: s1 labels: masked)
#     s1 label r4: Recognised revenue (EUR)  (masked: s1 label r4: Row 1)
# ---------------------------------------------------------------------------
RECOGNITION_MAX_ROWS = 400              # rows with text per sheet, title and header rows included
_RC_LABELS = re.compile(r"^s(?P<s>\d+) labels: (?P<mode>metric|masked)$")
_RC_LABEL = re.compile(r"^s(?P<s>\d+) label r(?P<row>[1-9]\d*): (?P<text>.+)$")
_MASKED_LABEL = re.compile(r"^Row [1-9]\d*$")


def recognition_text(sheets: List[Dict]) -> str:
    """The text for [{"name", "titles", "headers", "labels": None | "metric" | "masked", "label_rows": [(row, text)], "samples",
    "profiles"}]: the lines of file_type_text, and after a sheet's headers its labels line and its label lines."""
    lines = []
    for k, sheet in enumerate(sheets, 1):
        lines.append(f"s{k}: {cell_text({'text': sheet['name']})}")
        lines += [f"s{k} title r{c['row']}c{c['col']}: {cell_text(c)}" for c in sheet["titles"] if cell_text(c)]
        lines += [f"s{k} header r{c['row']}c{c['col']}: {cell_text(c)}" for c in sheet["headers"] if cell_text(c)]
        if sheet.get("labels"):
            lines.append(f"s{k} labels: {sheet['labels']}")
            lines += [f"s{k} label r{row}: {text}" for row, text in sheet.get("label_rows") or [] if text]
        lines += [f"s{k} c{col} sample: {v}" for col in sorted(sheet["samples"]) for v in sheet["samples"][col]]
        lines += [f"s{k} c{col} profile: distinct {p['distinct']}, typical length {p['length']}, shape {p['shape']}"
                  for col, p in sorted(sheet["profiles"].items())]
    return "\n".join(lines)


def parse_recognition_text(text: str) -> Optional[List[Dict]]:
    """The sheets of a recognition text, or None when a line is of no kind, a sheet line is out of order or a label line comes
    before its sheet's labels line."""
    sheets: Dict[int, Dict] = {}
    for line in (text or "").split("\n"):
        for kind, rx in (("name", _FT_SHEET), ("titles", _FT_TITLE), ("headers", _FT_HEADER), ("sample", _FT_SAMPLE),
                         ("profile", _FT_PROFILE), ("mode", _RC_LABELS), ("label", _RC_LABEL)):
            m = rx.match(line)
            if m:
                break
        else:
            return None
        k = int(m.group("s"))
        if kind == "name":
            if k in sheets or k != len(sheets) + 1:
                return None
            sheets[k] = {"name": m.group("text"), "titles": [], "headers": [], "samples": {}, "profiles": {}, "labels": None,
                         "label_rows": []}
            continue
        if k not in sheets:
            return None
        sheet = sheets[k]
        if kind in ("titles", "headers"):
            sheet[kind].append({"row": int(m.group("row")), "col": int(m.group("col")), "text": m.group("text")})
        elif kind == "sample":
            sheet["samples"].setdefault(int(m.group("col")), []).append(m.group("value"))
        elif kind == "profile":
            sheet["profiles"][int(m.group("col"))] = {"distinct": int(m.group("distinct")), "length": int(m.group("length")),
                                                      "shape": m.group("shape")}
        elif kind == "mode":
            if sheet["labels"] is not None:
                return None
            sheet["labels"] = m.group("mode")
        else:
            if sheet["labels"] is None:
                return None
            sheet["label_rows"].append((int(m.group("row")), m.group("text")))
    return list(sheets.values()) or None


def recognition_cells(sheet: Dict) -> List[Dict]:
    """The text cells of one sheet in the order redaction reads them: the name, titles, headers and the label lines (column 0)."""
    return file_type_cells(sheet) + [{"row": row, "col": 0, "text": text} for row, text in sheet.get("label_rows") or []]


def recognition_text_problem(text: str) -> Optional[str]:
    """Why a recognition text may not reach the model, or None: the problems of the file-type text, a label line on a masked sheet
    that is not "Row n", a label that is a figure, or more than 400 rows with text on one sheet."""
    sheets = parse_recognition_text(text)
    if sheets is None:
        return "not_cells"
    problem = file_type_text_problem("\n".join(l for l in text.split("\n") if not (_RC_LABELS.match(l) or _RC_LABEL.match(l))))
    if problem:
        return problem
    for sheet in sheets:
        if sheet["labels"] == "masked" and any(not _MASKED_LABEL.match(t) for _, t in sheet["label_rows"]):
            return "label_on_masked_sheet"
        if any(is_figure(t) for _, t in sheet["label_rows"]):
            return "figure_in_label"
        rows = {c["row"] for c in sheet["titles"] + sheet["headers"]} | {r for r, _ in sheet["label_rows"]}
        if len(rows) > RECOGNITION_MAX_ROWS:
            return "too_many_rows"
    return None


# ---------------------------------------------------------------------------
# Redaction (spec section 3)
# ---------------------------------------------------------------------------
EMAIL, PHONE, PERSON, REDACTED = "[email]", "[phone]", "[person]", "[redacted]"
PLACEHOLDERS = (EMAIL, PHONE, PERSON, REDACTED)
_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
# "+" or "0" followed by 9-15 digits in groups: +44 20 7946 0958, 020-7946-0958, (0)20 7946 0958.
_PHONE = re.compile(r"(?<![\w+])(?:\+|(?<![\d.,])0)(?:[\s().\-/]{0,2}\d){9,15}(?![\d])")
# A cell that is an amount, a year or a date is never a phone number.
_AMOUNT = re.compile(r"^\s*[(+\-−]?\s*(?:US\$|[£$€¥₹])?\s*\d{1,3}(?:[,.]\d{3})*(?:[.,]\d+)?\s*"
                     r"(?:k|m|mn|bn|thousand|million|billion|%)?\s*\)?\s*$", re.IGNORECASE)
_YEAR_OR_DATE = re.compile(r"^\s*(?:(?:19|20)\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}(?:-\d{2})?)\s*$")
# Person-role headers: a name-shaped cell under one is a person ("Hire: Jane Doe").
_PERSON_ROLE = re.compile(r"(?i)(?<![^\W\d_])(?:names?|founders?|co-founders?|ceo|owners?|contacts?|hires?)(?![^\W\d_])")
# 1 to 4 capitalised words, no digits: "Jane Doe", "J. Smith", "Иван Петров"; not "Head of Sales".
_NAME_SHAPE = re.compile(r"^\s*(?:[^\W\d_a-zа-я][^\W\d_]*\.?(?:[-'’][^\W\d_]+)*)(?:\s+[^\W\d_a-zа-я][^\W\d_]*\.?(?:[-'’][^\W\d_]+)*){0,3}\s*$")
_PSEUDONYM = re.compile(r"Customer_\d+|Segment [A-Z]+")
CUSTOMER_PREFIX = "Customer_"
MIN_NAME_LENGTH = 4

# Bundled first names (English, German, French, Bulgarian in Latin and Cyrillic letters). Words that
# are also everyday words in a deck ("May", "Will", "Mark", "Max", "Grace", "Hope") are left out.
FIRST_NAMES = frozenset("""
Aaron Adam Adrian Alan Albert Alex Alexander Alexandra Alice Alicia Alison Amanda Amelia Amy Andrea Andreas Andrew Angela
Anja Ann Anna Anne Anthony Antoine Anton Ashley Barbara Ben Benjamin Bernard Beth Birgit Boris Brandon Brenda Brian Bruce
Camille Carl Carlos Carol Caroline Catherine Charles Charlie Charlotte Chloe Chloé Chris Christian Christina Christine
Christopher Claire Claudia Daniel Daniela David Deborah Dennis Diana Diane Dieter Dimitar Donna Dorothy Douglas Edward
Elena Elizabeth Ella Emil Emily Emma Eric Erik Eva Evgeni Felix Finn Florian Frank Gabriel Gary George Georgi Gergana
Gillian Gregory Hannah Hans Harry Heather Helen Henry Hristo Hugo Ian Isabel Isabella Ivan Ivanka Jack Jacob James Jan
Jane Janet Jason Jean Jeffrey Jennifer Jessica Joan Johannes John Jonas Jonathan Joseph Joshua Julia Julian Julien Julie
Jürgen Justin Kalina Karen Katharina Katherine Kathleen Katrin Kevin Kiril Klaus Krasimir Kyle Laura Lauren Lea Lena
Leon Linda Lisa Louis Louise Lucas Lukas Lyubomir Margaret Maria Marie Marina Marion Markus Martin Mary Mathilde Matthew
Matthias Maximilian Megan Melissa Mia Michael Michelle Milena Monika Moritz Nadezhda Nancy Natalie Nicholas Nicolas Nicole
Niklas Nikolay Oliver Olivia Pamela Patricia Patrick Paul Peter Petar Petra Philip Pierre Plamen Rachel Radostina Rebecca
Richard Robert Ronald Rumen Ryan Samantha Samuel Sandra Sarah Scott Sebastian Sharon Shirley Simon Sophia Sophie Stefan
Stephanie Stephen Steven Stoyan Susan Susanne Svetlana Teodora Thomas Tim Timothy Tobias Todor Tsvetelina Ursula Valentin
Vasil Victoria Viktoria Vincent William Wolfgang Yavor Yordanka Zdravko
Иван Георги Димитър Николай Петър Христо Стоян Тодор Васил Пламен Красимир Мартин Борис Кирил Мария Елена Иванка
Десислава Гергана Радостина Цветелина Светлана Йорданка Милена Теодора Виктория Калина Надежда Румен Любомир Стефан
Александър Атанас Емил Евгени Огнян Валентин Венцислав Явор Здравко
""".split())
_FIRST_NAME = re.compile(r"(?<![^\W\d_])(?:" + "|".join(sorted(map(re.escape, FIRST_NAMES), key=len, reverse=True))
                         + r")\s+[^\W\d_a-zа-я][^\W\d_]+(?:[-'’][^\W\d_]+)?(?![^\W\d_])")


def _edge(text: str, i: int) -> bool:
    """True when position i of the text is a word boundary: the start or end of the text, a character
    that is not a letter or a digit on either side (a space, punctuation, a hyphen), or a change of
    case: "acmeCorp" between e and C, "ACMECorp" between E and C."""
    if i <= 0 or i >= len(text):
        return True
    a, b = text[i - 1], text[i]
    if not a.isalnum() or not b.isalnum():
        return True
    return (a.islower() and b.isupper()) or (a.isupper() and b.isupper() and i + 1 < len(text) and text[i + 1].islower())


def _word_spans(text: str, word: str) -> List[Tuple[int, int]]:
    """Every place the word stands as a whole word in the text, in any case, overlaps included."""
    word = (word or "").strip()
    if not word:
        return []
    found = (m.span(1) for m in re.finditer("(?=(" + re.escape(word) + "))", text, re.IGNORECASE))
    return [(s, e) for s, e in found if _edge(text, s) and _edge(text, e)]


def has_word(text: str, word: Optional[str]) -> bool:
    """True when the word stands in the text as a whole word, in any case (the boundaries of _edge)."""
    return bool(_word_spans(text or "", word))


def _protected(text: str, company_name: Optional[str]) -> List[Tuple[int, int]]:
    """Spans no rule may rewrite: the target company's own name (as a whole word), existing pseudonyms
    and placeholders."""
    spans = [m.span() for m in _PSEUDONYM.finditer(text)]
    spans += [(m.start(), m.end()) for p in PLACEHOLDERS for m in re.finditer(re.escape(p), text)]
    spans += _word_spans(text, company_name)
    return spans


def _replace(text: str, pattern: "re.Pattern", repl, company_name: Optional[str]) -> Tuple[str, int]:
    """Replace every match of `pattern` that does not overlap a protected span."""
    keep = _protected(text, company_name)
    out, last, count = [], 0, 0
    for m in pattern.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in keep):
            continue
        out.append(text[last:m.start()])
        out.append(repl(m) if callable(repl) else repl)
        last, count = m.end(), count + 1
    return "".join(out) + text[last:], count


def _is_amount_or_date(text: str) -> bool:
    return bool(_AMOUNT.match(text) or _YEAR_OR_DATE.match(text))


def _under_person_role(cell: Dict, cells: List[Dict]) -> bool:
    """True when a cell above it in its column range is a person-role header (name, founder, CEO...)."""
    span = range(cell["col"], cell["col"] + cell.get("col_span", 1))
    return any(c["row"] < cell["row"] and any(k in range(c["col"], c["col"] + c.get("col_span", 1)) for k in span)
               and _PERSON_ROLE.search(c["text"]) for c in cells)


def redact_cells(cells: List[Dict], company_name: Optional[str]) -> Tuple[List[Dict], Dict[str, int]]:
    """(cells, counts): emails become [email]; phone numbers become [phone] ("+" or "0" and 9-15 digits
    in groups, never in a cell that is an amount, a year or a date); names become [person] (a
    name-shaped cell under a person-role header, or two capitalised words starting with a bundled
    first name). The target company's name, pseudonyms and placeholders are never rewritten, so a
    second pass changes nothing. The input is not modified."""
    return _redact(cells, company_name, ("email", "phone", "person"))


def _redact(cells: List[Dict], company_name: Optional[str], rules) -> Tuple[List[Dict], Dict[str, int]]:
    counts = {"email": 0, "phone": 0, "person": 0}
    out = []
    for cell in cells:
        text = cell["text"]
        if "email" in rules:
            text, n = _replace(text, _EMAIL, EMAIL, company_name)
            counts["email"] += n
        if "phone" in rules and not _is_amount_or_date(text):
            text, n = _replace(text, _PHONE, PHONE, company_name)
            counts["phone"] += n
        if "person" in rules:
            if _NAME_SHAPE.match(text) and _under_person_role(cell, cells) and not _protected(text, company_name):
                text, n = PERSON, 1
            else:
                text, n = _replace(text, _FIRST_NAME, PERSON, company_name)
            counts["person"] += n
        out.append({**cell, "text": text})
    return out, counts


def _replace_words(text: str, words: List[Tuple[str, str]], company_name: Optional[str]) -> Tuple[str, int]:
    """Replace each (word, replacement) wherever the word stands as a whole word, in any case. Where two
    words overlap the longer one wins; protected spans are never rewritten."""
    taken = _protected(text, company_name)
    found = []
    for word, repl in sorted(words, key=lambda w: len(w[0].strip()), reverse=True):
        for s, e in _word_spans(text, word):
            if not any(s < b and a < e for a, b in taken):
                taken.append((s, e))
                found.append((s, e, repl))
    out, last = [], 0
    for s, e, repl in sorted(found):
        out += [text[last:s], repl]
        last = e
    return "".join(out) + text[last:], len(found)


def _usable_name(name: str) -> bool:
    """A customer name the replacement may use: 4 characters or more, not a number or a date."""
    name = (name or "").strip()
    return len(name) >= MIN_NAME_LENGTH and not re.fullmatch(r"[\d\s.,:/%+\-]+", name) and not _YEAR_OR_DATE.match(name)


def customer_names(mapping: Dict[str, str], company_name: Optional[str]) -> List[Tuple[str, str]]:
    """(name, pseudonym) for every usable customer name in the mapping. The target company's own name
    and existing pseudonyms are never among them."""
    company = (company_name or "").strip().lower()
    return [(real.strip(), pseudo) for real, pseudo in mapping.items() if pseudo.startswith(CUSTOMER_PREFIX)
            and _usable_name(real) and real.strip().lower() != company and not _PSEUDONYM.fullmatch(real.strip())]


def pseudonymise_cells(cells: List[Dict], mapping: Dict[str, str], company_name: Optional[str]
                       ) -> Tuple[List[Dict], int]:
    """(cells, count): every customer name in the per-audit mapping (pseudonym_map, shared with the
    narrative path) is replaced by its pseudonym wherever it stands as a whole word, in any case. A
    word ends at the start or end of the cell, a space, punctuation, a hyphen or a change of case
    ("AcmeCorp" holds Acme; "Acmes" and "customers" hold no Acme or Cust). Names under 4 characters,
    numbers and dates are skipped; the target company's own name and existing pseudonyms are never
    rewritten, so a second pass changes nothing."""
    names = customer_names(mapping, company_name)
    total, out = 0, []
    for cell in cells:
        text, n = _replace_words(cell["text"], names, company_name) if names else (cell["text"], 0)
        total += n
        out.append({**cell, "text": text})
    return out, total


def file_type_withheld(audit: Dict) -> Tuple[str, ...]:
    """What the file-type text withholds (chat-upload.md section 19): the target company's own name, which often stands in
    a sheet name or a title row ("<Company> LTD - April 2024 Report"). Unit markers are untouched."""
    company = str(audit.get("company_name") or "").strip()
    return (company,) if company else ()


def withhold_cells(cells: List[Dict], withheld: Tuple[str, ...]) -> Tuple[List[Dict], int]:
    """(cells, count): each withheld value (the target company's name, in the file-type text) becomes
    [redacted] wherever it stands as a whole word, in any case. The target's own name does not shield
    it; placeholders and pseudonyms are left alone."""
    words = [(w, REDACTED) for w in withheld if w and w.strip()]
    total, out = 0, []
    for cell in cells:
        text, n = _replace_words(cell["text"], words, None) if words else (cell["text"], 0)
        total += n
        out.append({**cell, "text": text})
    return out, total


def redact_structure(cells: List[Dict], company_name: Optional[str], mapping: Dict[str, str],
                     withheld: Tuple[str, ...] = ()) -> Tuple[List[Dict], Dict[str, int]]:
    """Every redaction rule on a structure's cells: the withheld values
    (`withheld`, see file_type_withheld), then emails and phone numbers, then customer names, then
    personal names. What the gateway runs again before a call."""
    # The withheld values go first, so no other rule can split one; emails and phones next, so a
    # customer name inside an address goes with it; customer names before personal names, so a
    # customer listed under a "Contact" header keeps its pseudonym.
    held, withheld_count = withhold_cells(cells, withheld)
    first, counts = _redact(held, company_name, ("email", "phone"))
    counts["withheld"] = withheld_count
    named, counts["customer"] = pseudonymise_cells(first, mapping, company_name)
    second, more = _redact(named, company_name, ("person",))
    counts["person"] = more["person"]
    return second, counts


# ---------------------------------------------------------------------------
# The sheet skeleton (chat-upload.md section 26): a P&L the rules cannot map, read as a statement. One line per non-blank text
# cell (title rows, headers and every row label), one line per row with content giving its indent and which columns hold a number
# or are blank, and one line per withheld column. Never a figure: a number is only "num" in its row's line.
#     r1c1: Product P&L, EUR thousands
#     r2c2: FY2021
#     r4c1: Revenue
#     r4 indent 0 num c2-c7
#     c1 withheld: text, 35 distinct values
# The lines are written and checked here, so the gateway checks them with no link to the sheet reader.
# ---------------------------------------------------------------------------
SHEET_MAX_ROWS = 400                # rows with text, title and header rows included; past it, the first 400 are read
WITHHOLD_DISTINCT = 30              # a column with 30 or more distinct texts ...
WITHHOLD_FINANCE_SHARE = 0.2        # ... under 20% of which hold a finance word is withheld: its body cells are never sent
_COLS = r"c[1-9]\d*(?:-c[1-9]\d*)?(?:,c[1-9]\d*(?:-c[1-9]\d*)?)*"
_SHEET_ROW = re.compile(rf"^r(?P<row>[1-9]\d*) indent (?P<indent>\d+)(?: num (?P<num>{_COLS}))?(?: blank (?P<blank>{_COLS}))?$")
_WITHHELD = re.compile(r"^c(?P<col>[1-9]\d*) withheld: text, (?P<n>\d+) distinct values$")
# A year header, with a tag letter or not ("2024", "2024B"), is a period and not a figure, even where it reads as one ("2024B" as
# billions). Below the header row the reader sends no such text: it is a number there.
_PERIOD_FIGURE = re.compile(r"^(?:19|20)\d{2}(?:\.0)?(?:\s?[AFBE])?$")
# The finance words of the withhold rule and of the label column (chat-upload.md section 26.10).
FINANCE_WORDS = frozenset("""
revenue revenues sales cost costs cogs goods sold direct services marketing advertising expense expenses margin gross profit
ebitda adjusted operating opex overheads general administrative g&a research development r&d personnel payroll salaries s&m
arr mrr recurring annual monthly churn churned lost growth yoy mom bookings booking acv tcv contract value customers customer
clients subscribers logos headcount fte ftes employees cash balance closing ending income loss total net tax interest
depreciation amortisation amortization fees rent wages bonus commission hosting software licences licenses subscriptions travel
insurance legal contractors other
""".split())


def sheet_figure(text: str) -> bool:
    """True when a cell's text is a figure the skeleton never sends: one figure and nothing else, other than a year header."""
    text = (text or "").strip()
    return is_figure(text) and not _PERIOD_FIGURE.match(text)


def has_finance_word(text: str) -> bool:
    return any(w in FINANCE_WORDS for w in re.findall(r"[a-z0-9&]+", (text or "").lower()))


def withheld_columns(cells: List[Dict]) -> Dict[int, int]:
    """{column: distinct texts} for every column the withhold rule takes: 30 or more distinct texts, under 20% of them holding a
    finance word (a customer list, a list of names). Read on the cells as they are sent, after redaction."""
    by_col: Dict[int, set] = {}
    for c in cells:
        text = cell_text(c)
        if text:
            by_col.setdefault(c["col"], set()).add(text)
    return {col: len(texts) for col, texts in by_col.items() if len(texts) >= WITHHOLD_DISTINCT
            and sum(1 for t in texts if has_finance_word(t)) < WITHHOLD_FINANCE_SHARE * len(texts)}


def col_ranges(cols) -> str:
    """Columns as a row line writes them: [2, 3, 4, 6] -> "c2-c4,c6"."""
    out, cols = [], sorted(set(cols))
    i = 0
    while i < len(cols):
        j = i
        while j + 1 < len(cols) and cols[j + 1] == cols[j] + 1:
            j += 1
        out.append(f"c{cols[i]}" if i == j else f"c{cols[i]}-c{cols[j]}")
        i = j + 1
    return ",".join(out)


def _parse_cols(text: Optional[str]) -> List[int]:
    out = []
    for part in (text or "").split(","):
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a[1:]), int(b[1:]) if b else int(a[1:])
        if hi < lo:
            return []
        out += range(lo, hi + 1)
    return out


def sheet_text(cells: List[Dict], rows: List[Dict], withheld: Dict[int, int]) -> str:
    """The skeleton for cells (row, col, text and a span), rows ({"row", "indent", "num", "blank"}) and the withheld columns: per
    row its cell lines and then its row line, in sheet order; the withheld lines last."""
    by_row: Dict[int, List[Dict]] = {}
    for c in cells:
        by_row.setdefault(c["row"], []).append(c)
    lines = []
    row_lines = {r["row"]: r for r in rows}
    for n in sorted(set(by_row) | set(row_lines)):
        if n in by_row:
            lines.append(structure_text(by_row[n]))
        r = row_lines.get(n)
        if r:
            line = f"r{n} indent {int(r.get('indent') or 0)}"
            if r.get("num"):
                line += f" num {col_ranges(r['num'])}"
            if r.get("blank"):
                line += f" blank {col_ranges(r['blank'])}"
            lines.append(line)
    lines += [f"c{col} withheld: text, {n} distinct values" for col, n in sorted(withheld.items())]
    return "\n".join(line for line in lines if line)


def parse_sheet_text(text: str) -> Optional[Dict]:
    """{"cells": [...], "rows": {row: {"indent", "num", "blank"}}, "withheld": {col: n}}, or None when a line is of no kind above, a
    row line comes twice or a column list is out of order."""
    cells, rows, withheld = [], {}, {}
    for line in (text or "").split("\n"):
        row, held = _SHEET_ROW.match(line), _WITHHELD.match(line)
        if row:
            n = int(row.group("row"))
            num, blank = _parse_cols(row.group("num")), _parse_cols(row.group("blank"))
            if n in rows or (row.group("num") and not num) or (row.group("blank") and not blank):
                return None
            rows[n] = {"indent": int(row.group("indent")), "num": num, "blank": blank}
        elif held:
            withheld[int(held.group("col"))] = int(held.group("n"))
        else:
            found = parse_structure_text(line)
            if not found or any(c.get("title") for c in found):
                return None
            cells += found
    return {"cells": cells, "rows": rows, "withheld": withheld}


def sheet_text_problem(text: str) -> Optional[str]:
    """Why a sheet skeleton may not reach the model, or None: a line of no kind, no text cell, more than 400 rows with text, a
    cell line that is a figure, or a column the withhold rule would take still sent."""
    parsed = parse_sheet_text(text)
    if parsed is None or not parsed["cells"]:
        return "not_cells"
    if len({c["row"] for c in parsed["cells"]}) > SHEET_MAX_ROWS:
        return "too_many_rows"
    if any(sheet_figure(c["text"]) for c in parsed["cells"]):
        return "figure"
    if withheld_columns(parsed["cells"]):
        return "withhold_missed"
    return None
