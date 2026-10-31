"""Deck figures: actuals, plan and segments (docs/design/deck-actuals.md, sections 1 to 6).

A pure module like claim_matching: it reads candidates and register rows and builds text from stored data. No model call, nothing stored, nothing
leaves the app. The register applies it (`claim_matching._row`), the candidates pass through `page_splits` after the fold (`decks.claims.fold_twins`),
the memo prints `appendix_lines` in Appendix C and `data_requests` in Appendix B.
"""
from __future__ import annotations

import re
from decimal import Decimal
from itertools import combinations
from typing import Dict, Iterable, List, Optional

from . import formatting as fmt

ACTUAL, PLAN, UNSET = "actual", "plan", "unset"
TAG = "deck only"
DIFFERS = "deck differs from file"
CONSISTENT, DIFFERS_STATUS = "consistent", "differs"
DECK_ONLY_REASON = "Deck only: nothing in the files for this period"
DIFFERS_REASON = DIFFERS + ": deck {deck}, file {file}"
NOT_CHECKED_NOTHING = "nothing in the files for this period"
SPLIT_TOLERANCE = Decimal("0.02")       # the app's reconciliation tolerance for a sum (claim_groups.TOLERANCE): figures of a page that add up to a third
SPLIT_SEARCH_MAX = 10                   # figures of a page searched for the parts of a total: 2^10 subsets at most
# What a row's reason says when the files hold nothing for the figure's period: the register turns these into "deck only" for a deck actual.
HOLDS_NOTHING = ("claim period not in supplied data", "Missing:", "Not computed", "not computed", "segment not in the data", "not computed by segment")
# The flags a split resolves: a part's period or label that disagreed was settled by the sum (section 4).
SPLIT_RESOLVES = ("sources disagree", "source ambiguous", "source not associated", "period not on page", "year under bar differs", "label mismatch",
                  "period is a range")
NO_LABEL = "no label read"
UNLABELLED = "Unlabelled part"          # the name of a split part that has no label of its own (or the total's): a segment under the total, never a rival total
DECK_ORIGINS_OUT = ("analyst", "forecast_file")
PAGE_READER = "ai"                      # the origin of a figure the page reader read: the default path, DECK_PIPELINE=ai (the rules read keeps its tests)
PAGE_UNITS = ("slide", "page")
TABLE_OF = {"Revenue": "revenue by customer and month", "ARR": "MRR by customer and month", "MRR": "MRR by customer and month",
            "Customer count": "customers by month", "NRR (12-month)": "revenue by customer and month",
            "Gross revenue churn": "revenue by customer and month", "Monthly gross revenue churn": "revenue by customer and month"}


# --- 1. the period sort --------------------------------------------------------------------------------------------------------------

def _index(day) -> Optional[int]:
    """Months since year 0 of a "YYYY-MM[-DD]" text or date, else None."""
    text = str(day or "")[:7]
    return int(text[:4]) * 12 + int(text[5:7]) - 1 if re.fullmatch(r"\d{4}-\d{2}", text) else None


def period_sort(c: dict, as_of: Optional[str]) -> Optional[str]:
    """Where a deck figure's own period stands against the audit's as-of month (section 1): "actual" when the period ends on or before it, "plan"
    when it ends after it, "unset" when the figure has no readable period. The deck's date is never read. None while the audit has no as-of month."""
    end, start, at = _index(c.get("period_end")), _index(c.get("period_start")), _index(as_of)
    if end is None or start is None:
        return UNSET
    if at is None:
        return None
    return ACTUAL if end <= at else PLAN


def is_deck_actual(c: dict, sort: Optional[str], figure_type: Optional[str]) -> bool:
    """A deck actual (section 1): a figure the page reader read from a deck whose own period has passed, whatever the reader marked it (projection,
    scenario) and whatever its words say; the mark is shown as a note (`mark_note`). The rules read (DECK_PIPELINE=rules, Add from deck) and the
    analyst's own claims keep their test. `figure_type` is not read: the period alone decides."""
    return sort == ACTUAL and c.get("origin") == PAGE_READER and c.get("value") is not None


def mark_note(c: dict) -> Optional[str]:
    """The note of a deck actual the page reader marked a projection or a scenario: the deck says so, the figure's period has passed, so it is
    checked as an actual all the same. A closed sentence of the reader's marks, no deck text."""
    mark = c.get("basis") if c.get("basis") in ("projection", "scenario") else "scenario" if c.get("scenario") not in (None, "none") else None
    return f"The deck marks this figure as a {mark}; its period has passed, so it is checked as an actual." if mark else None


def holds_nothing(reason: Optional[str]) -> bool:
    """Whether a row's reason says the files hold no figure for the claim (and not that the claim itself is unclear)."""
    return str(reason or "").startswith(HOLDS_NOTHING)


# --- text ---------------------------------------------------------------------------------------------------------------------------

def number(value: float, places: int = 2) -> str:
    """501378.04 -> "501,378.04", 482475.0 -> "482,475": trailing zeros of the decimals dropped."""
    return fmt.fmt_number(value)


def file_text(source: Optional[dict]) -> Optional[str]:
    """"File <sheet>!<cell>[, ...]" of an observed source that names cells; else its file and rows; else None."""
    if not source:
        return None
    cells = source.get("cells")
    if cells and source.get("sheet"):
        return ", ".join(f"File {source['sheet']}!{cell}" for cell in cells)
    parts = [p for p in (source.get("file"), source.get("sheet"), source.get("rows")) if p]
    return "File " + " · ".join(str(p) for p in parts) if parts else None


def page_words(page_ref: Optional[str]) -> Optional[str]:
    """"p12" -> "page 12"; "slide 4, p5" -> "slide 4"; the first page the figure was read on."""
    first = str(page_ref or "").split(",")[0].strip()
    if re.fullmatch(r"p\d+", first):
        return "page " + first[1:]
    return first or None


def source_text(row: dict) -> Optional[str]:
    """The Source column (section 2): "File <sheet>!<cell>" of the figure reconciled with a file, "Deck p<n>" of a figure only the deck states."""
    if row.get("deck_status") in (CONSISTENT, DIFFERS_STATUS) or (row.get("observed_value") is not None and row.get("deck_status") is None):
        return file_text(row.get("observed_source"))
    if row.get("deck_status") == TAG:
        first = str(row.get("page_ref") or "").split(",")[0].strip()
        return f"Deck {first}" if first else "Deck"
    return None


# --- 3. the details block ----------------------------------------------------------------------------------------------------------------

BLOCK_PARTS = ("inputs", "formula", "checked", "not_checked")


def deck_block(row: dict, label: Optional[str], formula: Optional[str] = None, note: Optional[str] = None) -> dict:
    """The details block of a deck figure, built from the row alone: the deck figure with its page and label as printed, the calculation with the numbers
    filled in, what a file confirmed (with the file cell) and what none did (by page)."""
    name = label or row.get("metric") or "Figure"
    period, page, value = row.get("period") or "no period", row.get("page_ref") or "", row.get("claimed_value")
    said = f"{row.get('metric') or name}, {period}"
    multiple = row.get("unit") == "x"
    inputs = [{"label": name, "value": value, "page": page}]
    where = file_text(row.get("observed_source"))
    status = row.get("deck_status")
    if status == TAG or (status is None and row.get("observed_value") is None):
        checked, unchecked = [NOT_CHECKED_NOTHING], [f"{name}, {period} ({page})" if page else f"{name}, {period}"]
        formula = formula or f"{said} = {number(value)} as printed" + (f" on {page_words(page)}" if page else "")
    else:
        observed = row.get("observed_value")
        shown = (fmt.fmt_ratio(observed) if multiple else number(observed)) if observed is not None else "no figure"
        if status == DIFFERS_STATUS:
            by = f" by {number(abs(value - observed) / abs(observed) * 100, 1)}%" if observed else ""
            checked, unchecked = [f"{said} differs from {where or 'the file'}{by} (deck {fmt.fmt_ratio(value) if multiple else number(value)}, file {shown})"], []
        elif status == CONSISTENT and where:
            checked, unchecked = [f"{said} matches {where} ({shown})"], []
        else:
            checked, unchecked = [f"{said} checked against the files ({shown})"], []
        parts = (row.get("observed_source") or {}).get("inputs") or []
        if len(parts) == 2 and observed is not None:         # a multiple: the two years' revenue with the numbers filled in
            formula = formula or f"{parts[0]['name']} ÷ {parts[1]['name']} = {number(parts[0]['value'])} ÷ {number(parts[1]['value'])} = {fmt.fmt_ratio(observed)}"
        formula = formula or (f"{row.get('metric') or name}, {row.get('observed_at') or period} = {shown}"
                              + (f" ({(row.get('observed_source') or {}).get('rule')})" if (row.get("observed_source") or {}).get("rule") else ""))
    block = {"inputs": inputs, "formula": formula, "checked": checked, "not_checked": unchecked}
    return {**block, "note": note} if note else block


def results_blocks(results: dict) -> List[dict]:
    """The details block of each metric the engine computed from files, from the stored results: [{"name", "block"}]. Inputs are the file cells or
    rows of the source, the formula is the source's rule with the figure filled in, everything is checked (the files are the input) and nothing is not."""
    out = []
    for key, name, field, unit in (("arr", "ARR", "value", "currency"), ("nrr", "NRR (12-month)", "overall_pct", "%"),
                                   ("gross_churn", "Gross revenue churn", "overall_pct", "%"), ("cac_payback", "CAC payback", None, None)):
        block = results.get(key) or {}
        src = block.get("source") or {}
        value = block.get(field) if field else None
        if not src or value is None:
            continue
        from . import formatting as fmt          # the memo's own number format, so its number check reads the figure as the engine stored it
        shown = fmt.fmt_pct(value) if unit == "%" else fmt.fmt_currency(value, results.get("reporting_currency"))
        where = " · ".join(str(p) for p in (src.get("file"), src.get("sheet"), src.get("rows")) if p)
        out.append({"name": name, "block": {"inputs": [{"label": name, "value": shown, "page": where}],
                                            "formula": f"{src.get('rule') or name} = {shown}", "checked": [f"{name} computed from {where}"],
                                            "not_checked": []}})
    return out


def appendix_lines(rows: List[dict], results: Optional[dict] = None) -> List[str]:
    """Appendix C, "Metric details": the block of every deck figure that has one and of every metric computed from files, in the same layout."""
    blocks = [(f"{r.get('metric') or r.get('claim_type')} · {r.get('period') or 'no period'} · #{r['rank']}"
               + (f" · {TAG}" if r.get("deck_only") else ""), r["details"], r.get("source")) for r in rows if r.get("details")]
    blocks += [(b["name"], b["block"], None) for b in results_blocks(results or {})]
    if not blocks:
        return []
    out = ["Metric details"]
    for title, d, source in blocks:
        out += [f"{title}" + (f" · Source: {source}" if source else ""),
                "Inputs: " + "; ".join(f"{i['label']} {number(i['value']) if isinstance(i['value'], (int, float)) else i['value']}"
                                       + (f" ({i['page']})" if i.get("page") else "") for i in d["inputs"]),
                f"Formula: {d['formula']}",
                "Checked against files: " + ("; ".join(d["checked"]) or "—"),
                "Not checked: " + ("; ".join(d["not_checked"]) or "—"), ""]
    return out


# --- 6. data requests ----------------------------------------------------------------------------------------------------------------------

def data_request(row: dict) -> Optional[str]:
    """What a deck-only metric asks for (section 6): the table behind the page, "revenue by customer and month behind page 12". Cohorts, sales cycle and
    win rate need a customer file or a CRM: a deck never carries row-level data for them, so they name no deck table."""
    table = TABLE_OF.get(row.get("metric") or "")
    page = page_words(row.get("page_ref"))
    return f"{table} behind {page}" if table and page and row.get("deck_status") == TAG else None


def data_requests(rows: Iterable[dict]) -> List[str]:
    """The data requests of the deck-only rows, each once, in register order."""
    out: List[str] = []
    for r in rows:
        ask = r.get("data_request")
        if ask and ask not in out:
            out.append(ask)
    return out


# --- 4. segments on a page ---------------------------------------------------------------------------------------------------------------------

def _pages(c: dict) -> set:
    return {s.get("slide") or s.get("page") for s in c.get("sources") or ()} - {None}


def _live(c: dict) -> bool:
    return c.get("status") != "rejected" and c.get("value") is not None and not c.get("by_period") and c.get("currency") \
        and c.get("value_high") is None and (c.get("value") or 0) > 0 and c.get("origin") not in DECK_ORIGINS_OUT


def _reconciles(parts: Decimal, total: Decimal) -> bool:
    return abs(parts - total) <= SPLIT_TOLERANCE * abs(total)


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def segment_name(c: dict) -> Optional[str]:
    """The name a part is called: the segment the page reader printed, else the label it cites when that names a segment (claim_matching rules)."""
    from . import claim_matching as cm
    return cm.page_segment(c.get("page_segment"), c.get("claim_type")) or (cm.label_segment(c.get("label_from")) if c.get("claim_type") in cm.MONEY_TYPES else None)


def _own_period(c: dict) -> Optional[tuple]:
    return (c.get("period_start"), c.get("period_end")) if c.get("period_start") and c.get("period_end") else None


def _periods_differ(parts: Iterable[dict]) -> bool:
    """Whether parts that each have a period of their own have two different ones: a table of years is separate totals, whatever the arithmetic."""
    return len({p for p in map(_own_period, parts) if p}) > 1


def page_splits(candidates: List[dict]) -> List[dict]:
    """Two or more figures of one page that add up, within the reconciliation tolerance, to a third figure of the same page are segments of it (section 4).
    They take the total's period and metric and sit under it as a split; the disagreement of a part's period or label is settled by the sum, so the flags
    that named it are gone and no card is raised. Each part carries `split_of` (the total's candidate id); the total is not changed. A copy of the list: the
    candidates are not edited in place. Only money amounts of one currency read from a deck are searched, never the analyst's, never a range."""
    out = list(candidates)
    by_page: Dict[tuple, List[int]] = {}
    for i, c in enumerate(out):
        if _live(c):
            for page in _pages(c):
                by_page.setdefault((c.get("deck_id"), c.get("file"), page, c.get("currency")), []).append(i)
    taken: set = set()
    for indexes in by_page.values():
        for t in sorted(indexes, key=lambda i: -out[i]["value"]):
            total = out[t]
            others = [i for i in indexes if i != t and i not in taken and i != t and out[i].get("split_of") is None
                      and not _reconciles(_decimal(out[i]["value"]), _decimal(total["value"]))
                      and _decimal(out[i]["value"]) < _decimal(total["value"])]
            if t in taken or total.get("split_of") or len(others) < 2:
                continue
            best = None
            for size in range(2, min(len(others), SPLIT_SEARCH_MAX) + 1):
                for subset in combinations(others[:SPLIT_SEARCH_MAX], size):
                    if _periods_differ(out[i] for i in subset):
                        continue
                    gap = abs(sum(_decimal(out[i]["value"]) for i in subset) - _decimal(total["value"]))
                    if gap <= SPLIT_TOLERANCE * _decimal(total["value"]) and (best is None or gap < best[0]):
                        best = (gap, subset)
            if best is None:
                continue
            for i in best[1]:
                taken.add(i)
                out[i] = _as_part(out[i], total)
            taken.add(t)
    return out


def _as_part(part: dict, total: dict) -> dict:
    """The part with the total's period and metric, its own segment name, and the flags the sum settled removed."""
    printed = " ".join((part.get("label_from") or "").split())
    name = printed if printed and printed != " ".join((total.get("label_from") or "").split()) else segment_name(part)     # the label it stands under, as printed
    name = name or UNLABELLED
    fields = {k: total.get(k) for k in ("target_date", "period_text", "period_start", "period_end", "period_read_note", "claim_type",
                                         "heading_metric", "basis", "scenario")}
    settled = [f for f in part.get("flags") or () if f in SPLIT_RESOLVES or f == NO_LABEL]
    return {**part, **fields, "split_of": total["id"], "split_segment": name,
            "flags": [f for f in part.get("flags") or () if f not in settled]}
