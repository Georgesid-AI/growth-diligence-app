"""The page pipeline: the model reads every sendable page of a deck, Python checks each claim (docs/design/ai-reads-rules-check.md).

The live path since 2026-10-22 (George; the switch DECK_PIPELINE, read by the gateway, defaults to "ai"): the rules read
(claims.detect_candidates) no longer lists candidates at upload; it stays as the library of Add from deck and of the checker's
converted rules, and as the former path under DECK_PIPELINE=rules for scripts/compare_pipelines.py. The model reads each page
with the `deck_reading` prompt of the store and answers claims in the register's fields plus `basis` (actual, projection,
scenario) and `scenario` (best, realistic, worst, none); the gateway caches a batch per audit by the hash of its page text (a
function of the file), so a deck uploaded again costs nothing.

Order for one deck: consent and the revenue-file gate as today -> the page grids (app/decks/pages.py) -> the pages that may go
(a figure as digits, not a dropped page; decision 1b) in batches of PAGES_PER_CALL -> each batch as printed, with no redaction
(page-image.md section 2), its lines over 200 characters left out (as for a structure cell; George, 2026-10-22, decision 1b on the
review of PR #159) and written by the one builder (redact.page_text), with one PNG of each whole page (decks/render.py) ->
gateway.read_structure with the type page_claims (consent, boundary and page-reader model checked again, cache, token caps, lock,
spend caps, prompt caching) -> a
batch too large for the cap, or whose reply was cut at the output limit, is split, a single page too large or cut is skipped
-> checker.check per page (page_check at cell level, then the flags) -> one approval row per claim,
"Matched to page" or "AI suggestion, not matched", with its `flags` (a flagged row is listed in the review tab, never deleted or
retyped), deduplicated against the rows already listed as today. What is stored (rule 17): the model's claims (closed words,
numbers and cell ids), the checked items without any text, the batch's metadata; never the text sent.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from ..decks import CANDIDATES_COLLECTION, TEXT_COLLECTION, claims
from ..decks import pages as page_grids_mod
from ..decks import render
from ..llm import gateway, guards
from ..llm.schemas import PAGE_CLAIMS
from . import association
from . import checker, completeness, page_check, redact

logger = logging.getLogger("growth.structures")

PIPELINES = gateway.PIPELINES
deck_pipeline = gateway.deck_pipeline          # the switch is read by the gateway, which refuses a page call under "rules"
PAGES_PER_CALL = redact.PAGES_PER_CALL
PARALLEL_PAGES = 8                             # pages read at a time (George, 2026-10-23, deck page reads: speed)
PARALLEL_AFTER_RATE_LIMIT = 4                  # ... for the rest of the deck after the provider answers 429
RETRY_STATUSES = ("not_read", "blocked")       # a later Run audit reads these pages again (not "stopped": the token cap refuses them again)
PAGE_TIMEOUT_SECONDS = 60.0                    # one page: the call, its retries and its checks; then "page n not read"
LINE_MAX = gateway.STRUCTURE_CELL_MAX          # a longer line is left out, as a structure cell is (decision 1b, review of PR #159)
_UNITS = {"%", "x", "days", "months", "years"}


def sendable_pages(grids: List[Dict]) -> List[Dict]:
    """[{"grid", "cells"}] for the pages that may go: every page whose text layer holds at least one digit (George, 2026-10-31). The lines over
    LINE_MAX characters are left out, so a page whose only digit sat in such a line has none and stays on the server."""
    out = []
    for grid in page_grids_mod.sendable(grids):
        kept = [c for c in grid["cells"] if len(c["text"]) <= LINE_MAX]
        if any(redact.has_digit(c["text"]) for c in kept):
            out.append({"grid": grid, "cells": kept})
    return out


async def audit_token_cap(db, audit_id: str) -> int:
    """The audit's structure token cap (guards.structure_token_cap): the pages with figures of every deck of the audit, from their completeness records,
    and the reads per page. The one place that reads the decks' documents for it; the gateway is handed the number."""
    rows = await db[TEXT_COLLECTION].find({"audit_id": audit_id}, {"_id": 0, "claims_record": 1}).to_list(1000)
    pages = sum(len((r.get("claims_record") or {}).get("expected") or ()) for r in rows)
    return guards.structure_token_cap(pages, 2 if completeness.second_read_required() else 1)


def second_read_enabled() -> bool:
    """Whether each page is read twice (the consistency read, docs/design/reading-consistency.md). On by default; PAGE_SECOND_READ=0 turns the
    second read off for a deployment that must hold the page-read cost down. The tests of the single read switch it off (tests/conftest.py)."""
    return completeness.second_read_required()


def batches(grids: List[Dict], per_call: int = PAGES_PER_CALL) -> List[List[Dict]]:
    """The sendable pages in consecutive groups of at most per_call pages."""
    pages = sendable_pages(grids)
    return [pages[i:i + per_call] for i in range(0, len(pages), per_call)]


def batch_text(batch: List[Dict]) -> str:
    """The text the model reads for a batch of pages, written by redact.page_text. The one builder of page text; nothing
    else of a deck reaches the gateway."""
    return redact.page_text([(page_grids_mod.page_number(p["grid"]), p["cells"]) for p in batch])


def skipped_pages(grids: List[Dict], page_count: Optional[int] = None) -> List[int]:
    """The pages of a deck that no call is made for: those with no digit in their text, decided before any call, so the panel can name them."""
    going = {page_grids_mod.page_number(p["grid"]) for p in sendable_pages(grids)}
    numbers = {page_grids_mod.page_number(g) for g in grids}
    return sorted((set(range(1, page_count + 1)) if page_count else numbers) - going)


async def read_pages(db, audit_id: str, deck_id: str, grids: List[Dict], image_for=None,
                     adapter=None, sleep=None, use_cache: bool = True, per_call: int = PAGES_PER_CALL, skip=(), parallel: int = 1,
                     page_timeout: float = PAGE_TIMEOUT_SECONDS, progress=None, seconds: Optional[Dict] = None, on_page=None,
                     token_cap: Optional[int] = None) -> List[Tuple[List[Dict], object]]:
    """[(grids of the call, StructureRead)] in page order, for every page of a deck that may go, `per_call` pages to a call and up to
    `parallel` calls at a time. The audit's deck read (process_deck_pages) asks for one page per call (the unit of the panel's "page n
    not read" and of a retry) and PARALLEL_PAGES at a time; the scripts keep the former five pages, one call after another. The first 429 the provider answers lowers it to
    PARALLEL_AFTER_RATE_LIMIT for the rest of the deck. A page that does not answer in `page_timeout` seconds, or errors, is
    "not_read" with the reason "timeout" or the gateway's; the deck keeps going. Pages in `skip` (read in an earlier run) are not
    asked again. A call the token cap refuses as too large, or whose reply the provider cut at the output limit ("truncated"), is
    split in two when it holds more than one page; a single page too large or cut is kept with its status. After the audit's token
    cap stops reading, the calls not yet started are marked stopped without a call. `use_cache=False` (a consistency pass) asks the
    model again for pages this audit already read. `progress(done, total)` is awaited after each call. `image_for(page)` is an async
    function giving the PNG of a page, or None when the file cannot be drawn (LibreOffice absent, page count differs, no stored file):
    that page then goes as text alone, as before, and is never "not read" for that reason. `seconds`, when given, is filled with the
    consistency read of each page that was read ({tuple(page numbers): StructureRead}): the same page, text and image, read a second time
    (docs/design/reading-consistency.md); a page whose second read failed or timed out has none, and its first read stands unflagged.
    `on_page(grids, result, again)` is awaited as soon as a call is finished, with its second read (or None): what a page gave is stored page by
    page, so a batch that stops leaves the pages already read stored (results stage ordering, 2026-11-05)."""
    queue = [b for b in batches(grids, per_call)
             if not all(page_grids_mod.page_number(p["grid"]) in set(skip) for p in b)]
    total = len(queue)
    results: Dict[int, Tuple[List[Dict], object]] = {}
    state = {"limit": max(1, parallel), "stopped": None, "done": 0, "next": 0}

    def lower():
        state["limit"] = min(state["limit"], PARALLEL_AFTER_RATE_LIMIT)

    async def read_one(batch, numbers, second=False):
        images = [await image_for(n) for n in numbers] if image_for else None
        if images is not None and any(i is None for i in images):
            images = None
        return await gateway.read_structure(
            db, audit_id, batch_text(batch), PAGE_CLAIMS, deck_id=deck_id, pages=numbers, adapter=adapter, sleep=sleep,
            use_cache=use_cache, on_rate_limit=lower, images=images, second_read=second, token_cap=token_cap)

    async def finished(grids_of, result, again=None, capped=False):
        if on_page:
            await on_page(grids_of, result, again, capped)
        return [(grids_of, result)]

    async def one(batch):
        grids_of = [p["grid"] for p in batch]
        numbers = [page_grids_mod.page_number(g) for g in grids_of]
        if state["stopped"] is not None:
            return await finished(grids_of, gateway._structure_result("stopped", PAGE_CLAIMS, state["stopped"]))
        try:
            result = await asyncio.wait_for(read_one(batch, numbers), page_timeout)
        except asyncio.TimeoutError:
            logger.warning("page not read: run_id=%s deck_id=%s pages=%s reason=timeout", audit_id, deck_id, numbers)
            return await finished(grids_of, gateway._structure_result("not_read", PAGE_CLAIMS, "timeout"))
        if result.status in ("too_large", "truncated") and len(batch) > 1:
            half = len(batch) // 2
            return [r for part in (batch[:half], batch[half:]) for r in await one(part)]
        if result.status == "stopped":
            state["stopped"] = result.reason
        again, capped = None, False
        if seconds is not None and result.status == "read":
            try:
                again = await asyncio.wait_for(read_one(batch, numbers, second=True), page_timeout)
            except Exception as exc:        # a timeout or an error: the first read stands, the page is compared with nothing
                logger.warning("page second read not completed: run_id=%s deck_id=%s pages=%s reason=%s", audit_id, deck_id, numbers, type(exc).__name__)
            else:
                if again.status == "read":
                    seconds[tuple(numbers)] = again
                else:
                    if again.status == "stopped":
                        state["stopped"], capped = again.reason, True       # the cap refused the second read: the page is marked cap
                    again = None
        return await finished(grids_of, result, again, capped)

    async def worker(index):
        # A worker above the current limit retires after its page; the first 429 lowers the limit mid-deck.
        while index < state["limit"] and state["next"] < total:
            position = state["next"]
            state["next"] += 1
            results[position] = await one(queue[position])
            state["done"] += 1
            if progress:
                await progress(state["done"], total)

    if progress:
        await progress(0, total)
    await asyncio.gather(*(worker(i) for i in range(state["limit"])))
    return [r for position in sorted(results) for r in results[position]]


def row_from_claim(item: Dict, grid: Dict, deck: Dict, fiscal_year_end: int) -> Dict:
    """One approval-list row for a checked page claim, citing its cell on its page. The snippet is the cell's own text; the period
    keeps the text of its period cells; "Label from" is label_text when the model read one, else the label cell's text when it is adjacent and not the cell itself."""
    from . import _reading, _target_date, _where         # the orchestrator's helpers, shared with the structure read
    by_id = {redact.cell_id(c): c for c in grid["cells"]}
    cell = by_id[item["value_cell"]]
    period_cells = [by_id[c]["text"] for c in item.get("period_cells") or () if c in by_id]
    label = item.get("label_text") or (by_id[item["label_cell"]]["text"] if item.get("label_cell") in by_id else None)     # label_cell only locates label_text
    layout = association.Layout(grid)
    if not label or layout.is_heading(label):       # a heading names the page, not a segment: the nearest legend item or rotated chart label does (deck-actuals.md section 4)
        label = layout.nearest_label(cell) or label
    unit = item.get("unit_other") if item.get("unit") == "other" else item.get("unit")
    target, stated = _target_date(item.get("period")), (" ".join(period_cells) or item.get("period"))
    source = {"file": deck["file"], **_where(grid), "kind": "page", "cell": item["value_cell"]}
    if cell.get("table") is not None:
        source.update(table=cell["table"], row=cell.get("trow"), col=cell.get("tcol"))
    shim = {**_where(grid), "table": cell.get("table")}
    place = {**cell, "row": cell.get("trow", cell["row"]), "col": cell.get("tcol", cell["col"])} if cell.get("table") is not None else cell
    candidate = {
        "claim_type": claims.PAGE_CLAIM_TYPE.get(item["metric"], item["metric"]), "value": item.get("value"), "value_high": item.get("value_high"),
        # The model's basis is kept as a note and sets no figure type: Python reads it from the period (George, 2026-10-23, M2).
        "figure_type": None, "figure_type_set_by": None,
        "unit": unit if unit in _UNITS else None, "currency": unit if unit and len(unit) == 3 and unit.isupper() else None,
        "target_date": target, "period_text": stated if target else None,
        "snippet": (cell.get("text") or "")[:claims.SNIPPET_MAX], "label_from": label if label and label != cell.get("text") else None,
        "date_from": stated if target and stated != cell.get("text") else None, "sources": [source],
        "inconsistent_dates": [], "origin": "ai", "cell": item["value_cell"], "position": item.get("position"),
        "readings": item["values"] if len(item.get("values") or ()) > 1 else [],
        "type_from": "heading" if label and label != cell.get("text") else "line" if claims._keywords(cell.get("text") or "") else None,
        "reading": _reading(deck.get("blocks") or (), shim, place),
        "ai_status": item["status"], "ai_label": page_check.label(item["status"]), "ai_checks": item.get("checks"),
        "period_cells": list(item.get("period_cells") or []), "basis": item.get("basis"), "scenario": item.get("scenario") or checker.NO_SCENARIO,
        "flags": list(item.get("flags") or []), "proposed_flags": [],
        "page_segment": item.get("segment"), "page_share_of": item.get("share_of"),      # as printed, shown on the row (page-image.md section 4)
        "heading_metric": layout.heading_metric(cell),      # the one metric word of the title over the figure; a closed word, no text
    }
    claims.recurring_year_end(candidate)             # "MRR in 2021" is Dec 2021 (issue #151)
    found = claims.period_range(candidate["target_date"], fiscal_year_end) if candidate.get("period_read_note") else \
        claims.period_range(item.get("period"), fiscal_year_end) if item.get("period") else None
    candidate["period_start"], candidate["period_end"] = found or (None, None)
    if candidate["claim_type"] == "customers":
        qualifier = claims.qualifier_of(label or "") or claims.qualifier_of(cell.get("text") or "")
        if qualifier:
            candidate.update(claim_type="users", qualifier=qualifier)
    return candidate


def corrected_row(item: Dict, grid: Dict, deck: Dict, fiscal_year_end: int, page: int):
    """(row, log): the approval-list row of a checked claim with the corrections its checks name (George, 2026-10-26). A correction with
    one candidate is applied before the register: the row carries `corrections` [{field, reason, original, corrected, state "applied",
    undo}] and the flag that named it is gone. With several candidates the flag stays and the entry is {state "choose", options
    [{value, set}]}, one button each; `set` and `undo` are the row fields the choice or the undo writes. `log` is the Diagnostics lines
    ({page, kind "corrected", field, reason, original, corrected}; a period the model set that a cited source reads otherwise, kept with
    SOURCES_DISAGREE (page_check._kept): {page, kind "sources disagree", field, original, read: [{period, cells, marker}]}, the periods the
    page reads by token and cell id); a label is logged by cell id, never by its text (rule 17)."""
    from . import corrections
    base, entries, log = dict(item), [], []
    flags = list(item.get("flags") or [])
    for plan in item.get("corrections") or ():
        field, options = plan["field"], plan["options"]
        undo = corrections.row_fields(field, row_from_claim(corrections.restore_original(base, plan), grid, deck, fiscal_year_end))
        entry = {"field": field, "reason": plan["flag"], "original": plan["original_text"], "undo": undo}
        if len(options) == 1 and field != "segment":
            base = corrections.apply_option(base, field, options[0])
            flags = [f for f in flags if f != plan["flag"]]
            entries.append({**entry, "state": "applied", "corrected": options[0]["value"], **_period_source(field, options[0])})
            # A period is logged as its token with the cells it was read from and its marker, never the heading's prose (section 4 of the design).
            log.append({"page": page, "kind": "corrected", "field": field, "reason": plan["flag"], "original": plan["original"],
                        "corrected": options[0]["ref"], **_period_source(field, options[0])})
        else:
            entries.append({**entry, "state": "choose", "options": [
                {"value": o["value"], **_period_source(field, o), **({"segment": o["segment"]} if field == "segment" else {}),
                 "set": corrections.row_fields(field, row_from_claim(corrections.apply_option(base, field, o), grid, deck, fiscal_year_end))}
                for o in options]})
            if field == "period" and plan["flag"] == checker.SOURCES_DISAGREE and plan["original"] is not None:
                # A period the model set that a cited source reads otherwise is kept (page-image.md section 5, review of PR #193): nothing is
                # applied, and one line says so, with the periods the page reads by token and cell id.
                log.append({"page": page, "kind": checker.SOURCES_DISAGREE, "field": field, "original": plan["original"],
                            "read": [{"period": o["ref"], **_period_source(field, o)} for o in options if o["ref"] != plan["original"]]})
    row = row_from_claim({**base, "flags": flags}, grid, deck, fiscal_year_end)
    if entries:
        row["corrections"] = entries
    return row, log


def _period_source(field: str, option: Dict) -> Dict:
    """The cells a period option was read from and its actual/forecast marker, kept beside the token (none for a label)."""
    return {"cells": list(option.get("period_cells") or []), "marker": option.get("marker")} if field == "period" else {}


def row_out_of_range(claim: Dict, page: int, deck: Dict) -> Dict:
    """The approval-list row of a claim on a page the document does not have (checker.PAGE_OUT_OF_RANGE): the model's values, no
    cell, no snippet, never matched; listed in the review tab."""
    unit = claim.get("unit_other") if claim.get("unit") == "other" else claim.get("unit")
    key = "slide" if deck.get("page_unit") == "slide" else "page"
    return {
        "claim_type": claims.PAGE_CLAIM_TYPE.get(claim["metric"], claim["metric"]), "value": claim.get("value"), "value_high": claim.get("value_high"),
        "figure_type": None, "figure_type_set_by": None,
        "unit": unit if unit in _UNITS else None, "currency": unit if unit and len(unit) == 3 and unit.isupper() else None,
        "target_date": _target_date_of(claim.get("period")), "period_text": claim.get("period"), "snippet": "", "label_from": None,
        "date_from": None, "sources": [{"file": deck["file"], key: page, "kind": "page", "cell": None}], "inconsistent_dates": [],
        "origin": "ai", "cell": None, "position": None, "readings": [], "type_from": None, "reading": None,
        "ai_status": page_check.UNMATCHED, "ai_label": page_check.UNMATCHED_LABEL, "ai_checks": None, "period_cells": [],
        "basis": claim.get("basis"), "scenario": claim.get("scenario") or checker.NO_SCENARIO, "flags": [checker.PAGE_OUT_OF_RANGE],
        "proposed_flags": [], "period_start": None, "period_end": None,
    }


def _target_date_of(period: Optional[str]) -> Optional[str]:
    from . import _target_date
    return _target_date(period)


def stored_items(checked: List[Dict]) -> Dict:
    """The checked claims as llm_structures keeps them (rule 17): cell ids, values, periods, statuses and checks. No text."""
    return {"claims": [_without_text(c) for c in checked]}


def _without_text(item: Dict) -> Dict:
    """A checked claim as it is stored: the corrections keep their cell ids and period labels, never the text of a label cell (rule 17); a
    period option keeps its token, the cells it was read from and its marker (section 4 of docs/design/claim-review-simplified-design.md)."""
    out = dict(item)
    for key in ("label_text", "segment", "share_of"):       # printed text of the page: on the approval-list row, never in the stored read
        out.pop(key, None)
    if out.get("corrections"):
        out["corrections"] = [{"flag": p["flag"], "field": p["field"], "original": p["original"],
                               "options": [o["ref"] for o in p["options"]],
                               **({"sources": [{"cells": list(o.get("period_cells") or []), "marker": o.get("marker")} for o in p["options"]]}
                                  if p["field"] == "period" else {})}
                              for p in out["corrections"]]
    return out


class RunState:
    """What one deck's checked replies share while its rows are written: the rows already stored for the file, the cells they list, the next
    place in the list, the ids written in this run and the Diagnostics lines (a page checked again replaces its lines)."""

    def __init__(self, reviewed: List[Dict], diagnostics: List[Dict]):
        from . import _python_cells
        self.reviewed, self.known, self.order = reviewed, _python_cells(reviewed), len(reviewed)
        self.diagnostics, self.fresh = diagnostics, set()


UNCERTAIN_KEY = "_uncertain"        # on a claim dict between merge_reads and apply_reply only; never stored


def _read_key(claim: Dict) -> Tuple:
    """What two reads must agree on for a figure to stand: the page, the metric, the period and the value."""
    value = claim.get("value")
    return (page_check.split_cell_id(claim.get("value_cell"))[0], claim.get("metric"), claim.get("period"), None if value is None else round(float(value), 6))


def _reading_option(claim: Dict, year_end: int) -> Dict:
    """One candidate of an uncertain figure as a button of the card: the words (metric, value, period) and the row fields choosing it sets."""
    from . import _target_date
    from .. import formatting as fmt
    period = claim.get("period")
    target = _target_date(period)
    found = claims.period_range(period, year_end) if period else None
    text = " · ".join(str(x) for x in (claim.get("metric"), None if claim.get("value") is None else fmt.fmt_number(claim["value"]), period) if x)
    fields = {"metric": claim.get("metric"), "value": None if claim.get("value") is None else fmt.fmt_number(claim["value"]), "period": period}
    return {"value": text, "ref": text, "fields": fields, "set": {"claim_type": claims.PAGE_CLAIM_TYPE.get(claim["metric"], claim["metric"]), "value": claim.get("value"),
                                                "value_high": claim.get("value_high"), "target_date": target, "period_text": period if target else None,
                                                "period_start": (found or (None, None))[0], "period_end": (found or (None, None))[1]}}


def _same_figure(a: Dict, b: Dict) -> bool:
    """Two reads agree on a figure when page, metric and value are equal and the period is equal or given by one read only (second pass, A2)."""
    ka, kb = _read_key(a), _read_key(b)
    return ka[:2] == kb[:2] and ka[3] == kb[3] and (ka[2] == kb[2] or ka[2] is None or kb[2] is None)


def merge_reads(first: List[Dict], second: Optional[List[Dict]], year_end: int = 12) -> List[Dict]:
    """The claims of a page read twice. A claim both reads give with the same metric and value, and the same period (or the period on one read only,
    which then stands: second pass, A2), stands as it is. Any other claim, one that only one read gives or that the other read gives with another
    metric, period or value, is kept (the first read's, else the second's) with `_uncertain`: the readings of the two reads that are present, as
    options. A claim of the second read that pairs with a first-read claim on the same cell is the other candidate of that one claim; the rest are
    claims of their own. A claim of the metric "other" is never marked (A3): the first read's stands, a second-read-only one is dropped. Without
    a second read nothing is marked."""
    if second is None:
        return list(first)
    pool, out, differing = list(second), [], []
    for claim in first:
        match = next((c for c in pool if _same_figure(c, claim)), None)
        if match is not None:
            pool.remove(match)
            out.append(claim if claim.get("period") or not match.get("period") else {**claim, "period": match["period"]})
        elif claim.get("metric") == "other":
            other = next((c for c in pool if c.get("value_cell") == claim.get("value_cell")), None)
            if other is not None:
                pool.remove(other)
            out.append(claim)
        else:
            differing.append(claim)
    for claim in differing:
        other = next((c for c in pool if c.get("value_cell") == claim.get("value_cell")), None)
        if other is not None:
            pool.remove(other)
            if other.get("metric") == "other":
                out.append(claim)               # the other read called it "other": no disagreement is raised on it
                continue
        out.append({**claim, UNCERTAIN_KEY: [_reading_option(c, year_end) for c in (claim, other) if c is not None]})
    out += [{**c, UNCERTAIN_KEY: [_reading_option(c, year_end)]} for c in pool if c.get("metric") != "other"]
    return out


def mark_uncertain(row: Dict, options: List[Dict]) -> Dict:
    """The row with the review flag READING_UNCERTAIN and a correction that waits: one button per reading. Choosing sets the row to that reading and
    removes the flag (server: answer_correction); nothing is chosen for the analyst. Undo brings the card back with the first reading's values."""
    entry = {"field": "reading", "reason": checker.READING_UNCERTAIN, "original": None, "undo": dict(options[0]["set"]), "state": "choose", "options": options}
    return {**row, "flags": list(row.get("flags") or []) + [checker.READING_UNCERTAIN], "corrections": list(row.get("corrections") or []) + [entry]}


async def apply_reply(db, audit_id: str, deck_id: str, deck: Dict, run: RunState, by_page: Dict, year_end: int, page_count: Optional[int],
                      key: str, numbers: List[int], reply_claims: List[Dict], second_claims: Optional[List[Dict]] = None) -> Dict:
    """Check the model's claims of one stored or new page reply against the pages' grids (Python only: no model call), write the rows and
    store the checked items with the normaliser version. Returns the counts of the checks (matched, unmatched, dropped, periods_corrected,
    flagged). The one path of a page read and of the checking again of a reply stored under an older normaliser (renormalise_audit).
    `second_claims` is the consistency read of the same pages: a figure the two reads do not both give with the same metric, period and value
    is stored with the review flag READING_UNCERTAIN and both readings as buttons (merge_reads)."""
    from ..claim_matching import entered_by_python
    from . import _cell_key, _python_cells, analyst_copy, rules_copy, store_candidate, value_match
    claims_of = page_check.by_page(merge_reads(reply_claims, second_claims, year_end))
    checked_all, counts = [], {"matched": 0, "unmatched": 0, "dropped": 0, "periods_corrected": 0, "flagged": 0}
    # A claim on a page the document does not have (the gateway checks every cited cell against the text sent, so this is a
    # guard, not an expected path): one row with the model's values, flagged, never matched (checker rule 4).
    rows = [(row_out_of_range(c, page, deck), page) for page, listed in claims_of.items() if page not in numbers
            and checker.out_of_range(page, page_count) for c in listed]
    diagnostics_new = []
    for page in numbers:
        grid = by_page[page]
        here = claims_of.get(page, [])
        checked = checker.check(grid, here, year_end, checker.page_blocks(deck.get("blocks") or [], grid), deck["file"])
        for k in counts:
            counts[k] += checked[k]
        cells = {page_check._id(c) for c in grid["cells"]}
        marks = [c.get(UNCERTAIN_KEY) for c in here if c["value_cell"] in cells]         # checker.check keeps the claims on this page's cells, in order
        checked_all += [{k: v for k, v in c.items() if k != UNCERTAIN_KEY} | {"page": page} for c in checked["items"]]
        for number, item in enumerate(checked["items"]):
            if item["drop"]:            # a derived figure, a launch date with no product, a quoted figure: no row, one Diagnostics line (George, 2026-10-26)
                counts["dropped"] += 1
                diagnostics_new.append({"page": page, "kind": item["drop"], "metric": item["metric"], "value": item.get("value"),
                                        "period": item.get("period")})
                continue
            row, log = corrected_row(item, grid, deck, year_end, page)
            if number < len(marks) and marks[number]:
                row = mark_uncertain(row, marks[number])
            rows.append((row, page))
            diagnostics_new += log
    counts["flagged"] += sum(1 for row, _ in rows if checker.review_flags(row["flags"]) and row["cell"] is None)
    run.diagnostics = [d for d in run.diagnostics if d["page"] not in numbers] + diagnostics_new
    # A page read again (Run audit, a new upload of the file): the rows an earlier run stored for this reply that nobody has touched
    # (pending, origin "ai") are replaced by the rows checked now, so a row stored before a check existed does not outlive it
    # (live bug, 2026-10-23: rows kept "unmatched" with no flags). A row the analyst approved, edited or rejected stays.
    # Untouched means pending, or entered by Python on its own with no analyst action (claim_matching.entered_by_python: "auto", no
    # edit, no Keep or reject); both are replaced. A row the analyst approved, edited or rejected keeps its values (PR 183).
    stale = [c for c in run.reviewed if c.get("origin") == "ai" and (c.get("status") == "pending" or entered_by_python(c))
             and c.get("structure_key") == key and c["id"] not in run.fresh]
    stale_orders = sorted(c.get("order", 0) for c in stale)
    for c in stale:
        await db[CANDIDATES_COLLECTION].delete_one({"audit_id": audit_id, "id": c["id"]})
        run.reviewed.remove(c)
    if stale:
        run.known = _python_cells(run.reviewed)
    # A cell whose reading the analyst chose (a "reading" correction applied, docs/design/reading-consistency.md): the chosen row stands,
    # whichever reading it took, and this reply's read of the cell is not listed again beside it (a Re-read, a Run audit, a new upload).
    chosen = {_cell_key(c) for c in run.reviewed if c.get("structure_key") == key
              and any(e.get("field") == "reading" and e.get("state") == "applied" for e in c.get("corrections") or [])}
    for candidate, page in rows:
        if candidate["cell"] is not None and _cell_key(candidate) in chosen:
            continue
        if candidate["cell"] is not None and \
                value_match(candidate["value"], candidate["value_high"], run.known.get(_cell_key(candidate), ())):
            continue                    # this cell already lists the value, or a range holding it
        twin = next((c for c in run.reviewed if claims.same_claim(c, candidate)), None)
        if twin is not None:
            if candidate["sources"][0] not in twin["sources"]:
                twin["sources"] = list(twin["sources"]) + candidate["sources"]
                await db[CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": twin["id"]},
                                                           {"$set": {"sources": twin["sources"]}})
            # A flagged read folded into a row still to review keeps its flags there (review of PR 164, L3).
            carried = [f for f in candidate["flags"] if f not in (twin.get("flags") or [])]
            if carried and twin.get("status") == "pending":
                twin["flags"] = list(twin.get("flags") or []) + carried
                await db[CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": twin["id"]}, {"$set": {"flags": twin["flags"]}})
            continue
        duplicate = rules_copy(run.reviewed, candidate)
        if duplicate is None and analyst_copy(run.reviewed, candidate) is not None:
            # The analyst already added this figure (M5): the claim is never replaced; the model's read is listed beside it, flagged.
            candidate = {**candidate, "flags": candidate["flags"] + [checker.MATCHES_ANALYST]}
        if duplicate is not None:
            candidate = {**candidate, "sources": candidate["sources"] + [s for s in duplicate["sources"] if s not in candidate["sources"]]}
            await db[CANDIDATES_COLLECTION].delete_one({"audit_id": audit_id, "id": duplicate["id"]})
            run.reviewed.remove(duplicate)
            row_order = duplicate.get("order", run.order + 1)
        elif stale_orders:
            row_order = stale_orders.pop(0)         # the replaced row's place in the list
        else:
            run.order = row_order = run.order + 1
        row = {**candidate, "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"],
               "id": str(uuid.uuid4()), "order": row_order, "status": "pending", "structure_key": key,
               "normaliser_version": checker.NORMALISER_VERSION}
        await store_candidate(db, row)
        run.reviewed.append(row)
        run.fresh.add(row["id"])
    await gateway.record_verification(db, audit_id, key, [c["status"] for c in checked_all], counts["dropped"],
                                      counts["periods_corrected"], stored_items(checked_all), normaliser_version=checker.NORMALISER_VERSION)
    return counts


def _from_page_reply(row: Dict) -> bool:
    """True for a row a page reply wrote (apply_reply: origin "ai", first source of kind "page"). A row of the structure read, the rules read or
    Add from deck has a structure key or none and no page reply behind it: it is never a reply "lost" (review of PR 225)."""
    return row.get("origin") == "ai" and ((row.get("sources") or [{}])[0] or {}).get("kind") == "page"


async def stale_replies(db, audit_id: str) -> Tuple[List[Dict], Set[str]]:
    """Read only: (the stored page replies an older normaliser checked, the decks holding rows of a page reply that is no longer stored). A deck
    being read (`ai_status` "reading") is left out of both: a reply the gateway has stored and its run has not yet checked reads as version 0,
    and that run checks it itself (review of PR 225: a poll of the deck list landing in a read wrote every row of such a reply twice)."""
    reading = {d.get("deck_id") for d in await db[TEXT_COLLECTION].find({"audit_id": audit_id, "ai_status": "reading"}, {"_id": 0, "deck_id": 1}).to_list(1000)}
    replies = await db[gateway.STRUCTURES_COLLECTION].find({"audit_id": audit_id, "type": PAGE_CLAIMS}, {"_id": 0}).to_list(100000)
    rows = await db[CANDIDATES_COLLECTION].find({"audit_id": audit_id, "origin": "ai"}, {"_id": 0, "structure_key": 1, "deck_id": 1, "normaliser_version": 1,
                                                                                         "origin": 1, "sources": 1}).to_list(100000)
    current = checker.NORMALISER_VERSION
    stale = [r for r in replies if (r.get("normaliser_version") or 0) < current and (r.get("output") or {}).get("claims") is not None
             and r.get("deck_id") not in reading]
    stored = {r.get("key") for r in replies}
    lost = {r.get("deck_id") for r in rows if _from_page_reply(r) and r.get("structure_key") and r["structure_key"] not in stored
            and (r.get("normaliser_version") or 0) < current and r.get("deck_id") and r["deck_id"] not in reading}
    return stale, lost


async def decks_to_reread(db, audit_id: str) -> Set[str]:
    """Read only, for opening the audit (the deck list): the ids of the decks that hold a stored page reply checked under an older normaliser,
    or rows of a page reply that is no longer stored. The panel says "Re-read needed" for them. Writes and deletes nothing (George, 2026-11-03,
    review of PR 225): Run audit checks the replies again (renormalise_audit)."""
    stale, lost = await stale_replies(db, audit_id)
    return {r["deck_id"] for r in stale if r.get("deck_id")} | lost


async def renormalise_audit(db, audit_id: str) -> Dict:
    """Run audit's check again of every stored page reply an older normaliser checked (George, 2026-11-02, moved from opening the audit on
    2026-11-03): the claims of the stored reply (the model's JSON output, never the page text) go through the same Python check against the
    deck's stored pages (apply_reply), with no model call and no change to the prompt version; the rows nobody has touched are replaced as on a
    new run, and the reply is stamped with the current normaliser version. A row whose reply is not stored cannot be checked again: its deck stays
    "Re-read needed" until its pages are read again. A deck whose check fails is left as it was and the others go on. Returns {"renormalised":
    replies checked again, "re_read_needed": decks with a reply gone}. Cheap when nothing is stale: three reads."""
    stale, lost = await stale_replies(db, audit_id)
    done = 0
    for deck_id in sorted({r["deck_id"] for r in stale if r.get("deck_id")}):
        try:
            done += await _check_deck_again(db, audit_id, deck_id, [r for r in stale if r.get("deck_id") == deck_id])
        except Exception as exc:        # the log names the error type only (rule 17: an exception message can quote a cell)
            logger.error("normaliser: check again failed: run_id=%s deck_id=%s error=%s", audit_id, deck_id, type(exc).__name__)
    if done or lost:
        logger.info("normaliser: run_id=%s replies checked again=%d decks to read again=%d", audit_id, done, len(lost))
    return {"renormalised": done, "re_read_needed": len(lost)}


async def _check_deck_again(db, audit_id: str, deck_id: str, replies: List[Dict]) -> int:
    deck = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id},
                                              {"_id": 0, "file": 1, "pages": 1, "blocks": 1, "layout": 1, "diagnostics": 1})
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0, "fiscal_year_end": 1})
    if not deck:
        return 0
    grids = page_grids_mod.page_grids(deck.get("blocks") or [], deck.get("layout"))
    by_page = {page_grids_mod.page_number(g): g for g in grids}
    page_count = deck.get("pages") or (max(by_page) if by_page else None)
    reviewed = await db[CANDIDATES_COLLECTION].find({"audit_id": audit_id, "file": deck["file"]}, {"_id": 0}).to_list(100000)
    run = RunState(reviewed, list(deck.get("diagnostics") or []))
    done = 0
    for reply in replies:
        numbers = [int(n) for n in reply.get("pages") or ([reply["page"]] if reply.get("page") else [])]
        again = await db[gateway.STRUCTURES_COLLECTION].find_one({"audit_id": audit_id, "key": reply["second_key"]}, {"_id": 0, "output": 1}) \
            if reply.get("second_key") else None
        await apply_reply(db, audit_id, deck_id, deck, run, by_page, int((audit or {}).get("fiscal_year_end") or 12), page_count,
                          reply["key"], numbers, reply["output"]["claims"], (again or {}).get("output", {}).get("claims"))
        done += 1
    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {"diagnostics": run.diagnostics}})
    return done


async def process_deck_pages(db, audit_id: str, deck_id: str, adapter=None, sleep=None) -> str:
    """Read one deck page by page with the model and check every claim against its page; returns the deck's AI status (the
    words of process_deck). Unticked consent: no call. A deck never waits for a file (read-check-review.md section 12)."""
    from . import (CANDIDATES_COLLECTION as _c, BLOCKED, NOT_READ, PYTHON_ONLY, READ, STOPPED, _cell_key,  # noqa: F401
                   CONSENT_OFF_LINE, PROMPT_MISSING, _deck_status, _python_cells, analyst_copy, rules_copy, store_candidate, value_match)
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0, "id": 1, "company_name": 1, "fiscal_year_end": 1,
                                                       "structure_reading_consent": 1})
    deck = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id},
                                              {"_id": 0, "file": 1, "format": 1, "page_unit": 1, "pages": 1, "blocks": 1, "layout": 1, "page_reads": 1, "retry_pages": 1, "claims_record": 1, "page_overrides": 1,
                                               "diagnostics": 1})
    if not audit or not deck:
        return NOT_READ
    if audit.get("structure_reading_consent") is not True:
        return await _deck_status(db, audit_id, deck_id, PYTHON_ONLY, CONSENT_OFF_LINE)
    year_end = int(audit.get("fiscal_year_end") or 12)
    grids = page_grids_mod.page_grids(deck.get("blocks") or [], deck.get("layout"))
    by_page = {page_grids_mod.page_number(g): g for g in grids}
    page_count = deck.get("pages") or (max(by_page) if by_page else None)
    reviewed = await db[CANDIDATES_COLLECTION].find({"audit_id": audit_id, "file": deck["file"]}, {"_id": 0}).to_list(100000)
    reads, sent, stopped_message = [], [], None
    shown = {}          # the provider's logged message of a failed page read, by its pages: logged, never stored
    # Diagnostics lines of the pages read so far; a page read again replaces its lines. `fresh`: the ids of the rows this run wrote, so a later
    # page with the same text never replaces them.
    run = RunState(reviewed, list(deck.get("diagnostics") or []))
    # A run that follows one that left pages to retry asks only for those pages; any other run reads the whole deck (the cache serves
    # the pages already read).
    # A page whose second read is not stored is read again with the rest (its first read is cached): "done" needs the second read of every page
    # read when the second read is on (results stage ordering, 2026-11-05).
    # A run cut before its last write leaves no retry list but a record with pages missing: the retry resumes from the record too (review of #240).
    second_on = second_read_enabled()
    resume = deck.get("retry_pages") or completeness.still_missing(deck.get("claims_record"), deck.get("page_overrides"), second_on)
    kept = [r for r in deck.get("page_reads") or [] if r.get("status") == "read" and (not second_on or r.get("second"))] if resume else []
    done_before = {n for r in kept for n in r.get("pages") or ()}
    skipped = skipped_pages(grids, page_count)

    async def progress(done: int, total: int) -> None:
        await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {"read_progress": {"done": done, "total": total}}})

    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {"skipped_pages": skipped}})
    # The model allow-list comes first (CLAUDE.md rule 31): a model off the list reads no page, so nothing is converted or drawn; the
    # gateway then answers every page "blocked" and the deck panel says so.
    permitted = bool(gateway.PAGE_READER_MODELS.fullmatch(gateway.page_reader_model()))      # the gateway logs the refusal, once per page
    # The deck's pages are drawn once from the stored file. A deck that cannot be drawn (no LibreOffice, another page count, no stored
    # file) or a page that fails goes as text alone, as before; the panel says so (`images_unavailable`). Never "not read" for that.
    pdf, no_file = None, False
    if permitted:
        try:
            pdf = await render.prepare(db, audit_id, deck_id, deck.get("format") or "pdf", deck.get("pages"))
        except render.PageImageError as exc:
            no_file = exc.reason == render.NO_FILE          # consent ticked again after the file was removed: the panel asks for a re-upload
            logger.warning("page images unavailable: run_id=%s deck_id=%s", audit_id, deck_id)
    undrawn = []

    async def image_for(page: int) -> Optional[bytes]:
        if pdf is not None:
            try:
                return await asyncio.to_thread(render.render_page, pdf, page)     # one page at a time: render.PDFIUM_LOCK
            except render.PageImageError:
                logger.warning("page image unavailable: run_id=%s deck_id=%s page=%d", audit_id, deck_id, page)
        undrawn.append(page)
        return None

    expected = [page_grids_mod.page_number(p["grid"]) for p in sendable_pages(grids)]
    began = datetime.now(timezone.utc)
    seconds: Dict = {}
    lock = asyncio.Lock()

    def ordered() -> List[Dict]:
        """The entries in page order, as the sequential read gave them: the calls finish in any order, the stored list does not."""
        return kept + sorted(reads, key=lambda r: min(r["pages"]) if r["pages"] else 0)

    cap_stop: Dict = {}         # {"used", "cap"} once the token cap refused a read of this run

    def record_now() -> Dict:
        done = kept + reads
        return completeness.claims_record(expected, [n for r in done if r["status"] == "read" for n in r["pages"]],
                                       [n for r in done if r["status"] == "read" and r.get("second") for n in r["pages"]], second_on,
                                       datetime.now(timezone.utc).isoformat(),
                                       unreadable=[(n, r["status"]) for r in done if r["status"] in completeness.UNREADABLE for n in r["pages"]],
                                       capped=[n for r in done if r.get("capped") for n in r["pages"]], cap=cap_stop or None)

    async def handle(batch, result, again, capped=False) -> None:
        """One call finished: its entry, its second read's link and its claims are stored at once, page by page, under a lock (the calls run in
        parallel and share the run's rows). A batch that stops later leaves these pages stored and counted in the record."""
        nonlocal stopped_message
        async with lock:
            numbers = [page_grids_mod.page_number(g) for g in batch]
            entry = {"pages": numbers, "status": result.status, "reason": result.reason, "key": result.key, "cache_hit": result.cache_hit}
            if result.status == "stopped" or capped:
                entry["capped"] = True
                cap_stop.update({"used": await guards.structure_tokens_used(db, audit_id), "cap": token_cap})
            if result.masked:
                # The deck line's two masking counts (read-check-review.md section 8): numbers only, never what was removed.
                entry["masked"] = {"personal": redact.personal_count(result.masked),
                                   "names": result.masked.get("customer", 0) + result.masked.get("company", 0)}
            if result.provider:
                # A page the provider call failed on: the status, the error type and the plain-words sentence (the message only reaches the log).
                entry["provider"] = {k: result.provider.get(k) for k in ("status", "type", "plain")}
                shown[tuple(numbers)] = result.provider.get("message") or "-"
            if result.rejected:
                entry["rejected"] = result.rejected
                for page in numbers:        # the validator's reason (closed words), never the reply text
                    logger.warning("page %d: reply rejected (%s)", page, result.rejected)
            if result.status == "stopped":
                stopped_message = result.reason
            if result.status == "read":
                entry["second"] = again is not None
                if not result.cache_hit:
                    sent.append({"pages": numbers, "type": PAGE_CLAIMS, "at": datetime.now(timezone.utc).isoformat()})
                if again is not None:
                    if not again.cache_hit:
                        sent.append({"pages": numbers, "type": PAGE_CLAIMS, "at": datetime.now(timezone.utc).isoformat(), "read": 2})
                    # The first reply names its second, so a check again of the stored reply (renormalise_audit) compares the two as before.
                    await db[gateway.STRUCTURES_COLLECTION].update_one({"audit_id": audit_id, "key": result.key}, {"$set": {"second_key": again.key}})
                counts = await apply_reply(db, audit_id, deck_id, deck, run, by_page, year_end, page_count, result.key, numbers, result.claims,
                                           again.claims if again is not None else None)
                entry.update(counts)
                logger.info("pages checked: run_id=%s deck_id=%s pages=%d matched=%d unmatched=%d dropped=%d flagged=%d", audit_id,
                            deck_id, len(numbers), counts["matched"], counts["unmatched"], counts["dropped"], counts["flagged"])
            reads.append(entry)
            change = {"page_reads": ordered(), "claims_record": record_now(), "diagnostics": run.diagnostics}
            if result.status == "read":
                change["claims_at"] = datetime.now(timezone.utc).isoformat()       # the newest claims a result can be built from
            await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": change})

    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {"claims_record": record_now()}})
    token_cap = await audit_token_cap(db, audit_id)         # includes this deck's pages: the record above is stored
    await read_pages(db, audit_id, deck_id, grids, image_for if permitted else None, adapter, sleep, per_call=1, skip=done_before,
                     parallel=PARALLEL_PAGES, progress=progress, seconds=seconds if second_on else None, on_page=handle, token_cap=token_cap)
    for entry in ordered()[len(kept):]:
        if entry["status"] != "read":
            for n in entry["pages"]:
                # Codes only (rule 17): the page, the status and the reason word; for a provider failure the same fields as the spreadsheet step's
                # "structure not read" line (reason, HTTP status, error type, the provider's message as logged).
                provider = entry.get("provider")
                if provider:
                    logger.warning("page %d not read: run_id=%s deck_id=%s reason=provider_error status=%s type=%s message=%s", n, audit_id,
                                   deck_id, provider.get("status") or "-", provider.get("type") or "-", shown.get(tuple(entry["pages"]), "-"))
                    continue
                logger.warning("page %d not read: run_id=%s deck_id=%s status=%s reason=%s", n, audit_id, deck_id, entry["status"],
                               entry["reason"] if entry["reason"] in ("timeout", "stopped") else "-")
    missing = any(r["reason"] == gateway.PROMPT_MISSING_TEXT for r in reads)
    blocked = any(r["status"] == "blocked" for r in reads)
    overall = STOPPED if stopped_message else READ if any(r["status"] == "read" for r in kept + reads) else BLOCKED if blocked else \
        PROMPT_MISSING if missing else NOT_READ
    previous = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id}, {"_id": 0, "sent": 1, "images_unavailable": 1, "images_need_file": 1})
    unread = sorted({n for r in reads if r["status"] != "read" for n in r["pages"]})
    # Run audit asks again for the pages a failure left unread, not for a page the cap, the size or a refusal will refuse again.
    retry = sorted({n for r in reads if r["status"] in RETRY_STATUSES for n in r["pages"]}
                   | {n for r in reads if second_on and r["status"] == "read" and not r.get("second") and not r.get("capped") for n in r["pages"]})
    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {
        "page_reads": ordered(), "sent": list((previous or {}).get("sent") or []) + sent, "unread_pages": unread, "retry_pages": retry,
        "images_unavailable": bool(undrawn) or bool(kept and (previous or {}).get("images_unavailable")),     # a retry keeps the earlier pages' state
        "images_need_file": no_file or bool(kept and (previous or {}).get("images_need_file")),
        "diagnostics": run.diagnostics, "claims_record": record_now()}})
    record = record_now()
    logger.info("claims run: run_id=%s deck_id=%s first=%d/%d second=%d/%d missing=%s elapsed=%.1fs timeout=%ds cap=%d", audit_id, deck_id, len(record["first"]),
                len(record["expected"]), len(record["second"]), len(record["first"]), ",".join(str(n) for n in record["missing"]) or "-",
                (datetime.now(timezone.utc) - began).total_seconds(), completeness.stage_timeout(len(record["expected"]), 2 if second_on else 1),
                token_cap)
    return await _deck_status(db, audit_id, deck_id, overall, stopped_message or (gateway.PROMPT_MISSING_TEXT if overall == PROMPT_MISSING else
                                                                                gateway.PAGE_READER_BLOCKED if overall == BLOCKED else None))
