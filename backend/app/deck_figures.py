"""Deck figures on the register path (docs/design/read-check-review.md sections 5 and 7; PR 3, item 4).

The page reader's figures are checked the way a sheet's cells are: the stored page text is opened and the figure looked for in it, within
the tolerance of its unit (money 0.5 %, a rate 1 point, a count exact). Three outcomes and no other, the same wording every time:

    Confirmed     the page's text holds the value within tolerance
    Rejected      the page has text with figures in it and none of them is the value: "Reading says {value}; page {n} holds no such figure."
    Cannot check  the page has no text layer with figures, or its extraction left a picture or chart unread and the value is not in the text
                  (the figure was read from the image): "Page {n} has no text layer; figure read from the image."

Nothing is corrected, nothing is stored here: the outcome is computed from the stored page text and the stored candidate each time it is asked,
so it always follows the deck as it now stands. No deck text leaves this module: a figure carries its page number, its value and the closed
words of the candidate, never a line of the page (rule 17).
"""
from typing import Dict, List, Optional

from . import checks
from .decks import claims
from .llm.schemas import SCHEMA_CURRENCIES
from .structures import checker

R_PAGE_RANGE = "Reading cites page {page}; the deck ends at page {last}."
R_PAGE = "Reading says {value}; page {n} holds no such figure."
PLAN_BASES = ("projection", "scenario")


def page_lines(deck: Dict, page: int) -> List[Dict]:
    """A stored page's lines: its text, notes and table lines ("b{n}") and its chart labels ("c{structure}:{cell}"), in the stored order."""
    key = "slide" if deck.get("page_unit") == "slide" else "page"
    lines = [{"ref": f"b{n}", "kind": b.get("kind"), "text": b.get("text") or ""}
             for n, b in enumerate(deck.get("blocks") or []) if b.get(key) == page and (b.get("text") or "").strip()]
    for s, structure in enumerate(deck.get("structures") or []):
        if structure.get("type") == "chart" and structure.get(key) == page:
            lines += [{"ref": f"c{s}:{n}", "kind": "chart", "text": cell.get("text") or ""}
                      for n, cell in enumerate(structure.get("cells") or []) if (cell.get("text") or "").strip()]
    return lines


def page_numbers(deck: Dict, page: int) -> List[float]:
    """Every figure the page's text states, as written and in full units (claims.figures scales k, m, bn; the unscaled number is kept too)."""
    out: List[float] = []
    for line in page_lines(deck, page):
        for f in claims.figures(line["text"]):
            out += [v for v in (f.get("value"), f.get("num")) if v is not None]
    return out


COUNT_UNITS = (None, "count", "x", "days", "months", "years")


def unit_of(candidate: Dict) -> Optional[str]:
    """The comparison unit of a candidate: a currency is money (0.5 %), a percent a rate (1 point), a count, a multiple or a duration is
    compared exactly. Any other unit ("other") has none: the figure cannot be checked (C_NO_UNIT)."""
    if candidate.get("currency"):
        return "money"
    unit = candidate.get("unit")
    if unit == "%":
        return "rate"
    if unit in COUNT_UNITS:
        return "count"
    return "money" if unit in SCHEMA_CURRENCIES else None


def page_of(candidate: Dict) -> Optional[int]:
    source = (candidate.get("sources") or [{}])[0]
    return source.get("page") or source.get("slide")


def figure_of(candidate: Dict, deck: Dict) -> Dict:
    """One deck figure in the file map's fields (value, unit, currency, period, actual/plan, source), its candidate's id for the register."""
    page = page_of(candidate)
    return {"id": candidate.get("id"), "deck_id": candidate.get("deck_id"), "metric": candidate.get("claim_type"), "value": candidate.get("value"),
            "unit": unit_of(candidate), "currency": candidate.get("currency"), "period": candidate.get("period_text") or candidate.get("target_date"),
            "actual_plan": "plan" if candidate.get("basis") in PLAN_BASES else "actual" if candidate.get("basis") == "actual" else None,
            "segment": candidate.get("page_segment"), "source": {"page": page, "text_layer": bool(page and page_numbers(deck, page))}}


def check_figure(figure: Dict, candidate: Dict, deck: Dict) -> Dict:
    """The outcome of one deck figure against the stored text of its page (see the module note)."""
    page, value = figure["source"]["page"], figure.get("value")
    base = {"key": f"deck:{figure.get('deck_id')}:{figure.get('id')}", "kind": "deck_figure", "metric": figure.get("metric"), "value": value,
            "page": page, "deck_id": figure.get("deck_id")}
    if page is None or value is None:
        return {**base, "outcome": checks.CANNOT, "reason": checks.C_NO_REF}
    if deck.get("pages") and page > int(deck["pages"]):
        return {**base, "outcome": checks.REJECTED, "reason": R_PAGE_RANGE.format(page=page, last=deck["pages"])}
    unit = figure["unit"]
    if unit not in ("money", "count", "rate"):
        return {**base, "outcome": checks.CANNOT, "reason": checks.C_NO_UNIT}
    numbers = page_numbers(deck, page)
    if any(checks.compare(unit, float(value), n) for n in numbers):
        return {**base, "outcome": checks.CONFIRMED, "reason": None}
    incomplete = checker.EXTRACTION_INCOMPLETE in (candidate.get("flags") or [])
    if not numbers or incomplete:
        return {**base, "outcome": checks.CANNOT, "reason": checks.C_NO_TEXT.format(n=page)}
    return {**base, "outcome": checks.REJECTED, "reason": R_PAGE.format(value=checks.shown(float(value)), n=page)}


async def checked(db, audit_id: str) -> List[Dict]:
    """[{"deck_id", "file", "pages", "figures": [figure + outcome]}] for the audit's decks, from the stored candidates and page text. A
    candidate the analyst rejected is not a figure; one the page reader did not read (an analyst's own, a rules read) is not checked here."""
    from .decks import CANDIDATES_COLLECTION, TEXT_COLLECTION
    out = []
    for deck in await db[TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0}).to_list(100):
        found = await db[CANDIDATES_COLLECTION].find({"audit_id": audit_id, "deck_id": deck.get("deck_id"), "origin": "ai",
                                                      "status": {"$ne": "rejected"}}, {"_id": 0}).to_list(10000)
        figures = []
        for candidate in found:
            figure = figure_of({**candidate, "deck_id": deck.get("deck_id")}, deck)
            figures.append({**figure, **check_figure(figure, candidate, deck)})
        out.append({"deck_id": deck.get("deck_id"), "file": deck.get("file"), "pages": deck.get("pages"), "figures": figures})
    return out
