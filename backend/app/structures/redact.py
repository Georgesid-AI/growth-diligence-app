"""Redaction of deck structure cells, and the structure text the model reads (pure, no I/O).

Spec: docs/specs/llm-structure-reading.md section 3; CLAUDE.md rule 16. Nothing here reads a
database or a file, and nothing here calls a model: the gateway runs these same functions again
on the text it is given and refuses the call if anything changes. Names are matched as whole
words, in any case; a word ends at a space, punctuation, a hyphen or a change of case. The client
name and the engagement reference become [redacted]; customer names their pseudonyms.

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
SUFFIX = r"(?:\s?(?P<suffix>k|K|mn|MM|m|M|bn|B|thousand|million|billion|Mio|Mrd|Tsd|млн|млрд|хил)(?![^\W\d_]))?"
# A figure, keyed by whether the structure writes a decimal comma (1.234,5).
NUMBER = {
    False: re.compile(r"(?P<open>\()?\s*(?:(?<![\w.])(?P<sign>[-−–]))?\s*(?<![\d.,])"
                      r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d]|[.,]\d)"
                      + SUFFIX + r"\s*(?P<pct>%)?\s*(?P<close>\))?"),
    True: re.compile(r"(?P<open>\()?\s*(?:(?<![\w.])(?P<sign>[-−–]))?\s*(?<![\d.,])"
                     r"(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(?![\d]|[.,]\d)"
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
# 3 sample values per numeric or date column, and a profile instead of values per text column.
#     r1c2: Invoice Date
#     c2 sample: 2025-01-31
#     c1 profile: distinct 42, typical length 12, shape Aa a
# No text cell value is ever on this path: a sample is a number or an ISO date, nothing else.
# ---------------------------------------------------------------------------
MAX_HEADER_ROWS = 3
MAX_SAMPLES = 3
_SAMPLE_LINE = re.compile(r"^c(?P<col>\d+) sample: (?P<value>.+)$")
_PROFILE_LINE = re.compile(r"^c(?P<col>\d+) profile: distinct (?P<distinct>\d+), typical length (?P<length>\d+), "
                           r"shape (?P<shape>[Aa0 \-_./@:,#()+&']{1,20})$")
# A sample value: a number (sign, currency symbol, separators, %) or an ISO date or date-time.
SAMPLE_VALUE = re.compile(r"^(?:[-+(]?\s?(?:[£$€¥]\s?)?\d[\d,]*(?:\.\d+)?\s?%?\)?"
                          r"|\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?)$")


def column_text(headers: List[Dict], samples: Dict[int, List[str]], profiles: Dict[int, Dict]) -> str:
    """The column-mapping text: header cells, then samples, then profiles, each in column order."""
    lines = [structure_text(headers)] if headers else []
    lines += [f"c{col} sample: {value}" for col in sorted(samples) for value in samples[col]]
    lines += [f"c{col} profile: distinct {p['distinct']}, typical length {p['length']}, shape {p['shape']}"
              for col, p in sorted(profiles.items())]
    return "\n".join(line for line in lines if line)


def parse_column_text(text: str) -> Optional[Dict]:
    """{"headers": cells, "samples": {col: [values]}, "profiles": {col: {...}}}, or None when a line is
    neither a header cell, a sample nor a profile."""
    headers, samples, profiles = [], {}, {}
    for line in (text or "").split("\n"):
        sample, profile = _SAMPLE_LINE.match(line), _PROFILE_LINE.match(line)
        if sample:
            samples.setdefault(int(sample.group("col")), []).append(sample.group("value"))
        elif profile:
            profiles[int(profile.group("col"))] = {"distinct": int(profile.group("distinct")),
                                                   "length": int(profile.group("length")), "shape": profile.group("shape")}
        else:
            cells = parse_structure_text(line)
            if not cells:
                return None
            headers += cells
    return {"headers": headers, "samples": samples, "profiles": profiles}


def column_text_problem(text: str) -> Optional[str]:
    """Why a column-mapping text may not reach the model, or None: more than 3 header rows, more than
    3 samples for a column, a sample that is not a number or a date (a text cell value), or a column
    with both samples and a profile."""
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


def withheld_values(audit: Dict) -> Tuple[str, ...]:
    """The audit's client name and engagement reference: never sent to the model, so a cell holding
    one is sent with [redacted] in its place."""
    return tuple(str(audit.get(k)).strip() for k in ("client_name", "engagement_reference")
                 if audit.get(k) is not None and str(audit.get(k)).strip())


def withhold_cells(cells: List[Dict], withheld: Tuple[str, ...]) -> Tuple[List[Dict], int]:
    """(cells, count): each withheld value (the client name, the engagement reference) becomes
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
    """Every redaction rule on a structure's cells: the client name and the engagement reference
    (`withheld`, see withheld_values), then emails and phone numbers, then customer names, then
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
