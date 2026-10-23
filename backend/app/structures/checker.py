"""checker: Python flags on the claims the model read from a deck page (docs/design/ai-reads-rules-check.md, built 2026-10-22).

Pure: no I/O, no model, no database. page_check decides, cell by cell, whether a claim is "Matched to page" (CLAUDE.md rule 18:
Python's value read from the cited cell, the unit in it or next to it, the period rebuilt from that cell's sources); this module
runs after it and adds `flags`. A failed check flags the claim; it never deletes or retypes it (George, 2026-10-22). A claim with
a flag is listed in the review tab of the deck panel, not in the main claims list; the analyst decides there.

Cell tolerance (George, 2026-10-23): a value that is not in the cited cell but is in another cell of the page is "Matched to page", flagged
CELL_CORRECTED, with value_cell set to the cell found (page_check.find_elsewhere); the value on no cell stays VALUE_NOT_ON_PAGE.
SIGN_NOT_ON_PAGE: a negative value whose value cell shows no minus sign and no loss, decline or decrease word.

Four checks per claim:
1. VALUE_NOT_ON_PAGE: the value (as written or in full units, page_check.figure_check) is in no cell of the page; a claim with no
   value and no period has nothing on the page behind it and is flagged the same way (a qualitative line is listed under Review, never matched).
2. CURRENCY_ASSUMED: the unit is a currency and neither its symbol nor its code stands in the value cell or one directly next to
   it (page_check.unit_check); UNIT_ASSUMED for "%", "x" and a time word whose mark is not there.
3. SCENARIO_NOT_ON_PAGE: the model set a scenario (best, realistic, worst) and its words stand neither in the value cell, nor in its text
   box, nor in a cell next to it (its header, the line above or below it, the label of another box directly beside it): the case label
   must be on the same line or block as the figure (George, 2026-10-23, review of PR 164, M1);
   PERIOD_NOT_ON_PAGE: the model set a period that page_check could not rebuild from the cell's sources and no cell of the page
   states it either.
4. PAGE_OUT_OF_RANGE (out_of_range): the claim's page is not within the document.

Post-checks converted from the rules read (claims.py section 2; they used to retype or drop a candidate, now they flag):
5. USE_OF_FUNDS: the value cell's line is a percentage of a use-of-funds slide (claims._funds_units: a cue phrase in the title or
   a heading).
6. ACQUISITION_CHANNEL: the value cell's line is one platform's count in brackets on a user-acquisition slide (claims._channel_units).
7. TURNOVER: the metric is revenue and the value or label cell holds a turnover term (turnover, GMV, TPV, transaction volume:
   claims._TURNOVER_TERM); the analyst answers Revenue or Volume.
8. BAR_YEAR: the value cell has a year label under its bar by place (bar_year, issue #148) and the model's period is another.
9. PIPELINE_COLUMN: a table cell under a column whose header names the pipeline, claimed as another metric (George, 2026-10-20).
10. AXIS_TICK and NOT_PLAN_LINE: what page_check used to drop before any check (an axis tick; a line about funds raised, tokens,
    careers or the industry) is flagged instead.

Added 2026-10-23 (review of PR 164): MATCHES_ANALYST (structures/pages.py: the model read the figure of a claim the analyst added; both are listed),
BASIS_SCENARIO_DISAGREE (basis actual with a case, or basis scenario with none) and BASIS_CONFLICT (a projection for a period on or
before the as-of month; derived when the list is read, because the as-of month is known only after the engine ran: `claim_flags`).
The model's `basis` never changes an evidence label (George, 2026-10-23, M2).

Added 2026-10-23 (George): YEAR_LABEL_BELOW, "year label below: YYYY", on a claim with no period whose value cell has a year label under
it by place (the rule of 8); a hint for Edit, the period is never set. It is FLAGS' one pattern, the year being a four-digit label.

Every flag is a closed string of FLAGS (backend/tests/test_gateway_data_boundary.py); no flag carries deck text.
"""
import re
from typing import Dict, List, Optional

from ..decks import claims, parser
from . import page_check, verify

VALUE_NOT_ON_PAGE = "value not on page"
CURRENCY_ASSUMED = "currency assumed"
UNIT_ASSUMED = "unit assumed"
SCENARIO_NOT_ON_PAGE = "scenario label not on page"
PERIOD_NOT_ON_PAGE = "period not on page"
PAGE_OUT_OF_RANGE = "page out of range"
USE_OF_FUNDS = "use-of-funds share"
ACQUISITION_CHANNEL = "acquisition channel"
TURNOVER = "turnover, not revenue"
BAR_YEAR = "year under bar differs"
PIPELINE_COLUMN = "pipeline column"
AXIS_TICK = "axis tick"
NOT_PLAN_LINE = "not a plan line"
MATCHES_ANALYST = "matches analyst claim"
BASIS_SCENARIO_DISAGREE = "basis and scenario disagree"
BASIS_CONFLICT = claims.BASIS_CONFLICT
CELL_CORRECTED = "cell corrected"
SIGN_NOT_ON_PAGE = "sign not on page"
FLAGS = (VALUE_NOT_ON_PAGE, CURRENCY_ASSUMED, UNIT_ASSUMED, SCENARIO_NOT_ON_PAGE, PERIOD_NOT_ON_PAGE, PAGE_OUT_OF_RANGE,
         USE_OF_FUNDS, ACQUISITION_CHANNEL, TURNOVER, BAR_YEAR, PIPELINE_COLUMN, AXIS_TICK, NOT_PLAN_LINE, MATCHES_ANALYST,
         BASIS_SCENARIO_DISAGREE, BASIS_CONFLICT, CELL_CORRECTED, SIGN_NOT_ON_PAGE)
INFORMATIONAL_FLAGS = claims.INFORMATIONAL_FLAGS        # a note on the row; the claim stays in the main list (George, 2026-10-23)
REVIEW_FLAGS = tuple(f for f in FLAGS if f not in INFORMATIONAL_FLAGS)      # the claim is listed under Review
review_flags = claims.review_flags
# Brackets are a minus sign for these metrics only; for every other metric a bracketed figure is positive (George, 2026-10-23).
BRACKET_NEGATIVE_METRICS = ("ebitda", "net_profit", "gross_profit", "costs", "cash", "burn")
_BRACKETED = re.compile(r"\(\s*[^\w()]{0,3}\d[^()]*\)")
YEAR_LABEL_BELOW = "year label below"        # the flag is "year label below: YYYY"
YEAR_LABEL_FLAG = re.compile(rf"{YEAR_LABEL_BELOW}: \d{{4}}")
NO_SCENARIO = "none"
CASES = claims.CASES                  # the scenarios that are no plan target (George, 2026-10-23): listed under Scenarios, never matched
_MINUS = ("-", "\u2212", "\u2013", "\u2014")                      # hyphen-minus, minus sign, en and em dash
_LOSS_WORD = re.compile(r"(?i)\b(?:loss(?:es)?|declin\w*|decreas\w*)\b")
# The words a page uses for each case, whole words, any case ("Best-Case Scenario", "Base case", "Downside").
SCENARIO_WORDS = {
    "best": r"best[\s-]*case|upside|optimistic|bull(?:ish)?[\s-]*case|high[\s-]*case",
    "realistic": r"realistic|base[\s-]*case|expected[\s-]*case|most[\s-]*likely|mid[\s-]*case|medium[\s-]*case",
    "worst": r"worst[\s-]*case|downside|pessimistic|conservative|bear(?:ish)?[\s-]*case|low[\s-]*case",
}
_SCENARIO = {name: re.compile(r"(?i)\b(?:" + words + r")\b") for name, words in SCENARIO_WORDS.items()}
_CURRENCY_UNITS = frozenset(code for code in page_check.CURRENCY_SYMBOLS) | {page_check.OTHER}
_TIME_UNITS = ("days", "months", "years")


def year_label_flag(year) -> str:
    return f"{YEAR_LABEL_BELOW}: {year}"


def out_of_range(page: int, page_count: Optional[int]) -> Optional[str]:
    """PAGE_OUT_OF_RANGE when the page is not within the document (1 to page_count); None when it is, or the count is unknown."""
    if page < 1 or (page_count is not None and page > page_count):
        return PAGE_OUT_OF_RANGE
    return None


def _cell_text(grid: Dict, cell_id: Optional[str]) -> str:
    by_id = {page_check._id(c): c for c in grid["cells"]}
    return by_id[cell_id]["text"] if cell_id in by_id else ""


def value_on_page(listed: Dict, claim: Dict, furniture: frozenset = frozenset()) -> bool:
    """Whether the claim's value (and the high end of a range) is a figure of any cell of the page, in full units as Python reads
    it, outside the page's furniture (a header or footer band, the page's own number) (items.list_items: "$1B+" is 1,000,000,000, never the written "1", so a digit inside another figure backs no claim)."""
    if claim.get("value") is None:
        return False
    items = [i for structure in listed.values() for i in structure["items"] if i["cell"] not in furniture]
    by_id = {i["id"]: i for i in items}

    def holds(item, value):
        return any(page_check._close(v["value"], value) for v in item["values"])

    for item in items:
        if not holds(item, claim["value"]):
            continue
        if claim.get("value_high") is None:
            return True
        span = item.get("range")
        if span and item["id"] == span["items"][0] and span["items"][1] in by_id and holds(by_id[span["items"][1]], claim["value_high"]):
            return True
    return False


def period_on_page(grid: Dict, period: str, fiscal_year_end: int) -> bool:
    """Whether any cell of the page states the period (its own text or its bar's year label)."""
    wanted = claims.period_range(period, fiscal_year_end)
    if not wanted:
        return False
    for cell in grid["cells"]:
        texts = [cell["text"]] + ([str(cell["bar_year"])] if cell.get("bar_year") else [])
        for text in texts:
            if any(claims.period_range(d["date"], fiscal_year_end) == wanted for d in claims.find_dates(text, table=cell.get("table") is not None)):
                return True
            found = claims.period_cell(text)
            if found and "relative" not in found and found.get("label") and claims.period_range(found["label"], fiscal_year_end) == wanted:
                return True
    return False


def scenario_near(structure: Dict, cell: Dict, scenario: Optional[str]) -> bool:
    """Whether the words of the scenario the model set stand on the figure's own line or block: its cell, the other lines of its text
    box, or a cell directly next to it (page_check.adjacent: its headers, the line above and below, the label of another box beside
    it). A page that names every case somewhere does not back a claim whose own case label is another (M1). A claim with no scenario
    needs none."""
    if not scenario or scenario == NO_SCENARIO:
        return True
    rx = _SCENARIO.get(scenario)
    near = [cell, *page_check._same_box(structure, cell), *page_check.adjacent(structure, cell)]
    return bool(rx and any(rx.search(c["text"]) for c in near))


def sign_shown(text: str, metric: Optional[str] = None) -> bool:
    """Whether a value cell shows a minus sign, a loss / decline / decrease word, or a bracketed number for a metric in
    BRACKET_NEGATIVE_METRICS (any other metric's bracketed figure is positive)."""
    return (any(mark in text for mark in _MINUS) or bool(_LOSS_WORD.search(text))
            or (metric in BRACKET_NEGATIVE_METRICS and bool(_BRACKETED.search(text))))


def basis_disagrees(basis: Optional[str], scenario: Optional[str]) -> bool:
    """The model's two words contradict each other: basis "actual" with a case named, or basis "scenario" with none (L8)."""
    case = bool(scenario) and scenario != NO_SCENARIO
    return (basis == "actual" and case) or (basis == "scenario" and not case)


# ---------------------------------------------------------------------------
# The converted rules
# ---------------------------------------------------------------------------
def rule_lines(blocks: Optional[List[Dict]], file: str) -> Dict[str, set]:
    """{"funds": the texts of the page's use-of-funds percentage lines, "channels": the texts of its platform lines}, by the rules
    read's own detectors over the page's parsed blocks (claims._funds_units, claims._channel_units). Empty without blocks."""
    if not blocks:
        return {"funds": set(), "channels": set()}
    units = claims._units(blocks, file)
    funds, _ = claims._funds_units(units)
    channels = claims._channel_units(units)
    return {"funds": {u["text"] for u in units if id(u) in funds}, "channels": {u["text"] for u in units if id(u) in channels}}


def page_blocks(blocks: List[Dict], grid: Dict) -> List[Dict]:
    """The parsed blocks of the grid's page."""
    key = (grid.get("slide"), grid.get("page"))
    return [b for b in blocks or () if parser._page_key(b) == key]


def _pipeline_column(structure: Dict, cell: Dict) -> bool:
    """Whether a table cell stands under a column whose header names the pipeline (every row of such a column is Pipeline)."""
    if cell.get("table") is None:
        return False
    headers = [h["text"] for h in verify.header_cells(structure, cell) if h["row"] < cell["row"]]
    return any((claims._borrow_keyword([h], nearest=False) or (None,))[0] == "pipeline" for h in headers)


def rule_flags(grid: Dict, grid_views: Dict, cell: Dict, claim: Dict, lines: Dict[str, set], fiscal_year_end: int) -> List[str]:
    """The flags of rules 5 to 10 for one claim on its cell."""
    out = []
    text = cell["text"]
    if text in lines["funds"]:
        out.append(USE_OF_FUNDS)
    if text in lines["channels"]:
        out.append(ACQUISITION_CHANNEL)
    if claim["metric"] == "revenue" and claims._TURNOVER_TERM.search(f"{text} {_cell_text(grid, claim.get('label_cell'))}"):
        out.append(TURNOVER)
    if cell.get("bar_year") and claim.get("period"):
        bar = (claims.period_cell(str(cell["bar_year"])) or {}).get("label")
        if claims.period_range(bar, fiscal_year_end) != claims.period_range(claim["period"], fiscal_year_end):
            out.append(BAR_YEAR)
    elif cell.get("bar_year") and re.fullmatch(r"\d{4}", str(cell["bar_year"]).strip()):
        out.append(year_label_flag(str(cell["bar_year"]).strip()))
    if claim["metric"] != "pipeline" and _pipeline_column(page_check.view_of(grid_views, cell), cell):
        out.append(PIPELINE_COLUMN)
    if cell.get("tick"):
        out.append(AXIS_TICK)
    if claims._NOT_PLAN_LINE.search(text):
        out.append(NOT_PLAN_LINE)
    return out


# ---------------------------------------------------------------------------
# One page
# ---------------------------------------------------------------------------
def check(grid: Dict, page_claims: List[Dict], fiscal_year_end: int = 12, blocks: Optional[List[Dict]] = None,
          file: str = "") -> Dict:
    """page_check.check over the page, every claim kept (a claim on a cell the page does not have is still dropped and counted:
    there is nothing to list it against), each item with its `flags` (closed strings of FLAGS, possibly none), `basis` and
    `scenario`; the counts of page_check plus "flagged"."""
    checked = page_check.check(grid, page_claims, fiscal_year_end, drop=False)
    grid_views = page_check.views(grid)
    listed = {id(s): page_check.items.list_items(s, titles=True) for s in [grid_views["boxes"], *grid_views["tables"].values()]}
    by_id = {page_check._id(c): c for c in grid["cells"]}
    lines = rule_lines(blocks, file)
    furniture = frozenset(i for i, c in by_id.items() if c.get("furniture"))
    kept = [c for c in page_claims if c["value_cell"] in by_id]
    assert len(kept) == len(checked["items"])
    for claim, item in zip(kept, checked["items"]):
        cell = by_id[item["value_cell"]]            # the cell the value was found in: the cited one, or another (cell tolerance)
        flags = [CELL_CORRECTED] if item.get("cell_corrected") else []
        if not item["checks"]["value"] and not value_on_page(listed, claim, furniture):
            if claim.get("value") is not None or not claim.get("period"):
                flags.append(VALUE_NOT_ON_PAGE)
        unit = claim.get("unit")
        if claim.get("value") is not None and unit and not item["checks"]["unit"]:
            if unit in _CURRENCY_UNITS:
                flags.append(CURRENCY_ASSUMED)
            elif unit in ("%", "x", *_TIME_UNITS):
                flags.append(UNIT_ASSUMED)
        if claim.get("value") is not None and claim["value"] < 0 and not sign_shown(cell["text"], claim.get("metric")):
            flags.append(SIGN_NOT_ON_PAGE)
        if not scenario_near(page_check.view_of(grid_views, cell), cell, claim.get("scenario")):
            flags.append(SCENARIO_NOT_ON_PAGE)
        if basis_disagrees(claim.get("basis"), claim.get("scenario")):
            flags.append(BASIS_SCENARIO_DISAGREE)
        if claim.get("period") and not item["checks"]["period"] and not period_on_page(grid, claim["period"], fiscal_year_end):
            flags.append(PERIOD_NOT_ON_PAGE)
        flags += [f for f in rule_flags(grid, grid_views, cell, claim, lines, fiscal_year_end) if f not in flags]
        item["flags"] = flags
        item["basis"] = claim.get("basis")
        item["scenario"] = claim.get("scenario") or NO_SCENARIO
    checked["flagged"] = sum(1 for i in checked["items"] if flagged(i))
    return checked


def flagged(item: Dict) -> bool:
    return bool(review_flags(item.get("flags")))
