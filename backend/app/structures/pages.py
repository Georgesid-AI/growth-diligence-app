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
from typing import Dict, List, Optional, Tuple

from ..decks import CANDIDATES_COLLECTION, TEXT_COLLECTION, claims
from ..decks import pages as page_grids_mod
from ..decks import render
from ..llm import gateway
from ..llm.schemas import PAGE_CLAIMS
from . import association
from . import checker, page_check, redact

logger = logging.getLogger("growth.structures")

PIPELINES = gateway.PIPELINES
deck_pipeline = gateway.deck_pipeline          # the switch is read by the gateway, which refuses a page call under "rules"
PAGES_PER_CALL = redact.PAGES_PER_CALL
PARALLEL_PAGES = 8                             # pages read at a time (George, 2026-10-23, deck page reads: speed)
PARALLEL_AFTER_RATE_LIMIT = 4                  # ... for the rest of the deck after the provider answers 429
RETRY_STATUSES = ("not_read", "stopped", "blocked")       # a later Run audit reads these pages again
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
                     page_timeout: float = PAGE_TIMEOUT_SECONDS, progress=None) -> List[Tuple[List[Dict], object]]:
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
    that page then goes as text alone, as before, and is never "not read" for that reason."""
    queue = [b for b in batches(grids, per_call)
             if not all(page_grids_mod.page_number(p["grid"]) in set(skip) for p in b)]
    total = len(queue)
    results: Dict[int, Tuple[List[Dict], object]] = {}
    state = {"limit": max(1, parallel), "stopped": None, "done": 0, "next": 0}

    def lower():
        state["limit"] = min(state["limit"], PARALLEL_AFTER_RATE_LIMIT)

    async def read_one(batch, numbers):
        images = [await image_for(n) for n in numbers] if image_for else None
        if images is not None and any(i is None for i in images):
            images = None
        return await gateway.read_structure(
            db, audit_id, batch_text(batch), PAGE_CLAIMS, deck_id=deck_id, pages=numbers, adapter=adapter, sleep=sleep,
            use_cache=use_cache, on_rate_limit=lower, images=images)

    async def one(batch):
        grids_of = [p["grid"] for p in batch]
        numbers = [page_grids_mod.page_number(g) for g in grids_of]
        if state["stopped"] is not None:
            return [(grids_of, gateway._structure_result("stopped", PAGE_CLAIMS, state["stopped"]))]
        try:
            result = await asyncio.wait_for(read_one(batch, numbers), page_timeout)
        except asyncio.TimeoutError:
            logger.warning("page not read: run_id=%s deck_id=%s pages=%s reason=timeout", audit_id, deck_id, numbers)
            return [(grids_of, gateway._structure_result("not_read", PAGE_CLAIMS, "timeout"))]
        if result.status in ("too_large", "truncated") and len(batch) > 1:
            half = len(batch) // 2
            return [r for part in (batch[:half], batch[half:]) for r in await one(part)]
        if result.status == "stopped":
            state["stopped"] = result.reason
        return [(grids_of, result)]

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


async def process_deck_pages(db, audit_id: str, deck_id: str, adapter=None, sleep=None) -> str:
    """Read one deck page by page with the model and check every claim against its page; returns the deck's AI status (the
    words of process_deck). Unticked consent: no call. A deck never waits for a file (read-check-review.md section 12)."""
    from . import (CANDIDATES_COLLECTION as _c, BLOCKED, NOT_READ, PYTHON_ONLY, READ, STOPPED, _cell_key,  # noqa: F401
                   CONSENT_OFF_LINE, PROMPT_MISSING, _deck_status, _python_cells, analyst_copy, rules_copy, store_candidate, value_match)
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0, "id": 1, "company_name": 1, "fiscal_year_end": 1,
                                                       "structure_reading_consent": 1})
    deck = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id},
                                              {"_id": 0, "file": 1, "format": 1, "page_unit": 1, "pages": 1, "blocks": 1, "layout": 1, "page_reads": 1, "retry_pages": 1,
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
    known = _python_cells(reviewed)
    order = len(reviewed)
    reads, sent, stopped_message = [], [], None
    diagnostics = list(deck.get("diagnostics") or [])      # Diagnostics lines of the pages read so far; a page read again replaces its lines
    fresh = set()                       # ids of the rows this run wrote: a later page with the same text never replaces them
    # A run that follows one that left pages to retry asks only for those pages; any other run reads the whole deck (the cache serves
    # the pages already read).
    kept = [r for r in deck.get("page_reads") or [] if r.get("status") == "read"] if deck.get("retry_pages") else []
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

    for batch, result in await read_pages(db, audit_id, deck_id, grids, image_for if permitted else None, adapter, sleep,
                                          per_call=1, skip=done_before, parallel=PARALLEL_PAGES, progress=progress):
        numbers = [page_grids_mod.page_number(g) for g in batch]
        entry = {"pages": numbers, "status": result.status, "reason": result.reason, "key": result.key, "cache_hit": result.cache_hit}
        if result.masked:
            # The deck line's two masking counts (read-check-review.md section 8): numbers only, never what was removed.
            entry["masked"] = {"personal": redact.personal_count(result.masked),
                               "names": result.masked.get("customer", 0) + result.masked.get("company", 0)}
        if result.rejected:
            entry["rejected"] = result.rejected
            for page in numbers:        # the validator's reason (closed words), never the reply text
                logger.warning("page %d: reply rejected (%s)", page, result.rejected)
        if result.status == "stopped":
            stopped_message = result.reason
        if result.status == "read":
            if not result.cache_hit:
                sent.append({"pages": numbers, "type": PAGE_CLAIMS, "at": datetime.now(timezone.utc).isoformat()})
            claims_of = page_check.by_page(result.claims)
            checked_all, counts = [], {"matched": 0, "unmatched": 0, "dropped": 0, "periods_corrected": 0, "flagged": 0}
            # A claim on a page the document does not have (the gateway checks every cited cell against the text sent, so this is a
            # guard, not an expected path): one row with the model's values, flagged, never matched (checker rule 4).
            rows = [(row_out_of_range(c, page, deck), page) for page, listed in claims_of.items() if page not in numbers
                    and checker.out_of_range(page, page_count) for c in listed]
            diagnostics_new = []
            for page in numbers:
                grid = by_page[page]
                checked = checker.check(grid, claims_of.get(page, []), year_end, checker.page_blocks(deck.get("blocks") or [], grid),
                                        deck["file"])
                for k in counts:
                    counts[k] += checked[k]
                checked_all += [{**c, "page": page} for c in checked["items"]]
                for item in checked["items"]:
                    if item["drop"]:            # a derived figure, a launch date with no product, a quoted figure: no row, one Diagnostics line (George, 2026-10-26)
                        counts["dropped"] += 1
                        diagnostics_new.append({"page": page, "kind": item["drop"], "metric": item["metric"], "value": item.get("value"),
                                                "period": item.get("period")})
                        continue
                    row, log = corrected_row(item, grid, deck, year_end, page)
                    rows.append((row, page))
                    diagnostics_new += log
            counts["flagged"] += sum(1 for row, _ in rows if checker.review_flags(row["flags"]) and row["cell"] is None)
            diagnostics = [d for d in diagnostics if d["page"] not in numbers] + diagnostics_new
            # A page read again (Run audit, a new upload of the file): the rows an earlier run stored for this reply that nobody has touched
            # (pending, origin "ai") are replaced by the rows checked now, so a row stored before a check existed does not outlive it
            # (live bug, 2026-10-23: rows kept "unmatched" with no flags). A row the analyst approved, edited or rejected stays.
            # Untouched means pending, or entered by Python on its own with no analyst action (claim_matching.entered_by_python: "auto", no
            # edit, no Keep or reject); both are replaced. A row the analyst approved, edited or rejected keeps its values (PR 183).
            from ..claim_matching import entered_by_python
            stale = [c for c in reviewed if c.get("origin") == "ai" and (c.get("status") == "pending" or entered_by_python(c))
                     and c.get("structure_key") == result.key and c["id"] not in fresh]
            stale_orders = sorted(c.get("order", 0) for c in stale)
            for c in stale:
                await db[CANDIDATES_COLLECTION].delete_one({"audit_id": audit_id, "id": c["id"]})
                reviewed.remove(c)
            if stale:
                known = _python_cells(reviewed)
            for candidate, page in rows:
                if candidate["cell"] is not None and \
                        value_match(candidate["value"], candidate["value_high"], known.get(_cell_key(candidate), ())):
                    continue                    # this cell already lists the value, or a range holding it
                twin = next((c for c in reviewed if claims.same_claim(c, candidate)), None)
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
                duplicate = rules_copy(reviewed, candidate)
                if duplicate is None and analyst_copy(reviewed, candidate) is not None:
                    # The analyst already added this figure (M5): the claim is never replaced; the model's read is listed beside it, flagged.
                    candidate = {**candidate, "flags": candidate["flags"] + [checker.MATCHES_ANALYST]}
                if duplicate is not None:
                    candidate = {**candidate, "sources": candidate["sources"] + [s for s in duplicate["sources"] if s not in candidate["sources"]]}
                    await db[CANDIDATES_COLLECTION].delete_one({"audit_id": audit_id, "id": duplicate["id"]})
                    reviewed.remove(duplicate)
                    row_order = duplicate.get("order", order + 1)
                elif stale_orders:
                    row_order = stale_orders.pop(0)         # the replaced row's place in the list
                else:
                    row_order = order = order + 1
                row = {**candidate, "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"],
                       "id": str(uuid.uuid4()), "order": row_order, "status": "pending", "structure_key": result.key}
                await store_candidate(db, row)
                reviewed.append(row)
                fresh.add(row["id"])
            await gateway.record_verification(db, audit_id, result.key, [c["status"] for c in checked_all], counts["dropped"],
                                              counts["periods_corrected"], stored_items(checked_all))
            entry.update(counts)
            logger.info("pages checked: run_id=%s deck_id=%s pages=%d matched=%d unmatched=%d dropped=%d flagged=%d", audit_id,
                        deck_id, len(numbers), counts["matched"], counts["unmatched"], counts["dropped"], counts["flagged"])
        reads.append(entry)
    for entry in reads:
        if entry["status"] != "read":
            for n in entry["pages"]:
                # Codes only (rule 17): the page, the status and the reason word.
                logger.warning("page %d not read: run_id=%s deck_id=%s status=%s reason=%s", n, audit_id, deck_id, entry["status"],
                               entry["reason"] if entry["reason"] in ("timeout", "stopped") else "-")
    missing = any(r["reason"] == gateway.PROMPT_MISSING_TEXT for r in reads)
    blocked = any(r["status"] == "blocked" for r in reads)
    overall = STOPPED if stopped_message else READ if any(r["status"] == "read" for r in kept + reads) else BLOCKED if blocked else \
        PROMPT_MISSING if missing else NOT_READ
    previous = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id}, {"_id": 0, "sent": 1, "images_unavailable": 1, "images_need_file": 1})
    unread = sorted({n for r in reads if r["status"] != "read" for n in r["pages"]})
    # Run audit asks again for the pages a failure left unread, not for a page the cap, the size or a refusal will refuse again.
    retry = sorted({n for r in reads if r["status"] in RETRY_STATUSES for n in r["pages"]})
    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {
        "page_reads": kept + reads, "sent": list((previous or {}).get("sent") or []) + sent, "unread_pages": unread, "retry_pages": retry,
        "images_unavailable": bool(undrawn) or bool(kept and (previous or {}).get("images_unavailable")),     # a retry keeps the earlier pages' state
        "images_need_file": no_file or bool(kept and (previous or {}).get("images_need_file")),
        "diagnostics": diagnostics}})
    return await _deck_status(db, audit_id, deck_id, overall, stopped_message or (gateway.PROMPT_MISSING_TEXT if overall == PROMPT_MISSING else
                                                                                gateway.PAGE_READER_BLOCKED if overall == BLOCKED else None))
