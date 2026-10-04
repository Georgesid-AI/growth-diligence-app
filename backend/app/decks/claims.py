"""Candidate claims: a text line that holds a number and a claim keyword. Python only, no model.

Each figure in such a line becomes one candidate:

    {"claim_type": "revenue", "value": 3600000, "unit": None, "currency": "USD",
     "target_date": "2013-01", "snippet": "...", "sources": [{"file": ..., "slide": 6, "kind": "text"}]}

A line is a parser text line; a table row is one line, and each figure keeps the row and
column of its own cell. A line whose only figures are dates gives one candidate per date
(value None): a launch month, a roadmap quarter. Candidates with the same type, value, unit,
currency and date are merged, keeping every source reference.
"""
import re
from typing import Dict, Iterable, List, Optional

SNIPPET_MAX = 300

# Keyword families (spec section 2). A keyword matches its plural and verb forms: "revenues",
# "growing", "hired", "launches". Acronyms match in capitals only, so "Sam" or "arr" do not count.
_FAMILIES = [
    ("revenue", r"\b(?:ARR|MRR|CAGR)\b|(?i:\brevenues?\b|\bgrowth\b|\bgr(?:ow|ows|owing|own|ew)\b|\bbookings?\b)"),
    ("retention", r"\bNRR\b|(?i:\bchurn(?:s|ed|ing)?\b|\bretention\b|\bretain(?:s|ed|ing)?\b)"),
    ("sales", r"\b(?:ACV|CAC)s?\b|(?i:\bsales cycles?\b|\bwin rates?\b|\bpipelines?\b|\bpayback\b)"),
    ("people", r"(?i:\bhir(?:e|es|ed|ing)\b|\bheadcounts?\b|\bteams?\b)"),
    ("product", r"(?i:\blaunch(?:es|ed|ing)?\b|\breleas(?:e|es|ed|ing)\b|\broadmaps?\b)"),
    ("market", r"\b(?:TAM|SAM|SOM)\b|(?i:\bmarket[ -]sizes?\b)"),
]
_KEYWORDS = [(family, re.compile(rx)) for family, rx in _FAMILIES]

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
        if unit is None:
            time = _TIME_UNIT.match(line, end)
            if time:
                unit = time.group("unit").lower().rstrip("s") + "s"
        out.append({"start": m.start(), "pos": num_start, "end": end, "num": float(g["num"].replace(",", "")),
                    "mult": mult, "currency": _CURRENCY.get(cur.strip()) if cur else None, "unit": unit})
    # A range shares its scale, unit and currency: "$12 - $13 million", "5-10%", "1-3 hours".
    for a, b in zip(out, out[1:]):
        if _RANGE.fullmatch(line[a["end"]:b["start"]]):
            a["mult"] = a["mult"] or b["mult"]
            a["unit"] = a["unit"] or b["unit"]
            a["currency"] = a["currency"] or b["currency"]
    for n in out:
        value = round(n["num"] * _SCALE.get((n["mult"] or "").lower(), 1), 6)
        n["value"] = int(value) if float(value).is_integer() else value
    return out


def _keywords(line: str) -> List[Dict]:
    return [{"start": m.start(), "end": m.end(), "family": family}
            for family, rx in _KEYWORDS for m in rx.finditer(line)]


def _distance(a: Dict, b: Dict) -> int:
    return max(0, a["start"] - b["end"], b["start"] - a["end"])


def _nearest(spans: List[Dict], target: Dict) -> Optional[Dict]:
    return min(spans, key=lambda s: (_distance(s, target), s["start"])) if spans else None


def _snippet(line: str, at: int) -> str:
    if len(line) <= SNIPPET_MAX:
        return line
    start = min(max(0, at - SNIPPET_MAX // 2), len(line) - SNIPPET_MAX)
    return line[start:start + SNIPPET_MAX]


def line_candidates(line: str, refs: Iterable[Dict]) -> List[Dict]:
    """Candidates in one line. `refs` gives each figure's source reference: a list of
    (start, end, ref) spans, so a table row cites the cell a figure sits in."""
    refs = list(refs)
    keywords = _keywords(line)
    date_words = [{"start": m.start(), "end": m.end()} for m in _DATE_WORD.finditer(line)]
    if not keywords and not date_words:
        return []
    dates = find_dates(line)
    numbers = find_numbers(line, dates)

    def ref_at(pos: int) -> Dict:
        return next((r for s, e, r in refs if s <= pos < e), refs[0][2])

    def claim(at: Dict, value=None, unit=None, currency=None, date=None) -> Dict:
        keyword = _nearest(keywords, at)
        pos = at.get("pos", at["start"])
        return {"claim_type": keyword["family"] if keyword else "product", "value": value, "unit": unit,
                "currency": currency, "target_date": date, "snippet": _snippet(line, pos),
                "sources": [ref_at(pos)]}

    if numbers:
        return [claim(n, n["value"], n["unit"], n["currency"], (_nearest(dates, n) or {}).get("date"))
                for n in numbers]
    # Only dates: a launch month or a roadmap quarter. A bare year counts only next to a
    # non-date keyword ("ARR by end of 2018"), not as a month or quarter's neighbour.
    return [claim(d, date=d["date"]) for d in dates if d["kind"] != "year" or keywords]


def _lines(blocks: List[Dict], file: str):
    """(line text, [(start, end, ref)]) per text line, and per table row with cells joined by ' | '."""
    rows = {}
    for b in blocks:
        where = {k: b[k] for k in ("slide", "page") if k in b}
        if b["kind"] != "table":
            ref = {"file": file, **where, "kind": b["kind"]}
            yield b["text"], [(0, len(b["text"]), ref)]
            continue
        key = (b.get("slide"), b.get("page"), b["table"], b["row"])
        rows.setdefault(key, []).append(b)
    for cells in rows.values():
        text, spans = "", []
        for cell in cells:
            if text:
                text += " | "
            ref = {"file": file, **{k: cell[k] for k in ("slide", "page") if k in cell}, "kind": "table",
                   "table": cell["table"], "row": cell["row"], "col": cell["col"]}
            spans.append((len(text), len(text) + len(cell["text"]), ref))
            text += cell["text"]
        yield text, spans


def detect_candidates(blocks: List[Dict], file: str) -> List[Dict]:
    """Every candidate in a parsed deck, duplicates merged in order of first appearance."""
    merged = {}
    for line, spans in _lines(blocks, file):
        for c in line_candidates(line, spans):
            key = (c["claim_type"], c["value"], c["unit"], c["currency"], c["target_date"])
            if key not in merged:
                merged[key] = c
            elif c["sources"][0] not in merged[key]["sources"]:
                merged[key]["sources"].append(c["sources"][0])
    return list(merged.values())
