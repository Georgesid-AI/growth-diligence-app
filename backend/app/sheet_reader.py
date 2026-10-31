"""Read, check, re-read once (docs/design/read-check-review.md section 3, steps 1 and 2; PR 2).

One spreadsheet in, one stored outcome out:

    1. the model reads the file through the gateway (one call; the gateway masks, counts, stores the reading once and serves a file it has
       read before with no call), and returns the file map;
    2. code opens every cell the map cites (app/checks.py) and gives each item an outcome;
    3. every rejected item is read once more, automatically, with its reason attached (one call for all of them), stored beside the first
       reading; the map is checked again, and each item says whether the second reading agrees with the cell, repeats the first reading or
       gives a third value;
    4. the outcome is stored for the audit (readings.save_checks) with the file's month, the evidence for it and the counts.

Nothing here corrects a citation: a re-read is the model's, and its answer is checked like the first. A failure of the model, a missing
prompt, a missing consent or a file over the limit gives a status and a message, never an exception: the upload goes on (rule 20).
"""
import asyncio
from typing import Dict, List

from . import checks, readings
from .llm import gateway, redaction
from .llm.schemas import SHEET_READING
from .structures import reading_input

READ_SECONDS = gateway.SHEET_READING_TIMEOUT_SECONDS + 30


def _group(items: List[Dict]) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}
    for item in items:
        key = f"last_actual:{item['sheet']}" if item["kind"] == "evidence" else item["key"]
        out.setdefault(key, []).append(item)
    return out


def _worst(items: List[Dict]) -> Dict:
    """The item of a key that decides it: the first rejected one, else the first."""
    return next((i for i in items if i["outcome"] == checks.REJECTED), items[0])


async def read_file(db, audit: dict, sheets: list, file_hash: str, file: str, fiscal_year_end: int = 12, adapter=None) -> Dict:
    """Read, check and re-read one workbook for one audit. Returns the stored outcome:

        {"status": "read", "file", "file_hash", "reading_key", "prompt_version", "model", "cache_hit", "masked": {...}, "counts": {...},
         "items": [...], "rereads": [...], "month": "YYYY-MM" or None, "evidence": text or None, "months": [per sheet]}

    or {"status": <gateway status or "none">, "reason": message} when nothing was read: no recognised sheet ("none"), no consent, no model,
    no prompt, a file over the limit, a reply that did not validate."""
    audit_id = audit["id"]
    text = reading_input.reading_text(sheets)
    if text is None:
        return {"status": "none", "reason": "No sheet with period columns to read."}
    try:
        first = await asyncio.wait_for(gateway.read_structure(db, audit_id, text, SHEET_READING, file_hash=file_hash, adapter=adapter),
                                       READ_SECONDS)
    except asyncio.TimeoutError:
        return {"status": "not_read", "reason": gateway.NOT_READ}
    if first.status != "read" or not first.file_map:
        return {"status": first.status, "reason": first.reason or gateway.NOT_READ}
    cells = checks.Cells(first.payload)
    before = checks.check_map(cells, first.file_map, fiscal_year_end)
    final, rereads, merged = before, [], first.file_map
    keys = checks.reread_keys(before["items"])
    if keys:
        groups = _group(before["items"])
        ask = [{"item": k, "reason": _worst(groups[k])["reason"]} for k in keys]
        second = await asyncio.wait_for(
            gateway.read_structure(db, audit_id, text, SHEET_READING, file_hash=file_hash, adapter=adapter, recheck=ask, reread_of=first.reading_key), READ_SECONDS)
        if second.status == "read" and second.file_map is not None:
            merged = checks.merge_reread(first.file_map, second.file_map, keys)
            final = checks.check_map(cells, merged, fiscal_year_end)
            after = _group(final["items"])
            for entry in ask:
                key = entry["item"]
                old, new = _worst(groups[key]), _worst(after[key]) if key in after else None
                if new is None:
                    new = {"outcome": checks.REJECTED, "reason": old["reason"]}
                result = checks.classify_reread(old, new)
                entry = {"item": key, "first_reason": old["reason"], "reread": result, "outcome": new["outcome"],
                         "reason": new.get("reason"), "action": "corrected automatically" if new["outcome"] == checks.CONFIRMED else "card"}
                if new["outcome"] == checks.REJECTED:
                    # Both readings go with the card: the first as the reader gave it, the second beside it.
                    entry["first"], entry["second"] = checks.reading_of(first.file_map, key), checks.reading_of(second.file_map, key)
                rereads.append(entry)
        else:
            rereads = [{"item": e["item"], "first_reason": e["reason"], "reread": None, "outcome": checks.REJECTED, "reason": e["reason"],
                        "action": "card", "first": checks.reading_of(first.file_map, e["item"]), "second": None} for e in ask]
    months = final["months"]
    best = max(months, key=lambda m: m["month"], default=None)
    doc = {"status": "read", "file": file, "file_hash": file_hash, "reading_key": first.reading_key, "prompt_version": first.prompt_version,
           "model": first.model, "cache_hit": first.cache_hit, "masked": first.masked or {}, "counts": final["counts"],
           "items": final["items"], "rereads": rereads, "months": months,
           "month": best["month"] if best else None,
           "evidence": (f"{best['evidence']} (confirmed on sheet {best['sheet']}, column {best['column']})" if best else None),
           "rows_mapped": sum(len(s.get("rows") or []) for s in merged.get("sheets") or []),
           "period_columns": max((redactless_cols(s) for s in merged.get("sheets") or []), default=0)}
    mapping = await redaction.get_map(db, audit_id)
    doc = redaction.restore_deep(doc, mapping)                   # display un-masks on the server; the reasons held masked cell texts
    await readings.save_checks(db, audit_id, file_hash, doc)
    return doc


def redactless_cols(sheet: Dict) -> int:
    from .structures import redact
    return redact.col_number(sheet["last_period_col"]) - redact.col_number(sheet["first_period_col"]) + 1


async def reads_for(db, audit_id: str) -> Dict[str, Dict]:
    """The stored outcomes of the audit's files by file hash (what as_of.detect reads)."""
    return {d["file_hash"]: d for d in await readings.checks_for(db, audit_id) if d.get("status") == "read"}
