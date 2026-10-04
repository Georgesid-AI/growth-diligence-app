"""Candidate claims: a figure and a claim keyword. Python only, no model (spec section 2).

Each figure becomes one candidate:

    {"claim_type": "revenue", "value": 3600000, "value_high": None, "unit": None, "currency": "USD",
     "target_date": "2013-01", "snippet": "<the figure's own line>", "label_from": None, "date_from": None,
     "sources": [{"file": ..., "slide": 6, "kind": "text"}]}

The type is the family of the nearest keyword in the figure's own line. A growth word gives a
rate (% or x) its type from the noun on the same line: revenue -> revenue_growth, users ->
user_growth, none or another noun -> growth. Beside a growth word, an amount or a count takes
the noun's own type ("ARR grew to $3.6M" is revenue). A count keeps the counted noun as its unit
("800 paying users"); a count whose line has no keyword borrows a label like any other figure.
Only plan claims are kept: axis ticks, background and cited-research pages, and lines about
funds raised, tokens, careers or the industry are dropped (see _axis_ticks and _not_plan).

A line is a parser text line; a table row is one line, and each figure keeps the row and
column of its own cell. A range ("$12 - $13 million") is one figure with a low and a high value.

A figure takes the keyword and the date of its own line. A line with its own keyword never
borrows a label. When it has none, the figure borrows one from nearby text, first match wins:
the table column header, the other lines of its text box (nearest first), the boxes on the same
row or above it within REACH (nearest first), the slide or page title. A missing date is
borrowed the same way. The snippet stays the figure's own line; the borrowed text is kept in
"label_from" and "date_from", so the analyst sees where the type and the date came from.

A line whose only figures are dates gives one candidate per date (value None): a launch month,
a roadmap quarter. A line with no figure at all gives one when it is a product line (its own
keyword, or the one it borrows, is a product keyword) and it can borrow a date: a roadmap
bullet. Candidates with the same type, value, unit, currency and date are merged, keeping
every source reference.
"""
import re
from math import hypot
from typing import Dict, Iterable, List, Optional, Tuple

SNIPPET_MAX = 300
# How far a figure looks for a label or a date by position, as a share of the slide or page.
REACH = 0.25
_LABEL_MAX = SNIPPET_MAX

# Keyword families (spec section 2). A keyword matches its plural and verb forms: "revenues",
# "growing", "hired", "launches". Acronyms match in capitals only, so "Sam" or "arr" do not count.
# "market" is a whole word: "marketing" and "marketplace" do not count.
# Where two keywords overlap, the longer one counts: "paying users" is customers, not users;
# "customer lifetime value" is sales, not customers.
_FAMILIES = [
    ("growth", r"\bCAGR\b|(?i:\bgrowth\b|\bgr(?:ow|ows|owing|own|ew)\b)"),
    ("revenue", r"\b(?:ARR|MRR)\b|(?i:\brevenues?\b|\bbookings?\b|\bturnover\b)"),
    ("retention", r"\bNRR\b|(?i:\bchurn(?:s|ed|ing)?\b|\bretention\b|\bretain(?:s|ed|ing)?\b|\bcustomer life\b)"),
    ("sales", r"\b(?:ACV|CAC|LTV)s?\b|(?i:\bsales cycles?\b|\bwin rates?\b|\bpipelines?\b|\bpayback\b"
              r"|\b(?:customer )?lifetime value\b|\bacqui(?:re|res|red|ring|sition)\b|\bconver(?:t|ts|ted|ting|sion|sions)\b"
              r"|\bleads\b)"),
    ("customers", r"(?i:\bcustomers?\b|\bclients?\b|\bpaying users?\b|\baccounts?\b"
                  r"|\bcompan(?:y|ies)\b|\bagenc(?:y|ies)\b|\bsubscribers?\b)"),
    ("users", r"(?i:\busers?\b)"),
    ("gross_margin", r"(?i:\bmargins?\b)"),
    ("people", r"(?i:\bhir(?:e|es|ed|ing)\b|\bheadcounts?\b|\bteams?\b|\brecruit(?:s|ed|ing|ment)?\b"
               r"|\battrition\b)"),
    ("product", r"(?i:\blaunch(?:es|ed|ing)?\b|\breleas(?:e|es|ed|ing)\b|\broadmaps?\b|\bship(?:s|ped|ping)?\b"
                r"|\bmilestones?\b)"),
    ("market", r"\b(?:TAM|SAM|SOM)\b|(?i:\baddressable markets?\b|\bmarket[ -]sizes?\b)"),
]
_KEYWORDS = [(family, re.compile(rx)) for family, rx in _FAMILIES]
_NOUN_KEYWORDS = [(family, rx) for family, rx in _KEYWORDS if family in ("customers", "users")]
_GROWTH_OF = {"revenue": "revenue_growth", "users": "user_growth"}
# Plan claims only: the company's own figures the growth plan depends on.
CLAIM_TYPES = ("revenue", "revenue_growth", "growth", "retention", "sales", "customers", "users", "user_growth",
               "gross_margin", "people", "product", "market")
# Words after a number that are not the thing counted: "20 of them", "5 per month".
_NOT_NOUNS = frozenset("""a an and are as at be by each for from has have in into is it its more of on or our
over per than that the this to under up was we were with""".split())
_COUNTED = re.compile(r"\s+(?P<noun>[A-Za-z][A-Za-z'’-]*)")
_UNIT_WORD = re.compile(r"[^\sA-Za-z]*(?P<word>\S*)")
UNIT_REACH = 4  # words after the number searched for a keyword noun

# Date words (Q1-Q4 and month names) are product keywords and also give the target date.
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
           "oct": 10, "nov": 11, "dec": 12}
_MONTH = (r"(?<![A-Za-z])(?P<month>(?i:january|february|march|april|june|july|august|september|october|"
          r"november|december)|May|MAY|(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
          r"JAN|FEB|MAR|APR|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC))(?![A-Za-z])")
_DATE_WORD = re.compile(_MONTH + r"|\bQ[1-4]\b")
_DATES = [
    # Q3 2021, Q1 17, Q1-Q2 2023
    ("quarter", re.compile(r"\bQ(?P<q>[1-4])(?:\s*[-–]\s*Q[1-4])?\s*['’]?\s*(?P<year>(?:19|20)\d{2}|\d{2})\b")),
    # 2021 Q3, 2021-Q3
    ("quarter", re.compile(r"(?<![\d.,])(?P<year>(?:19|20)\d{2})\s*[-/]?\s*Q(?P<q>[1-4])\b")),
    # January 2011, Feb. 2007, April of 2011, May, 2021, Nov28,08, Aug2008, Mar '15
    ("month", re.compile(_MONTH + r"\.?,?\s*(?:(?:\d{1,2})(?:st|nd|rd|th)?,\s*(?P<y2>\d{2})\b|"
                         r"(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(?:of\s+)?(?P<year>(?:19|20)\d{2})\b|['’](?P<y3>\d{2})\b)")),
    # a bare year: 2024, by end of 2020
    ("year", re.compile(r"(?<![\w$€£.,'’])(?P<year>(?:19|20)\d{2})(?![\d%]|\.\d|,\d)")),
]

_NUMBER = re.compile(
    r"(?<![\w.,])(?P<cur>US\$|\$|€|£|(?:USD|EUR|GBP)(?=\s?\d))?\s?~?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\+?"
    r"(?:(?P<mult>MM|mn|bn|[KkMmBbT])(?![A-Za-z])|\s?(?P<word>(?i:thousand|million|billion|trillion))\b)?\+?"
    r"(?:\s?(?P<pct>%)|(?P<x>[xX])(?![A-Za-z]))?(?P<ord>st|nd|rd|th)?")
_SPACED_MULT = re.compile(r"\s(?P<mult>MM|bn|[KMBT])(?![A-Za-z])")       # "$52 B": only after a currency
_SUFFIX_CURRENCY = re.compile(r"\s?(?P<cur>USD|EUR|GBP|€)(?![A-Za-z])")
_TIME_UNIT = re.compile(r"\s*(?P<unit>months?|years?|weeks?|days?|hours?)\b", re.I)
_RANGE = re.compile(r"\s*(?:-|–|—|to)\s*")
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9,
          "billion": 1e9, "t": 1e12, "trillion": 1e12}
_CURRENCY = {"$": "USD", "US$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP"}


def _year(text: str) -> int:
    return int(text) if len(text) == 4 else 2000 + int(text)


def find_dates(line: str) -> List[Dict]:
    """[{"start", "end", "date", "kind"}], longest forms first, no overlaps."""
    found = []
    for kind, rx in _DATES:
        for m in rx.finditer(line):
            if any(m.start() < d["end"] and d["start"] < m.end() for d in found):
                continue
            g = m.groupdict()
            if kind == "quarter":
                date = f"{_year(g['year'])}-Q{g['q']}"
            elif kind == "month":
                year = g.get("year") or g.get("y2") or g.get("y3")
                date = f"{_year(year)}-{_MONTHS[g['month'][:3].lower()]:02d}"
            else:
                date = g["year"]
            found.append({"start": m.start(), "end": m.end(), "date": date, "kind": kind})
    return sorted(found, key=lambda d: d["start"])


def find_numbers(line: str, dates: List[Dict]) -> List[Dict]:
    """Figures in the line that are not part of a date and not an ordinal ("2nd half")."""
    out = []
    for m in _NUMBER.finditer(line):
        num_start = m.start("num")
        if m.group("ord") or any(d["start"] <= num_start < d["end"] for d in dates):
            continue
        g = m.groupdict()
        end = m.end()
        mult = g["mult"] or g["word"]
        if g["cur"] and not mult and not g["pct"] and not g["x"]:
            spaced = _SPACED_MULT.match(line, end)
            if spaced:
                mult, end = spaced.group("mult"), spaced.end()
        cur = g["cur"]
        if not cur and not g["pct"]:
            suffix = _SUFFIX_CURRENCY.match(line, end)
            if suffix:
                cur, end = suffix.group("cur"), suffix.end()
        unit = "%" if g["pct"] else "x" if g["x"] else None
        count = False
        if unit is None:
            time = _TIME_UNIT.match(line, end)
            if time:
                unit = time.group("unit").lower().rstrip("s") + "s"
        if unit is None and not cur:
            unit, count = _counted(line, end)
        out.append({"start": m.start(), "pos": num_start, "end": end, "num": float(g["num"].replace(",", "")),
                    "mult": mult, "currency": _CURRENCY.get(cur.strip()) if cur else None, "unit": unit,
                    "count": count})
    for n in out:
        n["value"], n["value_high"] = _scaled(n["num"], n["mult"]), None
    # A range is one figure: "$12 - $13 million", "5-10%", "from 40 to 100". The low end takes
    # the high end's scale, unit and currency.
    ranged = []
    for n in out:
        low = ranged[-1] if ranged else None
        if low and low["value_high"] is None and _RANGE.fullmatch(line[low["end"]:n["start"]]):
            low["value"] = _scaled(low["num"], low["mult"] or n["mult"])
            low["value_high"] = n["value"]
            low["unit"] = low["unit"] or n["unit"]
            low["count"] = low["count"] or n["count"]
            low["currency"] = low["currency"] or n["currency"]
            low["end"] = n["end"]
        else:
            ranged.append(n)
    return ranged


def _counted(line: str, end: int) -> Tuple[Optional[str], bool]:
    """(noun, True) when the figure counts something: "800 paying users", "1.5 million updates".
    The noun is a keyword noun within the next UNIT_REACH words, up to the next figure
    ("50 Dutch work agencies"), else the word right after the number."""
    m = _COUNTED.match(line, end)
    if not m or m.group("noun").lower() in _NOT_NOUNS:
        return None, False
    pos = m.start("noun")
    for _ in range(UNIT_REACH):
        w = _UNIT_WORD.match(line, pos)
        if any(ch.isdigit() for ch in w.group(0)):
            break
        for _, rx in _NOUN_KEYWORDS:
            k = rx.match(line, w.start("word"))
            if k:
                return k.group(0).lower(), True
        pos = w.end()
        while pos < len(line) and line[pos].isspace():
            pos += 1
    return m.group("noun").lower(), True


def _scaled(num: float, mult: Optional[str]):
    value = round(num * _SCALE.get((mult or "").lower(), 1), 6)
    return int(value) if float(value).is_integer() else value


def _keywords(line: str) -> List[Dict]:
    """Claim keywords, not counting the date words (Q1-Q4, month names). Of two overlapping
    keywords the longer one stays."""
    found = sorted(({"start": m.start(), "end": m.end(), "family": family}
                    for family, rx in _KEYWORDS for m in rx.finditer(line)), key=lambda k: k["start"] - k["end"])
    kept = []
    for k in found:
        if not any(k["start"] < o["end"] and o["start"] < k["end"] for o in kept):
            kept.append(k)
    return sorted(kept, key=lambda k: k["start"])


def _type(keyword: Dict, keywords: List[Dict], unit: Optional[str] = "%") -> str:
    """A keyword's claim type. A growth word types a rate by the nearest revenue, users or
    customers noun; an amount or a count beside it takes that noun's own type."""
    if keyword["family"] != "growth":
        return keyword["family"]
    noun = _nearest([k for k in keywords if k["family"] in ("revenue", "users", "customers")], keyword)
    if unit in ("%", "x"):
        return _GROWTH_OF.get(noun["family"], "growth") if noun else "growth"
    return noun["family"] if noun else "growth"


def _distance(a: Dict, b: Dict) -> int:
    return max(0, a["start"] - b["end"], b["start"] - a["end"])


def _nearest(spans: List[Dict], target: Dict) -> Optional[Dict]:
    return min(spans, key=lambda s: (_distance(s, target), s["start"])) if spans else None


def _snippet(text: str, at: int) -> str:
    if len(text) <= SNIPPET_MAX:
        return text
    start = min(max(0, at - SNIPPET_MAX // 2), len(text) - SNIPPET_MAX)
    return text[start:start + SNIPPET_MAX]


def _label(text: str) -> str:
    return text if len(text) <= _LABEL_MAX else text[:_LABEL_MAX - 1] + "…"


def _borrow_keyword(texts: Iterable[str]) -> Optional[Tuple[str, str]]:
    """(family, text) of the first text that holds a claim keyword."""
    for text in texts:
        found = _keywords(text)
        if found:
            return _type(found[0], found), text
    return None


def _borrow_date(texts: Iterable[str]) -> Optional[Tuple[str, str]]:
    """(date, text): the first month or quarter in the texts, else the first year."""
    texts = list(texts)
    for wanted in (("quarter", "month"), ("year",)):
        for text in texts:
            found = [d for d in find_dates(text) if d["kind"] in wanted]
            if found:
                return found[0]["date"], text
    return None


def line_candidates(line: str, refs: Iterable, context: Iterable[str] = (), headers: Optional[Dict] = None) -> List[Dict]:
    """Candidates in one line. `refs` gives each figure's source reference: a list of
    (start, end, ref) spans, so a table row cites the cell a figure sits in. `context` is the
    nearby text to borrow from, most relevant first; `headers` maps a table column to its header."""
    refs, context, headers = list(refs), list(context), headers or {}
    keywords = _keywords(line)
    date_words = [{"start": m.start(), "end": m.end()} for m in _DATE_WORD.finditer(line)]
    dates = find_dates(line)
    numbers = find_numbers(line, dates)

    def ref_at(pos: int) -> Dict:
        return next((r for s, e, r in refs if s <= pos < e), refs[0][2])

    def claim(pos, family, value=None, high=None, unit=None, currency=None, date=None, label=None, date_from=None):
        return {"claim_type": family, "value": value, "value_high": high, "unit": unit, "currency": currency,
                "target_date": date, "snippet": _snippet(line, pos), "label_from": label and _label(label),
                "date_from": date_from and date_from != label and _label(date_from) or None, "sources": [ref_at(pos)]}

    out = []
    for n in numbers:
        own = _nearest(keywords, n)
        header = headers.get(ref_at(n["pos"]).get("col"))
        nearby = [header] if header else []
        borrowed = None if own else _borrow_keyword(nearby + context)
        if own:
            family = _type(own, keywords, n["unit"])
        elif borrowed:
            family = borrowed[0]
        elif date_words:
            family = "product"
        else:
            continue
        own_date = _nearest(dates, n)
        date = None if own_date else _borrow_date(nearby + context)
        out.append(claim(n["pos"], family, n["value"], n["value_high"], n["unit"], n["currency"],
                         own_date["date"] if own_date else date and date[0],
                         label=borrowed and borrowed[1], date_from=date and date[1]))
    if numbers:
        return out
    if dates:
        # Only dates: a launch month or a roadmap quarter. A bare year counts only next to a
        # claim keyword in its own line ("ARR by end of 2018").
        if not keywords and not date_words:
            borrowed = _borrow_keyword(context)
            if not borrowed or all(d["kind"] == "year" for d in dates):
                return []
        return [claim(d["start"], _type(_nearest(keywords, d), keywords) if keywords else "product", date=d["date"])
                for d in dates if d["kind"] != "year" or keywords]
    # No figure at all: a product line ("Launch the API", a roadmap bullet) takes a nearby date.
    own = _nearest(keywords, {"start": 0, "end": len(line)})
    borrowed = None if keywords else _borrow_keyword(context)
    if (own or {}).get("family") != "product" and (borrowed or [None])[0] != "product":
        return []
    date = _borrow_date(context)
    if not date:
        return []
    return [claim(0, "product", date=date[0], label=borrowed and borrowed[1], date_from=date[1])]


# ---------------------------------------------------------------------------
# Lines, their boxes and their context
# ---------------------------------------------------------------------------
def _units(blocks: List[Dict], file: str) -> List[Dict]:
    """Text lines and table rows (cells joined by ' | '), with what borrowing needs."""
    units, tables = [], {}
    for b in blocks:
        where = {k: b[k] for k in ("slide", "page") if k in b}
        page = (b.get("slide"), b.get("page"))
        if b["kind"] == "table":
            tables.setdefault((page, b["table"]), {}).setdefault(b["row"], []).append(b)
            continue
        ref = {"file": file, **where, "kind": b["kind"]}
        units.append({"text": b["text"], "spans": [(0, len(b["text"]), ref)], "page": page,
                      "box": (page, b["box"]) if b.get("box") is not None else None,
                      "bbox": b.get("bbox"), "title": bool(b.get("title")), "headers": {}})
    for (page, table), rows in tables.items():
        first = min(rows)
        header = {cell["col"]: cell["text"] for cell in rows[first]}
        for r, cells in rows.items():
            text, spans = "", []
            for cell in cells:
                if text:
                    text += " | "
                ref = {"file": file, **{k: cell[k] for k in ("slide", "page") if k in cell}, "kind": "table",
                       "table": cell["table"], "row": cell["row"], "col": cell["col"]}
                spans.append((len(text), len(text) + len(cell["text"]), ref))
                text += cell["text"]
            boxes = [c["bbox"] for c in cells if c.get("bbox")]
            bbox = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                    max(b[3] for b in boxes)] if boxes else None
            units.append({"text": text, "spans": spans, "page": page, "box": ("table", page, table), "bbox": bbox,
                          "title": False, "headers": header if r != first else {}, "table_row": True})
    return units


def _reach(line_bbox, box_bbox) -> Optional[float]:
    """Distance from a line to a box on the same row or above it; None when the box is below."""
    x0, y0, x1, y1 = line_bbox
    bx0, by0, bx1, by1 = box_bbox
    if by0 >= y1:
        return None
    return hypot(max(0.0, bx0 - x1, x0 - bx1), max(0.0, y0 - by1))


def _contexts(units: List[Dict]) -> Dict[int, List[str]]:
    """id(unit) -> nearby texts, most relevant first."""
    pages, boxes = {}, {}
    for u in units:
        pages.setdefault(u["page"], []).append(u)
        if u["box"] is not None:
            boxes.setdefault(u["box"], []).append(u)
    shapes = {}     # box -> (joined text, bbox)
    for key, members in boxes.items():
        placed = [m["bbox"] for m in members if m["bbox"]]
        bbox = [min(b[0] for b in placed), min(b[1] for b in placed), max(b[2] for b in placed),
                max(b[3] for b in placed)] if placed else None
        shapes[key] = (" ".join(m["text"] for m in members), bbox)
    out = {}
    for page, members in pages.items():
        title = " ".join(m["text"] for m in members if m["title"])
        for u in members:
            texts = []
            if u["box"] is not None and not u.get("table_row"):
                box = boxes[u["box"]]
                i = next(k for k, m in enumerate(box) if m is u)
                texts += [m["text"] for k, m in sorted(enumerate(box), key=lambda km: (abs(km[0] - i), km[0] > i))
                          if m is not u]
            if u["bbox"]:
                near = []
                for key, (text, bbox) in shapes.items():
                    if key[-2 if key[0] == "table" else 0] != page or key == u["box"] or not bbox:
                        continue
                    distance = _reach(u["bbox"], bbox)
                    if distance is not None and distance <= REACH:
                        near.append((distance, bbox[1], text))
                texts += [text for _, _, text in sorted(near)]
            if title and not u["title"]:
                texts.append(title)
            out[id(u)] = texts
    return out


_WORD = re.compile(r"[A-Za-z]{2,}")

# Not plan claims (spec section 2): whole slides or pages of background or cited research, and
# lines about funds raised, tokens, people's careers or the industry and the world at large.
_BACKGROUND_TITLE = re.compile(r"(?i)\b(?:problems?|why now|trends?|landscape|background|tokens?|allocation)\b")
_CITED = re.compile(r"(?i)^\s*(?:sources?\s*:|via\s+https?://)|^\s*\d+\.\s*(?:https?://|\S.*\bresearch\b)")
# "1.", "2. Research at MIT", a bare URL; not "3.9x more messages" (a decimal)
_FOOTNOTE = re.compile(r"(?i)^\s*(?:\d+\.(?!\d)|https?://)")
_NOT_PLAN_LINE = re.compile(
    r"(?i)\b(?:rais(?:e|es|ed|ing)|funding|investments?|investors?|valuation|seed round|series [a-d]|pre-seed|"
    r"post-seed|tokens?|allocation|vesting|total supply|lock-?up|co-?founders?|founders?|founded|ceo|cto|cfo|coo|"
    r"chief|former(?:ly)?|previously|employee|exec(?:utive)? team|industry|industries|global|worldwide|economy)\b")


def _not_plan(units: List[Dict]) -> set:
    """id() of the lines that are not plan claims: every line of a slide titled Problem, Why now and
    the like or of a page that cites outside research, and lines about funds, tokens, careers or
    the industry."""
    pages = {}
    for u in units:
        pages.setdefault(u["page"], []).append(u)
    out = set()
    for members in pages.values():
        title = " ".join(m["text"] for m in members if m["title"])
        cited = any(_CITED.search(m["text"]) for m in members) or \
            sum(1 for m in members if _FOOTNOTE.search(m["text"])) >= 2
        if _BACKGROUND_TITLE.search(title) or cited:
            out.update(id(m) for m in members)
        out.update(id(m) for m in members if _NOT_PLAN_LINE.search(m["text"]))
    return out


def _bare_values(text: str) -> List[float]:
    """The figures of a line that holds nothing but numbers ("800,000", "40%", "$5.5T"); else []."""
    if _WORD.search(text):
        return []
    return [n["value"] for n in find_numbers(text, find_dates(text))]


def _evenly_spaced(values: List[float]) -> bool:
    distinct = sorted(set(values))
    if len(distinct) < 3:
        return False
    steps = [b - a for a, b in zip(distinct, distinct[1:])]
    return all(abs(step - steps[0]) <= 1e-6 * max(1.0, abs(steps[0])) for step in steps)


def _axis_ticks(units: List[Dict]) -> set:
    """id() of the lines that are chart axis ticks: 3 or more numbers, evenly spaced in value, in
    one line, or one bare number per line stacked in a column or lined up in a row."""
    ticks = set()
    pages = {}
    for u in units:
        if u.get("table_row"):
            continue
        values = _bare_values(u["text"])
        if len(values) >= 3 and _evenly_spaced(values):
            ticks.add(id(u))
        elif len(values) == 1 and u["bbox"]:
            pages.setdefault(u["page"], []).append((u, values[0]))
    for found in pages.values():
        for axis in (0, 1):           # 0: a column (overlapping x), 1: a row (overlapping y)
            lo, hi = (0, 2) if axis == 0 else (1, 3)
            for u, _ in found:
                group = [(v, w) for w, v in found if min(u["bbox"][hi], w["bbox"][hi]) > max(u["bbox"][lo], w["bbox"][lo])]
                if len(group) >= 3 and _evenly_spaced([v for v, _ in group]):
                    ticks.update(id(w) for _, w in group)
    return ticks


def _tick_cells(blocks: List[Dict]) -> set:
    """(page, table, row, col) of table cells that are row numbers or axis-like headers: one bare
    number per cell, 3 or more evenly spaced down a column or along a row ("1 2 3", "Y/E 22 23 24")."""
    cells = {}
    for b in blocks:
        if b["kind"] == "table":
            values = _bare_values(b["text"])
            if len(values) == 1:
                cells[(b.get("slide") or b.get("page"), b["table"], b["row"], b["col"])] = values[0]
    out = set()
    for axis in (2, 3):                 # same column, then same row
        groups = {}
        for key, value in cells.items():
            groups.setdefault(key[:2] + (key[axis],), []).append((key, value))
        for members in groups.values():
            if len(members) >= 3 and _evenly_spaced([v for _, v in members]):
                out.update(k for k, _ in members)
    return out


def detect_candidates(blocks: List[Dict], file: str) -> List[Dict]:
    """Every candidate in a parsed deck, duplicates merged in order of first appearance."""
    units = _units(blocks, file)
    contexts = _contexts(units)
    skipped = _axis_ticks(units) | _not_plan(units)
    tick_cells = _tick_cells(blocks)
    merged = {}
    for u in units:
        if id(u) in skipped:
            continue
        for c in line_candidates(u["text"], u["spans"], contexts[id(u)], u["headers"]):
            s = c["sources"][0]
            if s["kind"] == "table" and (s.get("slide") or s.get("page"), s["table"], s["row"], s["col"]) in tick_cells:
                continue
            key = (c["claim_type"], c["value"], c["value_high"], c["unit"], c["currency"], c["target_date"])
            if key not in merged:
                merged[key] = c
            elif c["sources"][0] not in merged[key]["sources"]:
                merged[key]["sources"].append(c["sources"][0])
    return list(merged.values())
