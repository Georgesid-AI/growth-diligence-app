"""The page pipeline: the model reads every sendable page of a deck, Python checks each claim (docs/design/ai-reads-rules-check.md).

Behind the switch DECK_PIPELINE (deck_pipeline): "rules", the default, keeps today's path (app/structures/__init__.process_deck:
the rules read and the structure read) and makes no page call; "ai" runs this module instead for a deck. No screen changes under
the default (PR A of the design note, section 7).

Order for one deck: consent and the revenue-file gate as today -> the page grids (app/decks/pages.py) -> the pages that may go
(a figure as digits, not a dropped page; decision 1b) in batches of PAGES_PER_CALL -> each batch redacted (redact.redact_page: the
structure rules plus the people-name rule over prose) and written by the one builder (redact.page_text) -> gateway.read_structure
with the type page_claims (consent, boundary and redaction checked again, cache, token caps, lock, spend caps, prompt caching) -> a
batch too large for the cap is split, a single page too large is skipped -> page_check per page -> one approval row per claim,
"Matched to page" or "AI suggestion, not matched", deduplicated against the rows already listed as today. What is stored (rule 17):
the model's claims (closed words, numbers and cell ids), the checked items without any text, the batch's metadata; never the
text sent.
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..decks import CANDIDATES_COLLECTION, TEXT_COLLECTION, claims
from ..decks import pages as page_grids_mod
from ..llm import gateway
from ..llm import redaction as llm_redaction
from ..llm.schemas import PAGE_CLAIMS
from . import page_check, redact

logger = logging.getLogger("growth.structures")

PIPELINES = ("rules", "ai")
PAGES_PER_CALL = redact.PAGES_PER_CALL
_UNITS = {"%", "x", "days", "months", "years"}


def deck_pipeline() -> str:
    """The DECK_PIPELINE switch: "rules" (default) or "ai". Anything else is "rules", so a typo changes nothing on screen."""
    value = os.environ.get("DECK_PIPELINE", "").strip().lower()
    return value if value in PIPELINES else "rules"


def redacted_pages(grids: List[Dict], company_name: Optional[str], mapping: Dict[str, str]) -> List[Dict]:
    """[{"grid", "cells"}] for the pages that may go: a sendable grid (a figure as digits by the parser's reader, not a dropped
    page) whose redacted cells (redact.redact_page: the structure rules plus the people-name rule over prose) still hold a figure
    as digits by the gateway's own floor (redact.digit_figure), so a page whose only digits were a phone number never goes."""
    out = []
    for grid in page_grids_mod.sendable(grids):
        cells, _ = redact.redact_page(grid["cells"], company_name, mapping)
        if any(redact.digit_figure(c["text"]) for c in cells):
            out.append({"grid": grid, "cells": cells})
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
                     adapter=None, sleep=None) -> List[Tuple[List[Dict], object]]:
    """[(grids of the batch, StructureRead)] for every batch of a deck's sendable pages. A batch the token cap refuses as too
    large is split in two and read again; a single page too large is kept with its status. After the audit's token cap stops
    reading, the remaining batches are marked stopped without a call."""
    queue = batches(grids, company_name, mapping)
    out, stopped = [], None
    while queue:
        batch = queue.pop(0)
        grids_of = [p["grid"] for p in batch]
        if stopped is not None:
            out.append((grids_of, gateway._structure_result("stopped", PAGE_CLAIMS, stopped)))
            continue
        text = batch_text(batch)
        result = await gateway.read_structure(db, audit_id, text, PAGE_CLAIMS, deck_id=deck_id,
                                              pages=[page_grids_mod.page_number(g) for g in grids_of], adapter=adapter, sleep=sleep)
        if result.status == "too_large" and len(batch) > 1:
            half = len(batch) // 2
            queue[:0] = [batch[:half], batch[half:]]
            continue
        if result.status == "stopped":
            stopped = result.reason
        out.append((grids_of, result))
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
        "unit": unit if unit in _UNITS else None, "currency": unit if unit and len(unit) == 3 and unit.isupper() else None,
        "target_date": target, "period_text": stated if target else None,
        "snippet": (cell.get("text") or "")[:claims.SNIPPET_MAX], "label_from": label if label and label != cell.get("text") else None,
        "date_from": stated if target and stated != cell.get("text") else None, "sources": [source],
        "inconsistent_dates": [], "origin": "ai", "cell": item["value_cell"], "position": item.get("position"),
        "readings": item["values"] if len(item.get("values") or ()) > 1 else [],
        "type_from": "heading" if label and label != cell.get("text") else "line" if claims._keywords(cell.get("text") or "") else None,
        "reading": _reading(deck.get("blocks") or (), shim, place),
        "ai_status": item["status"], "ai_label": page_check.label(item["status"]), "ai_checks": item.get("checks"),
        "period_cells": list(item.get("period_cells") or []), "actual_or_forecast": item.get("actual_or_forecast"),
        "proposed_flags": [],
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


def stored_items(checked: List[Dict]) -> Dict:
    """The checked claims as llm_structures keeps them (rule 17): cell ids, values, periods, statuses and checks. No text."""
    return {"claims": [dict(c) for c in checked]}


async def process_deck_pages(db, audit_id: str, deck_id: str, adapter=None, sleep=None) -> str:
    """Read one deck page by page with the model and check every claim against its page; returns the deck's AI status (the
    words of process_deck). Unticked consent: no call. Ticked but the revenue file not yet mapped: the deck waits, so no customer
    name goes out unmapped."""
    from . import (CANDIDATES_COLLECTION as _c, NOT_READ, PYTHON_ONLY, READ, STOPPED, WAITING, WAITING_TEXT, _cell_key,  # noqa: F401
                   _deck_status, _python_cells, recognition_settled, revenue_mapped, rules_copy, value_match)
    audit = await db.audits.find_one({"id": audit_id}, {"_id": 0, "id": 1, "company_name": 1, "fiscal_year_end": 1,
                                                       "structure_reading_consent": 1})
    deck = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id},
                                              {"_id": 0, "file": 1, "page_unit": 1, "blocks": 1})
    if not audit or not deck:
        return NOT_READ
    if audit.get("structure_reading_consent") is not True:
        return await _deck_status(db, audit_id, deck_id, PYTHON_ONLY)
    revenue = await db.datasets.find_one({"audit_id": audit_id, "dtype": "revenue"},
                                         {"_id": 0, "mapping": 1, "mapped_at": 1, "recognition_only": 1})
    if not revenue_mapped(revenue):
        return await _deck_status(db, audit_id, deck_id, WAITING, WAITING_TEXT)
    if revenue.get("recognition_only") and recognition_settled is not None \
            and await recognition_settled(db, audit_id) is False:
        return await _deck_status(db, audit_id, deck_id, WAITING, WAITING_TEXT)
    mapping = await llm_redaction.get_map(db, audit_id)
    year_end = int(audit.get("fiscal_year_end") or 12)
    grids = page_grids_mod.page_grids(deck.get("blocks") or [])
    by_page = {page_grids_mod.page_number(g): g for g in grids}
    reviewed = await db[CANDIDATES_COLLECTION].find({"audit_id": audit_id, "file": deck["file"]}, {"_id": 0}).to_list(100000)
    known = _python_cells(reviewed)
    order = len(reviewed)
    reads, sent, stopped_message = [], [], None
    for batch, result in await read_pages(db, audit_id, deck_id, grids, audit.get("company_name"), mapping, adapter, sleep):
        numbers = [page_grids_mod.page_number(g) for g in batch]
        entry = {"pages": numbers, "status": result.status, "reason": result.reason, "key": result.key, "cache_hit": result.cache_hit}
        if result.status == "stopped":
            stopped_message = result.reason
        if result.status == "read":
            if not result.cache_hit:
                sent.append({"pages": numbers, "type": PAGE_CLAIMS, "at": datetime.now(timezone.utc).isoformat()})
            claims_of = page_check.by_page(result.claims)
            checked_all, counts = [], {"matched": 0, "unmatched": 0, "dropped": 0, "periods_corrected": 0}
            for page in numbers:
                grid = by_page[page]
                checked = page_check.check(grid, claims_of.get(page, []), year_end)
                for k in counts:
                    counts[k] += checked[k]
                checked_all += [{**c, "page": page} for c in checked["items"]]
                for item in checked["items"]:
                    candidate = row_from_claim(item, grid, deck, year_end)
                    if value_match(candidate["value"], candidate["value_high"], known.get(_cell_key(candidate), ())):
                        continue                    # this cell already lists the value, or a range holding it
                    twin = next((c for c in reviewed if claims.same_claim(c, candidate)), None)
                    if twin is not None:
                        if candidate["sources"][0] not in twin["sources"]:
                            twin["sources"] = list(twin["sources"]) + candidate["sources"]
                            await db[CANDIDATES_COLLECTION].update_one({"audit_id": audit_id, "id": twin["id"]},
                                                                       {"$set": {"sources": twin["sources"]}})
                        continue
                    duplicate = rules_copy(reviewed, candidate)
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
            logger.info("pages checked: run_id=%s deck_id=%s pages=%d matched=%d unmatched=%d dropped=%d", audit_id, deck_id,
                        len(numbers), counts["matched"], counts["unmatched"], counts["dropped"])
        reads.append(entry)
    overall = STOPPED if stopped_message else READ if any(r["status"] == "read" for r in reads) else NOT_READ
    previous = await db[TEXT_COLLECTION].find_one({"audit_id": audit_id, "deck_id": deck_id}, {"_id": 0, "sent": 1})
    await db[TEXT_COLLECTION].update_one({"audit_id": audit_id, "deck_id": deck_id}, {"$set": {
        "page_reads": reads, "sent": list((previous or {}).get("sent") or []) + sent}})
    return await _deck_status(db, audit_id, deck_id, overall, stopped_message)
