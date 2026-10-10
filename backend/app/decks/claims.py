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
A table row gives one candidate: its figures of one type sit in "by_period", each with its date
and its column header ("Y/E 22"); value and target_date of the row itself are None.
Periods ("Y/E 22", "23 Y/E", "FY23", "2023E", "H1 24") are dates, never values. A figure's date
comes from its own line, then its column header, then a period line at the top of its text box,
then the borrowing below. Candidates that give the same type and stated period different values
carry that period in "inconsistent_dates" (see _flag_inconsistencies).

Every value keeps its period three ways: "target_date" ("2025", "2025-Q3", "2025-H1", "2025-03"),
"period_text" (the date as the deck states it, "FY25", for display) and "period_start" and
"period_end" (ISO dates). A fiscal year ("FY25", "Y/E 25", "FY2024/25") is named by the calendar
year in which it ends, so its target_date is that year. The ranges follow the audit's fiscal
year-end: with December every period is the calendar one; with any other month every year,
quarter and half label is fiscal ("2025E", "Q1 25", "H1 25" as much as "FY25"), so with a March
year-end 2025 and FY25 run 2024-04-01 to 2025-03-31 and Q1 25 runs 2024-04-01 to 2024-06-30.
Months stay calendar months, but a month under a year header ("Apr" under "FY2025" or "2025",
target_date "FY2025-04") or stated with one ("Apr FY25") falls inside that year: up to the year-end
month it is in the named year, after it in the calendar year before (with a March year-end April
of FY2025 is April 2024). remap_periods re-runs the ranges for a new year-end.

A figure takes the keyword and the date of its own line. A line with its own keyword never
borrows a label. When it has none, its type comes from its table column header, else from the nearest
heading (decision of 2026-10-08): the closest text on the page, in its own text box, in a box on the same
row or above it within REACH, or the slide or page title, that is a heading (a word, no figure, at most
HEADING_MAX characters) or holds a keyword. A heading that names no type gives the figure none: type
Unknown, however clear a heading further away. A missing date is borrowed by position, first match wins.
The snippet stays the figure's own line; the borrowed text is kept in "label_from" and "date_from", so the
analyst sees where the type and the date came from.

A line whose only figures are dates gives one candidate per date (value None): a launch month,
a roadmap quarter. A line with no figure at all gives one when it is a product line (its own
keyword, or the one it borrows, is a product keyword) and it can borrow a date: a roadmap
bullet. A direction with no figure ("Positive EBITDA") is a candidate with no value and a
"claim_direction". Candidates with the same type, value, unit, currency and date are merged, keeping every
source reference.
"""
import calendar
import re
from datetime import date
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
# "customer lifetime value" is ltv, not customers or customer_lifetime; "LTV / CAC", "LTV:CAC" is ltv_cac.
_FAMILIES = [
    ("growth", r"\bCAGR\b|(?i:\bgrowth\b|\bgr(?:ow|ows|owing|own|ew)\b)"),
    ("revenue", r"\b(?:ARR|MRR)\b|(?i:\brevenues?\b|\bbookings?\b|\bturnover\b|\bGMV\b|\bTPV\b|\b(?:trading|payment|transaction) volume\b)"),
    ("retention", r"\bNRR\b|(?i:\bchurn(?:s|ed|ing)?\b|\bretention\b|\bretain(?:s|ed|ing)?\b)"),
    ("sales", r"\bACVs?\b|(?i:\bsales cycles?\b|\bwin rates?\b|\bpipelines?\b|\bpayback\b"
              r"|\bacqui(?:re|res|red|ring)\b|\bconver(?:t|ts|ted|ting|sion|sions)\b|\bleads\b)"),
    ("customers", r"(?i:\bcustomers?\b|\bclients?\b|\bpaying users?\b|\baccounts?\b"
                  r"|\bcompan(?:y|ies)\b|\bagenc(?:y|ies)\b|\bsubscribers?\b|\binstitutions?\b)"),
    ("users", r"(?i:\busers?\b)"),
    ("gross_margin", r"(?i:\bmargins?\b)"),
    ("gross_profit", r"(?i:\bgross profits?\b)"),
    ("costs", r"(?i:\bcosts?\b|\bopex\b)"),
    ("ebitda", r"\bEBITDA\b|(?i:\bprofitab(?:ility|le)\b|\bbreak[- ]?even\b)"),
    ("net_profit", r"(?i:\bnet (?:profits?|income|loss(?:es)?)\b)"),
    ("people", r"(?i:\bhir(?:e|es|ed|ing)\b|\bheadcounts?\b|\bteams?\b|\brecruit(?:s|ed|ing|ment)?\b"
               r"|\battrition\b)"),
    ("product", r"(?i:\blaunch(?:es|ed|ing)?\b|\breleas(?:e|es|ed|ing)\b|\broadmaps?\b|\bship(?:s|ped|ping)?\b"
                r"|\bmilestones?\b)"),
    ("market", r"\b(?:TAM|SAM|SOM)\b|(?i:\baddressable markets?\b|\bmarket[ -]sizes?\b)"),
    # Issue #45: the keywords of LTV, CAC and customer life moved here from sales and retention; "cash flow" is no
    # cash keyword. "Profitable" stays ebitda unless its figure is in months (_PROFITABLE).
    ("cash", r"(?i:\bcash\b(?![- ]?flows?\b))"),
    ("burn", r"(?i:\b(?:net )?burn(?:s|ed|ing)?(?: rates?)?\b)"),
    ("runway", r"(?i:\brunways?\b)"),
    ("ltv", r"\bLTVs?\b|(?i:\b(?:customer )?lifetime values?\b)"),
    ("cac", r"\bCACs?\b|(?i:\bcosts? (?:of|per) (?:paid )?(?:customer )?acquisitions?\b|\bacquisition costs?\b)"),
    ("customer_lifetime", r"(?i:\bcustomer life(?:time)?s?\b)"),
    ("ltv_cac", r"\bLTV\s*(?:/|:|\bto\b)\s*CAC\b"),
    ("trials_per_day", r"(?i:\btrials?\s*(?:per|/)\s*day\b)"),
]
_KEYWORDS = [(family, re.compile(rx)) for family, rx in _FAMILIES]
_NOUN_KEYWORDS = [(family, rx) for family, rx in _KEYWORDS if family in ("customers", "users")]
_GROWTH_OF = {"revenue": "revenue_growth", "users": "user_growth"}
# Plan claims only: the company's own figures the growth plan depends on.
CLAIM_TYPES = ("revenue", "revenue_growth", "growth", "retention", "sales", "customers", "users", "user_growth",
               "gross_margin", "gross_profit", "costs", "ebitda", "net_profit", "people", "product", "market",
               "cash", "burn", "runway", "ltv", "cac", "customer_lifetime", "ltv_cac", "trials_per_day",
               "months_to_profitability")
# A figure no line and no heading names a type for: listed as "unknown" and approved only once the analyst chooses a
# type (docs/specs/deck-parser.md section 2), like the model's "other" (structure-labelling.md section 4).
UNKNOWN = "unknown"
# An allocation share on a raise slide (deck-parser.md section 2, "Use of funds"): unit %, no engine metric, never Sales or Revenue.
USE_OF_FUNDS = "use_of_funds"

# The order of the claims table (deck-parser.md section 6): the group of a type, then slide or page. Revenue covers ARR,
# MRR and bookings; P&L items and unit economics are listed with their neighbours, and the types no group names
# (use of funds, the model's "other") are Other.
GROUPS = {1: "revenue", 2: "P&L", 3: "customers and sales", 4: "hiring and roadmap", 5: "market size", 6: "unknown", 7: "other"}
_GROUP_OF = {
    "revenue": 1, "revenue_growth": 1,
    "gross_profit": 2, "ebitda": 2, "burn": 2, "cash": 2, "runway": 2, "costs": 2, "net_profit": 2, "gross_margin": 2,
    "months_to_profitability": 2,
    "customers": 3, "users": 3, "user_growth": 3, "growth": 3, "retention": 3, "sales": 3, "ltv": 3, "cac": 3, "ltv_cac": 3,
    "customer_lifetime": 3, "trials_per_day": 3, "usage": 3,
    "people": 4, "product": 4,
    "market": 5, UNKNOWN: 6,
}
COLLAPSED_GROUPS = (6, 7)


def type_group(claim_type: Optional[str]) -> int:
    """1 to 7: the group a claim type sorts under."""
    return _GROUP_OF.get(claim_type or "", 7)
# A net loss is a negative net profit: "Net loss of $2M" is stored as -2,000,000.
_DIRECTION = re.compile(r"(?i)\b(positive|negative)\b")
_NET_LOSS = re.compile(r"(?i)\bnet loss(?:es)?\b")
# A gross margin given as an amount ("Gross margin £1.2M") is gross profit.
_GROSS_MARGIN = re.compile(r"(?i)\bgross margins?\b")
# "Profitable in 10 months" is months to profitability; any other "profitable" figure or line stays ebitda, a dated
# one a break-even milestone (decision of 2026-10-06 on issue #45).
_PROFITABLE = re.compile(r"(?i)\bprofitable\b")
# Lines that are a claim with no figure, given a date: a roadmap bullet, a break-even milestone.
_MILESTONES = ("product", "ebitda")
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
# Tables, structure text and the verifier match month names in English, German and Bulgarian,
# short and long forms, any case (spec section 2, period rules). Prose lines keep _MONTH above.
MONTH_NAMES = {
    1: ("january", "jan", "januar", "jän", "януари", "яну"),
    2: ("february", "feb", "februar", "февруари", "фев"),
    3: ("march", "mar", "märz", "maerz", "mär", "mrz", "март", "мар"),
    4: ("april", "apr", "април", "апр"),
    5: ("may", "mai", "май"),
    6: ("june", "jun", "juni", "юни"),
    7: ("july", "jul", "juli", "юли"),
    8: ("august", "aug", "август", "авг"),
    9: ("september", "sept", "sep", "септември", "сеп"),
    10: ("october", "oct", "oktober", "okt", "октомври", "окт"),
    11: ("november", "nov", "ноември", "ное"),
    12: ("december", "dec", "dezember", "dez", "декември", "дек"),
}
_MONTH_NUMBER = {name: n for n, names in MONTH_NAMES.items() for name in names}
_MONTH_ANY = (r"(?<![^\W\d_])(?P<month>(?i:" + "|".join(sorted(map(re.escape, _MONTH_NUMBER), key=len, reverse=True))
              + r"))(?![^\W\d_])")
_YY = r"(?P<year>(?:19|20)\d{2}|\d{2})"
_FY = r"(?P<fy>FY)\s*['’]?(?:(?:(?:19|20)\d{2}|\d{2})\s*/\s*)?" + _YY    # FY25, FY2024/25: named by the end year
# (kind, pattern). A fiscal year (FY, Y/E) is named by the year it ends in. Whether a range is fiscal is
# decided by the year-end alone (period_range).
_DATES = [
    # Apr FY25, FY2025 Apr: a month of a fiscal year ("FY2025-04")
    ("month", re.compile(_MONTH + r"\.?\s*[-/]?\s*" + _FY + r"\b")),
    ("month", re.compile(r"\b" + _FY + r"\s*[-/]?\s*" + _MONTH)),
    # Q1 FY25, FY25 Q1, H1 FY2024/25, FY25-H2: a quarter or half of a fiscal year
    ("quarter", re.compile(r"\bQ(?P<q>[1-4])\s*[-/]?\s*" + _FY + r"\b")),
    ("quarter", re.compile(r"\b" + _FY + r"\s*[-/]?\s*Q(?P<q>[1-4])\b")),
    ("half", re.compile(r"\bH(?P<h>[12])\s*[-/]?\s*" + _FY + r"\b")),
    ("half", re.compile(r"\b" + _FY + r"\s*[-/]?\s*H(?P<h>[12])\b")),
    # Q1-Q2 2023, Q3-Q4 23, 2023 Q1-Q2: the first and the second half (issue #55). Any other quarter range has no
    # period (no_period_dates).
    ("half", re.compile(r"\b(?P<hq>Q1\s*[-–]\s*Q2|Q3\s*[-–]\s*Q4)\s*['’]?\s*" + _YY + r"\b")),
    ("half", re.compile(r"(?<![\d.,])(?P<year>(?:19|20)\d{2})\s*[-/]?\s*(?P<hq>Q1\s*[-–]\s*Q2|Q3\s*[-–]\s*Q4)\b")),
    # Q3 2021, Q1 17
    ("quarter", re.compile(r"\bQ(?P<q>[1-4])\s*['’]?\s*" + _YY + r"\b")),
    # 2021 Q3, 2021-Q3
    ("quarter", re.compile(r"(?<![\d.,])(?P<year>(?:19|20)\d{2})\s*[-/]?\s*Q(?P<q>[1-4])\b")),
    # 3Q25, 3Q 2025
    ("quarter", re.compile(r"(?<![\w.,])(?P<q>[1-4])Q\s*['’]?" + _YY + r"\b")),
    # Periods (spec section 2): H1 24, 1H 2024, then FY2024/25, Y/E 22, 23 Y/E, FY23, 2023E
    ("half", re.compile(r"\bH(?P<h>[12])\s*['’]?\s*" + _YY + r"\b")),
    ("half", re.compile(r"(?<![\w.,])(?P<h>[12])H\s*['’]?" + _YY + r"\b")),
    # FY2024/25, FY24/25: the fiscal year that ends in the second year
    ("year", re.compile(r"\bFY\s*['’]?(?:(?:19|20)\d{2}|\d{2})\s*/\s*(?P<year>(?:19|20)\d{2}|\d{2})\b")),
    ("year", re.compile(r"\b(?:Y/?E|FY)\s*['’]?" + _YY + r"\b")),
    ("year", re.compile(r"(?<![\w$€£.,])" + _YY + r"\s*Y/?E\b")),
    ("year", re.compile(r"(?<![\w$€£.,'’])(?P<year>(?:19|20)\d{2})[EAFBP]\b")),
    # January 2011, Feb. 2007, April of 2011, May, 2021, Nov28,08, Aug2008, Mar '15
    ("month", re.compile(_MONTH + r"\.?,?\s*(?:(?:\d{1,2})(?:st|nd|rd|th)?,\s*(?P<y2>\d{2})\b|"
                         r"(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(?:of\s+)?(?P<year>(?:19|20)\d{2})\b|['’](?P<y3>\d{2})\b)")),
    # a bare year: 2024, by end of 2020
    ("year", re.compile(r"(?<![\w$€£.,'’])(?P<year>(?:19|20)\d{2})(?![\d%]|\.\d|,\d)")),
]


def _table_dates() -> list:
    """_DATES with month names in every language and case, and ISO months (2025-03) just before the
    plain month form, for tables."""
    out = []
    for kind, rx in _DATES:
        if kind == "month":
            if "fy" not in rx.groupindex:
                out.append(("month", re.compile(r"(?<![\d.,/-])(?P<year>(?:19|20)\d{2})-(?P<mnum>0[1-9]|1[0-2])(?![\d-])")))
            rx = re.compile(rx.pattern.replace(_MONTH, _MONTH_ANY))
        out.append((kind, rx))
    return out


_TABLE_DATES = _table_dates()

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


# A date written with slashes, d/d/yy or d/d/yyyy ("5/1/18", "12/31/2018"; issue #53, option a): the order of day
# and month is not stated, so it is a date with no period. None of its parts is a figure, it is no period cell and
# nothing is dated from it, its year included.
_SLASH_DATE = re.compile(r"(?<![\w/.,])(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?:\d{4}|\d{2})(?![\w/]|[.,]\d)")


def slash_dates(text: str) -> List[Tuple[int, int]]:
    """(start, end) of each date written with slashes in a text: d/d/yy or d/d/yyyy, both parts 1 to 31 and one of
    them at most 12."""
    return [m.span() for m in _SLASH_DATE.finditer(text or "")
            if all(1 <= int(m.group(g)) <= 31 for g in "ab") and min(int(m.group("a")), int(m.group("b"))) <= 12]


# A quarter range that is no half ("Q2-Q3 2023", "2023 Q1-Q3"; decision of 2026-10-07 on issue #55): it has no period,
# so nothing is dated from it and its year is no figure. "Q1-Q2" and "Q3-Q4" are the halves (_DATES).
_QUARTER_RANGES = (re.compile(r"\bQ(?P<a>[1-4])\s*[-–]\s*Q(?P<b>[1-4])(?:\s*['’]?\s*" + _YY + r"\b)?"),
                   re.compile(r"(?<![\d.,])(?:19|20)\d{2}\s*[-/]?\s*Q(?P<a>[1-4])\s*[-–]\s*Q(?P<b>[1-4])\b"))


def no_period_dates(text: str) -> List[Tuple[int, int]]:
    """(start, end) of each date with no period in a text: a date written with slashes (slash_dates) and a quarter
    range that is no half."""
    ranges = [m.span() for rx in _QUARTER_RANGES for m in rx.finditer(text or "")
              if (m.group("a"), m.group("b")) not in (("1", "2"), ("3", "4"))]
    return slash_dates(text) + ranges


def _year(text: str) -> int:
    return int(text) if len(text) == 4 else 2000 + int(text)


def find_dates(line: str, table: bool = False) -> List[Dict]:
    """[{"start", "end", "date", "kind", "text"}], longest forms first, no overlaps. In a table cell
    (`table`) month names are matched in English, German and Bulgarian, any case. A date with no period (a date
    written with slashes, a quarter range that is no half) gives none (no_period_dates)."""
    found, slashes = [], no_period_dates(line)
    for kind, rx in (_TABLE_DATES if table else _DATES):
        for m in rx.finditer(line):
            if any(m.start() < d["end"] and d["start"] < m.end() for d in found) \
                    or any(m.start() < end and start < m.end() for start, end in slashes):
                continue
            g = m.groupdict()
            if kind == "quarter":
                date = f"{_year(g['year'])}-Q{g['q']}"
            elif kind == "half":
                date = f"{_year(g['year'])}-H{g.get('h') or _half(g['hq'])}"
            elif kind == "month":
                year = g.get("year") or g.get("y2") or g.get("y3")
                month = int(g["mnum"]) if g.get("mnum") else _month_number(g["month"])
                date = f"{'FY' if g.get('fy') else ''}{_year(year)}-{month:02d}"
            else:
                date = str(_year(g["year"]))
            found.append({"start": m.start(), "end": m.end(), "date": date, "kind": kind, "text": m.group(0)})
    return sorted(found, key=lambda d: d["start"])


def _half(quarters: str) -> str:
    """The half a quarter range gives: "Q1-Q2" -> "1", "Q3-Q4" -> "2" (issue #55)."""
    return "1" if quarters.lstrip().startswith("Q1") else "2"


def _month_number(name: str) -> int:
    name = name.lower().rstrip(".")
    return _MONTH_NUMBER.get(name) or _MONTHS[name[:3]]


# A header that counts periods from a start the sheet does not give: M1...M24, Month 3, Year 1.
_RELATIVE = re.compile(r"(?i)^\s*(?:M|Month|Monat|Y|Year|Jahr|Q|Quarter)\s*-?\s*(?P<n>\d{1,3})\s*$")
_PART = re.compile(r"(?i)^\s*(?:(?P<hq>Q1\s*[-–]\s*Q2|Q3\s*[-–]\s*Q4)|Q(?P<q>[1-4])|H(?P<h>[12])|" + _MONTH_ANY
                   + r")\.?\s*$")


def period_cell(text: str) -> Optional[Dict]:
    """What one header cell says about a period (spec section 2, period rules):

        {"label": "2025-Q3", "text": "Q3 2025", "kind": "quarter"}  a full period
        {"part": "Q3"} / {"part": "03"} / {"part": "H1"}              a quarter, month or half with no year
        {"relative": 3}                                               M3, Month 3, Year 3: no start date
        None                                                          no period

    A full period is a cell with exactly one date. A bare year is a full period and can also stand
    above a part ("Mar" under "2025" is FY2025-03, see combine_period). "Q3" with no year is a part,
    never a period: the year is never inferred from the deck date, the file name or neighbouring
    columns. Month names are matched in English, German and Bulgarian, any case."""
    text = (text or "").strip()
    if not text:
        return None
    m = _PART.match(text)
    if m:
        if m.group("hq"):
            return {"part": f"H{_half(m.group('hq').upper())}"}
        if m.group("q"):
            return {"part": f"Q{m.group('q')}"}
        if m.group("h"):
            return {"part": f"H{m.group('h')}"}
        return {"part": f"{_month_number(m.group('month')):02d}"}
    if _RELATIVE.match(text) and not find_dates(text, table=True):
        return {"relative": int(_RELATIVE.match(text).group("n"))}
    dates = find_dates(text, table=True)
    if len(dates) != 1:
        return None
    d = dates[0]
    return {"label": d["date"], "text": d["text"], "kind": d["kind"]}


def combine_period(part_cell: Optional[Dict], year_cell: Optional[Dict]) -> Optional[Dict]:
    """A period built from two cells: a month, quarter or half and the year cell above it ("Q3" + "2025"
    or "FY2025" -> 2025-Q3; "Mar" + "2025" or "FY2025" -> FY2025-03, the March inside that year). Both
    follow the year-end (period_range). None when the upper cell is not a year."""
    if not part_cell or "part" not in part_cell or not year_cell or year_cell.get("kind") != "year" \
            or not re.fullmatch(r"\d{4}", year_cell.get("label") or ""):
        return None
    part = part_cell["part"]
    label = f"{year_cell['label']}-{part}" if part[0] in "QH" else f"FY{year_cell['label']}-{part}"
    return {"label": label, "kind": "two_cell"}


def period_range(label: Optional[str], fiscal_year_end: int = 12) -> Optional[Tuple[str, str]]:
    """(start, end) as ISO dates for a period label, or None when it is not one.

    "2025-03" is a calendar month. "2025", "2025-Q3", "2025-H1", "FY2025" and "FY2024/25" follow the
    year-end: fiscal year 2025 ends on the last day of `fiscal_year_end` (1-12) in 2025 and starts 12
    months earlier, and its quarters and halves count from that start. "FY2025-04" is the April inside
    year 2025: up to the year-end month in 2025, after it in 2024. With December every period is the
    calendar one.
    """
    m = re.fullmatch(r"FY(?P<y>\d{4})-(?P<m>0[1-9]|1[0-2])", label or "")
    if m:
        year, month = int(m.group("y")), int(m.group("m"))
        label = f"{year - 1 if month > fiscal_year_end else year}-{month:02d}"
    m = re.fullmatch(r"FY(?:(?P<c>\d{2})\d{2}/)?(?P<y>\d{2}|\d{4})", label or "")
    if m:                                           # FY2024/25: the second year in the century of the first
        y = m.group("y")
        label = (m.group("c") or "20") + y if len(y) == 2 else y
    m = re.fullmatch(r"(?P<y>\d{4})(?:-(?P<part>Q[1-4]|H[12]|0[1-9]|1[0-2]))?", label or "")
    if not m:
        return None
    year, part = int(m.group("y")), m.group("part")
    start = year * 12 + fiscal_year_end - 12        # months since year 0 to the fiscal year's first month
    if part is None:
        first, length = start, 12
    elif part[0] == "Q":
        first, length = start + 3 * (int(part[1]) - 1), 3
    elif part[0] == "H":
        first, length = start + 6 * (int(part[1]) - 1), 6
    else:
        first, length = year * 12 + int(part) - 1, 1
    (y0, m0), (y1, m1) = divmod(first, 12), divmod(first + length - 1, 12)
    return date(y0, m0 + 1, 1).isoformat(), date(y1, m1 + 1, calendar.monthrange(y1, m1 + 1)[1]).isoformat()


def resolve_period(value: Dict, fiscal_year_end: int = 12) -> Dict:
    """Set "period_start" and "period_end" on a value from its target_date."""
    found = period_range(value.get("target_date"), fiscal_year_end)
    value["period_start"], value["period_end"] = found or (None, None)
    return value


def remap_periods(candidates: List[Dict], fiscal_year_end: int = 12) -> List[Dict]:
    """Re-run the date range of every value for a fiscal year-end (spec section 2). The stated text and
    the target date stay; only the ranges move."""
    for c in candidates:
        resolve_period(c, fiscal_year_end)
        for item in c.get("by_period") or ():
            resolve_period(item, fiscal_year_end)
    return candidates


def find_numbers(line: str, dates: List[Dict]) -> List[Dict]:
    """Figures in the line that are not part of a date (one with no period included, no_period_dates) and not an
    ordinal ("2nd half")."""
    out, slashes = [], no_period_dates(line)
    for m in _NUMBER.finditer(line):
        num_start = m.start("num")
        if m.group("ord") or any(d["start"] <= num_start < d["end"] for d in dates) \
                or any(start <= num_start < end for start, end in slashes):
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


class _Text(str):
    """The joined text of a text box (or of a slide title) that keeps its lines, so a label can name the one line that
    holds the keyword (docs/specs/deck-parser.md section 2: "Label from" is a single heading)."""

    def __new__(cls, lines: Iterable[str], distance: Optional[float] = None):
        lines = list(lines)
        text = super().__new__(cls, " ".join(lines))
        text.lines = lines
        text.distance = distance      # from the line it is context of, on the page; None when the file has no layout
        return text


HEADING_MAX = 59       # the label length of deck-parser.md section 7: a box this short is one (wrapped) heading


def _heading(text: str, start: int, end: int) -> str:
    """The heading that holds the keyword at start..end. A box or title that fits HEADING_MAX is one heading, wrapped
    over its lines ("Spend as" / "% of revenue"); a longer one holds several, and the heading is the line the keyword
    sits on (the lines it runs over, if it wraps: "MARKET" / "SIZE")."""
    lines = getattr(text, "lines", None)
    if not lines or len(lines) < 2 or len(text) <= HEADING_MAX:
        return str(text)
    held, at = [], 0
    for line in lines:
        if at < end and start < at + len(line):
            held.append(line)
        at += len(line) + 1
    return " ".join(held) or str(text)


def _is_heading(text: str) -> bool:
    """A label, not a data line or prose: a word, no figure of its own, and no longer than a heading (HEADING_MAX). A
    text with a claim keyword is read as a heading whatever it holds ("Revenue $5M" names its type); a figure line or
    a sentence without one is passed over."""
    return bool(_WORD.search(text)) and len(text) <= HEADING_MAX and not find_numbers(text, find_dates(text))


def _borrow_keyword(texts: Iterable[str], nearest: bool = True) -> Optional[Tuple[str, str, str]]:
    """(family, text, heading) of the heading that names the type; the heading is the one line of the text that holds
    the keyword (the text itself when it is one line). With `nearest` only the nearest heading counts (docs/specs/
    deck-parser.md section 2): the closest text on the page that is a heading or holds a keyword (the first in the
    order given when the file has no layout); when it names no type the figure has none. Without it the first text
    with a keyword wins wherever it sits, which only tells that a type exists further away."""
    texts = list(texts)
    if not nearest:
        texts = [t for t in texts if _keywords(t)]
    else:
        texts = [t for t in texts if _keywords(t) or _is_heading(t)]
        texts.sort(key=lambda t: float("inf") if getattr(t, "distance", None) is None else t.distance)   # stable
    for text in texts[:1]:
        found = _keywords(text)
        if found:
            return _type(found[0], found), text, _heading(text, found[0]["start"], found[0]["end"])
    return None


def _borrow_date(texts: Iterable[str]) -> Optional[Tuple[str, str, str]]:
    """(date, text, the date as stated): the first month or quarter in the texts, else the first year."""
    texts = list(texts)
    for wanted in (("quarter", "half", "month"), ("year",)):
        for text in texts:
            found = [d for d in find_dates(text) if d["kind"] in wanted]
            if found:
                return found[0]["date"], text, found[0]["text"]
    return None


def line_candidates(line: str, refs: Iterable, context: Iterable[str] = (), headers: Optional[Dict] = None,
                    box_period: Optional[str] = None, column_periods: Optional[Dict] = None,
                    bar_label: Optional[str] = None, percent_type: Optional[str] = None) -> List[Dict]:
    """Candidates in one line. `refs` gives each figure's source reference: a list of
    (start, end, ref) spans, so a table row cites the cell a figure sits in. `context` is the
    nearby text to borrow from, most relevant first; `headers` maps a table column to its header;
    `box_period` is the period line at the top of the line's text box ("23 Y/E"). `column_periods`
    maps a table column to the period its header stack states, or NO_PERIOD (see column_periods);
    a table row is read with the table period rules. `bar_label` is the year label under the figure's bar (see
    _bar_labels). `percent_type` types a percentage that no keyword or heading names (a share of a raise)."""
    refs, context, headers, column_periods = list(refs), list(context), headers or {}, column_periods
    table = column_periods is not None
    keywords = _keywords(line)
    date_words = [{"start": m.start(), "end": m.end()} for m in _DATE_WORD.finditer(line)]
    dates = find_dates(line, table=table)
    numbers = find_numbers(line, dates)

    def ref_at(pos: int) -> Dict:
        return next((r for s, e, r in refs if s <= pos < e), refs[0][2])

    def claim(pos, family, value=None, high=None, unit=None, currency=None, date=None, label=None, date_from=None,
              stated=False, period_text=None, type_from="line", direction=None):
        # "_stated": the date is the figure's own, its column header's or its box's period, not one
        # borrowed by position; only stated periods are compared for a deck inconsistency.
        return {"claim_type": family, "value": value, "value_high": high, "unit": unit, "currency": currency,
                "target_date": date, "period_text": period_text if date else None, "snippet": _snippet(line, pos),
                "label_from": label and _label(label),
                "date_from": date_from and date_from != label and _label(date_from) or None, "sources": [ref_at(pos)],
                "type_from": None if family == UNKNOWN else type_from, "claim_direction": direction, "_stated": stated}

    out = []
    for n in numbers:
        own = _nearest(keywords, n)
        header = headers.get(ref_at(n["pos"]).get("col"))
        nearby = [header] if header else []
        borrowed = None if own else _borrow_keyword(nearby, nearest=False) or _borrow_keyword(context)
        if own:
            family = _type(own, keywords, n["unit"])
        elif borrowed:
            family = borrowed[0]
        elif date_words or _borrow_keyword(nearby + context, nearest=False):
            # No line and no nearest heading names a type: not guessed. A date word, or a keyword only further away,
            # keeps the figure as a candidate.
            family = UNKNOWN
        elif percent_type and n["unit"] == "%":
            family = percent_type
        else:
            continue
        if family == "gross_margin" and n["currency"] and _GROSS_MARGIN.search(borrowed[1] if borrowed else line):
            family = "gross_profit"
        if family == "ebitda" and n["unit"] == "months" and \
                _PROFITABLE.search(borrowed[1] if borrowed else line[own["start"]:own["end"]]):
            family = "months_to_profitability"
        if family == "net_profit" and _NET_LOSS.search(borrowed[1] if borrowed else line[own["start"]:own["end"]]):
            n = {**n, "value": -(n["value_high"] if n["value_high"] is not None else n["value"]),
                 "value_high": -n["value"] if n["value_high"] is not None else None}
        own_date = _nearest(dates, n)
        stacked = (column_periods or {}).get(ref_at(n["pos"]).get("col"))
        if own_date or stacked is None:
            # The year label under a bar is the figure's own date: taken after its own date, column header and box period, before
            # any text further away, and "stated", so it is compared for a deck inconsistency (docs/specs/deck-parser.md section 2).
            date = None if own_date else _borrow_date(nearby) or _borrow_date([box_period] if box_period else []) \
                or _borrow_date([bar_label] if bar_label else [])
            stated = bool(own_date or date)
            date = date or (None if own_date else _borrow_date(context))
        else:
            # The header stack states the column's period, or says it has none (a month or quarter
            # with no year above it, a relative column): never borrowed from anywhere else.
            date = None if stacked is NO_PERIOD else (stacked["label"], stacked["text"], stacked["text"])
            stated = date is not None
        out.append(claim(n["pos"], family, n["value"], n["value_high"], n["unit"], n["currency"],
                         own_date["date"] if own_date else date and date[0],
                         label=borrowed and borrowed[2], date_from=date and date[1], stated=stated,
                         period_text=own_date["text"] if own_date else date and date[2],
                         type_from="line" if own else "heading"))
    if numbers:
        return out
    if dates:
        # Only dates: a launch month or a roadmap quarter. A bare year counts only next to a
        # claim keyword in its own line ("ARR by end of 2018").
        borrowed = None if keywords else _borrow_keyword(context)
        if not keywords and not date_words:
            if not (borrowed or _borrow_keyword(context, nearest=False)) or all(d["kind"] == "year" for d in dates):
                return []
        # A bare date under a milestone ("Positive EBITDA" / "Q2 2024") takes the milestone's type.
        family = "ebitda" if not keywords and (borrowed or [None])[0] == "ebitda" else "product"
        if not keywords and not borrowed:
            family = UNKNOWN              # a date word alone names no type
        # "Positive EBITDA" above or beside a date: a direction, and no figure.
        said = _DIRECTION.search(line if keywords else borrowed[2] if borrowed else "") \
            if "ebitda" in (family, *(k["family"] for k in keywords)) else None
        return [claim(d["start"], _type(_nearest(keywords, d), keywords) if keywords else family, date=d["date"],
                      label=family not in ("product", UNKNOWN) and borrowed[2] or None, stated=True, period_text=d["text"],
                      type_from="line" if keywords else "heading", direction=said and said.group(1).lower())
                for d in dates if d["kind"] != "year" or keywords]
    # No figure at all: a product line ("Launch the API", a roadmap bullet) or a break-even
    # milestone ("Positive EBITDA") takes a nearby date.
    own = _nearest(keywords, {"start": 0, "end": len(line)})
    borrowed = None if keywords else _borrow_keyword(context)
    family = own["family"] if own else borrowed and borrowed[0]
    if not own and not borrowed:
        # A milestone word only further away: the line is kept, its type is not guessed.
        far = _borrow_keyword(context, nearest=False)
        family = UNKNOWN if far and far[0] in _MILESTONES else None
    if family not in _MILESTONES and family != UNKNOWN:
        return []
    date = _borrow_date(context)
    if not date:
        return []
    # "Positive EBITDA": a direction and no figure, shown as such and never tested against a number.
    said = _DIRECTION.search(line) if family == "ebitda" and own else None
    return [claim(0, family, date=date[0], label=borrowed and borrowed[2], date_from=date[1], period_text=date[2],
                  type_from="line" if own else "heading", direction=said and said.group(1).lower())]


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
        periods = column_periods(rows)
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
                          "title": False, "headers": header if r != first else {}, "table_row": True,
                          "header_row": r == first, "column_periods": periods})
    return units


# A table column whose header stack says it has no period: a month or quarter with no year cell
# above it, or a relative column ("M1", "Year 1"). Its figures borrow no date from elsewhere.
NO_PERIOD = {"label": None}


def column_periods(rows: Dict[int, List[Dict]]) -> Dict[int, Dict]:
    """col -> the period a table's header stack gives that column (spec section 2, period rules).

    The header stack is the rows above the first row that holds a figure other than a date. For
    each column, the lowest header cell covering it that is a period decides: a full period
    ("Y/E 22", "Q3 2025", "Mär 2025"), a month, quarter or half combined with the year cell
    above it in the same column range ("Q3" under "2025" spanning the quarters), or NO_PERIOD for
    a part with no year above it or a relative column. A column no period cell covers is absent,
    and its figures borrow a date as before."""
    order = sorted(rows)
    stack = []
    for r in order:
        if not _header_like(rows[r]):
            break
        stack.append(r)
    if not stack or len(stack) == len(order):
        return {}

    def covers(cell, col):
        return cell["col"] <= col < cell["col"] + cell.get("col_span", 1)

    out = {}
    columns = {c["col"] for r in order[len(stack):] for c in rows[r]}
    for col in sorted(columns):
        for i in range(len(stack) - 1, -1, -1):
            cell = next((c for c in rows[stack[i]] if covers(c, col)), None)
            found = period_cell(cell["text"]) if cell else None
            if not found:
                continue
            if "label" in found:
                out[col] = {"label": found["label"], "text": found["text"]}
            elif "part" in found:
                span = range(cell["col"], cell["col"] + cell.get("col_span", 1))
                above = [c for j in range(i - 1, -1, -1) for c in rows[stack[j]]
                         if all(covers(c, k) for k in span) and period_cell(c["text"])]
                joined = combine_period(found, period_cell(above[0]["text"])) if above else None
                out[col] = {"label": joined["label"], "text": f"{cell['text']} {above[0]['text']}"} if joined else NO_PERIOD
            else:
                out[col] = NO_PERIOD
            break
    return out


def _period_only(text: str) -> bool:
    """A line that is nothing but a period: "23 Y/E", "FY24", "Q3 25"."""
    dates = find_dates(text)
    return len(dates) == 1 and not re.search(r"\w", text[:dates[0]["start"]] + text[dates[0]["end"]:])


def _box_periods(units: List[Dict]) -> Dict[int, str]:
    """id(unit) -> the period line at the top of its text box, for every other line of the box."""
    boxes = {}
    for u in units:
        if u["box"] is not None and not u.get("table_row"):
            boxes.setdefault(u["box"], []).append(u)
    out = {}
    for members in boxes.values():
        top = min(members, key=lambda m: m["bbox"][1]) if all(m["bbox"] for m in members) else members[0]
        if len(members) > 1 and _period_only(top["text"]):
            out.update((id(m), top["text"]) for m in members if m is not top)
            out[id(top)] = None         # the period line itself is never a candidate
    return out


BAR_ROW = 0.02      # the year labels of one chart axis share a line: their tops differ by less than this (page fraction)
BAR_REACH = 0.6     # a bar's value sits at most this far above its label (page fraction): the bar itself fills the gap


def _bar_labels(units: List[Dict]) -> Dict[int, str]:
    """id(unit) -> the year label under the figure's bar. A bar chart read from the page's text has its values above the
    bars and one year or FY label under each ("FY2023", "2024"); the labels are two or more lines on one row, each
    nothing but a year. A figure takes the nearest such label below it that overlaps it from side to side; with no
    such row, or no label under the figure, it has none (docs/specs/deck-parser.md section 2)."""
    out = {}
    pages = {}
    for u in units:
        if u["bbox"] and not u.get("table_row") and not u["title"]:
            pages.setdefault(u["page"], []).append(u)
    for members in pages.values():
        labels = [u for u in members if _period_only(u["text"]) and find_dates(u["text"])[0]["kind"] == "year"]
        rows = [[l for l in labels if abs(l["bbox"][1] - top["bbox"][1]) < BAR_ROW] for top in labels]
        axis = [l for row in rows if len(row) >= 2 for l in row]
        for u in members:
            if u in labels or not find_numbers(u["text"], find_dates(u["text"])):
                continue
            x0, y0, x1, y1 = u["bbox"]
            under = [l for l in axis if l["bbox"][1] >= y1 - 0.005 and l["bbox"][1] - y1 <= BAR_REACH
                     and l["bbox"][0] < x1 and x0 < l["bbox"][2]]
            if under:
                centre = (x0 + x1) / 2
                best = min(under, key=lambda l: (abs((l["bbox"][0] + l["bbox"][2]) / 2 - centre), l["bbox"][1]))
                out[id(u)] = best["text"]
    return out


def _reach(line_bbox, box_bbox) -> Optional[float]:
    """Distance from a line to a box on the same row or above it; None when the box is below."""
    x0, y0, x1, y1 = line_bbox
    bx0, by0, bx1, by1 = box_bbox
    if by0 >= y1:
        return None
    return hypot(max(0.0, bx0 - x1, x0 - bx1), max(0.0, y0 - by1))


def _gap(a, b) -> Optional[float]:
    """Distance between two boxes on the page (0 when they touch or overlap); None when either has no position."""
    if not a or not b:
        return None
    return hypot(max(0.0, b[0] - a[2], a[0] - b[2]), max(0.0, b[1] - a[3], a[1] - b[3]))


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
        shapes[key] = (_Text(m["text"] for m in members), bbox)
    out = {}
    for page, members in pages.items():
        title = _Text(m["text"] for m in members if m["title"])
        for u in members:
            texts = []
            if u["box"] is not None and not u.get("table_row"):
                box = boxes[u["box"]]
                i = next(k for k, m in enumerate(box) if m is u)
                texts += [_Text([m["text"]], _gap(u["bbox"], m["bbox"]))
                          for k, m in sorted(enumerate(box), key=lambda km: (abs(km[0] - i), km[0] > i)) if m is not u]
            if u["bbox"]:
                near = []
                for key, (text, bbox) in shapes.items():
                    if key[-2 if key[0] == "table" else 0] != page or key == u["box"] or not bbox:
                        continue
                    distance = _reach(u["bbox"], bbox)
                    if distance is not None and distance <= REACH:
                        near.append((distance, bbox[1], text))
                texts += [_Text(text.lines, distance) for distance, _, text in sorted(near, key=lambda n: n[:2])]
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
        if _page_excluded(members):
            out.update(id(m) for m in members)
        out.update(id(m) for m in members if _NOT_PLAN_LINE.search(m["text"]))
    return out


def _page_excluded(members: List[Dict]) -> bool:
    """A slide titled Problem, Why now and the like, or a page that cites outside research."""
    title = " ".join(m["text"] for m in members if m["title"])
    cited = any(_CITED.search(m["text"]) for m in members) or \
        sum(1 for m in members if _FOOTNOTE.search(m["text"])) >= 2
    return bool(_BACKGROUND_TITLE.search(title) or cited)


def excluded_pages(blocks: List[Dict]) -> set:
    """(slide, page) keys of the pages whose every figure is dropped as background or cited research
    (spec section 2). The structure detector skips them too (spec section 7)."""
    pages = {}
    for u in _units(blocks, ""):
        pages.setdefault(u["page"], []).append(u)
    return {page for page, members in pages.items() if _page_excluded(members)}


def figures(text: str) -> List[Dict]:
    """The figures of a text that are not dates (a period is a date, never a value)."""
    return find_numbers(text, find_dates(text))


def has_product_keyword(text: str) -> bool:
    """True when a text holds a product keyword: launch, release, roadmap, ship, milestone."""
    return any(k["family"] == "product" for k in _keywords(text or ""))


def tick_cells(blocks: List[Dict]) -> set:
    """(page, table, row, col) of the table cells that are row numbers (see _tick_cells)."""
    return _tick_cells(blocks)


def tick_lines(blocks: List[Dict]) -> set:
    """id() of the text lines that are chart axis ticks (see _axis_ticks)."""
    lines = [b for b in blocks if b["kind"] != "table"]
    units = [{"text": b["text"], "page": (b.get("slide"), b.get("page")), "bbox": b.get("bbox")} for b in lines]
    ticks = _axis_ticks(units)
    return {id(b) for b, u in zip(lines, units) if id(u) in ticks}


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
    """(page, table, row, col) of table cells that are row numbers: one bare number per cell, 3 or
    more evenly spaced down a column ("1 2 3"). A row of a table is a series of values, never
    ticks, and the header row is never ticks."""
    first = {}
    for b in blocks:
        if b["kind"] == "table":
            key = (b.get("slide") or b.get("page"), b["table"])
            first[key] = min(first.get(key, b["row"]), b["row"])
    cells = {}
    for b in blocks:
        if b["kind"] == "table" and b["row"] != first[(b.get("slide") or b.get("page"), b["table"])]:
            values = _bare_values(b["text"])
            if len(values) == 1:
                cells[(b.get("slide") or b.get("page"), b["table"], b["row"], b["col"])] = values[0]
    out, columns = set(), {}
    for key, value in cells.items():
        columns.setdefault(key[:2] + (key[3],), []).append((key, value))
    for members in columns.values():
        if len(members) >= 3 and _evenly_spaced([v for _, v in members]):
            out.update(k for k, _ in members)
    return out


def _period_header(text: str) -> bool:
    """A table header row of periods ("Y/E 22 | Y/E 23", "Q1 24 | Q2 24", "Q1 | Q2 | Q3"): labels, not claims."""
    dates = find_dates(text, table=True)
    cells = [c for c in text.split(" | ") if c.strip()]
    parts = cells and all(period_cell(c) and "label" not in period_cell(c) for c in cells[1:] or cells)
    return (bool(dates) or bool(parts)) and _header_like([{"text": c} for c in cells])


_BRACKET = re.compile(r"[(\[]([^()\[\]]{1,30})[)\]]")
_BRACKET_SCALE = re.compile(r"(?i)(?<![a-z])(?:k|m|mm|mn|bn|b|million|thousand|billion)(?![a-z])")
_BRACKET_CURRENCY = re.compile(r"US\$|[$€£]|(?<![A-Za-z])(?:USD|EUR|GBP)(?![A-Za-z])")
_BRACKET_BASIS = (
    (re.compile(r"(?i)/\s*(?:year|yr|annum|a)\b|\bper\s+(?:year|yr|annum)\b|\bp\.?a\.?(?![a-z])|\bannual(?:ly)?\b|\byearly\b"), "per year"),
    (re.compile(r"(?i)/\s*(?:month|mo)\b|\bper\s+month\b|\bmonthly\b"), "per month"),
    (re.compile(r"(?i)/\s*(?:quarter|qtr)\b|\bper\s+quarter\b|\bquarterly\b"), "per quarter"),
)


def bracket_units(text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(currency, period basis) a label states in brackets: "Turnover (£/year)" -> ("GBP", "per year"). A bracket that
    scales the figure ("(€m)", "($k)") is not read: the value would be wrong by the scale. Nothing is guessed: no
    symbol, code or period word, no answer."""
    currency = basis = None
    for m in _BRACKET.finditer(text or ""):
        inner = m.group(1)
        if _BRACKET_SCALE.search(inner):
            continue
        found = _BRACKET_CURRENCY.search(inner)
        if found and not currency:
            currency = _CURRENCY[found.group(0)]
        if not basis:
            basis = next((name for rx, name in _BRACKET_BASIS if rx.search(inner)), None)
    return currency, basis


def label_units(candidate: Dict) -> Tuple[Optional[str], Optional[str]]:
    """The currency and period basis a candidate's label (the heading it borrowed, else its own line) states in brackets."""
    for text in (candidate.get("label_from"), candidate.get("snippet")):
        currency, basis = bracket_units(text)
        if currency or basis:
            return currency, basis
    return None, None


def _apply_label_units(found: List[Dict]) -> None:
    """Before scoring: the currency and period basis a label states fill what the figure itself leaves empty. A figure
    with its own currency or unit keeps it. The date is never taken from here: "per year" is not a year."""
    for c in found:
        c.setdefault("period_basis", None)
        if c.get("value") is None:
            continue
        currency, basis = label_units(c)
        if not c.get("currency") and not c.get("unit") and currency:
            c["currency"] = currency
        if basis:
            c["period_basis"] = basis


def detect_candidates(blocks: List[Dict], file: str, fiscal_year_end: int = 12) -> List[Dict]:
    """Every candidate in a parsed deck, duplicates merged in order of first appearance. Each value's
    period resolves to a date range under the audit's fiscal year-end (1-12, default December)."""
    units = _units(blocks, file)
    contexts = _contexts(units)
    skipped = _axis_ticks(units) | _not_plan(units)
    funds, mixed = _funds_units(units)
    tick_cells = _tick_cells(blocks)
    periods = _box_periods(units)
    bars = _bar_labels(units)
    merged = {}
    for u in units:
        if id(u) in skipped or (u.get("header_row") or u.get("table_row") and _in_stack(u)) and _period_header(u["text"]) \
                or id(u) in periods and periods[id(u)] is None:
            continue
        found = []
        for c in line_candidates(u["text"], u["spans"], contexts[id(u)], u["headers"], periods.get(id(u)),
                                 u.get("column_periods") if u.get("table_row") else None, bars.get(id(u)),
                                 USE_OF_FUNDS if id(u) in funds else None):
            s = c["sources"][0]
            if s["kind"] == "table" and (s.get("slide") or s.get("page"), s["table"], s["row"], s["col"]) in tick_cells:
                continue
            found.append(resolve_period(c, fiscal_year_end))
        if u.get("table_row"):
            found = _row_series(found, u["headers"])
        for c in found:
            if id(u) in mixed and c["unit"] == "%":
                c.update(claim_type=UNKNOWN, type_from=None, label_from=None, mixed_slide=True)
            elif id(u) in funds and c["unit"] == "%":
                # A share of the raise is not a plan claim: whatever keyword the category name holds ("Acquisition"),
                # it is never Sales or Revenue, and the heading it borrowed no longer names it.
                c.update(claim_type=USE_OF_FUNDS, type_from="heading", label_from=None)
                if not c.get("by_period"):
                    c["_funds"] = {"form": funds[id(u)], "category": _category(u["text"])}
        box = u.get("bbox")
        for c in found:
            c["reading"] = [round(box[1], 3), round(box[0], 3)] if box else None      # top, left: the reading order
            key = (c["claim_type"], c["value"], c["value_high"], c["unit"], c["currency"], c["target_date"],
                   c["period_start"], c["period_end"],
                   tuple((i["value"], i["value_high"], i["target_date"], i["period_start"], i["period_end"])
                         for i in c.get("by_period") or ()))
            if key not in merged:
                merged[key] = c
            else:
                kept = merged[key]
                kept["sources"] += [s for s in c["sources"] if s not in kept["sources"]]
                kept["_stated"] = kept["_stated"] or c["_stated"]
                for a, b in zip(kept.get("by_period") or (), c.get("by_period") or ()):
                    a["_stated"] = a["_stated"] or b["_stated"]
    found = _merge_unknown(list(merged.values()))
    _apply_label_units(found)
    _flag_inconsistencies(found)
    _flag_funds_inconsistencies(found)
    for c in found:
        c.pop("_funds", None)
    return found


def same_claim(a: Dict, b: Dict) -> Optional[Dict]:
    """The value of `a` that `b` states again: the same type, value, currency and period, and the same kind of unit when it is
    a rate (docs/specs/deck-parser.md section 2). Used to merge what the parser and the model read twice. A claim with no
    value (a milestone, a direction) never matches: two lines with the same date are not one claim."""
    if a.get("claim_type") != b.get("claim_type") or (a.get("currency") or None) != (b.get("currency") or None):
        return None
    if (a.get("unit") in ("%", "x") or b.get("unit") in ("%", "x")) and a.get("unit") != b.get("unit"):
        return None
    for x in claim_values(a):
        for y in claim_values(b):
            if x["value"] is not None and x["target_date"] and (x["value"], x["value_high"], x["target_date"], x["period_start"],
                                                                x["period_end"]) == (y["value"], y["value_high"], y["target_date"],
                                                                                     y["period_start"], y["period_end"]):
                return x
    return None


def _merge_unknown(found: List[Dict]) -> List[Dict]:
    """A date-only claim typed Unknown that gives the same figure and period as a Product claim is that claim: its
    sources join it (before issue "Unknown type" both were Product and merged, so no row appears)."""
    def rest(c):
        return (c["value"], c["value_high"], c["unit"], c["currency"], c["target_date"], c["period_start"], c["period_end"],
                tuple((i["value"], i["value_high"], i["target_date"], i["period_start"], i["period_end"])
                      for i in c.get("by_period") or ()))
    product = {}
    for c in found:
        if c["claim_type"] == "product":
            product.setdefault(rest(c), c)
    out = []
    for c in found:
        into = product.get(rest(c)) if c["claim_type"] == UNKNOWN else None
        if into is None:
            out.append(c)
            continue
        into["sources"] += [s for s in c["sources"] if s not in into["sources"]]
        into["_stated"] = into["_stated"] or c["_stated"]
    return out


def _header_like(cells: List[Dict]) -> bool:
    """A table row of labels and periods: no cell holds a figure other than a date, a month or quarter
    without its year, or a relative column ("Year 1", "M3")."""
    return not any(find_numbers(c["text"], find_dates(c["text"], table=True)) and not period_cell(c["text"])
                   for c in cells)


def _in_stack(unit: Dict) -> bool:
    """True for a table row in its header stack."""
    return _header_like([{"text": t} for t in unit["text"].split(" | ")])


_TURNOVER_TERM = re.compile(r"(?i)\b(?:turnover|GMV|TPV|gross merchandise (?:value|volume)|(?:total )?(?:trading|payment|transaction) volume)\b")
_RECURRING_TERM = re.compile(r"\b(?:ARR|MRR)\b")


def deck_label(c: Dict) -> Optional[str]:
    """The word the deck uses for a revenue-type figure: "Turnover" when its label or line holds a turnover term (and no
    ARR or MRR), else "Revenue". None for every other type. A turnover figure is never compared with a revenue figure
    for a deck inconsistency (docs/specs/claim-matching.md section 11)."""
    if c.get("claim_type") != "revenue":
        return None
    text = f"{c.get('label_from') or ''} {c.get('snippet') or ''}"
    return "Turnover" if _TURNOVER_TERM.search(text) and not _RECURRING_TERM.search(text) else "Revenue"


def _figure_of(c: Dict, v: Dict) -> Dict:
    """One stated figure with what the explanation of a deck inconsistency compares: value, currency, unit, date, place
    and the deck's own label."""
    return {"value": v["value"], "value_high": v["value_high"], "currency": c.get("currency"), "unit": c.get("unit"),
            "date": v["target_date"], "source": (v.get("sources") or [None])[0], "claim_type": c.get("claim_type"),
            "label": deck_label(c)}


def _flag_inconsistencies(candidates: List[Dict]) -> None:
    """Deck inconsistency: one deck gives the same type and period different values ("Gross Profit
    £150K" for Y/E 23 on a panel, £ 50,000 in the table). Every candidate holding one of them gets
    the period in "inconsistent_dates". Only stated periods are compared (the figure's own date,
    its column header's or its box's period), not a date borrowed by position; amounts in different
    currencies, or a rate and an amount, are not compared. Turnover is compared with turnover and revenue with revenue,
    never one with the other (claim-matching.md section 11)."""
    seen = {}
    for i, c in enumerate(candidates):
        for v in claim_values(c):
            if v["value"] is not None and v["target_date"] and v["_stated"]:
                key = (c["claim_type"], deck_label(c), v["target_date"], (v["period_start"], v["period_end"]), c["currency"],
                       c["unit"] if c["unit"] in ("%", "x") else None)
                seen.setdefault(key, []).append((i, (v["value"], v["value_high"]), _figure_of(c, v)))
    for (_, _, stated, _, _, _), found in seen.items():
        if len({value for _, value, _ in found}) > 1:
            for i, value, mine in found:
                dates = candidates[i].setdefault("inconsistent_dates", [])
                if stated not in dates:
                    dates.append(stated)
                # The explanation is built from the two figures themselves: this one and the first that differs from it.
                other = next(fig for _, v2, fig in found if v2 != value)
                candidates[i].setdefault("inconsistencies", []).append({"this": mine, "other": other})
    for c in candidates:
        c.setdefault("inconsistent_dates", [])
        c.setdefault("inconsistencies", [])
        c["inconsistent_dates"].sort()
        c.pop("_stated", None)
        for i in c.get("by_period") or ():
            i.pop("_stated", None)


# ---------------------------------------------------------------------------
# Use of funds (deck-parser.md section 2)
# ---------------------------------------------------------------------------
# The phrases that make a slide a raise (George, 2026-10-10): whole words, any case, in a slide title, a heading or a chart title.
FUNDS_CUES = ("use of funds", "use of proceeds", "the ask", "our ask", "funding ask", "investment ask", "funding request",
              "capital raise", "raise", "funding round", "financing", "proposed financing", "round details", "round size",
              "raise size", "funding requirements", "capital requirements", "capital sought", "funding sought",
              "sources & uses", "sources and uses", "investor proposition", "investment opportunity")
_FUNDS_CUE = re.compile(r"(?i)\b(?:" + "|".join(re.escape(c).replace(r"\ ", r"\s+") for c in FUNDS_CUES) + r")\b")
# Words that make a slide's percentages a split of something else (revenue by region, by year, ...). Acronyms in capitals only.
_NOT_FUNDS = re.compile(r"\b(?:ARR|MRR)\b|(?i:\b(?:revenues?|sales|turnover|bookings?|customers?|segments?|geograph(?:y|ies|ic|ical)"
                        r"|countr(?:y|ies)|regions?|product lines?|by years?)\b)")
_YEAR_LABEL = re.compile(r"\b(?:(?:19|20)\d{2}[A-Z]?|FY ?\d{2})\b")
YEAR_RUN = 3                    # this many different year labels on a slide are a run of years
MIXED_SLIDE = "mixed slide – check"
# A percentage on a line with one of these words is a rate ("15% MoM growth", "retention 90%"), not a share of the raise.
_RATE_WORDS = re.compile(dict(_FAMILIES)["growth"] + "|" + dict(_FAMILIES)["retention"] + "|" + dict(_FAMILIES)["gross_margin"])
_SHARE = re.compile(r"\s*[(\[]?\s*\d+(?:[.,]\d+)?\s*%\s*[)\]]?\s*")


def _percentages(text: str) -> List[float]:
    return [n["value"] for n in find_numbers(text, find_dates(text)) if n["unit"] == "%" and n["value"] is not None]


def _heading_unit(u: Dict) -> bool:
    """A slide title, a table's header row, or a line that is a heading (a word, no figure, at most HEADING_MAX characters)."""
    return bool(u["title"] or u.get("header_row") or _is_heading(u["text"]))


def _funds_units(units: List[Dict]) -> Tuple[Dict[int, str], set]:
    """(funds, mixed): `funds` maps id() of the lines whose percentages are a use of funds to their form, "text" (a line that
    names its category, "Marketing (25%)") or "chart" (a figure alone, a pie's data label); `mixed` holds id() of the
    percentage lines of a slide that is both. A cue phrase (FUNDS_CUES) in the slide's title, a heading or a table's header row
    is required; without one nothing is a use of funds, whatever the percentages sum to or the slide shows (a raise amount
    and a sum of 95-105 only confirm a cue, and change nothing). A slide whose title, headings (a heading line above the
    first percentage; a legend beside or below it is a label) or table headers hold a word of _NOT_FUNDS, or whose text holds
    a run of year labels, is a split of something else: with a cue it is "mixed" (the figures stay Unknown), without one it
    is not looked at. The label attached to a percentage is no heading: "Sales & Marketing 30%" stays a use of funds."""
    pages = {}
    for u in units:
        pages.setdefault(u["page"], []).append(u)
    funds, mixed = {}, set()
    for members in pages.values():
        if not any(_FUNDS_CUE.search(m["text"]) for m in members if _heading_unit(m)):
            continue
        shares = [u for u in members if not u.get("header_row") and not _RATE_WORDS.search(u["text"]) and _percentages(u["text"])]
        if not shares:
            continue
        first = min(members.index(u) for u in shares)
        tops = [u["bbox"][1] for u in shares if u.get("bbox")]

        def above(m):
            if m.get("bbox") and tops and len(tops) == len(shares):
                return m["bbox"][1] < min(tops)
            return members.index(m) < first

        heads = " ".join(m["text"] for m in members if m not in shares and
                         (m["title"] or m.get("header_row") or (_is_heading(m["text"]) and above(m))))
        text = " ".join(m["text"] for m in members)
        if _NOT_FUNDS.search(heads) or len(set(_YEAR_LABEL.findall(text))) >= YEAR_RUN:
            mixed.update(id(u) for u in shares)
        else:
            funds.update({id(u): "text" if _WORD.search(u["text"]) else "chart" for u in shares})
    return funds, mixed


def _category(text: str) -> str:
    return re.sub(r"\s+", " ", _SHARE.sub(" ", text)).strip(" :-–—,;")


def _rescale_note(text: List[Dict], chart: List[Dict]) -> Tuple[Optional[str], Optional[int], bool]:
    """(note, dropped, paired): the text figures and the chart's, in value order, are the same shares when the chart has one value
    fewer and each text value, rescaled to 100 after dropping one category, rounds to the chart's: then the note
    "chart excludes <category>, rescaled" (paired is False if two different categories would fit); or they are the same count
    and are paired in value order, with no note. Anything else is not paired: two sets of shares with no names on
    one side are never matched by guess."""
    t = sorted(text, key=lambda c: -c["value"])
    ch = sorted(chart, key=lambda c: -c["value"])
    if len(ch) == len(t) - 1 and ch:
        fits = []
        for k in range(len(t)):
            rest = [c["value"] for i, c in enumerate(t) if i != k]
            if sum(rest) and all(abs(v * 100 / sum(rest) - c["value"]) <= 0.5 for v, c in zip(rest, ch)):
                fits.append(k)
        names = {t[k]["_funds"]["category"] for k in fits}
        if len(names) == 1:
            return f"chart excludes {names.pop()}, rescaled", fits[0], True
        return None, None, False
    return None, None, len(ch) == len(t)


def _flag_funds_inconsistencies(candidates: List[Dict]) -> None:
    """Deck inconsistency on a use-of-funds slide: the narrative text and the chart give different percentages for the
    same categories (deck-parser.md section 2). Both figures of each pair carry it, labelled "text" and "chart", and
    the note "chart excludes <category>, rescaled" when the chart's values are the text's rescaled without one
    category. Never Contradicted: the label stays Unverified."""
    pages = {}
    for c in candidates:
        if c.get("_funds"):
            pages.setdefault(min((s.get("slide") or s.get("page") or 0) for s in c["sources"]), []).append(c)
    for members in pages.values():
        text = [c for c in members if c["_funds"]["form"] == "text"]
        chart = [c for c in members if c["_funds"]["form"] == "chart"]
        if not text or not chart or sorted(c["value"] for c in text) == sorted(c["value"] for c in chart):
            continue
        note, dropped, paired = _rescale_note(text, chart)
        if not paired:
            continue
        t = sorted(text, key=lambda c: -c["value"])
        ch = sorted(chart, key=lambda c: -c["value"])
        if dropped is not None:
            t = t[:dropped] + t[dropped + 1:]
        for a, b in zip(t, ch):
            if a["value"] == b["value"]:
                continue
            for mine, theirs in ((a, b), (b, a)):
                pair = {"this": {**_figure_of(mine, mine), "label": mine["_funds"]["form"]},
                        "other": {**_figure_of(theirs, theirs), "label": theirs["_funds"]["form"]}}
                if note:
                    pair["note"] = note
                mine.setdefault("inconsistencies", []).append(pair)


def _row_series(found: List[Dict], headers: Dict) -> List[Dict]:
    """One candidate per table row: the row's figures of one type become a single candidate
    whose values sit in "by_period", each with the date and the period of its column header
    ("Registered Users: 200 (Y/E 22) · 5,000 (Y/E 23)"). A lone figure stays a plain candidate."""
    def kind(c):
        return c["claim_type"], c["unit"], c["currency"]
    groups = {}
    for c in found:
        if c["value"] is not None:
            groups.setdefault(kind(c), []).append(c)
    out = []
    for c in found:
        group = groups.get(kind(c)) if c["value"] is not None else None
        if not group or len(group) == 1:
            out.append(c)
        elif c is group[0]:
            def period(item):
                header = headers.get(item["sources"][0].get("col"))
                if item["period_text"] and item["date_from"] == item["period_text"]:
                    return item["period_text"]          # the header stack's period ("Q3 2025")
                return header if header and find_dates(header) else item["date_from"]
            out.append({**c, "value": None, "value_high": None, "target_date": None, "date_from": None,
                        "period_text": None, "period_start": None, "period_end": None,
                        "label_from": next((i["label_from"] for i in group if i["label_from"]), None),
                        "sources": [i["sources"][0] for i in group],
                        "by_period": [{"value": i["value"], "value_high": i["value_high"], "target_date": i["target_date"],
                                       "period": period(i), "period_text": i["period_text"],
                                       "period_start": i["period_start"], "period_end": i["period_end"],
                                       "source": i["sources"][0], "_stated": i["_stated"]}
                                      for i in group]})
    return out


def claim_values(candidate: Dict) -> List[Dict]:
    """Each value a candidate states, as {value, value_high, target_date, period_start, period_end,
    sources}: the values of a table row by period, or the candidate itself."""
    if candidate.get("by_period"):
        return [{"value": i["value"], "value_high": i["value_high"], "target_date": i["target_date"],
                 "period_start": i.get("period_start"), "period_end": i.get("period_end"),
                 "sources": [i["source"]], "_stated": i.get("_stated")} for i in candidate["by_period"]]
    return [{k: candidate.get(k) for k in ("value", "value_high", "target_date", "period_start", "period_end",
                                           "sources", "_stated")}]


# ---------------------------------------------------------------------------
# Confidence of a candidate (docs/specs/deck-parser.md section 6)
# ---------------------------------------------------------------------------
def _place(source: Dict) -> Tuple:
    return tuple(source.get(k) for k in ("slide", "page", "kind", "table", "row", "col", "cell"))


def _value_keys(candidate: Dict) -> set:
    return {(candidate["claim_type"], v["value"], v["value_high"], candidate.get("unit"), candidate.get("currency"))
            for v in claim_values(candidate) if v["value"] is not None}


def _corroborated(candidate: Dict, peers: List[Dict]) -> bool:
    """The value is stated at another place of the deck: a duplicate merged into this candidate from another slide or
    page, or another candidate of the deck with the same type, value, unit and currency. The cells of one table row
    are one place."""
    keys = _value_keys(candidate)
    if not candidate.get("by_period") and len({_place(s) for s in candidate.get("sources") or ()}) > 1:
        return True
    mine = {_place(s) for s in candidate.get("sources") or ()}
    return any(other is not candidate and keys & _value_keys(other) and not mine & {_place(s) for s in other.get("sources") or ()}
               for other in peers)


def confidence(candidate: Dict, peers: List[Dict]) -> Dict:
    """High, Medium or Low from the checks the parser already runs, never from a model's own score: the claim has a
    date, a unit (or currency), a heading or line that names its type, and its value is corroborated elsewhere in the
    deck. No failed check is High, one is Medium, two or more Low. A check that cannot apply to a claim with no
    value (unit, corroboration) is skipped. `peers` are the candidates of the same deck. A claim the analyst added is
    not scored: its confidence reads "Analyst-entered"."""
    if candidate.get("origin") == "analyst":
        return {"level": None, "failed": [], "text": "Analyst-entered"}
    values = claim_values(candidate)
    has_value = any(v["value"] is not None for v in values)
    named = candidate.get("claim_type") not in (UNKNOWN, "other") and \
        bool(candidate.get("type_from", "line") or "parsed" in candidate)
    checks = [("no date", all(v["target_date"] for v in values))]
    if candidate.get("claim_direction") and not has_value:
        checks.append(("no figure", False))          # a direction is never better than Medium
    if has_value:
        # A label that states the currency in brackets ("Turnover (£/year)") counts, also on a candidate stored before the
        # label was read into its currency field: only what is still missing after that is listed.
        checks.append(("no unit", bool(candidate.get("unit") or candidate.get("currency") or label_units(candidate)[0])))
    checks.append(("no heading", named))
    if has_value:
        checks.append(("not corroborated", _corroborated(candidate, peers)))
    failed = [name for name, ok in checks if not ok]
    level = "High" if not failed else "Medium" if len(failed) == 1 else "Low"
    return {"level": level, "failed": failed, "text": level + (" – " + ", ".join(failed) if failed else "")}
