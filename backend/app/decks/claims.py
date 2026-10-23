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
import copy
import re
from datetime import date
from math import floor, hypot, log10
from typing import Dict, Iterable, List, Optional, Tuple

from app.decks.parser import _WRAP_WORDS

SNIPPET_MAX = 300
# How far a figure looks for a label or a date by position, as a share of the slide or page.
REACH = 0.25
_LABEL_MAX = SNIPPET_MAX

# Keyword families (spec section 2). A keyword matches its plural and verb forms: "revenues",
# "growing", "hired", "launches". Acronyms match in capitals only, so "Sam" or "arr" do not count.
# "market" is a whole word: "marketing" and "marketplace" do not count.
# Where two keywords overlap, the longer one counts: "paying users" is customers, not users;
# "customer lifetime value" is ltv, not customers or customer_lifetime; "LTV / CAC", "LTV:CAC" is ltv_cac.
# A revenue word, "per" or "/", and at most one adjective; the noun must then end the phrase: nothing, a mark, a figure or a period word follows.
# The noun X after "per" decides (George, 2026-10-20): account, client, customer -> ARPA; user, subscriber -> ARPU; month, quarter, year ->
# Revenue; a non-customer unit (employee, FTE, order, transaction, store, seat, licence) -> Other; any other noun (segment, region, product,
# country, geography, market, channel, type, cohort, line, use case, vertical...) is a breakdown, Revenue. A noun that a hyphen, a slash or another noun follows is a breakdown ("per customer-segment", "per
# employee type") and is Revenue.
_REVENUE_WORDS = r"(?:revenues?|sales|income|spend|ARR|MRR|bookings?)"
# "Sales / Marketing" and "Income / expenses" are no per-unit phrases: sales, income and spend take "per" only.
_PER_UNIT = r"\b(?:(?:average|avg) (?:\w+ )?)?(?:(?:revenues?|ARR|MRR|bookings?)\s*(?:per|/)|(?:sales|income|spend)\s*per)\s*(?:(?:paying|active|new|existing|average) )?"
_END_WORDS = r"by|in|per|over|for|at|monthly|annual|annually|quarterly|yearly|yoy|mom|ytd|ttm|fy|year|month|quarter|q[1-4]|h[12]"
_ENDS = r"(?![-/])(?=\s*(?:$|[^\w\s/]|\d|\b(?:" + _END_WORDS + r")\b))"
# The same phrase with a hyphen, a slash or another noun after the noun: a breakdown, Revenue (it outranks "customers" or "users" in the line).
_BREAKDOWN = r"(?i:" + _PER_UNIT + r"\w+(?:[-/][A-Za-z]|\s+(?!(?:" + _END_WORDS + r")\b)[A-Za-z]))"
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
    # George, 2026-10-20: a title, header or line is unit economics (ARPA, ARPU) when it says ARPA or ARPU, "average revenue per", or a
    # revenue word per customer, client, account or user ("Revenue / customer", "ARR per customer") and that noun ENDS the phrase:
    # "Revenue per customer segment", "per client type", "per user group" are breakdowns and stay Revenue. A count per account
    # ("Seats per account") has no revenue word and is no unit economics.
    ("arpa", r"\bARPAs?\b|(?i:" + _PER_UNIT + r"(?:account|client|customer)s?" + _ENDS + ")"),
    ("arpu", r"\bARPUs?\b|(?i:" + _PER_UNIT + r"(?:user|subscriber)s?" + _ENDS + ")"),
    ("revenue", _BREAKDOWN),
    ("other", r"(?i:" + _PER_UNIT + r"(?:employee|fte|order|transaction|store|seat|licen[cs]e)s?" + _ENDS + ")"),
    # The columns of a pipeline table, never revenue or bookings (George, 2026-10-20); "weighted pipeline" is longer than "pipeline" (Sales).
    ("pipeline", r"(?i:\bsize of (?:the )?opportunit(?:y|ies)\b|\bopportunity size\b|\bweighted (?:in )?(?:the )?(?:forecast|pipeline)\b"
                 r"|\bweighted (?:opportunit(?:y|ies)|value)\b)"),
]
# A customers noun that one of these words precedes, in its own cell or phrase, within QUALIFIER_REACH words and with no figure
# between them, counts people who are not paying customers ("Registered Institutions", "40 trial accounts"): the figure is Users,
# and the word, lower case, is kept as the candidate's "qualifier" (George, 2026-10-13). "Target 500 customers" is a plan target:
# the qualifier is the figure's, not the noun's, and the claim stays Customers.
QUALIFIERS = ("registered", "signed-up", "sign-ups", "signups", "onboarded", "waitlist", "waitlisted", "pipeline", "target",
              "targeted", "addressable", "potential", "prospective", "trial", "free")
QUALIFIER_REACH = 3
_KEYWORDS = [(family, re.compile(rx)) for family, rx in _FAMILIES]
_NOUN_KEYWORDS = [(family, rx) for family, rx in _KEYWORDS if family in ("customers", "users")]
_GROWTH_OF = {"revenue": "revenue_growth", "users": "user_growth"}
# Plan claims only: the company's own figures the growth plan depends on.
CLAIM_TYPES = ("revenue", "revenue_growth", "growth", "retention", "sales", "customers", "users", "user_growth",
               "gross_margin", "gross_profit", "costs", "ebitda", "net_profit", "people", "product", "market",
               "cash", "burn", "runway", "ltv", "cac", "customer_lifetime", "ltv_cac", "trials_per_day",
               "months_to_profitability", "arpa", "arpu", "pipeline")
# George, 2026-10-23 (engine contract 8): recurring revenue, churn and payback are register types of their own, no longer folded into Revenue,
# Retention or Sales. The page reader gives them (PAGE_METRICS); the rules parser never does, so they are not in CLAIM_TYPES (which the
# structure reads keep, schemas.CLAIM_METRICS). The analyst may choose them (ANALYST_TYPES: the editor and Add claim).
RECURRING_TYPES = ("arr", "mrr", "churn", "nrr", "cac_payback")
ANALYST_TYPES = CLAIM_TYPES + RECURRING_TYPES
TYPE_NAMES = {"arr": "ARR", "mrr": "MRR", "churn": "Churn", "nrr": "NRR", "cac_payback": "CAC payback"}


def type_name(claim_type: Optional[str]) -> str:
    """How a sentence names a claim type: the five recurring types by their label ("CAC payback"), every other type by its stored word."""
    return TYPE_NAMES.get(claim_type or "", str(claim_type or "claim"))


# A figure no line and no heading names a type for: listed as "unknown" and approved only once the analyst chooses a
# type (docs/specs/deck-parser.md section 2), like the model's "other" (structure-labelling.md section 4).
UNKNOWN = "unknown"
# A price list or a price point (George, 2026-10-23, the page reader's `pricing`): an amount, no engine metric, never matched; a type of its own, not offered
# in the analyst's list, like use of funds.
PRICING = "pricing"
# An allocation share on a raise slide (deck-parser.md section 2, "Use of funds"): unit %, no engine metric, never Sales or Revenue.
USE_OF_FUNDS = "use_of_funds"
# A per-platform figure on a user-acquisition slide (chat-upload.md section 17): count, no currency, no engine metric.
ACQUISITION_CHANNELS = "acquisition_channels"
COUNT = "count"         # the unit of an acquisition-channels figure
# A count of installed units, read only from a forecast table (chat-upload.md section 20): no engine metric, in no type list.
INSTALLED_UNITS = "installed_units"

# The order of the claims table (deck-parser.md section 6): the group of a type, then slide or page. Revenue covers ARR,
# MRR and bookings; P&L items and unit economics are listed with their neighbours; acquisition channels and use of funds
# have a group each, above Other (chat-upload.md section 17); the types no group names (the model's "other") are Other.
# The old group 6 (Unknown) is gone: a figure no heading names a type for is Other (claim-types-and-correction.md section 4). Group 6 is Scenarios
# since 2026-10-23 (SCENARIO_GROUP).
GROUPS = {1: "revenue", 2: "P&L", 3: "customers and sales", 4: "hiring and roadmap", 5: "market size", 6: "scenarios",
          7: "acquisition channels", 8: "use of funds", 9: "other", 10: "pricing"}
_GROUP_OF = {
    "revenue": 1, "revenue_growth": 1, "arr": 1, "mrr": 1,
    "gross_profit": 2, "ebitda": 2, "burn": 2, "cash": 2, "runway": 2, "costs": 2, "net_profit": 2, "gross_margin": 2,
    "months_to_profitability": 2,
    "customers": 3, "users": 3, "user_growth": 3, "growth": 3, "retention": 3, "sales": 3, "ltv": 3, "cac": 3, "ltv_cac": 3,
    "churn": 3, "nrr": 3, "cac_payback": 3,
    "customer_lifetime": 3, "trials_per_day": 3, "arpa": 3, "arpu": 3, "pipeline": 3, "usage": 3, INSTALLED_UNITS: 3,
    "people": 4, "product": 4,
    "market": 5, ACQUISITION_CHANNELS: 7, USE_OF_FUNDS: 8, PRICING: 10,
}
# The page reader's metric words that are no register claim type, and the type each stands for (George, 2026-10-23): market share is Market size.
# arr, mrr, churn, nrr and cac_payback are types of their own since engine contract 8 (RECURRING_TYPES). Every other word is its own type.
PAGE_CLAIM_TYPE = {"market_share": "market"}
OTHER_GROUP = 9
# George, 2026-10-23 (review of PR 164, H2): a best-case or worst-case figure of the page read is listed in a section of its own, whatever its type;
# only realistic / none are plan targets. The screen puts the section above Other (frontend CLAIM_GROUPS).
SCENARIO_GROUP = 6
CASES = ("best", "worst")
BASIS_CONFLICT = "basis conflicts with period"        # a projection for a period on or before the as-of month (claim_matching.flags_of)
# Flags the analyst only reads: the claim stays in the main list with the note on its row; every other flag lists it under Review
# (George, 2026-10-23). A new flag is added to checker.REVIEW_FLAGS or here, and the screen's list (informational_flags.json) follows.
INFORMATIONAL_FLAGS = ("cell corrected", "currency assumed", "unit assumed", "period from page heading")


def review_flags(flags) -> list:
    return [f for f in flags or [] if f not in INFORMATIONAL_FLAGS]
COLLAPSED_GROUPS = (8, 9, 10)          # use of funds, other, pricing (George, 2026-10-23)
# docs/specs/claim-types-and-correction.md section 4: a figure the parser cannot type and an item the model labelled other are Other:
# never matched, never a task, listed collapsed under their count. The analyst may type a claim Other, and retype it out.
OTHER_TYPES = ("other", UNKNOWN)


def type_group(claim_type: Optional[str]) -> int:
    """1 to 9: the group a claim type sorts under; Other (other, unknown) sorts under Other."""
    if claim_type in OTHER_TYPES:
        return OTHER_GROUP
    return _GROUP_OF.get(claim_type or "", OTHER_GROUP)


def is_case(c: Dict) -> bool:
    """A best-case or worst-case figure (the page reader's `scenario`)."""
    return c.get("scenario") in CASES


def claim_group(c: Dict) -> int:
    """The group a claim is listed under: Scenarios for a best or worst case, else the group of its type. An Other figure stays Other."""
    if c.get("claim_type") in OTHER_TYPES:
        return OTHER_GROUP
    return SCENARIO_GROUP if is_case(c) else type_group(c.get("claim_type"))


# ---------------------------------------------------------------------------
# Claim fields (docs/specs/claim-types-and-correction.md sections 1-2)
# ---------------------------------------------------------------------------
FIGURE_TYPES = ("actual", "target", "unknown")
# Target cues, whole words, any case. "plan" and "plans" are not cues ("Free to Paid plans"). Measured on the 10 public decks: 4 of
# 225 candidates carry one (front slide 16, moz page 18, buffer slide 7 twice).
TARGET_CUE = re.compile(r"(?i)\b(?:target(?:s|ed)?|planned|forecast(?:s|ed)?|budget(?:ed)?|goals?|projected|projections?|expected"
                        r"|guidance|outlook|aim(?:s|ing)?)\b")
# The population each type may state, and what a value reads as in a sentence.
POPULATIONS = {"customers": ("paying", "registered", "active"), "users": ("paying", "registered", "active"),
               "user_growth": ("paying", "registered", "active"), "sales": ("deals won", "all closed", "open")}
EDIT_REASONS = {"parser_misread": "Parser misread the deck", "deck_context": "Deck context says otherwise", "other": "Other"}


def target_cue(text: str) -> bool:
    return bool(TARGET_CUE.search(text or ""))


def parsed_fields(candidate: Dict) -> Dict:
    """What the parser reads into the fields of section 2 from the claim's own line and label: the figure type when a target cue is
    there, the population a customers keyword or a qualifier names. Nothing else is guessed: the rest is read on matching."""
    text = f"{candidate.get('snippet') or ''} {candidate.get('label_from') or ''}"
    out: Dict = {}
    if target_cue(text):
        out.update(figure_type="target", figure_type_set_by="parser")
    if candidate.get("claim_type") == "customers":
        out.update(population="paying", population_set_by="parser")
    elif candidate.get("claim_type") == "users" and candidate.get("qualifier") in QUALIFIERS:
        out.update(population="registered", population_set_by="parser")
    return out
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
# The cue of a break-even line among the ebitda ones ("Profitable by 2024"); an EBITDA heading has none (PR 147 review M2).
_BREAK_EVEN_CUE = re.compile(r"(?i)\b(?:profitab(?:ility|le)|break[- ]?even)\b")


def is_milestone(c: Dict) -> bool:
    """True for a candidate with no figure that is a milestone line and not a heading: a product line, a line of unknown type, or a
    line (or the heading it borrowed) with a break-even cue. Told by the cue and not by the claim type, which "2023 EBITDA" shares."""
    return c["claim_type"] in ("product", UNKNOWN) or bool(_BREAK_EVEN_CUE.search(f"{c.get('snippet') or ''} {c.get('label_from') or ''}"))
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


# A range of years ("2022–2024", "2022 -2024", "2022 to 2024", "FY22–24", "FY2022-2024"; issue #148): it is no single year, so nothing is
# dated from it, its years are no figures and a heading that holds one gives no year to the figures under it. The end of a range
# written with two digits is above 12 ("2022-03" is a month, not a range); "to" joins four-digit years only.
_YEAR_RANGES = (re.compile(r"(?<![\w$€£.,'’/-])(?:FY\s*['’]?)?(?P<a>(?:19|20)\d{2}|\d{2})\s*[-–—]\s*(?:FY\s*['’]?)?(?P<b>(?:19|20)\d{2}|\d{2})(?![\w%]|[.,]\d|-\d)"),
                re.compile(r"(?<![\w$€£.,'’/-])(?P<a>(?:19|20)\d{2})\s+to\s+(?P<b>(?:19|20)\d{2})(?![\w%]|[.,]\d|-\d)"))


def _year_range(m: "re.Match") -> bool:
    text, a, b = m.group(0), m.group("a"), m.group("b")
    if len(a) == 2 and not text.lstrip().upper().startswith("FY"):
        return False                      # "5-10", "20-25": a range of numbers, not of years
    return len(b) == 4 or int(b) > 12


def no_period_dates(text: str) -> List[Tuple[int, int]]:
    """(start, end) of each date with no period in a text: a date written with slashes (slash_dates), a quarter range that is
    no half and a range of years."""
    ranges = [m.span() for rx in _QUARTER_RANGES for m in rx.finditer(text or "")
              if (m.group("a"), m.group("b")) not in (("1", "2"), ("3", "4"))]
    ranges += [m.span() for rx in _YEAR_RANGES for m in rx.finditer(text or "") if _year_range(m)]
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


_PHRASE_BREAK = re.compile(r"[|;:,.()\[\]•·\n]")      # a table cell or a phrase ends here


def _qualifier(text: str, noun: Dict) -> Optional[str]:
    """The QUALIFIERS word nearest before a customers noun, in the noun's own cell or phrase, within QUALIFIER_REACH words and
    with no figure between them."""
    phrase = _PHRASE_BREAK.split(text[:noun["start"]])[-1]
    for word in reversed(phrase.split()[-QUALIFIER_REACH:]):
        if any(ch.isdigit() for ch in word):
            return None
        word = word.strip("\"'“”‘’*-–—/").lower()
        if word in QUALIFIERS:
            return word
    return None


def _typed(text: str, keyword: Dict, keywords: List[Dict], unit: Optional[str] = "%") -> Tuple[str, Optional[str]]:
    """(claim type, qualifier) of a keyword in `text`: its type, but Users and the qualifier when the customers noun that types
    it is qualified ("Registered Institutions")."""
    family = _type(keyword, keywords, unit)
    if family != "customers":
        return family, None
    noun = keyword if keyword["family"] == "customers" else \
        _nearest([k for k in keywords if k["family"] in ("revenue", "users", "customers")], keyword)
    qualifier = _qualifier(text, noun)
    return ("users", qualifier) if qualifier else (family, None)


def qualifier_of(text: str) -> Optional[str]:
    """The qualifier of the first qualified customers noun in `text` ("Registered Institutions": "registered"); None if none. How
    a model-read claim of type Customers is checked (deck-parser.md section 2, amended 2026-10-13)."""
    return next((q for k in _keywords(text) if k["family"] == "customers" for q in [_qualifier(text, k)] if q), None)


def qualified_label(text: str, qualifier: str) -> str:
    """'registered institutions': the qualifier and the customers noun it qualifies in `text`, lower case; the qualifier alone when
    the text no longer holds the pair. Both words come from closed lists (QUALIFIERS and the customers keywords)."""
    for k in _keywords(text):
        if k["family"] == "customers" and _qualifier(text, k) == qualifier:
            return f"{qualifier} {' '.join(text[k['start']:k['end']].lower().split())}"
    return qualifier


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


def _borrow_keyword(texts: Iterable[str], nearest: bool = True) -> Optional[Tuple[str, str, str, Optional[str]]]:
    """(family, text, heading, qualifier) of the heading that names the type; the heading is the one line of the text that holds
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
            family, qualifier = _typed(text, found[0], found)
            return family, text, _heading(text, found[0]["start"], found[0]["end"]), qualifier
    return None


# A line that says something instead of naming something (issue #154): a subject pronoun or an auxiliary verb, or a closing stop.
_SENTENCE_WORDS = frozenset("""i we you they he she it is are was were be been am will would can could shall should may might must has have
had do does did""".split())
_SENTENCE_END = re.compile(r"[.;,!?][\"'”’)\]]*$")


def _is_sentence(line: str) -> bool:
    """A sentence is no date source (issue #154): a line longer than a heading (HEADING_MAX), with a subject pronoun or an auxiliary
    verb ("IN 2022 WE FOCUS ON GROWTH OF ARPA"), or ending on a stop. A year comes only from the figure's own text, its label, a heading or
    an axis label."""
    line = line.strip()
    return len(line) > HEADING_MAX or bool(_SENTENCE_END.search(line)) \
        or any(w in _SENTENCE_WORDS for w in re.findall(r"[^\W\d_]+", line.lower()))


def _date_lines(text: str) -> List[str]:
    """The parts of a nearby text that may give a date: the text itself when it fits a heading (a wrapped heading is one), else its
    lines that are no sentence and no wrapped part of one (a line after one that ends on "of" or a comma, or ending on "in")."""
    lines = getattr(text, "lines", None)
    if not lines or len(lines) < 2 or len(text) <= HEADING_MAX:
        return [] if _is_sentence(str(text)) else [str(text)]
    out, wrapped = [], False
    for line in lines:
        words = re.findall(r"[^\W_]+|,", line.lower())
        if not (wrapped or _is_sentence(line) or words and words[-1] in _WRAP_WORDS | {","}):
            out.append(line)
        wrapped = bool(words) and (words[-1] in _WRAP_WORDS or words[-1] == ",")
    return out


def _borrow_date(texts: Iterable[str], nearby: bool = False) -> Optional[Tuple[str, str, str]]:
    """(date, text, the date as stated): the first month or quarter in the texts, else the first year. A sentence gives none
    (issue #154); `nearby` marks texts found around the figure, which are checked for it. A column header, a box period and a bar label are
    the figure's own and are not."""
    texts = list(texts)
    parts = [(part, text) for text in texts for part in (_date_lines(text) if nearby else [text])]
    for wanted in (("quarter", "half", "month"), ("year",)):
        for part, text in parts:
            found = [d for d in find_dates(part) if d["kind"] in wanted]
            if found:
                return found[0]["date"], text, found[0]["text"]
    return None


UNCLEAR = "unclear"      # the counts of periods and figures differ: no figure of the cell takes a period (George, 2026-10-20)


def _shared_cell_periods(numbers: List[Dict], dates: List[Dict], refs: List, headers: Dict) -> Dict[int, Optional[Tuple[str, str, str]]]:
    """id(number) -> the period of a figure that shares its table cell with other figures of the same unit and currency (a borderless
    PDF table read into one cell, issue #136). The k-th figure takes the k-th period of its column header, or of the header cells
    from its column rightwards, when the counts match; otherwise every figure of the cell gets none: no figure takes the header's
    first period (decision 3 of 2026-10-19: a period that cannot be read is not read). A figure with a date of its own is left out."""
    def col_of(n):
        return next((r.get("col") for s, e, r in refs if s <= n["pos"] < e), None)
    groups: Dict[Tuple, List[Dict]] = {}
    for n in numbers:
        if not _nearest(dates, n):
            groups.setdefault((col_of(n), n["unit"], n["currency"]), []).append(n)
    out: Dict[int, Optional[Tuple[str, str, str]]] = {}
    for (col, _, _), members in groups.items():
        if col is None or len(members) < 2:
            continue
        own = find_dates(headers.get(col) or "", table=True)
        across = [d for c in sorted(c for c in headers if c >= col) for d in find_dates(headers[c] or "", table=True)]
        for found in (own, across):
            if len(found) == len(members):
                for n, d in zip(sorted(members, key=lambda m: m["pos"]), found):
                    out[id(n)] = (d["date"], d["text"], d["text"])
                break
        else:
            for n in members:
                out[id(n)] = UNCLEAR
    return out


_REVENUE_WORD = re.compile(r"(?i)\b" + _REVENUE_WORDS + r"\b")
_AVERAGE_WORD = re.compile(r"(?i)\b(?:ARPA|ARPU|average|avg|mean|blended|total|overall)\b")


def _is_name(label: str) -> bool:
    """A row label or a bar label that names an entity: not a date, not a figure, no keyword of its own."""
    return bool(_WORD.search(label)) and not find_dates(label, table=True) and not find_numbers(label, []) and not _keywords(label)


def _names_a_unit(line: str, pos: int, header: str) -> bool:
    """A column header "Revenue per client" (or "Sales per client", "ARR per customer"...) over a row that names its client ("Acme |
    $500,000") gives that client's revenue: the figure is Revenue, not ARPA (George, 2026-10-20). A row label that is a date, holds a figure or a
    keyword, or says average does not name one."""
    label = line.split(" | ")[0]
    if pos < len(label) + 3 or not _revenue_header(header) or _AVERAGE_WORD.search(header + " " + label):
        return False
    return _is_name(label)


def _bar_names_a_unit(title: str, name: Optional[str]) -> bool:
    """The same for a chart: a title "Revenue per client" with one bar per named entity ("Acme", "Beta") is each entity's revenue."""
    return bool(name) and _revenue_header(title) and not _AVERAGE_WORD.search(title + " " + name) and _is_name(name)


def _revenue_header(header: str) -> bool:
    return bool(_REVENUE_WORD.search(header))


def line_candidates(line: str, refs: Iterable, context: Iterable[str] = (), headers: Optional[Dict] = None,
                    box_period: Optional[str] = None, column_periods: Optional[Dict] = None,
                    bar_label: Optional[str] = None, percent_type: Optional[str] = None, bar_name: Optional[str] = None) -> List[Dict]:
    """Candidates in one line. `refs` gives each figure's source reference: a list of
    (start, end, ref) spans, so a table row cites the cell a figure sits in. `context` is the
    nearby text to borrow from, most relevant first; `headers` maps a table column to its header;
    `box_period` is the period line at the top of the line's text box ("23 Y/E"). `column_periods`
    maps a table column to the period its header stack states, or NO_PERIOD (see column_periods);
    a table row is read with the table period rules. `bar_label` is the year label under the figure's bar (see
    _bar_labels). `bar_name` is the name label under the bar of a chart with one bar per named entity. `percent_type` types a percentage that no keyword or heading names (a share of a raise)."""
    refs, context, headers, column_periods = list(refs), list(context), headers or {}, column_periods
    table = column_periods is not None
    keywords = _keywords(line)
    date_words = [{"start": m.start(), "end": m.end()} for m in _DATE_WORD.finditer(line)]
    dates = find_dates(line, table=table)
    numbers = find_numbers(line, dates)

    def ref_at(pos: int) -> Dict:
        return next((r for s, e, r in refs if s <= pos < e), refs[0][2])

    def claim(pos, family, value=None, high=None, unit=None, currency=None, date=None, label=None, date_from=None,
              stated=False, period_text=None, type_from="line", direction=None, qualifier=None):
        # "_stated": the date is the figure's own, its column header's or its box's period, not one
        # borrowed by position; only stated periods are compared for a deck inconsistency.
        return {"claim_type": family, "value": value, "value_high": high, "unit": unit, "currency": currency,
                "target_date": date, "period_text": period_text if date else None, "snippet": _snippet(line, pos),
                "label_from": label and _label(label),
                "date_from": date_from and date_from != label and _label(date_from) or None, "sources": [ref_at(pos)],
                "type_from": None if family == UNKNOWN else type_from, "claim_direction": direction, "_stated": stated,
                **({"qualifier": qualifier} if qualifier else {})}

    out = []
    shared = _shared_cell_periods(numbers, dates, refs, headers) if table else {}
    for n in numbers:
        own = _nearest(keywords, n)
        header = headers.get(ref_at(n["pos"]).get("col"))
        nearby = [header] if header else []
        if own and header and (_borrow_keyword(nearby, nearest=False) or (None,))[0] == "pipeline":
            own = None          # under a pipeline column every row is Pipeline, whatever its row label says (George, 2026-10-20)
        borrowed = None if own else _borrow_keyword(nearby, nearest=False) or _borrow_keyword(context)
        qualifier = None
        if own:
            family, qualifier = _typed(line, own, keywords, n["unit"])
        elif borrowed:
            family, qualifier = borrowed[0], borrowed[3]
        elif date_words or _borrow_keyword(nearby + context, nearest=False):
            # No line and no nearest heading names a type: not guessed. A date word, or a keyword only further away,
            # keeps the figure as a candidate.
            family = UNKNOWN
        elif percent_type and n["unit"] == "%":
            family = percent_type
        else:
            continue
        if family in ("arpa", "arpu") and borrowed and (header and borrowed[1] is header and _names_a_unit(line, n["pos"], header)
                                                          or borrowed[1] is not header and _bar_names_a_unit(borrowed[1], bar_name)):
            family = "revenue"
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
        if id(n) in shared:
            # Figures that share one table cell: each takes the period of its own position in the header, or none (issue #136)
            own_date, date = None, None if shared[id(n)] == UNCLEAR else shared[id(n)]
            stated = date is not None
        elif own_date or stacked is None:
            # The year label under a bar is the figure's own date: taken after its own date, column header and box period, before
            # any text further away, and "stated", so it is compared for a deck inconsistency (docs/specs/deck-parser.md section 2).
            date = None if own_date else _borrow_date(nearby) or _borrow_date([box_period] if box_period else []) \
                or _borrow_date([bar_label] if bar_label else [])
            stated = bool(own_date or date)
            date = date or (None if own_date else _borrow_date(context, nearby=True))
        else:
            # The header stack states the column's period, or says it has none (a month or quarter
            # with no year above it, a relative column): never borrowed from anywhere else.
            date = None if stacked is NO_PERIOD else (stacked["label"], stacked["text"], stacked["text"])
            stated = date is not None
        out.append(claim(n["pos"], family, n["value"], n["value_high"], n["unit"], n["currency"],
                         own_date["date"] if own_date else date and date[0],
                         label=borrowed and borrowed[2], date_from=date and date[1], stated=stated,
                         period_text=own_date["text"] if own_date else date and date[2],
                         type_from="line" if own else "heading", qualifier=qualifier))
        if shared.get(id(n)) == UNCLEAR:
            out[-1]["period_unclear"] = True
    if numbers:
        return [recurring_year_end(c) for c in out]
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
        typed = [_typed(line, _nearest(keywords, d), keywords) if keywords else (family, None) for d in dates]
        return [claim(d["start"], kind, date=d["date"],
                      label=family not in ("product", UNKNOWN) and borrowed[2] or None, stated=True, period_text=d["text"],
                      type_from="line" if keywords else "heading", direction=said and said.group(1).lower(), qualifier=qualifier)
                for d, (kind, qualifier) in zip(dates, typed) if d["kind"] != "year" or keywords]
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
    date = _borrow_date(context, nearby=True)
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


def _bar_labels(units: List[Dict], names: bool = False, skip: set = ()) -> Dict[int, str]:
    """id(unit) -> the year label under the figure's bar (with `names`, the name label: a chart with one bar per named entity). A bar chart read from the page's text has its values above the
    bars and one year or FY label under each ("FY2023", "2024"); the labels are two or more lines on one row, each
    nothing but a year. A figure takes the nearest such label below it that overlaps it from side to side; with no
    such row, or no label under the figure, it has none (docs/specs/deck-parser.md section 2). When the figures above one row of year
    labels are as many as the labels, each takes the label of its place, left to right, whether or not it overlaps one (issue #148); `skip`
    holds the lines that are no bars (axis ticks)."""
    out = {}
    pages = {}
    for u in units:
        if u["bbox"] and not u.get("table_row") and not u["title"]:
            pages.setdefault(u["page"], []).append(u)
    for members in pages.values():
        labels = [u for u in members if (_is_name(u["text"]) and len(u["text"].split()) <= 4 if names else
                                         _period_only(u["text"]) and find_dates(u["text"])[0]["kind"] == "year")]
        rows = [[label for label in labels if abs(label["bbox"][1] - top["bbox"][1]) < BAR_ROW] for top in labels]
        axis = [label for row in rows if len(row) >= 2 for label in row]
        for u in members:
            if u in labels or not find_numbers(u["text"], find_dates(u["text"])):
                continue
            x0, y0, x1, y1 = u["bbox"]
            under = [label for label in axis if label["bbox"][1] >= y1 - 0.005 and label["bbox"][1] - y1 <= BAR_REACH
                     and label["bbox"][0] < x1 and x0 < label["bbox"][2]]
            if under:
                centre = (x0 + x1) / 2
                best = min(under, key=lambda label: (abs((label["bbox"][0] + label["bbox"][2]) / 2 - centre), label["bbox"][1]))
                out[id(u)] = best["text"]
        if not names:
            out.update(_bar_places(members, labels, rows, skip))
    return out


def _value_line(text: str) -> bool:
    """A line that is a figure and nothing else ("€1.48MM", "$210B", "40% (+3pp)"): the value written over a bar, never a sentence that
    holds a number ("layer-1 to layer-2")."""
    numbers = find_numbers(text, find_dates(text))
    for n in reversed(numbers):
        text = text[:n["start"]] + " " + text[n["end"]:]
    return bool(numbers) and not _WORD.search(text)


def _bar_places(members: List[Dict], labels: List[Dict], rows: List[List[Dict]], skip: set) -> Dict[int, str]:
    """id(unit) -> the year label of the figure's place (issue #148): the figures above one row of year labels (those whose nearest row
    below them it is, and that stand between its first and last label, a label's spacing beyond) are as many as the row's labels, and
    the k-th figure from the left takes the k-th label; with any other count a figure takes the label nearest to it, within half a spacing and alone
    on it. Only a line that is a figure and nothing else counts (_value_line): a roadmap's
    sentences ("layer-1 to layer-2") over its dates are no bars."""
    def centre(box):
        return (box[0] + box[2]) / 2
    axes = {}
    for row in rows:
        if len(row) >= 2:
            axes[tuple(sorted(id(label) for label in row))] = sorted(row, key=lambda label: centre(label["bbox"]))
    placed = {key: [] for key in axes}
    for u in members:
        if u in labels or id(u) in skip or not _value_line(u["text"]):
            continue
        y1 = u["bbox"][3]
        below = [(row[0]["bbox"][1] - y1, key) for key, row in axes.items()
                 if row[0]["bbox"][1] >= y1 - 0.005 and row[0]["bbox"][1] - y1 <= BAR_REACH]
        if not below:
            continue
        key = min(below)[1]
        row = axes[key]
        spacing = (centre(row[-1]["bbox"]) - centre(row[0]["bbox"])) / (len(row) - 1)
        if centre(row[0]["bbox"]) - spacing <= centre(u["bbox"]) <= centre(row[-1]["bbox"]) + spacing:
            placed[key].append(u)
    out = {}
    for key, bars in placed.items():
        row = axes[key]
        if len(bars) == len(row):
            if len({round(centre(b["bbox"]), 4) for b in bars}) == len(bars):
                for bar, label in zip(sorted(bars, key=lambda b: centre(b["bbox"])), row):
                    out[id(bar)] = label["text"]
            continue
        # Fewer or more figures than labels (a chart that writes the value on some bars only, issue #154): a figure takes the label nearest
        # to it when that is less than half a label's spacing away and no other figure is nearer to the same label.
        spacing = (centre(row[-1]["bbox"]) - centre(row[0]["bbox"])) / (len(row) - 1)
        nearest = {}
        for bar in bars:
            first = min(row, key=lambda label: abs(centre(label["bbox"]) - centre(bar["bbox"])))
            if abs(centre(first["bbox"]) - centre(bar["bbox"])) < spacing / 2:
                nearest.setdefault(id(first), []).append(bar)
        for label in row:
            if len(nearest.get(id(label), ())) == 1:
                out[id(nearest[id(label)][0])] = label["text"]
    return out


def bar_years(lines: List[Dict], ticks: set = ()) -> Dict[int, str]:
    """id(line) -> the year label of a text line's bar, for the lines of one deck page (a KPI panel's cells, issue #148): the label
    under it or of its place (_bar_labels). `ticks` holds the id() of the lines that are axis ticks (tick_lines)."""
    units = [{"text": b["text"], "page": (b.get("slide"), b.get("page")), "bbox": b.get("bbox"), "title": bool(b.get("title")),
              "src": b} for b in lines if b["kind"] != "table"]
    found = _bar_labels(units, skip={id(u) for u in units if id(u["src"]) in ticks})
    return {id(u["src"]): found[id(u)] for u in units if id(u) in found}


def _share_bar_row(units: List[Dict], contexts: Dict[int, List[str]], bars: Dict[int, str]) -> None:
    """The bars of one chart row share the chart's caption (issue #143): a bar further than REACH from the caption, at the far end of the
    row, takes the nearby texts of its row mates instead of falling back to the page title ("2022 FORECAST: CLIENT COMPOSITION" over a
    chart "Average revenue per account"). Only a bar with no nearby heading of its own; the title stays last."""
    rows = {}
    for u in units:
        if id(u) in bars and u["bbox"]:
            rows.setdefault(u["page"], []).append(u)
    for members in rows.values():
        for u in members:
            if any(getattr(t, "distance", None) is not None and (_keywords(t) or _is_heading(t)) for t in contexts[id(u)]):
                continue
            mates = sorted((m for m in members if m is not u and abs(m["bbox"][1] - u["bbox"][1]) < BAR_ROW),
                           key=lambda m: abs(m["bbox"][0] - u["bbox"][0]))
            near = [t for m in mates for t in contexts[id(m)] if getattr(t, "distance", None) is not None and (_keywords(t) or _is_heading(t))]
            if near:
                contexts[id(u)] = near + contexts[id(u)]


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


# A printed page number: a line that is only a number of up to three digits, with "Page", "Slide", "p." or "pg." before it, "/ m",
# "of m" or "| m" after it, dashes, bars or dots around it ("3", "Slide 3", "3/25", "Page 3 of 20", "- 3 -"). It is no figure
# when it is the page's own number (George, 2026-10-22, M1 of the review of PR #159): the page grid (pages.page_grid) and the
# gateway's floor (structures/redact.page_text_problem) both call this, so the two readers agree.
_PAGE_NUMBER_LINE = re.compile(r"(?i)^[\s\-–—|.]*(?:page|slide|pg\.?|p\.)?\s*(?P<n>\d{1,3})\s*(?:(?:/|of|\|)\s*\d{1,3})?[\s\-–—|.]*$")


def page_number_line(text: str, page: int) -> bool:
    """True when the line is only the page's own number."""
    m = _PAGE_NUMBER_LINE.match(text or "")
    return bool(m) and int(m.group("n")) == int(page or 0)


# Page furniture (George, 2026-10-23, deck page reads): a digit in an email, a URL or a phone number is no figure of the page, and neither is
# one on a running header or footer line, within the top 5% or the bottom 7% of the page (the page's own number and a header date are
# covered above and by find_dates). A pdf marks its topmost line a title, so a running header is one too; the bands are thin enough for
# a real title to stay outside them. The same patterns as the redaction's (structures/redact.py), which the parser does not import.
_CONTACT = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+"                                                    # an email
                      r"|(?i:\b(?:https?://|www\.)\S+|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|co|ai|de|uk|fr|eu|nl)\b(?:/\S*)?)"   # a URL
                      r"|(?<![\w+])(?:\+|(?<![\d.,])0)(?:[\s().\-/]{0,2}\d){9,15}(?![\d])")               # a phone number
HEADER_BAND, FOOTER_BAND = 0.05, 0.07


def page_furniture_line(block: Dict) -> bool:
    """True when a text line sits in the header or footer band of its page."""
    bbox = block.get("bbox")
    return bool(bbox) and (bbox[3] <= HEADER_BAND or bbox[1] >= 1 - FOOTER_BAND)


def page_figures(text: str, page: int) -> List[Dict]:
    """The figures of a line of `page` that count for the page: none in an email, a URL or a phone number, none when the line is only the
    page's own number."""
    if page_number_line(text, page):
        return []
    return figures(_CONTACT.sub(" ", text or ""))


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


RUN_MIN = 4
_LIST_MARK = re.compile(r"^\s*#?\d+\s*[.:)]\s*$")      # "1.", "#3:", "2)": the number of a list item, not a figure on an axis
_ROUND_STEPS = (1.0, 2.0, 2.5, 5.0)         # a round step: 1, 2, 2.5 or 5 times a power of ten (2,000, 25, 0.5)


def _round_step(step: float) -> bool:
    if step <= 0:
        return False
    mantissa = step / 10 ** floor(log10(step))
    return any(abs(mantissa - m) < 1e-9 for m in _ROUND_STEPS)


def _round_runs(values: List[float]) -> set:
    """The values that belong to a run of RUN_MIN or more round figures with one equal, round step ("0, 2,000, 4,000 ... 10,000"): the
    run starts at a multiple of its step. Anything else is not a run."""
    distinct = sorted(set(values))
    out = set()
    for i, first in enumerate(distinct):
        for second in distinct[i + 1:]:
            step = second - first
            if not _round_step(step) or abs(first / step - round(first / step)) > 1e-9:
                continue
            run, nxt = [first], first + step
            while any(abs(nxt - v) <= 1e-9 * max(1.0, abs(nxt)) for v in distinct):
                run.append(nxt)
                nxt += step
            if len(run) >= RUN_MIN:
                out.update(v for v in distinct if any(abs(v - r) <= 1e-9 * max(1.0, abs(v)) for r in run))
    return out


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
    loose = {}
    for u in units:
        if not u.get("table_row") and not _LIST_MARK.match(u["text"]):
            values = _bare_values(u["text"])
            if len(values) == 1:
                loose.setdefault(u["page"], []).append((u, values[0]))
    for found in loose.values():       # issue #143: a run of 4 or more round, equally spaced figures on one page, wherever they sit
        run = _round_runs([v for _, v in found])
        ticks.update(id(u) for u, v in found if v in run)
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
    bars = _bar_labels(units, skip=skipped)
    _share_bar_row(units, contexts, bars)
    funds, mixed = _funds_units(units)
    channels = _channel_units(units)
    tick_cells = _tick_cells(blocks)
    periods = _box_periods(units)
    bar_names = _bar_labels(units, names=True)
    merged = {}
    for u in units:
        if id(u) in skipped or (u.get("header_row") or u.get("table_row") and _in_stack(u)) and _period_header(u["text"]) \
                or id(u) in periods and periods[id(u)] is None:
            continue
        found = []
        for c in ([_channel_candidate(u, *channels[id(u)])] if id(u) in channels else
                  line_candidates(u["text"], u["spans"], contexts[id(u)], u["headers"], periods.get(id(u)),
                                  u.get("column_periods") if u.get("table_row") else None, bars.get(id(u)),
                                  USE_OF_FUNDS if id(u) in funds else None, bar_names.get(id(u)))):
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
                   c["period_start"], c["period_end"], c.get("channel"), c.get("qualifier"),
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
    found = _drop_label_headings(_merge_unknown(_merge_rounded(list(merged.values()))))
    _apply_label_units(found)
    _flag_inconsistencies(found)
    _flag_funds_inconsistencies(found)
    for c in found:
        c.pop("_funds", None)
        if c.get("claim_type") in GROWTH_TYPES:
            c["growth_basis"] = growth_basis(f"{c.get('snippet') or ''} {c.get('label_from') or ''}")
        c.update(parsed_fields(c))
    return found


# ---------------------------------------------------------------------------
# Growth basis (docs/specs/dates-and-periods.md section 5)
# ---------------------------------------------------------------------------
GROWTH_TYPES = ("revenue_growth", "growth", "user_growth")
# The cue words of each basis, whole words; "annual" and "monthly" do not count inside "annual / monthly recurring revenue", and
# "over" counts only before a year, a fiscal year or a duration ("over 2023", "over the last 12 months"), never before a figure.
_PERIOD_AFTER_OVER = (r"(?:the\s+(?:last|past|next)\s+)?(?:\d+\s+|one\s+|two\s+|three\s+|four\s+|five\s+)?"
                      r"(?:(?:19|20)\d{2}|FY\s?\d{2}|years?|months?|quarters?)\b")
GROWTH_CUES = {
    "mom": re.compile(r"\bMoM\b|\bm/m\b|(?i:\bmonth[- ](?:on|over)[- ]month\b|\bmonthly\b(?!\s+recurring\s+revenue)|\bper\s+month\b)"),
    "yoy": re.compile(r"\bYoY\b|\by/y\b|(?i:\byear[- ](?:on|over)[- ]year\b|\bannual\b(?!\s+recurring\s+revenue)|\bper\s+year\b)"),
    "annualised": re.compile(r"\bCAGR\b|(?i:\bannuali[sz]ed\b)"),
    "cumulative": re.compile(r"(?i:\bsince\b|\bover\s+" + _PERIOD_AFTER_OVER + r")"),
}


def growth_basis(text: str) -> str:
    """mom, yoy, annualised or cumulative when the claim's words carry the cues of exactly one basis; else "unknown" (none, or
    two bases): the analyst sets it with one click."""
    found = [basis for basis, rx in GROWTH_CUES.items() if rx.search(text or "")]
    if "annualised" in found:           # "CAGR of 40% since 2020": the window is the period of the annualised rate, not a second basis
        found = [b for b in found if b != "cumulative"]
    return found[0] if len(found) == 1 else "unknown"


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


def _whole(value: Optional[float]) -> Optional[int]:
    return None if value is None else int(floor(value + 0.5))


def _decimals(value: float) -> int:
    text = repr(float(value))
    return 0 if "e" in text or "." not in text else len(text.split(".")[1].rstrip("0"))


def _pages(candidate: Dict) -> set:
    return {s.get("slide") or s.get("page") for s in candidate.get("sources") or ()} - {None}


def _merge_rounded(found: List[Dict]) -> List[Dict]:
    """The same figure read at two precisions on one page ("501,378" and "501,378.04"): same type, unit, currency and period, values
    equal after rounding to whole units, and a page in common is one claim. The more precise value is kept and the other's source
    location joins its sources, which are its evidence. Only money amounts, where a whole unit is small against the figure: never a rate, a ratio or a count (whole units would join
    12.4% and 12.0%, or a 2.6 ratio and a 3.1 one). Never across pages or periods, never a table row's values by period."""
    def rest(c):
        return (c["claim_type"], _whole(c["value"]), _whole(c["value_high"]), c["unit"], c["currency"], c["target_date"],
                c["period_start"], c["period_end"], c.get("channel"), c.get("qualifier"))
    out, kept = [], {}
    for c in found:
        if c.get("by_period") or c["value"] is None or not c["currency"] or not _pages(c):
            out.append(c)
            continue
        into = next((k for k in kept.get(rest(c), ()) if _pages(k) & _pages(c)), None)
        if into is None:
            kept.setdefault(rest(c), []).append(c)
            out.append(c)
            continue
        if (_decimals(c["value"]), _decimals(c["value_high"] or 0)) > (_decimals(into["value"]), _decimals(into["value_high"] or 0)):
            sources = into["sources"]
            into.update({k: v for k, v in c.items() if k not in ("sources", "_stated")})
            into["sources"] = list(c["sources"]) + [s for s in sources if s not in c["sources"]]
        else:
            into["sources"] = list(into["sources"]) + [s for s in c["sources"] if s not in into["sources"]]
        into["_stated"] = into["_stated"] or c["_stated"]
    return out


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


def _page_of(source: Dict):
    return source.get("slide") or source.get("page")


def _drop_label_headings(found: List[Dict]) -> List[Dict]:
    """A candidate with no figure is dropped when a figure on the same page already uses its line as its label ("2020 REVENUE" over
    "151K", whose "Label from" it is): the figure is the claim, the heading only names it (issue #146). A direction ("Positive
    EBITDA") and a milestone line (a product line, a line of unknown type, a break-even cue: `is_milestone`) are kept, and so is every other
    candidate with no figure. A figure uses a heading when its "Label from" is the heading's whole line. A heading read on several
    pages loses the sources of the pages whose figure uses it and is dropped when none is left."""
    used = {}
    for c in found:
        if c.get("label_from") and any(v["value"] is not None for v in claim_values(c)):
            for s in c["sources"]:
                used.setdefault(_page_of(s), set()).add(" ".join(c["label_from"].split()).lower())
    out = []
    for c in found:
        line = " ".join((c.get("snippet") or "").split()).lower()
        if c.get("value") is not None or c.get("value_high") is not None or c.get("by_period") or c.get("claim_direction") \
                or is_milestone(c) or not line:
            out.append(c)
            continue
        left = [s for s in c["sources"] if line not in used.get(_page_of(s), ())]
        if left:
            out.append({**c, "sources": left})
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
_RECURRING_TERM = re.compile(r"\b(?:ARR|MRR)\b|(?i:\b(?:annual|monthly) recurring revenue\b)")
_NEW_MRR_TERM = re.compile(r"(?i)\bnew mrr\b")
# A contract value (George, 2026-10-19, issue #136): a figure the deck labels as contracted or committed is a contract value, never
# revenue. The words of docs/specs/revenue-file-recognition.md section 2.1, whole words, any case.
CONTRACT_TERM = re.compile(r"(?i)\b(?:(?:annual|total)?\s*contract(?:ed)?\s+values?|contracted\s+revenues?|contracted\s+(?:arr|mrr)"
                           r"|committed\s+(?:arr|mrr)|tcv|acv|carr)\b"
                           r"|(?i:\b(?:arr|mrr)\s*[(\[]\s*(?:contracted|committed)\s*[)\]])")
CONTRACT_LABEL = "Contract value"


def deck_label(c: Dict) -> Optional[str]:
    """The word the deck uses for a revenue-type figure: "Contract value" when its label or line holds a contract-value term,
    "New MRR", "MRR" or "ARR" when its own label holds that term (issue #151: a monthly or annual recurring figure is never Revenue),
    "Turnover" when it holds a turnover term, else "Revenue"; a figure with a unit (a percentage, a count, a multiple) gets none of MRR,
    ARR or New MRR. None for every other type. Figures with different labels are never
    compared with each other for a deck inconsistency (docs/specs/claim-matching.md section 11)."""
    if c.get("claim_type") != "revenue":
        return None
    text = f"{c.get('label_from') or ''} {c.get('snippet') or ''}"
    if CONTRACT_TERM.search(text):
        return CONTRACT_LABEL
    recurring = None if c.get("unit") else _RECURRING_TERM.search(text)       # "50% of MRR" is a share, not a run rate (PR 152)
    if recurring:
        if _NEW_MRR_TERM.search(text):
            return "New MRR"
        return "ARR" if re.search(r"(?i)\b(?:ARR|annual)", recurring.group(0)) else "MRR"
    return "Turnover" if _TURNOVER_TERM.search(text) else "Revenue"


_IN_YEAR = re.compile(r"(?i)\bin\s+((?:19|20)\d{2})\b")


def recurring_year_end(c: Dict) -> Dict:
    """An MRR or ARR figure stated "in 2021" is the run rate at the end of that year: its period is Dec 2021, and the candidate keeps
    "period_read_note" saying so (issue #151; the analyst can change the date, which drops the note). Only a bare year in the
    figure's own line, only MRR and ARR; a month the deck states, a contract value and every other type keep their period."""
    year = (_IN_YEAR.search(c.get("snippet") or "") or [None, None])[1]
    text = f"{c.get('label_from') or ''} {c.get('snippet') or ''}"
    recurring = c.get("claim_type") in ("arr", "mrr") and not CONTRACT_TERM.search(text) or c.get("claim_type") == "revenue" and deck_label(c) in ("MRR", "ARR")
    if year and recurring and c.get("target_date") == year:
        c["target_date"] = f"{year}-12"
        c["period_read_note"] = f"period read as Dec {year} from 'in {year}'"
    return c


_SALES_METRICS = [("ACV", r"\bACVs?\b"), ("win rate", r"(?i:\bwin rates?\b)"), ("sales cycle", r"(?i:\bsales cycles?\b)"),
                  ("pipeline", r"(?i:\bpipelines?\b)"), ("payback", r"(?i:\bpayback\b)"), ("conversion", r"(?i:\bconver(?:t|ts|ted|ting|sion|sions)\b)"),
                  ("acquisition", r"(?i:\bacqui(?:re|res|red|ring)\b)"), ("leads", r"(?i:\bleads\b)")]
_SALES_METRICS = [(name, re.compile(rx)) for name, rx in _SALES_METRICS]


def sales_metric(c: Dict) -> Optional[str]:
    """The Sales metric a figure's own text names (the words of the Sales family: ACV, win rate, sales cycle, ...; the first in the
    text), None for every other type or when no word is found. Figures of different Sales metrics are never compared for a deck
    inconsistency (PR 152, George 2026-10-22; docs/specs/claim-matching.md section 11)."""
    if c.get("claim_type") != "sales":
        return None
    text = f"{c.get('label_from') or ''} {c.get('snippet') or ''}"
    hits = [(m.start(), name) for name, rx in _SALES_METRICS for m in [rx.search(text)] if m]
    return min(hits)[1] if hits else None


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
    never one with the other, and a Sales figure only with one of the same Sales metric (claim-matching.md section 11)."""
    seen = {}
    for i, c in enumerate(candidates):
        if is_case(c):          # a best or worst case is no plan target, so no figure to compare (George, 2026-10-23)
            continue
        for v in claim_values(c):
            if v["value"] is not None and v["target_date"] and v["_stated"]:
                # a qualified count ("Registered Institutions") is never compared with plain users
                key = (c["claim_type"], deck_label(c), sales_metric(c), c.get("qualifier"), v["target_date"], (v["period_start"], v["period_end"]),
                       c["currency"], c["unit"] if c["unit"] in ("%", "x") else None)
                seen.setdefault(key, []).append((i, (v["value"], v["value_high"]), _figure_of(c, v)))
    for (_, _, _, _, stated, _, _, _), found in seen.items():
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


def cross_deck_inconsistencies(candidates: List[Dict]) -> List[Dict]:
    """The deck inconsistency rule read over stored candidates of several decks (integrity-coverage.md section 1, check 6): the
    pairs {"this", "other"} of figures with the same type, label and stated period and different values. A stored candidate keeps no
    "_stated": a date is stated unless it was borrowed from a heading or a neighbour ("date_from"); a table row's periods are its
    column headers'. Nothing is changed in place."""
    work = []
    for c in candidates:
        c = {**copy.deepcopy(c), "inconsistent_dates": [], "inconsistencies": []}
        c["_stated"] = not c.get("date_from")
        for i in c.get("by_period") or ():
            i["_stated"] = True
        c.setdefault("currency", None)
        c.setdefault("unit", None)
        work.append(c)
    _flag_inconsistencies(work)
    return [pair for c in work for pair in c["inconsistencies"]]

# ---------------------------------------------------------------------------
# Use of funds (deck-parser.md section 2)
# ---------------------------------------------------------------------------
# The phrases that make a slide a raise (George, 2026-10-10): whole words, any case. A phrase of several words counts in a
# slide title, a heading, a chart title or a table's header row; a single word ("raise") only in a slide title,
# being too common in body text and headings ("Raise brand awareness in Europe"). Body text and footnotes never carry a cue.
FUNDS_CUES = ("use of funds", "use of proceeds", "the ask", "our ask", "funding ask", "investment ask", "funding request",
              "capital raise", "funding round", "proposed financing", "round details", "round size",
              "raise size", "funding requirements", "capital requirements", "capital sought", "funding sought",
              "sources & uses", "sources and uses", "investor proposition")
FUNDS_CUE_WORDS = ("raise",)
_FUNDS_CUE = re.compile(r"(?i)\b(?:" + "|".join(re.escape(c).replace(r"\ ", r"\s+") for c in FUNDS_CUES) + r")\b")
_FUNDS_CUE_WORD = re.compile(r"(?i)\b(?:" + "|".join(FUNDS_CUE_WORDS) + r")\b")
_BULLET = re.compile(r"\s*[-–—*•·▪●◦‣■□►]")
CUE_HEADING_EXTRA = 3           # a heading carries a cue phrase and at most this many other words ("Use of Funds - Series A")
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


def _cue_unit(u: Dict, above) -> bool:
    """Whether the line carries a cue phrase where a cue counts. A slide title: any cue. A table's header row: a phrase of
    several words, never the single word (a merged title row is a heading). A heading: a phrase of several
    words in a short line with no figure that sits above the first percentage, does not start with a bullet, dash or
    asterisk, and holds at most CUE_HEADING_EXTRA other words. Anywhere else (body text, a footnote, a bullet below the
    figures) nothing counts."""
    text = u["text"]
    if u["title"]:
        return bool(_FUNDS_CUE.search(text) or _FUNDS_CUE_WORD.search(text))
    if u.get("header_row"):
        return bool(_FUNDS_CUE.search(text))
    found = _FUNDS_CUE.search(text)
    if not found or not _is_heading(text) or _BULLET.match(text) or not above(u):
        return False
    return len(_WORD.findall(_FUNDS_CUE.sub(" ", text))) <= CUE_HEADING_EXTRA


def _funds_units(units: List[Dict]) -> Tuple[Dict[int, str], set]:
    """(funds, mixed): `funds` maps id() of the lines whose percentages are a use of funds to their form, "text" (a line that
    names its category, "Marketing (25%)") or "chart" (a figure alone, a pie's data label); `mixed` holds id() of the
    percentage lines of a slide that is both. A cue phrase (FUNDS_CUES, see _cue_unit for where it counts)
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
        shares = [u for u in members if not u.get("header_row") and not _RATE_WORDS.search(u["text"]) and _percentages(u["text"])]
        if not shares:
            continue
        first = min(members.index(u) for u in shares)
        tops = [u["bbox"][1] for u in shares if u.get("bbox")]

        def above(m):
            if m.get("bbox") and tops and len(tops) == len(shares):
                return m["bbox"][1] < min(tops)
            return members.index(m) < first

        if not any(_cue_unit(m, above) for m in members):
            continue
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


# ---------------------------------------------------------------------------
# Acquisition channels (chat-upload.md section 17)
# ---------------------------------------------------------------------------
# The cues that make a slide a user-acquisition slide: whole words, any case. They count in the slide's title, in a heading
# or chart title (a short line with no figure and at most CUE_HEADING_EXTRA other words, above the first platform line, not a bullet) and in a table's header row.
# Body text never carries a cue. Without one, "Telegram(30K)" is read as before (and is Other when no heading names a type).
ACQUISITION_CUES = ("user acquisition", "acquisition channels", "acquisition channel", "acquisition", "channels",
                    "traffic sources", "traffic source", "funnel")
_ACQUISITION_CUE = re.compile(r"(?i)\b(?:" + "|".join(re.escape(c).replace(r"\ ", r"\s+") for c in ACQUISITION_CUES) + r")\b")
CHANNEL_NAME_MAX = 40
# One platform: its name, then the number in brackets ("Telegram(30K)", "Facebook (12,500)", "YouTube [1.2M]").
_CHANNEL_LINE = re.compile(r"^\s*(?P<name>[^()\[\]%]*?[^\W\d_][^()\[\]%]*?)\s*[(\[](?P<inside>[^()\[\]]{1,20})[)\]]\s*$")
_CHANNEL_APPROX = re.compile(r"^\s*(?:~|≈|approx\.?|c\.)\s*")


def _channel_figure(text: str) -> Optional[Tuple[str, Dict]]:
    """(platform name, number) when the whole line is a platform and a count in brackets; None otherwise. The bracket holds one
    plain number, with or without a K, M or B: no currency, no percentage, no word after it, no date."""
    m = _CHANNEL_LINE.match(text)
    if not m:
        return None
    name, inside = m.group("name").strip(" :-–—,;"), _CHANNEL_APPROX.sub("", m.group("inside")).strip()
    if not name or len(name) > CHANNEL_NAME_MAX or find_dates(name) or find_dates(inside):
        return None
    numbers = find_numbers(inside, [])
    if len(numbers) != 1 or numbers[0]["start"] != 0 or numbers[0]["end"] != len(inside) or numbers[0]["value_high"] is not None \
            or numbers[0]["unit"] or numbers[0]["currency"] or numbers[0]["value"] is None:
        return None
    return name, numbers[0]


def _channel_cue_unit(u: Dict, above) -> bool:
    text = u["text"]
    if u["title"] or u.get("header_row"):
        return bool(_ACQUISITION_CUE.search(text))
    if not _ACQUISITION_CUE.search(text) or not _is_heading(text) or _BULLET.match(text) or not above(u):
        return False
    return len(_WORD.findall(_ACQUISITION_CUE.sub(" ", text))) <= CUE_HEADING_EXTRA       # a heading, not a sentence


def _channel_units(units: List[Dict]) -> Dict[int, Tuple[str, Dict]]:
    """id() of each line that is one platform's figure on a user-acquisition slide, mapped to (name, number). The slide needs a cue
    (ACQUISITION_CUES) in its title, a heading or chart title, or a table's header row; a platform line is a text line, never a
    table row."""
    pages = {}
    for u in units:
        pages.setdefault(u["page"], []).append(u)
    out = {}
    for members in pages.values():
        lines = {id(u): _channel_figure(u["text"]) for u in members if not u["title"] and not u.get("table_row")}
        lines = {k: v for k, v in lines.items() if v}
        if not lines:
            continue
        first = min(members.index(u) for u in members if id(u) in lines)
        tops = [u["bbox"][1] for u in members if id(u) in lines and u.get("bbox")]

        def above(m):
            if m.get("bbox") and tops and len(tops) == len(lines):
                return m["bbox"][1] < min(tops)
            return members.index(m) < first

        if any(_channel_cue_unit(m, above) for m in members if id(m) not in lines):
            out.update(lines)
    return out


def _channel_candidate(u: Dict, name: str, number: Dict) -> Dict:
    """One platform's claim: type Acquisition channels, the platform as its label (`channel`), the number in brackets as a count
    with no currency. No period: a funnel figure is not dated by a heading, so nothing is borrowed."""
    return {"claim_type": ACQUISITION_CHANNELS, "value": number["value"], "value_high": None, "unit": COUNT, "currency": None,
            "target_date": None, "period_text": None, "snippet": _snippet(u["text"], 0), "label_from": None, "date_from": None,
            "sources": [u["spans"][0][2]], "type_from": "heading", "claim_direction": None, "_stated": False, "channel": name}


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
                if item["target_date"] is None:
                    return None                             # no period was read: none is shown (issue #136)
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
                                       "source": i["sources"][0], "_stated": i["_stated"],
                                       **({"period_unclear": True} if i.get("period_unclear") else {})}
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


def page_confidence(candidate: Dict) -> Dict:
    """The confidence of a claim the page read found (George, 2026-10-23; chat-upload.md section 28, claim-matching.md section 4.2):
    High = matched to the page with no review flag; Medium = matched with an informational flag, or with no date; Low = not matched, or
    a review flag. Read from the checker's flags and the claim's period, never from a model's own score."""
    flags = candidate.get("flags") or []
    review = review_flags(flags)
    matched = candidate.get("ai_status") == "matched"
    if not matched or review:
        failed = (["not matched"] if not matched else []) + review
        level = "Low"
    else:
        failed = [f for f in flags if f in INFORMATIONAL_FLAGS] + ([] if candidate.get("target_date") else ["no date"])
        level = "Medium" if failed else "High"
    return {"level": level, "failed": failed, "text": level + (" – " + ", ".join(failed) if failed else "")}


def confidence(candidate: Dict, peers: List[Dict]) -> Dict:
    """High, Medium or Low from the checks the parser already runs, never from a model's own score: the claim has a
    date, a unit (or currency), a heading or line that names its type, and its value is corroborated elsewhere in the
    deck. No failed check is High, one is Medium, two or more Low. A check that cannot apply to a claim with no
    value (unit, corroboration) is skipped. `peers` are the candidates of the same deck. A claim the analyst added is
    not scored: its confidence reads "Analyst-entered"; one the analyst edited reads "Analyst-edited" (issue #146)."""
    if candidate.get("origin") == "analyst":
        return {"level": None, "failed": [], "text": "Analyst-entered"}
    if candidate.get("status") == "edited" or "parsed" in candidate:
        return {"level": None, "failed": [], "text": "Analyst-edited"}
    if candidate.get("origin") == "ai" and candidate.get("ai_status") in ("matched", "unmatched"):
        return page_confidence(candidate)
    values = claim_values(candidate)
    has_value = any(v["value"] is not None for v in values)
    named = candidate.get("claim_type") not in (UNKNOWN, "other") and bool(candidate.get("type_from", "line"))
    checks = [("no date", all(v["target_date"] for v in values))]
    if not has_value and (candidate.get("claim_direction") or not is_milestone(candidate)):
        checks.append(("no figure", False))          # a direction or a heading no figure uses is never better than Medium (issue #146)
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
