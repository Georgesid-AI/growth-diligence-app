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
import logging
from typing import Dict, List, Optional

from . import cards, checks, consistency, lines as lines_mod, read_reasons, readings
from .llm import gateway, redaction
from .llm.schemas import SHEET_READING
from .structures import reading_input, redact, workbook_facts

READ_SECONDS = gateway.SHEET_READING_TIMEOUT_SECONDS + 30       # one sheet's call; a workbook read sheet by sheet is given this for each sheet


def read_seconds(text: str) -> float:
    """The time a whole read of the workbook is given: READ_SECONDS for each sheet that is sent (the gateway reads them one after another)."""
    return READ_SECONDS * max(1, len(gateway.sheet_units(text)))
logger = logging.getLogger("growth")


async def _no_stage(name: str, **counts) -> None:
    return None


def _cited(file_map: Dict) -> int:
    """How many rows and figures a map cites: the "m" of "n of m figures checked"."""
    return sum(len(s.get("rows") or []) for s in file_map.get("sheets") or []) + len(file_map.get("figures") or [])


def _group(items: List[Dict]) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}
    for item in items:
        key = f"last_actual:{item['sheet']}" if item["kind"] == "evidence" else item["key"]
        out.setdefault(key, []).append(item)
    return out


def _worst(items: List[Dict]) -> Dict:
    """The item of a key that decides it: the first rejected one, else the first."""
    return next((i for i in items if i["outcome"] == checks.REJECTED), items[0])


FORMULA_ERRORS = checks.FORMULA_ERRORS      # a cell that holds exactly one of these is a formula error


def file_facts(sheets: list) -> Dict:
    """What the workbook itself says, apart from what the model reads: {"hidden_sheets": [names], "formula_errors": [{"sheet", "cell", "error"}]}.
    A hidden sheet is read like any other and named so; a cell whose whole value is a formula error is counted and listed (sheet order, then row by
    row). Names, cell positions and the four error codes only, never a cell value."""
    hidden = [s.sheet for s in sheets if (s.fmt or {}).get("hidden")]
    errors = [{"sheet": s.sheet, "cell": f"{redact.col_letters(c)}{r}", "error": str(v).strip()}
              for s in sheets for r, line in enumerate(s.grid or [], 1) for c, v in enumerate(line, 1)
              if isinstance(v, str) and v.strip() in FORMULA_ERRORS]
    return {"hidden_sheets": hidden, "formula_errors": errors}


async def read_file(db, audit: dict, sheets: list, file_hash: str, file: str, fiscal_year_end: int = 12, adapter=None, capture: Optional[Dict] = None,
                    on_stage=None, structure: Optional[Dict] = None) -> Dict:
    """Read, check and re-read one workbook for one audit. Returns the stored outcome:

        {"status": "read", "file", "file_hash", "reading_key", "prompt_version", "model", "cache_hit", "masked": {...}, "counts": {...},
         "items": [...], "rereads": [...], "month": "YYYY-MM" or None, "evidence": text or None, "months": [per sheet]}

    or {"status": <gateway status or "none">, "reason": message} when nothing was read: no recognised sheet ("none"), no consent, no model,
    no prompt, a file over the limit, a reply that did not validate.

    `on_stage(name, **counts)` is told where the file stands, for the Upload page's stage tag: "removing_personal_data", then "reading_the_sheet"
    (the gateway calls it once the payload is masked), then "checking_cells" with `checked` and `total` (rows and figures the map cites) and,
    once the pass is done, `matched`. It carries names and counts only."""
    audit_id = audit["id"]
    stage = on_stage or _no_stage
    text = reading_input.reading_text(sheets, structure)           # `structure`: the facts read from the file (workbook_facts.extract), None for a CSV
    blocks = reading_input.facts_blocks(sheets, structure)
    if text is None:
        return {"status": "none", "reason": "No sheet with period columns to read."}
    await stage("removing_personal_data")
    allowed = read_seconds(text)
    try:
        first = await asyncio.wait_for(gateway.read_structure(db, audit_id, text, SHEET_READING, file_hash=file_hash, adapter=adapter,
                                                           fiscal_year_end=fiscal_year_end, on_stage=stage, facts_blocks=blocks), allowed)
    except asyncio.TimeoutError:
        return {"status": "not_read", "reason": gateway.NOT_READ, "read_reason": read_reasons.timeout_line(allowed)}
    if first.status != "read" or not first.file_map:
        return {"status": first.status, "reason": first.reason or gateway.NOT_READ, "provider": first.provider,
                "unread_sheets": first.unread_sheets, "read_reason": read_reasons.sheets_line(first.unread_sheets)}
    # The consistency read (docs/design/reading-consistency.md): the same input read a second time, beside the first. A stored second read is
    # reused (a file read before makes at most this one call); a failure of any kind leaves the first reading standing, compared with nothing.
    second, same = await _second_read(db, audit_id, text, file_hash, adapter, fiscal_year_end, stage, first, blocks)
    if capture is not None:
        capture["second_map"] = second.file_map if second is not None else None       # for the fixture job's verdict; never stored
    cells = checks.Cells(first.payload)
    total = _cited(first.file_map)
    await stage("checking_cells", checked=0, total=total)
    facts = _masked_structure(structure, sheets, first.payload)         # the file's sum formulas decide the parent rows (structure-extraction.md section 3)
    base = checks.plan_fallback(checks.classify_by_label(first.file_map, cells), cells, fiscal_year_end)      # a sheet read with no last actual column gets one from code, where the file shows a plan
    base, parent_notes = checks.apply_formula_parents(base, facts)
    before = checks.check_map(cells, base, fiscal_year_end)
    await stage("checking_cells", checked=total, total=total, matched=before["counts"].get(checks.CONFIRMED, 0), items=len(before["items"]))
    final, rereads, merged = before, [], base
    keys = checks.reread_keys(before["items"])
    if keys:
        groups = _group(before["items"])
        ask = [{"item": k, "reason": _worst(groups[k])["reason"]} for k in keys]
        failure = None
        second = None
        try:
            second = await asyncio.wait_for(
                gateway.read_structure(db, audit_id, text, SHEET_READING, file_hash=file_hash, adapter=adapter, recheck=ask,
                                       reread_of=first.reading_key, on_stage=stage, facts_blocks=blocks), read_seconds(text))
            if second.status != "read" or second.file_map is None:
                failure = second.reason or second.status
        except asyncio.TimeoutError:
            failure = "timed out"
        except Exception as exc:           # an error, a cap, a missing prompt: whatever the re-read met, the first reading stands
            failure = type(exc).__name__ if not str(exc) else str(exc)
        if failure is None:
            merged = checks.plan_fallback(checks.classify_by_label(checks.merge_reread(base, second.file_map, keys), cells), cells, fiscal_year_end)
            merged, again = checks.apply_formula_parents(merged, facts)
            parent_notes += [n for n in again if n not in parent_notes]
            final = checks.check_map(cells, merged, fiscal_year_end)
            await stage("checking_cells", checked=total, total=total, matched=final["counts"].get(checks.CONFIRMED, 0), items=len(final["items"]))
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
                    entry["first"], entry["second"] = checks.reading_of(base, key), checks.reading_of(second.file_map, key)
                rereads.append(entry)
        else:
            # The first reading stands, checked as it was; its rejected items say the re-read was not completed. Never not_read.
            note = f"re-read not completed: {failure}"
            rereads = [{"item": e["item"], "first_reason": e["reason"], "reread": None, "outcome": checks.REJECTED, "reason": note,
                        "action": "card", "first": checks.reading_of(base, e["item"]), "second": None} for e in ask]
            for item in final["items"]:
                if item["outcome"] == checks.REJECTED:
                    item["reread_note"] = note
    if capture is not None:
        capture["file_map"] = merged          # for the fixture job's comparison; never stored
    months = final["months"]
    best = max(months, key=lambda m: m["month"], default=None)
    doc = {"status": "read", "file": file, "file_hash": file_hash, "reading_key": first.reading_key, "prompt_version": first.prompt_version,
           "model": first.model, "cache_hit": first.cache_hit, "masked": first.masked or {}, "counts": final["counts"],
           "items": final["items"], "totals": final["totals"], "rereads": rereads, "months": months,
           "month": best["month"] if best else None,
           "evidence": (f"{best['evidence']} (confirmed on sheet {best['sheet']}, column {best['column']})" if best else None),
           "unread_sheets": first.unread_sheets, "read_reason": read_reasons.sheets_line(first.unread_sheets),
           "lines": sheet_lines(merged, cells, final["items"]), **file_facts(sheets),
           "structure_findings": workbook_facts.findings(structure), "parent_rows_from_formula": parent_notes,
           "consistency": same,
           "dims": {name: [sheet.max_row, sheet.max_col] for name, sheet in cells.sheets.items()},
           "rows_mapped": sum(len(s.get("rows") or []) for s in merged.get("sheets") or []),
           "period_columns": max((redactless_cols(s) for s in merged.get("sheets") or []), default=0)}
    mapping = await redaction.get_map(db, audit_id)
    doc["dims"] = {redaction.restore(name, mapping): dims for name, dims in doc["dims"].items()}      # keyed by the sheet's own name, as the map is
    doc = redaction.restore_deep(doc, mapping)                   # display un-masks on the server; the reasons held masked cell texts
    await readings.save_checks(db, audit_id, file_hash, doc)
    await cards.open_for_checks(db, audit_id, doc)
    return doc


def _masked_structure(structure: Optional[Dict], sheets: list, payload: str) -> Optional[Dict]:
    """The structure facts of the sheets the payload holds, each named as the masked payload names it. The sheets of the payload are those of the reading
    text, in order; each is matched to its facts by its position in the workbook, never by name (a masked or repeated name would match the wrong sheet)."""
    if not structure:
        return None
    index = [s.workbook_index for s in reading_input.recognised_sheets(sheets) if reading_input.sheet_cells(s, structure)]
    rename = dict(zip(index, checks.Cells(payload).sheets))
    return {**structure, "sheets": [{**s, "name": rename[i]} for i, s in enumerate(structure.get("sheets") or []) if i in rename]}


async def _second_read(db, audit_id: str, text: str, file_hash: str, adapter, fiscal_year_end: int, stage, first, blocks=None) -> tuple:
    """(the second read or None, the consistency record): {"status": "compared" | "not_compared", "reason", "items", "reads"}. The tokens of both
    reads are logged per file (llm_calls, `read_no`) and counted here by number only."""
    reads = {"first": {"input_tokens": first.input_tokens, "output_tokens": first.output_tokens, "cache_hit": bool(first.cache_hit)}}
    failure = None
    second = None
    try:
        second = await asyncio.wait_for(gateway.read_structure(db, audit_id, text, SHEET_READING, file_hash=file_hash, adapter=adapter,
                                                              fiscal_year_end=fiscal_year_end, on_stage=stage, second_read=True, facts_blocks=blocks), read_seconds(text))
        if second.status != "read" or second.file_map is None:
            failure = second.reason or second.status
    except asyncio.TimeoutError:
        failure = "timed out"
    except Exception as exc:           # an error, a cap, a missing prompt: the first reading stands, nothing is flagged
        failure = type(exc).__name__ if not str(exc) else str(exc)
    if failure is not None:
        logger.warning("sheet reads: run_id=%s hash=%s second read not completed", audit_id, file_hash[:12])
        return None, {"status": "not_compared", "reason": f"second read not completed: {failure}", "items": [], "reads": reads}
    reads["second"] = {"input_tokens": second.input_tokens, "output_tokens": second.output_tokens, "cache_hit": bool(second.cache_hit)}
    # A sheet either read lost to the output limit is no disagreement: it is left out of the comparison.
    lost = {u["sheet"] for read in (first, second) for u in read.unread_sheets or []}
    only = lambda m: {**m, "sheets": [sh for sh in m.get("sheets") or [] if sh["sheet"] not in lost]}      # noqa: E731
    cells = checks.Cells(first.payload)          # the rows are compared after the label rule (a reading stored before it gets it here): the reads agree on its roles
    items = consistency.compare(only(checks.classify_by_label(first.file_map, cells)), only(checks.classify_by_label(second.file_map, cells)))
    logger.info("sheet reads: run_id=%s hash=%s first=%d/%d second=%d/%d uncertain=%d", audit_id, file_hash[:12], first.input_tokens,
                first.output_tokens, second.input_tokens, second.output_tokens, len(items))
    return second, {"status": "compared", "reason": None, "items": items, "reads": reads}


def sheet_lines(file_map: Dict, cells: "checks.Cells", items: List[Dict]) -> List[Dict]:
    """[{"sheet", "lines"}] of a map: the lines of each sheet in file order (app/lines.py), their labels read from the cells the reader was sent."""
    out = []
    for smap in file_map.get("sheets") or []:
        sheet = cells.sheet(smap["sheet"])
        labels = {}
        for row in smap.get("rows") or []:
            # A row the reader gave no label cell for (a rate row under its line) has its label in the sheet's label column, on its own row.
            pos = checks.parse_ref(row.get("label_cell")) or (checks.parse_ref(f"{smap['label_col']}{row['row']}") if smap.get("label_col") else None)
            if sheet is not None and pos:
                labels[row["row"]] = (sheet.get(*pos) or "").strip()
        built = lines_mod.build(smap, labels)
        for line in built:
            found = next((i for i in items if i["key"] == f"row:{smap['sheet']}:{line['row']}"), None)
            line["outcome"] = found["outcome"] if found else None
        out.append({"sheet": smap["sheet"], "lines": built})
    return out


def redactless_cols(sheet: Dict) -> int:
    from .structures import redact
    return redact.col_number(sheet["last_period_col"]) - redact.col_number(sheet["first_period_col"]) + 1


async def reads_for(db, audit_id: str) -> Dict[str, Dict]:
    """The stored outcomes of the audit's files by file hash (what as_of.detect reads)."""
    return {d["file_hash"]: d for d in await readings.checks_for(db, audit_id) if d.get("status") == "read"}
