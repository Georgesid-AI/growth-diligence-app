"""The page pipeline: the model reads every sendable page of a deck, Python checks each claim (docs/design/ai-reads-rules-check.md).

The live path since 2026-10-22 (George; the switch DECK_PIPELINE, read by the gateway, defaults to "ai"): the rules read
(claims.detect_candidates) no longer lists candidates at upload; it stays as the library of Add from deck and of the checker's
converted rules, and as the former path under DECK_PIPELINE=rules for scripts/compare_pipelines.py. The model reads each page
with the `deck_reading` prompt of the store and answers claims in the register's fields plus `basis` (actual, projection,
scenario) and `scenario` (best, realistic, worst, none); the gateway caches a batch per audit by the hash of its page text (a
function of the file), so a deck uploaded again costs nothing.

Order for one deck: consent and the revenue-file gate as today -> the page grids (app/decks/pages.py) -> the pages that may go
(a figure as digits, not a dropped page; decision 1b) in batches of PAGES_PER_CALL -> each batch redacted (redact.redact_page: the
structure rules plus the people-name rule over prose), its lines over 200 characters left out (as for a structure cell; George,
2026-10-22, decision 1b on the review of PR #159) and written by the one builder (redact.page_text) -> gateway.read_structure
with the type page_claims (consent, boundary and redaction checked again, cache, token caps, lock, spend caps, prompt caching) -> a
batch too large for the cap, or whose reply was cut at the output limit, is split, a single page too large or cut is skipped
-> checker.check per page (page_check at cell level, then the flags) -> one approval row per claim,
"Matched to page" or "AI suggestion, not matched", with its `flags` (a flagged row is listed in the review tab, never deleted or
retyped), deduplicated against the rows already listed as today. What is stored (rule 17): the model's claims (closed words,
numbers and cell ids), the checked items without any text, the batch's metadata; never the text sent.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..decks import CANDIDATES_COLLECTION, TEXT_COLLECTION, claims
from ..decks import pages as page_grids_mod
from ..llm import gateway
from ..llm import redaction as llm_redaction
from ..llm.schemas import PAGE_CLAIMS
from . import checker, page_check, redact

logger = logging.getLogger("growth.structures")

PIPELINES = gateway.PIPELINES
deck_pipeline = gateway.deck_pipeline          # the switch is read by the gateway, which refuses a page call under "rules"
PAGES_PER_CALL = redact.PAGES_PER_CALL
LINE_MAX = gateway.STRUCTURE_CELL_MAX          # a longer line is left out, as a structure cell is (decision 1b, review of PR #159)
_UNITS = {"%", "x", "days", "months", "years"}


def redacted_pages(grids: List[Dict], company_name: Optional[str], mapping: Dict[str, str]) -> List[Dict]:
    """[{"grid", "cells"}] for the pages that may go: a sendable grid (a figure as digits by the parser's reader, not a dropped
    page) whose redacted cells (redact.redact_page: the structure rules plus the people-name rule over prose), the lines over
    LINE_MAX characters left out, still hold a figure as digits by the gateway's own floor (redact.page_figure: not a year, a
    date or the page's own number), so a page whose only digits were a phone number or its page number never goes."""
    out = []
    for grid in page_grids_mod.sendable(grids):
        page = page_grids_mod.page_number(grid)
        cells, _ = redact.redact_page(grid["cells"], company_name, mapping)
        kept = [c for c in cells if len(c["text"]) <= LINE_MAX]
        if len(kept) < len(cells):
            # The rules run once more on the lines as sent, so the gateway's re-run (which sees no dropped line) finds nothing to change.
            kept, _ = redact.redact_page(kept, company_name, mapping)
        if any(redact.page_figure(c["text"], page) for c in kept):
            out.append({"grid": grid, "cells": kept})
    return out


def batches(grids: List[Dict], company_name: Optional[str], mapping: Dict[str, str], per_call: int = PAGES_PER_CALL) -> List[List[Dict]]:
    """The redacted sendable pages in consecutive groups of at most per_call pages."""
    pages = redacted_pages(grids, company_name, mapping)
    return [pages[i:i + per_call] for i in range(0, len(pages), per_call)]


def batch_text(batch: List[Dict]) -> str:
    """The text the model reads for a batch of redacted pages, written by redact.page_text. The one builder of page text; nothing
    else of a deck reaches the gateway."""
    return redact.page_text([(page_grids_mod.page_number(p["grid"]), p["cells"]) for p in batch])


async def read_pages(db, audit_id: str, deck_id: str, grids: List[Dict], company_name: Optional[str], mapping: Dict[str, str],
                     adapter=None, sleep=None, use_cache: bool = True,
                     progress=None) -> List[Tuple[List[Dict], object]]:
    """[(grids of the batch, StructureRead)] for every batch of a deck's sendable pages. A batch the token cap refuses as too
    large, or whose reply the provider cut at the output limit ("truncated"; the same batch would be cut again), is split in two
    and read again; a single page too large or cut is kept with its status. After the audit's token cap stops reading, the
    remaining batches are marked stopped without a call. `use_cache=False` (a consistency pass) asks the model again for pages
    this audit already read, so the pass measures the model and not the cache. `progress(done, total)` is awaited before the first batch
    and after each one, in pages (the deck panel's "page n of N")."""
    queue = batches(grids, company_name, mapping)
    total, done = sum(len(b) for b in queue), 0
    out, stopped = [], None
    if progress:
        await progress(0, total)
    while queue:
        batch = queue.pop(0)
        grids_of = [p["grid"] for p in batch]
        if stopped is not None:
            out.append((grids_of, gateway._structure_result("stopped", PAGE_CLAIMS, stopped)))
            continue
        text = batch_text(batch)
        result = await gateway.read_structure(db, audit_id, text, PAGE_CLAIMS, deck_id=deck_id,
                                              pages=[page_grids_mod.page_number(g) for g in grids_of], adapter=adapter, sleep=sleep,
                                              use_cache=use_cache)
        if result.status in ("too_large", "truncated") and len(batch) > 1:
            half = len(batch) // 2
            queue[:0] = [batch[:half], batch[half:]]
            continue
        if result.status == "stopped":
            stopped = result.reason
        out.append((grids_of, result))
        done += len(batch)
        if progress:
            await progress(done, total)
    return out


def row_from_claim(item: Dict, grid: Dict, deck: Dict, fiscal_year_end: int) -> Dict:
    """One approval-list row for a checked page claim, citing its cell on its page. The snippet is the cell's own text; the period
    keeps the text of its period cells; "Label from" is the label cell's text when it is adjacent and not the cell itself."""
    from . import _reading, _target_date, _where         # the orchestrator's helpers, shared with the structure read
    by_id = {redact.cell_id(c): c for c in grid["cells"]}
    cell = by_id[item["value_cell"]]
    period_cells = [by_id[c]["text"] for c in item.get("period_cells") or () if c in by_id]
    label = by_id[item["label_cell"]]["text"] if item.get("label_cell") in by_id else None
    unit = item.get("unit_other") if item.get("unit") == "other" else item.get("unit")
    target, stated = _target_date(item.get("period")), (" ".join(period_cells) or item.get("period"))
    source = {"file": deck["file"], **_where(grid), "kind": "page", "cell": item["value_cell"]}
    if cell.get("table") is not None:
        source.update(table=cell["table"], row=cell.get("trow"), col=cell.get("tcol"))
    shim = {**_where(grid), "table": cell.get("table")}
    place = {**cell, "row": cell.get("trow", cell["row"]), "col": cell.get("tcol", cell["col"])} if cell.get("table") is not None else cell
    candidate = {
        "claim_type": item["metric"], "value": item.get("value"), "value_high": item.get("value_high"),
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


def row_out_of_range(claim: Dict, page: int, deck: Dict) -> Dict:
    """The approval-list row of a claim on a page the document does not have (checker.PAGE_OUT_OF_RANGE): the model's values, no
    cell, no snippet, never matched; listed in the review tab."""
    unit = claim.get("unit_other") if claim.get("unit") == "other" else claim.get("unit")
    key = "slide" if deck.get("page_unit") == "slide" else "page"
    return {
        "claim_type": claim["metric"], "value": claim.get("value"), "value_high": claim.get("value_high"),
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
    return {"claims": [dict(c) for c in checked]}


async def process_deck_pages(db, audit_id: str, deck_id: str, adapter=None, sleep=None) -> str:
    """Read one deck page by page with the model and check every claim against its page; returns the deck's AI status (the
    words of process_deck). Unticked consent: no call. Ticked but the revenue file not yet mapped: the deck waits, so no customer
    name goes out unmapped."""
    from . import (CANDIDATES_COLLECTION as _c, NOT_READ, PYTHON_ONLY, READ, STOPPED, WAITING, WAITING_TEXT, _cell_key,  # noqa: F401
                   CONSENT_OFF_LINE, PROMPT_MISSING, _deck_status, _python_cells, analyst_copy, revenue_ready, rules_copy, value_match)
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0, "id": 1, "company_name": 1, "fiscal_year_end": 1,
                                                       "structure_reading_consent": 1})
    deck = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id},
                                              {"_id": 0, "file": 1, "page_unit": 1, "pages": 1, "blocks": 1})
    if not audit or not deck:
        return NOT_READ
    if audit.get("structure_reading_consent") is not True:
        return await _deck_status(db, audit_id, deck_id, PYTHON_ONLY, CONSENT_OFF_LINE)
    if not await revenue_ready(db, audit_id):
        return await _deck_status(db, audit_id, deck_id, WAITING, WAITING_TEXT)
    mapping = await llm_redaction.get_map(db, audit_id)
    year_end = int(audit.get("fiscal_year_end") or 12)
    grids = page_grids_mod.page_grids(deck.get("blocks") or [])
    by_page = {page_grids_mod.page_number(g): g for g in grids}
    page_count = deck.get("pages") or (max(by_page) if by_page else None)
    reviewed = await db[CANDIDATES_COLLECTION].find({"audit_id": audit_id, "file": deck["file"]}, {"_id": 0}).to_list(100000)
    known = _python_cells(reviewed)
    order = len(reviewed)
    reads, sent, stopped_message = [], [], None
    async def progress(done: int, total: int) -> None:
        await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {"read_progress": {"done": done, "total": total}}})

    for batch, result in await read_pages(db, audit_id, deck_id, grids, audit.get("company_name"), mapping, adapter, sleep, progress=progress):
        numbers = [page_grids_mod.page_number(g) for g in batch]
        entry = {"pages": numbers, "status": result.status, "reason": result.reason, "key": result.key, "cache_hit": result.cache_hit}
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
            for page in numbers:
                grid = by_page[page]
                checked = checker.check(grid, claims_of.get(page, []), year_end, checker.page_blocks(deck.get("blocks") or [], grid),
                                        deck["file"])
                for k in counts:
                    counts[k] += checked[k]
                checked_all += [{**c, "page": page} for c in checked["items"]]
                rows += [(row_from_claim(item, grid, deck, year_end), page) for item in checked["items"]]
            counts["flagged"] += sum(1 for row, _ in rows if row["flags"] and row["cell"] is None)
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
                else:
                    row_order = order = order + 1
                row = {**candidate, "audit_id": audit_id, "deck_id": deck_id, "file": deck["file"],
                       "id": str(uuid.uuid4()), "order": row_order, "status": "pending", "structure_key": result.key}
                await db[CANDIDATES_COLLECTION].insert_one(row)
                reviewed.append(row)
            await gateway.record_verification(db, audit_id, result.key, [c["status"] for c in checked_all], counts["dropped"],
                                              counts["periods_corrected"], stored_items(checked_all))
            entry.update(counts)
            logger.info("pages checked: run_id=%s deck_id=%s pages=%d matched=%d unmatched=%d dropped=%d flagged=%d", audit_id,
                        deck_id, len(numbers), counts["matched"], counts["unmatched"], counts["dropped"], counts["flagged"])
        reads.append(entry)
    missing = any(r["reason"] == gateway.PROMPT_MISSING_TEXT for r in reads)
    overall = STOPPED if stopped_message else READ if any(r["status"] == "read" for r in reads) else PROMPT_MISSING if missing else NOT_READ
    previous = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id}, {"_id": 0, "sent": 1})
    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {
        "page_reads": reads, "sent": list((previous or {}).get("sent") or []) + sent}})
    return await _deck_status(db, audit_id, deck_id, overall, stopped_message or (gateway.PROMPT_MISSING_TEXT if overall == PROMPT_MISSING else None))
